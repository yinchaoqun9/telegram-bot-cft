"""
Lightweight string match against pantry inventory for consume flows.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Tuple


EATABLE = {"冻干", "罐头", "汤包", "猫条", "零食", "干粮"}


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def item_category_canonical(item: Dict[str, Any]) -> str:
    """Map stored category (incl. English sample labels) to canonical ZH."""
    from services.product_category import normalize_category

    keyed = (item.get("category_key") or "").strip()
    if keyed:
        return keyed
    return normalize_category(item.get("category") or "")


def is_eatable_item(item: Dict[str, Any]) -> bool:
    return item_category_canonical(item) in EATABLE


def score_item(query: str, item: Dict[str, Any]) -> int:
    q = _norm(query)
    if not q:
        return 0
    brand = _norm(item.get("brand"))
    flavor = _norm(item.get("flavor"))
    cat = _norm(item.get("category"))
    blob = f"{brand} {flavor} {cat}".strip()
    score = 0
    if brand and brand in q:
        score += 50
    if flavor and flavor in q:
        score += 40
    if cat and cat in q:
        score += 20
    # reverse containment: query token in fields
    for tok in re_split_tokens(q):
        if len(tok) < 2:
            continue
        if tok in brand:
            score += 30
        if tok in flavor:
            score += 25
        if tok in cat:
            score += 15
        if tok in blob:
            score += 5
    return score


def re_split_tokens(q: str) -> List[str]:
    import re

    return [t for t in re.split(r"[\s,，、/]+", q) if t]


def _best_by_key(item: Dict[str, Any]) -> str:
    return str(item.get("best_by") or "9999-99-99")


def _eligible_for_action(
    it: Dict[str, Any],
    action: Optional[str],
    *,
    eatable_only: bool = False,
) -> bool:
    qty = int(it.get("quantity") or 0)
    has_open = bool(it.get("has_open_lot"))
    if action == "open" and qty < 1:
        return False
    if action == "used" and qty < 1 and not has_open:
        return False
    if qty <= 0 and not has_open:
        return False
    if eatable_only and not is_eatable_item(it):
        return False
    return True


def _weak_fuzzy_score(query: str, item: Dict[str, Any]) -> float:
    """0–100 soft similarity when strict token score is 0."""
    q = _norm(query)
    if not q:
        return 0.0
    blob = " ".join(
        _norm(item.get(k)) for k in ("brand", "flavor", "category") if item.get(k)
    )
    if not blob:
        return 0.0
    try:
        from rapidfuzz import fuzz

        return float(fuzz.partial_ratio(q, blob))
    except Exception:
        return 0.0


def rank_candidates(
    items: List[Dict[str, Any]],
    query: str,
    *,
    action: Optional[str] = None,
    eatable_only: bool = False,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """
    Rank inventory rows for a consume query (strict: score > 0 when query set).
    action='open' requires sealed qty>=1; action='used' allows open lots or sealed qty.
    """
    scored: List[tuple] = []
    for it in items:
        if not _eligible_for_action(it, action, eatable_only=eatable_only):
            continue
        s = score_item(query, it)
        if s <= 0 and query.strip():
            continue
        if s <= 0 and not query.strip():
            # empty query: still allow ranking by open / best_by for disambiguation UI
            s = 1
        scored.append((s, it))
    scored.sort(
        key=lambda x: (
            -x[0],
            0 if x[1].get("has_open_lot") else 1,
            _best_by_key(x[1]),
        )
    )
    return [it for _, it in scored[:limit]]


def soft_suggest_candidates(
    items: List[Dict[str, Any]],
    query: str,
    *,
    action: Optional[str] = None,
    eatable_only: bool = False,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """
    When strict match is empty: action-eligible rows ranked by weak fuzzy,
    then open lots, then soonest best_by. Never for auto-apply.
    """
    pool: List[tuple] = []
    for it in items:
        if not _eligible_for_action(it, action, eatable_only=eatable_only):
            continue
        weak = _weak_fuzzy_score(query, it)
        pool.append((weak, it))
    pool.sort(
        key=lambda x: (
            -x[0],
            0 if x[1].get("has_open_lot") else 1,
            _best_by_key(x[1]),
            -(int(x[1].get("quantity") or 0)),
        )
    )
    return [it for _, it in pool[:limit]]


def suggest_consume_candidates(
    items: List[Dict[str, Any]],
    query: str,
    *,
    action: Optional[str] = None,
    eatable_only: bool = False,
    limit: int = 3,
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Returns (candidates, strict).
    strict=True → score>0 hits (may auto-apply).
    strict=False → soft fallback only (buttons only, never auto).
    """
    strict = rank_candidates(
        items, query, action=action, eatable_only=eatable_only, limit=limit
    )
    if strict:
        return strict, True
    soft = soft_suggest_candidates(
        items, query, action=action, eatable_only=eatable_only, limit=limit
    )
    return soft, False


def pick_eat_today(
    items: List[Dict[str, Any]],
    *,
    limit: int = 3,
    today: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Top N eatable rows: open lots first, then soonest best_by."""
    today = today or date.today()
    pool = []
    for it in items:
        if not is_eatable_item(it):
            continue
        qty = int(it.get("quantity") or 0)
        if qty <= 0 and not it.get("has_open_lot"):
            continue
        pool.append(it)

    def sort_key(it: Dict[str, Any]):
        has_open = 0 if it.get("has_open_lot") else 1
        bb = it.get("best_by")
        return (has_open, str(bb or "9999-99-99"), -(int(it.get("quantity") or 0)))

    pool.sort(key=sort_key)
    return pool[:limit]


def has_urgent_expiry(items: List[Dict[str, Any]], today: Optional[date] = None) -> bool:
    today = today or date.today()
    for it in items:
        bb = it.get("best_by")
        if not bb:
            continue
        try:
            d = date.fromisoformat(str(bb)[:10])
        except ValueError:
            continue
        days = (d - today).days
        if days <= 7:
            return True
    return False

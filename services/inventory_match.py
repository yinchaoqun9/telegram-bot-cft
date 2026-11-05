"""
Lightweight string match against pantry inventory for consume flows.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple


EATABLE = {"冻干", "罐头", "汤包", "猫条", "零食", "干粮"}

# Strict hit must clear this after brand-aware scoring
MIN_STRICT_SCORE = 50
# Soft suggestions must clear this (or have solid brand evidence)
MIN_SOFT_FUZZ = 78
MIN_SOFT_BRAND = 55


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def fold_alnum(s: Any) -> str:
    """Lowercase + strip punctuation so Hill's ≈ hills, 9-Lives ≈ 9lives."""
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", _norm(s))


def re_split_tokens(q: str) -> List[str]:
    return [t for t in re.split(r"[\s,，、/+\-]+", q) if t]


def item_category_canonical(item: Dict[str, Any]) -> str:
    """Map stored category (incl. English sample labels) to canonical ZH."""
    from services.product_category import normalize_category

    keyed = (item.get("category_key") or "").strip()
    if keyed:
        return keyed
    return normalize_category(item.get("category") or "")


def is_eatable_item(item: Dict[str, Any]) -> bool:
    return item_category_canonical(item) in EATABLE


def brand_match_strength(query: str, item: Dict[str, Any]) -> int:
    """
    0–100 evidence that the item's brand appears in the query.
    Apostrophes / spaces / hyphens are folded away.
    """
    brand = _norm(item.get("brand"))
    if not brand:
        return 0
    q = _norm(query)
    if not q:
        return 0

    bf = fold_alnum(brand)
    qf = fold_alnum(query)
    if bf and len(bf) >= 2 and bf in qf:
        return 100

    brand_toks = [t for t in re_split_tokens(brand) if len(fold_alnum(t)) >= 2]
    q_toks = [t for t in re_split_tokens(q) if len(fold_alnum(t)) >= 2]
    if brand_toks and q_toks:
        hits = 0
        for bt in brand_toks:
            btf = fold_alnum(bt)
            for qt in q_toks:
                qtf = fold_alnum(qt)
                if not btf or not qtf:
                    continue
                if btf == qtf or (len(btf) >= 3 and (btf in qtf or qtf in btf)):
                    hits += 1
                    break
                try:
                    from rapidfuzz import fuzz

                    if fuzz.ratio(btf, qtf) >= 88:
                        hits += 1
                        break
                except Exception:
                    pass
        if hits == len(brand_toks) and hits > 0:
            return 95
        if hits > 0:
            return min(85, 45 + 25 * hits)

    try:
        from rapidfuzz import fuzz

        if bf and qf:
            pr = float(fuzz.partial_ratio(bf, qf))
            if pr >= 92 and len(bf) >= 4:
                return 80
            if pr >= 85 and len(bf) >= 5:
                return 60
    except Exception:
        pass
    return 0


def flavor_match_strength(query: str, item: Dict[str, Any]) -> int:
    flavor = _norm(item.get("flavor"))
    if not flavor:
        return 0
    q = _norm(query)
    ff = fold_alnum(flavor)
    qf = fold_alnum(query)
    if ff and len(ff) >= 2 and ff in qf:
        return 40
    for tok in re_split_tokens(q):
        tf = fold_alnum(tok)
        if len(tf) < 3:
            continue
        if tf == ff or (tf in ff or ff in tf):
            return 35
        try:
            from rapidfuzz import fuzz

            if fuzz.ratio(tf, ff) >= 90:
                return 30
        except Exception:
            pass
    return 0


def score_item(query: str, item: Dict[str, Any]) -> int:
    """
    Brand-aware score. Flavor-only hits are capped so “chicken” alone
    cannot auto-open the wrong brand.
    """
    q = _norm(query)
    if not q:
        return 0

    brand_s = brand_match_strength(query, item)
    flavor_s = flavor_match_strength(query, item)
    cat = _norm(item.get("category"))
    cat_s = 0
    if cat:
        cf = fold_alnum(cat)
        qf = fold_alnum(query)
        if cf and len(cf) >= 2 and cf in qf:
            cat_s = 15
        else:
            for tok in re_split_tokens(q):
                if len(tok) >= 3 and fold_alnum(tok) in cf:
                    cat_s = 12
                    break

    # Common flavor words without brand must not look like a confident hit
    if brand_s == 0 and flavor_s > 0:
        flavor_s = min(flavor_s, 30)

    score = brand_s + flavor_s + cat_s
    # Small bonus when both brand and flavor align
    if brand_s >= 55 and flavor_s >= 30:
        score += 15
    return int(score)


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

        return float(fuzz.token_set_ratio(q, blob))
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
    Rank inventory rows for a consume query (strict: solid score when query set).
    action='open' requires sealed qty>=1; action='used' allows open lots or sealed qty.
    """
    scored: List[tuple] = []
    for it in items:
        if not _eligible_for_action(it, action, eatable_only=eatable_only):
            continue
        s = score_item(query, it)
        if query.strip():
            if s < MIN_STRICT_SCORE:
                continue
        else:
            # empty query: still allow ranking by open / best_by for disambiguation UI
            s = max(s, 1)
        scored.append((s, brand_match_strength(query, it), it))
    scored.sort(
        key=lambda x: (
            -x[0],
            -x[1],
            0 if x[2].get("has_open_lot") else 1,
            _best_by_key(x[2]),
        )
    )
    return [it for _, _, it in scored[:limit]]


def soft_suggest_candidates(
    items: List[Dict[str, Any]],
    query: str,
    *,
    action: Optional[str] = None,
    eatable_only: bool = False,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """
    When strict match is empty: only suggest rows with real brand evidence
    or a strong fuzzy score. Never for auto-apply.
    """
    pool: List[tuple] = []
    for it in items:
        if not _eligible_for_action(it, action, eatable_only=eatable_only):
            continue
        weak = _weak_fuzzy_score(query, it)
        b = brand_match_strength(query, it)
        if b < MIN_SOFT_BRAND and weak < MIN_SOFT_FUZZ:
            continue
        # Reject flavor-only soft hits (common words like chicken/tuna)
        if b < 40 and flavor_match_strength(query, it) > 0 and weak < 90:
            continue
        pool.append((weak, b, it))
    pool.sort(
        key=lambda x: (
            -x[1],  # brand first
            -x[0],
            0 if x[2].get("has_open_lot") else 1,
            _best_by_key(x[2]),
            -(int(x[2].get("quantity") or 0)),
        )
    )
    return [it for _, _, it in pool[:limit]]


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
    strict=True → solid score hits (may auto-apply only via should_auto_apply).
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


def should_auto_apply(query: str, candidates: List[Dict[str, Any]]) -> bool:
    """
    Auto open/used only with clear brand evidence and a decisive lead.
    Flavor-only or weak single hits must show confirmation buttons instead.
    """
    q = (query or "").strip()
    if not q or not candidates:
        return False
    top = candidates[0]
    s0 = score_item(q, top)
    b0 = brand_match_strength(q, top)
    if b0 < 55:
        return False
    if s0 < 70:
        return False
    if len(candidates) == 1:
        # Single hit still needs brand + healthy score
        return b0 >= 70 or s0 >= 90
    s1 = score_item(q, candidates[1])
    b1 = brand_match_strength(q, candidates[1])
    if b0 >= 80 and b1 < 55 and s0 >= s1 + 15:
        return True
    if s0 >= s1 + 35 and s0 >= 85 and b0 >= 70:
        return True
    return False


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

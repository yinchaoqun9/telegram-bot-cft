"""
Parse a free-text Fix reply into brand / quantity / category.

Supports multi-field in one message, e.g. "丸味 冻干" → brand + category.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from services.product_category import normalize_category

_QTY_PREFIX = re.compile(
    r"^(?:quantity|qty|数量|数量改成|改成数量|改数量)\s*[:：]?\s*",
    re.IGNORECASE,
)
_CAT_PREFIX = re.compile(
    r"^(?:category|类别|分类|品类)\s*[:：]?\s*",
    re.IGNORECASE,
)
_BRAND_PREFIX = re.compile(
    r"^(?:brand|品牌)\s*[:：]?\s*",
    re.IGNORECASE,
)
_BARE_INT = re.compile(r"^(\d{1,4})$")
_SPLIT = re.compile(r"[\s,，、/;｜|]+")

# Exact category labels / aliases (whole token only — never substring of brand)
_CATEGORY_TOKENS = {
    "冻干",
    "罐头",
    "汤包",
    "猫条",
    "零食",
    "湿粮",
    "wet",
    "wetfood",
    "wet food",
    "canned",
    "canned food",
    "freeze-dried",
    "freeze dried",
    "freezedried",
    "treat",
    "treats",
    "cat stick",
    "主食罐",
    "湿粮罐",
    "猫罐头",
    "主食冻干",
}


def parse_fix_patch(text: str) -> Dict[str, object]:
    """
    Return a patch dict for update_inventory_fields (may include multiple keys).

    Examples:
      "3" → {quantity: 3}
      "冻干" → {category: 冻干}
      "丸味" → {brand: 丸味}
      "丸味 冻干" → {brand: 丸味, category: 冻干}
      "Orijen 3 wet food" → {brand: Orijen, quantity: 3, category: 罐头}
    """
    raw = (text or "").strip()
    if not raw:
        return {}

    # Explicit single-field prefixes
    m = _QTY_PREFIX.match(raw)
    if m:
        n = _extract_int(raw[m.end() :])
        return {"quantity": n} if n is not None else {}

    m = _CAT_PREFIX.match(raw)
    if m:
        rest = raw[m.end() :].strip()
        cat = normalize_category(rest, rest, default="")
        return {"category": cat} if cat else {}

    m = _BRAND_PREFIX.match(raw)
    if m:
        rest = raw[m.end() :].strip()
        return {"brand": rest} if rest else {}

    if _BARE_INT.match(raw):
        return {"quantity": int(raw)}

    # Tokenize; pull qty + category tokens; remainder = brand
    tokens = [t for t in _SPLIT.split(raw) if t]
    if not tokens:
        return {}

    # Merge "wet"+"food" / "freeze"+"dried" if split
    tokens = _merge_multiword_category_tokens(tokens)

    brand_parts: List[str] = []
    patch: Dict[str, object] = {}
    for tok in tokens:
        if _BARE_INT.match(tok):
            patch["quantity"] = int(tok)
            continue
        cat = _token_as_category(tok)
        if cat:
            patch["category"] = cat
            continue
        brand_parts.append(tok)

    if brand_parts:
        patch["brand"] = " ".join(brand_parts).strip()

    # Single token that is only a known category phrase with spaces already merged
    if not patch and raw:
        cat = _token_as_category(raw)
        if cat:
            return {"category": cat}
        return {"brand": raw}

    return patch


def parse_fix_message(text: str) -> Tuple[Optional[str], Dict[str, object]]:
    """
    Backward-compatible wrapper: (primary_field, patch).
    primary_field is the first of brand|quantity|category present.
    """
    patch = parse_fix_patch(text)
    if not patch:
        return None, {}
    for key in ("brand", "quantity", "category"):
        if key in patch:
            return key, patch
    return None, patch


def _token_as_category(tok: str) -> str:
    t = (tok or "").strip()
    if not t:
        return ""
    if t.lower() not in {c.lower() for c in _CATEGORY_TOKENS} and t not in _CATEGORY_TOKENS:
        # still allow exact normalize if the whole token is exactly a canonical
        if t in ("冻干", "罐头", "汤包", "猫条", "零食"):
            return t
        return ""
    return normalize_category(t, "", default="")


def _merge_multiword_category_tokens(tokens: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(tokens):
        if i + 1 < len(tokens):
            pair = f"{tokens[i]} {tokens[i + 1]}"
            if pair.lower() in {c.lower() for c in _CATEGORY_TOKENS}:
                out.append(pair)
                i += 2
                continue
        out.append(tokens[i])
        i += 1
    return out


def _extract_int(s: str) -> Optional[int]:
    s = (s or "").strip()
    m = re.search(r"(\d{1,4})", s)
    if not m:
        return None
    return int(m.group(1))

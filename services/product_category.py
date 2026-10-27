"""
Normalize product category (冻干 / 罐头 / 汤包 / 猫条 / 零食) from LLM + transcript.
No API calls.
"""

import re
from typing import List, Optional, Tuple

# canonical -> spoken / English aliases (longer phrases first for substring scan)
_CATEGORY_ALIASES: List[Tuple[str, List[str]]] = [
    (
        "冻干",
        [
            "freeze-dried",
            "freeze dried",
            "freezedried",
            "主食冻干",
            "生骨肉冻干",
            "冻干",
        ],
    ),
    (
        "罐头",
        [
            "主食罐",
            "湿粮罐",
            "猫罐头",
            "罐头",
            "湿粮",
            "wet food",
            "wetfood",
            "wet",
            "canned food",
            "canned",
        ],
    ),
    (
        "汤包",
        [
            "汤包",
            "汤罐",
            "broth pouch",
            "soup pouch",
            "broth",
        ],
    ),
    (
        "猫条",
        [
            "猫条",
            "肉泥条",
            "lickable",
            "cat stick",
            "stick treat",
        ],
    ),
    (
        "零食",
        [
            "零食",
            "磨牙棒",
            "小零食",
            "treats",
            "treat",
            "reward",
        ],
    ),
]


def _flatten_alias_pairs() -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    for canonical, aliases in _CATEGORY_ALIASES:
        for a in [canonical] + aliases:
            a = (a or "").strip()
            if len(a) < 1:
                continue
            pairs.append((a, canonical))
    pairs.sort(key=lambda x: -len(x[0]))
    out: List[Tuple[str, str]] = []
    seen_lower: set = set()
    for a, c in pairs:
        lk = a.lower()
        if lk in seen_lower:
            continue
        seen_lower.add(lk)
        out.append((a, c))
    return out


_ALIAS_PAIRS = _flatten_alias_pairs()


def _token_in_text(needle: str, haystack: str) -> bool:
    n = needle.strip()
    if len(n) < 1:
        return False
    if not haystack:
        return False
    if all(ord(c) < 128 for c in n):
        pat = r"(?<!\w)" + re.escape(n) + r"(?!\w)"
        return re.search(pat, haystack, re.IGNORECASE) is not None
    return n in haystack


def infer_category_from_transcription(transcription: str) -> str:
    if not transcription:
        return ""
    for alias, canonical in _ALIAS_PAIRS:
        if _token_in_text(alias, transcription):
            return canonical
    return ""


# Default when voice/LLM does not specify a type (wet food)
DEFAULT_CATEGORY = "罐头"


def normalize_category(
    raw: str, transcription: str = "", *, default: Optional[str] = None
) -> str:
    """
    Map LLM category string to one of the five canonical labels, or infer from transcript.
    If still empty, use default (湿粮/罐头 = wet food) unless default=\"\".
    """
    s = (raw or "").strip()
    if s:
        s_lower = s.lower()
        for alias, canonical in _ALIAS_PAIRS:
            if s == canonical or s_lower == alias.lower():
                return canonical
        for alias, canonical in _ALIAS_PAIRS:
            if len(alias) >= 2 and alias.lower() in s_lower:
                return canonical
        for alias, canonical in _ALIAS_PAIRS:
            if len(alias) >= 2 and alias in s:
                return canonical
    inferred = infer_category_from_transcription(transcription)
    if inferred:
        return inferred
    if default is None:
        default = DEFAULT_CATEGORY
    return default or ""

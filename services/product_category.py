"""
Normalize product category for pet pantry items (food, litter, meds).
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
            "狗罐头",
            "罐头",
            "湿粮",
            "wet food",
            "wetfood",
            "wet",
            "canned food",
            "canned",
            # spoken “two cans” / “tuna can” / “a can of …”
            "cans",
            "can",
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
    (
        "干粮",
        [
            "干粮",
            "干饭",
            "主粮",
            "dry food",
            "dryfood",
            "kibble",
            "dog food",
            "cat food",
        ],
    ),
    (
        "猫砂",
        [
            "猫砂",
            "猫沙",
            "litter",
            "cat litter",
            "kitty litter",
        ],
    ),
    (
        "药品",
        [
            "药品",
            "药物",
            "吃药",
            "服药",
            "处方药",
            "medication",
            "medicine",
            "meds",
            "med",
            "pill",
            "pills",
            "tablet",
            "tablets",
            "rx",
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

CANONICAL_CATEGORIES = [c for c, _ in _CATEGORY_ALIASES]


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
    """Return Chinese canonical key inferred from transcript (for matching / logic)."""
    if not transcription:
        return ""
    for alias, canonical in _ALIAS_PAIRS:
        if _token_in_text(alias, transcription):
            return canonical
    return ""


def spoken_category_alias_from_transcription(transcription: str) -> str:
    """
    Return the category wording as spoken in the transcript (not forced ZH).
    English matches keep the casing found in the transcript.
    """
    if not transcription:
        return ""
    for alias, _canonical in _ALIAS_PAIRS:
        if not _token_in_text(alias, transcription):
            continue
        if all(ord(c) < 128 for c in alias):
            m = re.search(
                r"(?<!\w)" + re.escape(alias) + r"(?!\w)",
                transcription,
                re.IGNORECASE,
            )
            if m:
                return m.group(0)
        return alias
    return ""


# Empty by default: do not force wet food when the user never said a type.
DEFAULT_CATEGORY = ""

# When the user spoke English but the LLM returned a ZH canonical, store EN.
_CANONICAL_EN_LABEL: dict = {
    "冻干": "freeze-dried",
    "罐头": "wet food",
    "汤包": "broth pouch",
    "猫条": "lickable",
    "零食": "treat",
    "干粮": "dry food",
    "猫砂": "litter",
    "药品": "meds",
}


def _has_cjk(s: str) -> bool:
    return any("\u4e00" <= c <= "\u9fff" for c in (s or ""))


def transcript_looks_english(transcription: str) -> bool:
    """True when Latin letters clearly dominate over CJK in the transcript."""
    t = transcription or ""
    latin = sum(1 for c in t if ("a" <= c.lower() <= "z"))
    cjk = sum(1 for c in t if "\u4e00" <= c <= "\u9fff")
    if latin == 0 and cjk == 0:
        return False
    return latin >= max(3, cjk * 2)


def normalize_category(
    raw: str, transcription: str = "", *, default: Optional[str] = None
) -> str:
    """
    Map LLM / stored category string to a Chinese canonical key for logic
    (EATABLE, open-shelf, dashboard category_key). Not for DB storage.
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


def category_keys_in_transcription(transcription: str) -> List[str]:
    """Distinct canonical keys mentioned in a (possibly multi-item) transcript."""
    if not transcription:
        return []
    found: List[str] = []
    seen = set()
    for alias, canonical in _ALIAS_PAIRS:
        if canonical in seen:
            continue
        if _token_in_text(alias, transcription):
            seen.add(canonical)
            found.append(canonical)
    return found


def _label_for_key(key: str, *, english: bool) -> str:
    if not key:
        return ""
    if english:
        return _CANONICAL_EN_LABEL.get(key, key)
    return key


def category_for_storage(raw: str, transcription: str = "") -> str:
    """
    Persist per-item category in the language the user spoke.

    Critical: do NOT scan the whole multi-item transcript for a single alias
    and apply it to every row (that turned Fancy Feast cans into freeze-dried).

    Order:
    1) Trust per-item LLM `raw` when it maps to a known type
    2) Only if raw is empty/unknown AND the transcript mentions exactly one
       category type, infer from transcript
    3) Otherwise leave empty (better than cross-item contamination)
    """
    s = (raw or "").strip()
    en_mode = transcript_looks_english(transcription)
    key_from_raw = normalize_category(s, "", default="") if s else ""

    if key_from_raw:
        if en_mode:
            if _has_cjk(s):
                return _label_for_key(key_from_raw, english=True)
            return s
        if _has_cjk(transcription) and not _has_cjk(s):
            return key_from_raw
        return s if s else key_from_raw

    keys = category_keys_in_transcription(transcription)
    if len(keys) == 1:
        key = keys[0]
        spoken = spoken_category_alias_from_transcription(transcription)
        if spoken and normalize_category(spoken, "", default="") == key:
            return spoken
        return _label_for_key(key, english=en_mode)
    return ""


def display_category(stored: str, lang: str = "en") -> str:
    """
    UI label for a stored category, following the user's /language setting.
    Storage may be EN or ZH; display is always localized.
    """
    from services.bot_i18n import normalize_lang

    key = normalize_category(stored or "", default="")
    if not key:
        return (stored or "").strip()
    return _label_for_key(key, english=(normalize_lang(lang) != "zh"))

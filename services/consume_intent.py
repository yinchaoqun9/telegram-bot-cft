"""
Detect open/used consume intents from voice/text transcripts.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

# Returns (action, residual_query) or (None, original)
_OPEN = re.compile(
    r"(?:"
    r"开了|打开了|开封了|拆了|拆开了|"
    r"\bopened\b|\bopening\b|\bopen\b"
    r")",
    re.IGNORECASE,
)
_USED = re.compile(
    r"(?:"
    r"用了|用掉|用完|吃了|吃完|吃光|喝了|喂了|搞定|"
    # finish/finished — common voice phrasing for “used up”
    r"\bused\b|\bfinished\b|\bfinish\b|\bfinishing\b|"
    r"\bate\b|\beaten\b|\ball\s+gone\b|\bgone\b"
    r")",
    re.IGNORECASE,
)


def detect_consume_intent(text: str) -> Tuple[Optional[str], str]:
    """
    If transcript is a consume action, return ('open'|'used', query_without_verb).
    Otherwise (None, original text).
    """
    raw = (text or "").strip()
    if not raw:
        return None, raw

    # Prefer open if both somehow match near the start
    open_m = _OPEN.search(raw)
    used_m = _USED.search(raw)

    if open_m and (not used_m or open_m.start() <= used_m.start()):
        query = (raw[: open_m.start()] + raw[open_m.end() :]).strip(" ，,。.!！?？")
        query = re.sub(r"^(一|两|二|三|\d+)\s*(罐|袋|盒|瓶|份|cans?|packs?)?", "", query, flags=re.I).strip()
        return "open", query or raw

    if used_m:
        query = (raw[: used_m.start()] + raw[used_m.end() :]).strip(" ，,。.!！?？")
        query = re.sub(r"^(一|两|二|三|\d+)\s*(罐|袋|盒|瓶|份|cans?|packs?)?", "", query, flags=re.I).strip()
        # Drop leading articles / filler
        query = re.sub(r"^(the|a|an|my|that|this)\s+", "", query, flags=re.I).strip()
        return "used", query or raw

    return None, raw

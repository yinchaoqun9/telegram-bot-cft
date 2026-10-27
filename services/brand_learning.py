"""
Per-user brand corrections (training layer).

When a user fixes a wrong brand in Telegram, we:
1) update the inventory row
2) store alias → canonical for that user
3) log the correction for future catalog mining

Next voice notes for the same user apply aliases before the global catalog.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from services.brand_catalog import BrandCatalog

logger = logging.getLogger(__name__)


def apply_user_aliases(
    brand_raw: str, aliases: List[Dict[str, str]]
) -> Optional[str]:
    """Exact (case-insensitive) hit on a learned alias → canonical."""
    q = (brand_raw or "").strip()
    if not q or not aliases:
        return None
    ql = q.lower()
    for row in aliases:
        a = (row.get("alias") or "").strip()
        c = (row.get("canonical") or "").strip()
        if a and c and a.lower() == ql:
            return c
    return None


def resolve_brand_with_user_learning(
    catalog: BrandCatalog,
    brand_raw: str,
    transcription: str,
    aliases: List[Dict[str, str]],
) -> str:
    """User aliases first, then global catalog resolve."""
    hit = apply_user_aliases(brand_raw, aliases)
    if hit:
        logger.info("Brand from user alias: %r -> %r", brand_raw, hit)
        return hit
    # Also: if transcript contains a learned alias, prefer that canonical
    tr = transcription or ""
    if tr and aliases:
        # longest alias first
        ordered = sorted(
            aliases,
            key=lambda r: -len((r.get("alias") or "")),
        )
        for row in ordered:
            a = (row.get("alias") or "").strip()
            c = (row.get("canonical") or "").strip()
            if len(a) >= 2 and a in tr and c:
                logger.info("Brand from user alias in transcript: %r -> %r", a, c)
                return c
            if len(a) >= 2 and a.lower() in tr.lower() and all(
                ord(ch) < 128 for ch in a
            ):
                logger.info("Brand from user alias in transcript: %r -> %r", a, c)
                return c
    return catalog.resolve_brand(brand_raw, transcription)

"""
Local pet food brand catalog: fuzzy match spoken / LLM brand strings to canonical names.
No LLM tokens — uses rapidfuzz against a static JSON file.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)

_DEFAULT_DATA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "cat_food_brands.json",
)


class BrandCatalog:
    """Load canonical brands + aliases; normalize user/LLM brand strings."""

    def __init__(self, data_path: Optional[str] = None, score_cutoff: int = 85):
        self._score_cutoff = score_cutoff
        self._choices: List[str] = []
        self._canonical_for_choice: Dict[str, str] = {}
        path = data_path or os.environ.get("BRAND_MAP_PATH") or _DEFAULT_DATA_PATH
        self._load(path)

    def _load(self, path: str) -> None:
        if not os.path.isfile(path):
            logger.warning("Brand catalog file not found: %s (brand normalization disabled)", path)
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                rows = json.load(f)
        except Exception as e:
            logger.exception("Failed to load brand catalog %s: %s", path, e)
            return

        if not isinstance(rows, list):
            logger.error("Brand catalog must be a JSON array")
            return

        for row in rows:
            if not isinstance(row, dict):
                continue
            canonical = (row.get("canonical") or "").strip()
            if not canonical:
                continue
            aliases = row.get("aliases") or []
            if not isinstance(aliases, list):
                aliases = []

            for label in [canonical] + [str(a).strip() for a in aliases if str(a).strip()]:
                if label.lower() not in {c.lower() for c in self._choices}:
                    self._choices.append(label)
                    self._canonical_for_choice[label.lower()] = canonical

        logger.info("Brand catalog loaded: %d match strings -> %d entries", len(self._choices), len(rows))

    def choice_count(self) -> int:
        """Number of indexed labels (for diagnostics)."""
        return len(self._choices)

    def normalize_brand(self, spoken: str) -> str:
        """
        Map a rough brand string to canonical name if fuzzy score >= cutoff.

        Returns:
            Canonical brand if matched; otherwise returns stripped original.
        """
        if not spoken or not str(spoken).strip():
            return ""
        query = str(spoken).strip()
        if not self._choices:
            return query

        result: Optional[Tuple[str, float, int]] = process.extractOne(
            query,
            self._choices,
            scorer=fuzz.WRatio,
        )
        if result is None:
            return query

        match_label, score, _ = result
        if score < self._score_cutoff:
            return query

        canonical = self._canonical_for_choice.get(match_label.lower(), match_label)
        if canonical != query:
            logger.debug("Brand normalized: %r -> %r (score=%s)", query, canonical, score)
        return canonical


_catalog: Optional[BrandCatalog] = None


def get_brand_catalog() -> BrandCatalog:
    """Singleton catalog (lazy)."""
    global _catalog
    if _catalog is None:
        # Default 80: one-letter ASR/LLM typos (e.g. akana/acana) often sit 80–84 WRatio
        cutoff = int(os.environ.get("BRAND_MATCH_THRESHOLD", "80"))
        path = os.environ.get("BRAND_MAP_PATH")
        _catalog = BrandCatalog(data_path=path, score_cutoff=cutoff)
    return _catalog

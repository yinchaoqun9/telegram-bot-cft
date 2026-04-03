"""
Local pet food brand catalog: fuzzy match spoken / LLM brand strings to canonical names.
No LLM tokens — uses rapidfuzz against a static JSON file.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)

_DEFAULT_DATA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "cat_food_brands.json",
)


def _alias_appears_in_text(alias: str, text: str) -> bool:
    """Match alias inside full transcription (substring for CJK; word-boundary for ASCII)."""
    a = (alias or "").strip()
    if len(a) < 2:
        return False
    if not text:
        return False
    if all(ord(c) < 128 for c in a):
        pat = r"(?<!\w)" + re.escape(a) + r"(?!\w)"
        return re.search(pat, text, re.IGNORECASE) is not None
    return a in text


class BrandCatalog:
    """Load canonical brands + aliases; normalize user/LLM brand strings."""

    def __init__(self, data_path: Optional[str] = None, score_cutoff: int = 85):
        self._score_cutoff = score_cutoff
        self._choices: List[str] = []
        self._canonical_for_choice: Dict[str, str] = {}
        self._alias_pairs: List[Tuple[str, str]] = []
        self._seen_alias_lower: set = set()
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
                lk = label.lower()
                if lk not in self._seen_alias_lower:
                    self._seen_alias_lower.add(lk)
                    self._alias_pairs.append((label, canonical))
                if label.lower() not in {c.lower() for c in self._choices}:
                    self._choices.append(label)
                    self._canonical_for_choice[label.lower()] = canonical

        self._alias_pairs.sort(key=lambda p: -len(p[0]))
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
        score = float(score)
        if score < self._score_cutoff:
            # Second chance: partial_ratio helps short queries vs long catalog labels
            pr = float(
                fuzz.partial_ratio(query.lower(), match_label.lower())
            )
            if pr < self._score_cutoff:
                return query
            score = pr

        canonical = self._canonical_for_choice.get(match_label.lower(), match_label)
        if canonical != query:
            logger.debug("Brand normalized: %r -> %r (score=%s)", query, canonical, score)
        return canonical

    def best_match_score(self, query: str) -> float:
        """
        Best rapidfuzz score (0–100) for query against catalog labels, using the
        same WRatio + partial_ratio fallback as normalize_brand.
        """
        if not query or not str(query).strip() or not self._choices:
            return 0.0
        q = str(query).strip()
        result: Optional[Tuple[str, float, int]] = process.extractOne(
            q, self._choices, scorer=fuzz.WRatio
        )
        if result is None:
            return 0.0
        match_label, score, _ = result
        score = float(score)
        if score < self._score_cutoff:
            pr = float(fuzz.partial_ratio(q.lower(), match_label.lower()))
            score = max(score, pr)
        return score

    def needs_web_search_fallback(self, brand_raw: str, transcription: str) -> bool:
        """
        True when fuzzy score on LLM brand is below cutoff AND transcript
        substring did not hit the catalog (so local matching failed twice).
        """
        if not os.environ.get("BRAND_WEB_SEARCH_ENABLED", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        ):
            return False
        if not (os.environ.get("GOOGLE_CSE_API_KEY") or "").strip():
            return False
        if not (
            os.environ.get("GOOGLE_CSE_CX") or os.environ.get("GOOGLE_CSE_ENGINE_ID") or ""
        ).strip():
            return False
        if self.infer_canonical_from_transcription(transcription or ""):
            return False
        raw = (brand_raw or "").strip()
        tr = (transcription or "").strip()
        if not raw and len(tr) < 4:
            return False
        if raw and self.best_match_score(raw) >= float(self._score_cutoff):
            return False
        return True

    def infer_canonical_from_transcription(self, transcription: str) -> str:
        """
        Find a catalog canonical whose alias appears verbatim in the transcript.
        Longest alias wins (sorted). No extra API cost; fixes LLM missing niche brands.
        """
        if not transcription or not self._alias_pairs:
            return ""
        for alias, canonical in self._alias_pairs:
            if _alias_appears_in_text(alias, transcription):
                logger.debug("Brand inferred from transcript: %r -> %r", alias, canonical)
                return canonical
        return ""

    def resolve_brand(self, brand_raw: str, transcription: str) -> str:
        """
        Combine fuzzy normalize( LLM brand ) with substring match against full transcript.
        """
        raw = (brand_raw or "").strip()
        tr = transcription or ""
        b1 = self.normalize_brand(raw)
        b2 = self.infer_canonical_from_transcription(tr)
        if b2:
            if not b1:
                return b2
            tr_lower = tr.lower()
            if raw and raw.lower() not in tr_lower:
                return b2
            if b1 == raw:
                return b2
        return b1 if b1 else raw


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

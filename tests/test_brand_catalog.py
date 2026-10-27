"""Unit tests for local brand catalog (no LLM / network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.brand_catalog import BrandCatalog, _alias_appears_in_text


@pytest.fixture
def catalog(tmp_path: Path) -> BrandCatalog:
    data = [
        {
            "canonical": "Royal Canin",
            "aliases": ["皇家", "皇家猫粮", "RC"],
        },
        {
            "canonical": "Acana",
            "aliases": ["爱肯拿", "akana"],
        },
        {
            "canonical": "Fancy Feast",
            "aliases": ["珍致"],
        },
    ]
    path = tmp_path / "brands.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return BrandCatalog(data_path=str(path), score_cutoff=80)


def test_normalize_exact_alias(catalog: BrandCatalog):
    assert catalog.normalize_brand("皇家") == "Royal Canin"


def test_normalize_typo_akana(catalog: BrandCatalog):
    # ASR/LLM typo akana → Acana (alias in catalog)
    assert catalog.normalize_brand("akana") == "Acana"


def test_normalize_unknown_kept(catalog: BrandCatalog):
    assert catalog.normalize_brand("TotallyUnknownBrandXYZ") == "TotallyUnknownBrandXYZ"


def test_normalize_empty(catalog: BrandCatalog):
    assert catalog.normalize_brand("") == ""
    assert catalog.normalize_brand("   ") == ""


def test_infer_from_chinese_transcript(catalog: BrandCatalog):
    tr = "今天买了皇家猫粮鸡肉口味两罐"
    assert catalog.infer_canonical_from_transcription(tr) == "Royal Canin"


def test_infer_ascii_word_boundary():
    assert _alias_appears_in_text("RC", "I bought RC chicken") is True
    assert _alias_appears_in_text("RC", "FORCE pack") is False


def test_resolve_prefers_transcript_when_llm_misses(catalog: BrandCatalog):
    # LLM returned empty/wrong; transcript has 珍致
    assert (
        catalog.resolve_brand("", "买了两罐珍致鸡肉罐头")
        == "Fancy Feast"
    )


def test_needs_web_search_respects_env(catalog: BrandCatalog, monkeypatch):
    monkeypatch.delenv("BRAND_WEB_SEARCH_ENABLED", raising=False)
    assert catalog.needs_web_search_fallback("unknown", "no brand here xyz") is False

    monkeypatch.setenv("BRAND_WEB_SEARCH_ENABLED", "1")
    monkeypatch.setenv("GOOGLE_CSE_API_KEY", "key")
    monkeypatch.setenv("GOOGLE_CSE_CX", "cx")
    # Transcript already hits catalog → no web
    assert catalog.needs_web_search_fallback("x", "皇家猫粮") is False
    # No transcript hit + low score → web
    assert catalog.needs_web_search_fallback("zzzzunknownbrand", "plain text") is True


def test_missing_file_disables_matching(tmp_path: Path):
    cat = BrandCatalog(data_path=str(tmp_path / "missing.json"), score_cutoff=80)
    assert cat.choice_count() == 0
    assert cat.normalize_brand("皇家") == "皇家"

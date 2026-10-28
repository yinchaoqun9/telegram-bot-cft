"""Unit tests for product category normalization."""

from __future__ import annotations

from services.product_category import infer_category_from_transcription, normalize_category


def test_normalize_canonical_chinese():
    assert normalize_category("冻干") == "冻干"
    assert normalize_category("罐头") == "罐头"
    assert normalize_category("药品") == "药品"
    assert normalize_category("猫砂") == "猫砂"


def test_normalize_english_alias():
    assert normalize_category("freeze-dried") == "冻干"
    assert normalize_category("canned") == "罐头"
    assert normalize_category("treat") == "零食"
    assert normalize_category("medication") == "药品"
    assert normalize_category("meds") == "药品"
    assert normalize_category("litter") == "猫砂"


def test_normalize_from_transcript_when_raw_empty():
    assert normalize_category("", "买了两盒猫条鸡肉味") == "猫条"
    assert normalize_category("", "broth pouch salmon") == "汤包"
    assert normalize_category("", "half bottle of Apoquel meds") == "药品"


def test_infer_prefers_longer_alias():
    assert infer_category_from_transcription("这是主食冻干") == "冻干"


def test_unknown_stays_empty_by_default():
    assert normalize_category("mystery type", "no category words") == ""
    assert normalize_category("", "just some leftovers") == ""


def test_explicit_default_still_works():
    assert normalize_category("", "no type", default="罐头") == "罐头"


def test_wet_food_alias():
    assert normalize_category("wet food") == "罐头"
    assert normalize_category("湿粮") == "罐头"

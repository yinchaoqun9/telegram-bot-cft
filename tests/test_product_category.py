"""Unit tests for product category normalization / storage / display."""

from __future__ import annotations

from services.product_category import (
    category_for_storage,
    display_category,
    infer_category_from_transcription,
    normalize_category,
)


def test_normalize_canonical_chinese():
    assert normalize_category("冻干") == "冻干"
    assert normalize_category("罐头") == "罐头"
    assert normalize_category("药品") == "药品"
    assert normalize_category("猫砂") == "猫砂"


def test_normalize_english_alias():
    assert normalize_category("freeze-dried") == "冻干"
    assert normalize_category("canned") == "罐头"
    assert normalize_category("cans") == "罐头"
    assert normalize_category("treat") == "零食"
    assert normalize_category("medication") == "药品"
    assert normalize_category("meds") == "药品"
    assert normalize_category("litter") == "猫砂"
    assert normalize_category("lickable") == "猫条"


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


def test_dry_food_alias():
    assert normalize_category("dry food") == "干粮"
    assert normalize_category("kibble") == "干粮"


def test_storage_keeps_spoken_english():
    assert category_for_storage("lickable") == "lickable"
    assert category_for_storage("can", "two cans of tuna") == "can"
    assert category_for_storage("cans", "two cans of tuna") == "cans"
    assert category_for_storage("Lickable", "bought some Lickable treats") == "lickable"


def test_storage_keeps_spoken_chinese():
    assert category_for_storage("猫条", "买了猫条") == "猫条"
    assert category_for_storage("湿粮", "买了湿粮") == "湿粮"
    assert category_for_storage("", "买了两盒猫条鸡肉味") == "猫条"


def test_storage_infers_english_from_transcript_single_type():
    assert category_for_storage("", "three lickable chicken sticks") == "lickable"
    assert category_for_storage("", "one broth pouch salmon") == "broth pouch"


def test_storage_does_not_bleed_freeze_dried_onto_cans():
    """Multi-item EN utterance: per-item LLM raw must win; no whole-transcript override."""
    tr = (
        "Two cans of Fancy Feast chicken, best by June first, "
        "and one bag of Ziwi beef freeze dried."
    )
    # Fancy Feast row from LLM — EN default is can (not wet food)
    assert category_for_storage("wet food", tr) == "can"
    assert category_for_storage("罐头", tr) == "can"
    assert category_for_storage("cans", tr) == "cans"
    # Ziwi row
    assert category_for_storage("freeze-dried", tr) == "freeze-dried"
    assert category_for_storage("冻干", tr) == "freeze-dried"
    # Empty raw + multi-type transcript → do not guess
    assert category_for_storage("", tr) == ""


def test_storage_en_maps_llm_chinese_without_transcript_hijack():
    assert category_for_storage("罐头", "bought two Fancy Feast chicken cans") == "can"
    # Even if another type word appears, per-item raw wins
    assert category_for_storage("罐头", "cans of tuna and also freeze dried") == "can"


def test_display_follows_ui_language():
    assert display_category("罐头", "en") == "can"
    assert display_category("wet food", "en") == "can"
    assert display_category("freeze-dried", "zh") == "冻干"
    assert display_category("冻干", "zh") == "冻干"
    assert display_category("lickable", "en") == "lickable"
    assert display_category("猫条", "en") == "lickable"


def test_normalize_can_alias():
    assert normalize_category("can") == "罐头"
    assert normalize_category("", "tuna can") == "罐头"

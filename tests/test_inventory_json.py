"""Unit tests for LLM inventory JSON parsing (no API calls)."""

from __future__ import annotations

import pytest

from services.inventory_json import parse_inventory_items_from_llm_text


def test_parse_plain_array():
    items = parse_inventory_items_from_llm_text(
        '[{"brand":"A","flavor":"chicken","category":"罐头","best_by":"2026-01-01","quantity":2}]'
    )
    assert len(items) == 1
    assert items[0]["brand"] == "A"
    assert items[0]["quantity"] == 2


def test_parse_items_wrapper():
    items = parse_inventory_items_from_llm_text(
        '{"items":[{"brand":"B","flavor":"x","category":"冻干","best_by":null,"quantity":1}]}'
    )
    assert len(items) == 1
    assert items[0]["brand"] == "B"


def test_parse_single_object():
    items = parse_inventory_items_from_llm_text(
        '{"brand":"C","flavor":"y","category":"零食","best_by":"2025-12-31","quantity":3}'
    )
    assert len(items) == 1
    assert items[0]["brand"] == "C"


def test_parse_code_fence_and_preamble():
    raw = """Here is the JSON:
```json
[{"brand":"Royal","flavor":"beef","category":"罐头","best_by":"2027-01-01","quantity":1}]
```
"""
    items = parse_inventory_items_from_llm_text(raw)
    assert items[0]["brand"] == "Royal"


def test_parse_empty_raises():
    with pytest.raises(ValueError, match="Empty"):
        parse_inventory_items_from_llm_text("   ")


def test_parse_no_valid_items_raises():
    with pytest.raises(ValueError, match="No valid"):
        parse_inventory_items_from_llm_text("[1, 2, 3]")


def test_parse_invalid_json_raises():
    with pytest.raises(ValueError, match="Failed to parse"):
        parse_inventory_items_from_llm_text("not json at all {{{")

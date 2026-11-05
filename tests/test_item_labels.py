"""Pantry line/button labels include best_by so same brand/flavor lots differ."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="module")
def main_mod():
    os.environ.setdefault("OPENAI_API_KEY", "test-openai")
    os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
    os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:ABC")
    import main as main_mod

    return main_mod


def test_item_label_includes_best_by(main_mod):
    label = main_mod._item_label(
        {
            "brand": "Ziwi",
            "flavor": "beef",
            "category": "wet food",
            "best_by": "2026-05-01",
            "quantity": 2,
        }
    )
    assert "Ziwi" in label
    assert "beef" in label
    assert "2026-05-01" in label
    assert "qty 2" in label


def test_item_label_missing_date(main_mod):
    label = main_mod._item_label({"brand": "Ziwi", "quantity": 1})
    assert "—" in label


def test_sort_pantry_soonest_expiry(main_mod):
    rows = [
        {"id": "a", "best_by": "2027-01-01", "quantity": 1, "has_open_lot": False},
        {"id": "b", "best_by": "2026-03-01", "quantity": 1, "has_open_lot": False},
        {"id": "c", "best_by": "2026-06-01", "quantity": 1, "has_open_lot": True},
    ]
    ordered = main_mod._sort_pantry_browse(rows)
    assert [r["id"] for r in ordered] == ["c", "b", "a"]


def test_consume_buttons_include_date(main_mod):
    kb = main_mod._consume_pick_keyboard(
        "open",
        [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "brand": "Ziwi",
                "flavor": "beef",
                "best_by": "2026-05-01",
                "quantity": 1,
            },
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "brand": "Ziwi",
                "flavor": "beef",
                "best_by": "2026-12-01",
                "quantity": 1,
            },
        ],
        lang="en",
    )
    texts = [row[0]["text"] for row in kb]
    assert any("2026-05-01" in t for t in texts)
    assert any("2026-12-01" in t for t in texts)
    assert texts[0] != texts[1]


def test_list_row_buttons_include_date(main_mod):
    btns = main_mod._open_used_row_buttons(
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "brand": "Ziwi",
            "flavor": "beef",
            "best_by": "2026-08-15",
            "quantity": 2,
        },
        lang="en",
    )
    assert btns
    assert all("2026-08-15" in b["text"] for b in btns)

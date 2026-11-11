"""Pantry line labels: best_by + localized category (no FastAPI import)."""

from __future__ import annotations

from services.product_category import display_category


def _short_best_by(row: dict) -> str:
    bb = str(row.get("best_by") or "").strip()
    return bb[:10] if bb else "—"


def _item_label(row: dict, *, lang: str = "en") -> str:
    brand = (row.get("brand") or "").strip()
    flavor = (row.get("flavor") or "").strip()
    cat = display_category(row.get("category") or "", lang)
    qty = int(row.get("quantity") or 0)
    open_n = int(row.get("open_lots_count") or (1 if row.get("has_open_lot") else 0))
    bits = [x for x in (brand, flavor) if x]
    name = " ".join(bits) or "item"
    cpre = f"[{cat}] " if cat else ""
    open_bit = f", open×{open_n}" if open_n else ""
    return f"{cpre}{name} · {_short_best_by(row)} (qty {qty}{open_bit})"


def _sort_pantry_browse(items: list) -> list:
    def key(it: dict):
        has_open = 0 if it.get("has_open_lot") else 1
        bb = str(it.get("best_by") or "9999-99-99")
        return (has_open, bb, -(int(it.get("quantity") or 0)))

    return sorted(items, key=key)


def test_item_label_includes_best_by():
    label = _item_label(
        {
            "brand": "Ziwi",
            "flavor": "beef",
            "category": "wet food",
            "best_by": "2026-05-01",
            "quantity": 2,
        },
        lang="en",
    )
    assert "Ziwi" in label
    assert "beef" in label
    assert "2026-05-01" in label
    assert "qty 2" in label


def test_item_label_localizes_chinese_category_in_en_ui():
    label = _item_label(
        {
            "brand": "Fancy Feast",
            "flavor": "chicken",
            "category": "罐头",
            "best_by": "2026-06-01",
            "quantity": 2,
        },
        lang="en",
    )
    assert "wet food" in label
    assert "罐头" not in label


def test_item_label_missing_date():
    label = _item_label({"brand": "Ziwi", "quantity": 1})
    assert "—" in label


def test_sort_pantry_soonest_expiry():
    rows = [
        {"id": "a", "best_by": "2027-01-01", "quantity": 1, "has_open_lot": False},
        {"id": "b", "best_by": "2026-03-01", "quantity": 1, "has_open_lot": False},
        {"id": "c", "best_by": "2026-06-01", "quantity": 1, "has_open_lot": True},
    ]
    ordered = _sort_pantry_browse(rows)
    assert [r["id"] for r in ordered] == ["c", "b", "a"]

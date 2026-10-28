"""Fix message auto-detect tests."""

from services.fix_parse import parse_fix_message, parse_fix_patch


def test_bare_quantity():
    assert parse_fix_patch("3") == {"quantity": 3}
    assert parse_fix_patch("quantity 12") == {"quantity": 12}


def test_category_wet_food():
    assert parse_fix_patch("wet food") == {"category": "罐头"}


def test_brand_default():
    assert parse_fix_patch("丸味") == {"brand": "丸味"}


def test_brand_and_category_together():
    """Regression: '丸味 冻干' must update BOTH, not only category."""
    patch = parse_fix_patch("丸味 冻干")
    assert patch.get("brand") == "丸味"
    assert patch.get("category") == "冻干"


def test_meds_category_token():
    assert parse_fix_patch("药品") == {"category": "药品"}
    assert parse_fix_patch("meds") == {"category": "药品"}
    assert parse_fix_patch("Apoquel 药品") == {"brand": "Apoquel", "category": "药品"}


def test_brand_qty_category():
    patch = parse_fix_patch("Orijen 3 wet food")
    assert patch.get("brand") == "Orijen"
    assert patch.get("quantity") == 3
    assert patch.get("category") == "罐头"


def test_parse_fix_message_wrapper():
    field, patch = parse_fix_message("丸味 冻干")
    assert field == "brand"
    assert "category" in patch

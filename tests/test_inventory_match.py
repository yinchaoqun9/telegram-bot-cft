from services.inventory_match import (
    brand_match_strength,
    has_urgent_expiry,
    pick_eat_today,
    rank_candidates,
    score_item,
    should_auto_apply,
    soft_suggest_candidates,
    suggest_consume_candidates,
)


def test_score_brand_flavor():
    item = {"brand": "Ziwi", "flavor": "牛肉", "category": "罐头"}
    assert score_item("Ziwi 牛肉", item) >= 50


def test_hills_apostrophe_brand_match():
    item = {
        "id": "h1",
        "brand": "Hill's",
        "flavor": "chicken",
        "category": "wet food",
        "quantity": 2,
        "has_open_lot": False,
        "best_by": "2026-08-01",
    }
    assert brand_match_strength("hills chicken", item) >= 70
    assert score_item("hills chicken", item) >= 70


def test_flavor_only_does_not_auto_open_wrong_brand():
    """Regression: open hills chicken must NOT auto-apply Purina chicken."""
    items = [
        {
            "id": "p1",
            "brand": "Purina",
            "flavor": "chicken",
            "category": "lickable",
            "quantity": 3,
            "has_open_lot": False,
            "best_by": "2026-05-01",
        },
        {
            "id": "h1",
            "brand": "Hill's",
            "flavor": "chicken",
            "category": "wet food",
            "quantity": 2,
            "has_open_lot": False,
            "best_by": "2026-08-01",
        },
    ]
    cands, strict = suggest_consume_candidates(
        items, "hills chicken", action="open", limit=5
    )
    assert strict is True
    assert cands[0]["id"] == "h1"
    assert should_auto_apply("hills chicken", cands) is True

    # Only Purina in pantry → flavor-only must NOT auto; preferably no strict hit
    only_purina = [items[0]]
    cands2, strict2 = suggest_consume_candidates(
        only_purina, "hills chicken", action="open", limit=5
    )
    if strict2:
        assert should_auto_apply("hills chicken", cands2) is False
    else:
        # soft may be empty (preferred) or buttons-only
        assert should_auto_apply("hills chicken", cands2) is False


def test_rank_open_requires_qty():
    items = [
        {
            "id": "1",
            "brand": "Ziwi",
            "flavor": "beef",
            "category": "罐头",
            "quantity": 0,
            "has_open_lot": True,
            "best_by": "2026-01-01",
        },
        {
            "id": "2",
            "brand": "Ziwi",
            "flavor": "beef",
            "category": "罐头",
            "quantity": 2,
            "has_open_lot": False,
            "best_by": "2026-06-01",
        },
    ]
    open_hits = rank_candidates(items, "Ziwi", action="open")
    assert [x["id"] for x in open_hits] == ["2"]
    used_hits = rank_candidates(items, "Ziwi", action="used")
    assert used_hits[0]["id"] == "1"  # open lot preferred


def test_pick_eat_today_prefers_open():
    items = [
        {
            "brand": "A",
            "flavor": "x",
            "category": "罐头",
            "quantity": 5,
            "has_open_lot": False,
            "best_by": "2026-01-01",
        },
        {
            "brand": "B",
            "flavor": "y",
            "category": "罐头",
            "quantity": 1,
            "has_open_lot": True,
            "best_by": "2027-01-01",
        },
    ]
    picks = pick_eat_today(items, limit=2)
    assert picks[0]["brand"] == "B"


def test_pick_eat_today_accepts_english_sample_categories():
    items = [
        {
            "brand": "Sheba",
            "flavor": "chicken",
            "category": "wet food",
            "quantity": 3,
            "has_open_lot": False,
            "best_by": "2026-05-01",
        },
        {
            "brand": "Orijen",
            "flavor": "original",
            "category": "dry food",
            "quantity": 2,
            "has_open_lot": False,
            "best_by": "2026-04-01",
        },
        {
            "brand": "World's Best",
            "flavor": "",
            "category": "litter",
            "quantity": 1,
            "has_open_lot": False,
            "best_by": "2027-01-01",
        },
    ]
    picks = pick_eat_today(items, limit=5)
    brands = {p["brand"] for p in picks}
    assert "Sheba" in brands
    assert "Orijen" in brands
    assert "World's Best" not in brands


def test_has_urgent_expiry():
    from datetime import date, timedelta

    today = date(2026, 3, 1)
    items = [{"best_by": (today + timedelta(days=3)).isoformat()}]
    assert has_urgent_expiry(items, today=today) is True
    assert has_urgent_expiry([{"best_by": "2099-01-01"}], today=today) is False


def test_strict_miss_soft_does_not_guess_random():
    """Unrelated query should not soft-suggest random pantry rows."""
    items = [
        {
            "id": "a",
            "brand": "Ziwi",
            "flavor": "beef",
            "category": "罐头",
            "quantity": 2,
            "has_open_lot": False,
            "best_by": "2026-12-01",
        },
        {
            "id": "b",
            "brand": "Tiki Cat",
            "flavor": "chicken",
            "category": "罐头",
            "quantity": 1,
            "has_open_lot": True,
            "best_by": "2026-06-01",
        },
    ]
    strict = rank_candidates(items, "Nulo salmon xyz", action="open")
    assert strict == []
    soft = soft_suggest_candidates(items, "Nulo salmon xyz", action="open")
    assert soft == []
    cands, is_strict = suggest_consume_candidates(
        items, "Nulo salmon xyz", action="open"
    )
    assert is_strict is False
    assert cands == []


def test_suggest_strict_when_brand_hits():
    items = [
        {
            "id": "1",
            "brand": "Nulo",
            "flavor": "chicken",
            "category": "罐头",
            "quantity": 3,
            "has_open_lot": False,
            "best_by": "2026-08-01",
        }
    ]
    cands, is_strict = suggest_consume_candidates(
        items, "Nulo chicken", action="open"
    )
    assert is_strict is True
    assert cands[0]["id"] == "1"
    assert should_auto_apply("Nulo chicken", cands) is True


def test_soft_suggest_empty_pantry():
    cands, is_strict = suggest_consume_candidates([], "Nulo", action="used")
    assert cands == []
    assert is_strict is False


def test_nine_lives_brand_fold():
    item = {"brand": "9Lives", "flavor": "tuna", "category": "can", "quantity": 1}
    assert brand_match_strength("9 lives tuna", item) >= 55
    assert score_item("9 lives tuna can", item) >= 50

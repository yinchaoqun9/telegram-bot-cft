from services.inventory_match import (
    has_urgent_expiry,
    pick_eat_today,
    rank_candidates,
    score_item,
    soft_suggest_candidates,
    suggest_consume_candidates,
)


def test_score_brand_flavor():
    item = {"brand": "Ziwi", "flavor": "牛肉", "category": "罐头"}
    assert score_item("Ziwi 牛肉", item) >= 50


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


def test_has_urgent_expiry():
    from datetime import date, timedelta

    today = date(2026, 3, 1)
    items = [{"best_by": (today + timedelta(days=3)).isoformat()}]
    assert has_urgent_expiry(items, today=today) is True
    assert has_urgent_expiry([{"best_by": "2099-01-01"}], today=today) is False


def test_strict_miss_soft_suggest_still_returns():
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
    assert len(soft) >= 1
    assert {x["id"] for x in soft} <= {"a", "b"}
    cands, is_strict = suggest_consume_candidates(
        items, "Nulo salmon xyz", action="open"
    )
    assert is_strict is False
    assert len(cands) >= 1


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


def test_soft_suggest_empty_pantry():
    cands, is_strict = suggest_consume_candidates([], "Nulo", action="used")
    assert cands == []
    assert is_strict is False

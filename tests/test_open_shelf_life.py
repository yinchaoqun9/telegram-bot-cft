from services.open_shelf_life import open_shelf_days


def test_open_shelf_known_categories():
    assert open_shelf_days("罐头") == 2
    assert open_shelf_days("冻干") == 30
    assert open_shelf_days("药品") == 90


def test_open_shelf_fallback():
    assert open_shelf_days("") == 7
    assert open_shelf_days("未知") == 7

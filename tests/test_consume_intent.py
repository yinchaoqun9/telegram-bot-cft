from services.consume_intent import detect_consume_intent


def test_open_zh():
    action, q = detect_consume_intent("开了一罐 Ziwi 牛肉")
    assert action == "open"
    assert "Ziwi" in q or "牛肉" in q


def test_used_zh():
    action, q = detect_consume_intent("用了冻干")
    assert action == "used"
    assert "冻干" in q


def test_open_en():
    action, q = detect_consume_intent("opened Tiki Cat chicken")
    assert action == "open"
    assert "Tiki" in q or "chicken" in q


def test_used_en():
    action, q = detect_consume_intent("used the freeze dried")
    assert action == "used"


def test_finish_en_is_used():
    """Voice often says finish, not finished/used."""
    action, q = detect_consume_intent("finish 9 lives tuna can")
    assert action == "used"
    assert "9" in q.lower() or "lives" in q.lower()
    assert "tuna" in q.lower()


def test_finished_en():
    action, q = detect_consume_intent("finished the Ziwi beef")
    assert action == "used"
    assert "Ziwi" in q or "beef" in q


def test_no_intent():
    action, q = detect_consume_intent("买了两罐罐头")
    assert action is None
    assert "买了" in q

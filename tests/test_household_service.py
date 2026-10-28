from services.household_service import free_max_members, hard_max_members, make_invite_code


def test_invite_code_shape():
    code = make_invite_code()
    assert code.startswith("PET-")
    assert len(code) == 8


def test_free_max_default(monkeypatch):
    monkeypatch.delenv("HOUSEHOLD_FREE_MAX_MEMBERS", raising=False)
    monkeypatch.delenv("HOUSEHOLD_MAX_MEMBERS", raising=False)
    assert free_max_members() == 2
    assert hard_max_members() == 2


def test_paid_cap_can_raise(monkeypatch):
    monkeypatch.setenv("HOUSEHOLD_FREE_MAX_MEMBERS", "2")
    monkeypatch.setenv("HOUSEHOLD_MAX_MEMBERS", "6")
    assert free_max_members() == 2
    assert hard_max_members() == 6

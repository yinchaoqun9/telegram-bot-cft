from services.bot_i18n import (
    DEFAULT_LANG,
    language_set_confirm,
    normalize_lang,
    welcome_message,
)


def test_default_lang_is_english():
    assert DEFAULT_LANG == "en"
    assert normalize_lang(None) == "en"
    assert normalize_lang("") == "en"
    assert normalize_lang("zh-CN") == "zh"
    assert normalize_lang("EN") == "en"


def test_welcome_default_english():
    msg = welcome_message("en", is_start=True, dashboard_url="")
    assert "Hi, I’m Pet Pantry" in msg or "Hi, I'm Pet Pantry" in msg
    assert "/language" in msg


def test_welcome_chinese():
    msg = welcome_message("zh", is_start=True, dashboard_url="https://example.com/dashboard")
    assert "嗨，我是 Pet Pantry" in msg
    assert "https://example.com/dashboard" in msg


def test_language_confirm():
    assert "English" in language_set_confirm("en")
    assert "中文" in language_set_confirm("zh")

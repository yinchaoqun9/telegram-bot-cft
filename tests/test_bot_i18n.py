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
    assert "saved as spoken" in msg.lower() or "as spoken" in msg.lower()


def test_welcome_chinese():
    msg = welcome_message("zh", is_start=True, dashboard_url="https://example.com/dashboard")
    assert "嗨，我是 Pet Pantry" in msg
    assert "https://example.com/dashboard" in msg
    assert "原文" in msg


def test_language_confirm():
    assert "English" in language_set_confirm("en")
    assert "中文" in language_set_confirm("zh")


def test_t_ui_only():
    from services.bot_i18n import t

    assert "Pantry is empty" in t("en", "list_empty")
    assert "柜子是空的" in t("zh", "list_empty")
    # inventory-like content is passed through, not translated by t()
    assert "丸味" in t("en", "heard", text="丸味冻干")

"""
Per-user bot language (independent of household).

Default: English. Persist on telegram_users.lang ('en' | 'zh').
"""

from __future__ import annotations

from typing import Any, Dict, Optional

DEFAULT_LANG = "en"
SUPPORTED = ("en", "zh")


def normalize_lang(raw: Optional[str]) -> str:
    s = (raw or "").strip().lower().replace("_", "-")
    if s.startswith("zh"):
        return "zh"
    if s.startswith("en"):
        return "en"
    if s in SUPPORTED:
        return s
    return DEFAULT_LANG


def lang_from_user_row(row: Optional[Dict[str, Any]]) -> str:
    if not row:
        return DEFAULT_LANG
    return normalize_lang(row.get("lang"))


def welcome_message(lang: str, *, is_start: bool, dashboard_url: str = "") -> str:
    lang = normalize_lang(lang)
    if lang == "zh":
        return _welcome_zh(is_start=is_start, dashboard_url=dashboard_url)
    return _welcome_en(is_start=is_start, dashboard_url=dashboard_url)


def language_prompt(lang: str) -> str:
    lang = normalize_lang(lang)
    if lang == "zh":
        return (
            "当前语言：中文\n"
            "点下面按钮切换，或发送：\n"
            "/language en\n"
            "/language zh\n\n"
            "这只影响你自己；家人可以选不同语言。"
        )
    return (
        "Current language: English\n"
        "Tap a button below, or send:\n"
        "/language en\n"
        "/language zh\n\n"
        "This is per person — household members can choose differently."
    )


def language_set_confirm(lang: str) -> str:
    lang = normalize_lang(lang)
    if lang == "zh":
        return "好的，已切换为中文。之后我会用中文和你说话。"
    return "Got it — switched to English. I’ll use English from now on."


def _dash_block_en(url: str) -> str:
    if url:
        return (
            f"\n\n🌐 Web dashboard\n{url}\n"
            "Log in with Telegram — you only see your pantry."
        )
    return (
        "\n\n🌐 Web dashboard\n"
        "Ask the admin for the /dashboard link once it’s set up."
    )


def _dash_block_zh(url: str) -> str:
    if url:
        return (
            f"\n\n🌐 网页看板\n{url}\n"
            "用 Telegram 登录后，只看你自己的柜子。"
        )
    return "\n\n🌐 网页看板\n问管理员要 /dashboard 链接（需先配置好）。"


def _welcome_en(*, is_start: bool, dashboard_url: str) -> str:
    hello = (
        "Hi, I’m Pet Pantry 🐾\n"
        "Log cat/dog food, litter, and meds with your voice — English or Chinese, whatever’s easy."
        if is_start
        else "Pet Pantry cheat sheet 🐾\nVoice or text work in English or Chinese."
    )
    return (
        f"{hello}\n"
        "\n"
        "───\n"
        "🎤 Log stock\n"
        "Send a voice note, e.g.\n"
        "· “Two cans of Fancy Feast chicken, best by June 2026”\n"
        "· 「丸味冻干还剩三袋」\n"
        "You can list several items at once. After save: Fix · Open · Delete.\n"
        "\n"
        "📦 Day to day\n"
        "/list — see what’s in the pantry\n"
        "/today — suggestions for today\n"
        "Open: say “opened XX” or 「开了 XX」\n"
        "Used: say “used XX” or 「用了 XX」\n"
        "(If it’s unclear, I’ll show buttons.)\n"
        "\n"
        "✏️ Fix a mistake\n"
        "Tap Fix, or /fix\n"
        "\n"
        "👫 Share with a partner (free for 2)\n"
        "/household — create / show invite code\n"
        "/join CODE — join their pantry\n"
        "/notify on — ping when they change something\n"
        "\n"
        "🌐 Language\n"
        "/language — switch English / 中文 (yours only)\n"
        f"{_dash_block_en(dashboard_url)}\n"
        "\n"
        "Send /help anytime for this cheat sheet ✨"
    )


def _welcome_zh(*, is_start: bool, dashboard_url: str) -> str:
    hello = (
        "嗨，我是 Pet Pantry 🐾\n"
        "帮你用语音记猫狗粮、猫砂和药——中英文都行，随便说。"
        if is_start
        else "Pet Pantry 使用小抄 🐾\n中英文语音 / 文字都行。"
    )
    return (
        f"{hello}\n"
        "\n"
        "───\n"
        "🎤 怎么记库存\n"
        "直接发一条语音，例如：\n"
        "· 「丸味冻干还剩三袋」\n"
        "· “Two cans of Fancy Feast chicken, best by June 2026”\n"
        "也可以一次说好几样。保存后可点 Fix / Open / Delete。\n"
        "\n"
        "📦 每天怎么用\n"
        "/list — 看看柜子里有什么\n"
        "/today — 今天建议吃 / 用哪几样\n"
        "开封：说「开了 XX」或 opened XX\n"
        "用完：说「用了 XX」或 used XX\n"
        "（对不上时会给你按钮选）\n"
        "\n"
        "✏️ 改错了\n"
        "点 Fix，或 /fix\n"
        "\n"
        "👫 和家人共用（免费 2 人）\n"
        "/household — 创建 / 看邀请码\n"
        "/join 邀请码 — 加入对方柜子\n"
        "/notify on — 对方改动时提醒你（可关）\n"
        "\n"
        "🌐 语言\n"
        "/language — 切换 English / 中文（只影响你自己）\n"
        f"{_dash_block_zh(dashboard_url)}\n"
        "\n"
        "再发 /help 随时回来看这张小抄 ✨"
    )

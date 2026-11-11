"""
Per-user bot UI language (independent of household).

- Default: English
- Persist: telegram_users.lang ('en' | 'zh')
- Inventory fields stay as spoken (voice/text content is NOT translated)
- Only system replies use the selected language
"""

from __future__ import annotations

from typing import Any, Dict, Optional

DEFAULT_LANG = "en"
SUPPORTED = ("en", "zh")

# key -> {en, zh}; use {name} placeholders
_MESSAGES: Dict[str, Dict[str, str]] = {
    "err_download": {
        "en": "Failed to download voice. Please try again.",
        "zh": "语音下载失败，请再试一次。",
    },
    "err_generic": {
        "en": "An error occurred. Please try again later.",
        "zh": "出错了，请稍后再试。",
    },
    "err_empty_voice": {
        "en": "Voice file was empty. Please try again.",
        "zh": "语音是空的，请再发一条。",
    },
    "err_ffmpeg": {
        "en": "Voice conversion failed (server needs ffmpeg). Ask admin to redeploy with Dockerfile or Nixpacks ffmpeg.",
        "zh": "语音转换失败（服务器需要 ffmpeg）。请管理员用带 ffmpeg 的镜像重新部署。",
    },
    "err_transcribe": {
        "en": "Could not transcribe the voice message. Please try again.",
        "zh": "没听清这条语音，请再说一次。",
    },
    "err_transcribe_failed": {
        "en": "Transcription failed. Please try again.",
        "zh": "转录失败，请再试一次。",
    },
    "err_empty_transcript": {
        "en": "Could not transcribe the voice message. Please try again.",
        "zh": "没听清这条语音，请再说一次。",
    },
    "err_extract": {
        "en": "Could not extract inventory data. Please try again.",
        "zh": "没提取出库存信息，请再试一次。",
    },
    "err_no_items": {
        "en": "Could not find any inventory items in your message. Please try again.",
        "zh": "这条消息里没找到可入库的内容，请再试一次。",
    },
    "err_save": {
        "en": "Failed to save inventory. Please try again.",
        "zh": "保存失败，请再试一次。",
    },
    "err_db": {
        "en": "Database error. Please try again later.",
        "zh": "数据库出错了，请稍后再试。",
    },
    "heard": {
        "en": "Heard: {text}",
        "zh": "听到了：{text}",
    },
    "missing_id": {
        "en": "Missing item id.",
        "zh": "缺少商品 id。",
    },
    "item_not_found": {
        "en": "Item not found.",
        "zh": "找不到这件商品。",
    },
    "deleted_ok": {
        "en": "Entry deleted.",
        "zh": "已删除。",
    },
    "used_finished_open": {
        "en": "Finished an open lot (sealed qty unchanged).",
        "zh": "已核销一份开封份（密封数量不变）。",
    },
    "used_deleted": {
        "en": "Removed from inventory (quantity reached 0).",
        "zh": "数量归零，已从柜子移除。",
    },
    "used_sealed": {
        "en": "Sealed quantity reduced by 1.",
        "zh": "密封库存 −1。",
    },
    "opened_last": {
        "en": "Opened last sealed unit.",
        "zh": "已打开最后一罐/袋密封库存。",
    },
    "opened_ok": {
        "en": "Opened −1 (new open lot; sealed qty −1).",
        "zh": "已开封 −1（新增开封份；密封库存 −1）。",
    },
    "open_verb": {"en": "Open", "zh": "开封"},
    "used_verb": {"en": "Used", "zh": "用完"},
    "consume_empty": {
        "en": "Your pantry is empty. Send a voice note to log something first.",
        "zh": "柜子是空的。先发一条语音记点东西吧。",
    },
    "consume_no_open": {
        "en": "Couldn't match “{query}”, and nothing has sealed stock left to open.\nTry /today or log more with a voice note.",
        "zh": "没匹配到「{query}」，也没有可开封的密封库存。\n试试 /today，或再用语音记一点。",
    },
    "consume_no_used": {
        "en": "Couldn't match “{query}”, and nothing is available to mark used.\nTry /today or log more with a voice note.",
        "zh": "没匹配到「{query}」，也没有可标记用完的项。\n试试 /today，或再用语音记一点。",
    },
    "consume_soft_header": {
        "en": "Couldn't match “{query}”. Closest in your pantry — tap one:",
        "zh": "没精确匹配「{query}」。最接近的几项——点一下：",
    },
    "consume_which": {
        "en": "Which item to {action}?",
        "zh": "要{action}哪一项？",
    },
    "consume_done": {
        "en": "{verb}: {label}\n{detail}",
        "zh": "{verb}：{label}\n{detail}",
    },
    "consume_fail": {
        "en": "Could not update: {detail}",
        "zh": "更新失败：{detail}",
    },
    "action_open": {"en": "open", "zh": "开封"},
    "action_used": {"en": "use", "zh": "用完"},
    "today_empty_food": {
        "en": "Nothing food-like to suggest (need wet/dry/freeze-dried/treats, etc.). Try /list to see all items.",
        "zh": "没有可推荐的食物类库存（湿粮/干粮/冻干/零食等）。发 /list 看全部。",
    },
    "today_empty": {
        "en": "No eatable pantry items right now. Log something with a voice note.",
        "zh": "现在没有可吃的库存。先发语音记一点吧。",
    },
    "today_header": {
        "en": "Today’s picks (open lots first, then soonest expiry):",
        "zh": "今日推荐（开封份优先，再按保质期由近到远）：",
    },
    "list_empty": {
        "en": "Pantry is empty. Send a voice note to log food, litter, or meds.",
        "zh": "柜子是空的。发语音记粮、猫砂或药品吧。",
    },
    "list_header": {
        "en": "Your pantry ({n} item(s)) — open lots first, then soonest expiry:",
        "zh": "你的柜子（共 {n} 项）— 开封份优先，再按保质期由近到远：",
    },
    "list_more_dash": {
        "en": "\n…and {n} more. Full list: {url}",
        "zh": "\n…还有 {n} 项。完整列表：{url}",
    },
    "list_more": {
        "en": "\n…and {n} more. Open the web dashboard for the full list.",
        "zh": "\n…还有 {n} 项。打开网页看板查看全部。",
    },
    "list_footer": {
        "en": "\nOr /today for a short suggestion.",
        "zh": "\n或发 /today 看今日短推荐。",
    },
    "fix_missing": {"en": "Missing item id.", "zh": "缺少商品 id。"},
    "fix_prompt": {
        "en": (
            "Send a correction (one or more fields in one message):\n"
            "• brand  (now: {brand})\n"
            "• quantity number  (now: {qty})\n"
            "• category e.g. 罐头/can/冻干  (now: {cat})\n"
            "Example: 丸味 冻干\n"
            "Or /cancel"
        ),
        "zh": (
            "发一条修正（可一次改多项）：\n"
            "• 品牌  （现在：{brand}）\n"
            "• 数量数字  （现在：{qty}）\n"
            "• 品类，如 罐头/can/冻干  （现在：{cat}）\n"
            "例如：丸味 冻干\n"
            "或 /cancel 取消"
        ),
    },
    "fix_cancelled": {"en": "Fix cancelled.", "zh": "已取消修正。"},
    "fix_parse_fail": {
        "en": "Could not detect fields. Examples: 丸味 / 3 / 冻干 / 丸味 冻干",
        "zh": "没识别出要改的字段。例如：丸味 / 3 / 冻干 / 丸味 冻干",
    },
    "fix_updated": {
        "en": "Updated {bits}.",
        "zh": "已更新 {bits}。",
    },
    "fix_learned": {
        "en": " I'll remember the brand mapping for next time.",
        "zh": " 下次语音我会记住这个品牌对应。",
    },
    "fix_usage": {
        "en": (
            "Usage:\n"
            "/fix <item_id>  (then send e.g. 丸味 冻干)\n"
            "/fix brand <item_id> <name>\n"
            "/fix quantity <item_id> <n>\n"
            "/fix category <item_id> <罐头|can|…>\n"
            "Or tap Fix under a Saved confirmation."
        ),
        "zh": (
            "用法：\n"
            "/fix <item_id>  （然后发例如 丸味 冻干）\n"
            "/fix brand <item_id> <名称>\n"
            "/fix quantity <item_id> <数量>\n"
            "/fix category <item_id> <罐头|can|…>\n"
            "或在保存确认下点 Fix。"
        ),
    },
    "fix_usage_short": {
        "en": "Usage: /fix <item_id>  or  /fix brand|quantity|category <item_id> <value>",
        "zh": "用法：/fix <item_id>  或  /fix brand|quantity|category <item_id> <值>",
    },
    "fix_parse_that": {
        "en": "Could not parse that fix.",
        "zh": "没法解析这条修正。",
    },
    "open_used_usage": {
        "en": "Usage: {cmd} <item_id>\nCopy the id from the daily digest, or tap Open −1 after save.",
        "zh": "用法：{cmd} <item_id>\n可从每日提醒复制 id，或在保存后点「开封 −1」。",
    },
    "unknown_cmd": {
        "en": "Unknown command. Try /help · /list · /today · /dashboard · /language",
        "zh": "未知命令。试试 /help · /list · /today · /dashboard · /language",
    },
    "dashboard_link": {
        "en": "🌐 Web dashboard\n\n{url}\n\nOpen the link, then Sign in with Telegram.",
        "zh": "🌐 网页看板\n\n{url}\n\n点开链接，再用 Telegram 登录。",
    },
    "dashboard_missing": {
        "en": "Dashboard URL is not configured (set DASHBOARD_PUBLIC_URL on the server).",
        "zh": "看板地址未配置（需在服务器设置 DASHBOARD_PUBLIC_URL）。",
    },
    "pipeline_crash": {
        "en": "Something went wrong while processing your voice. Please try again.",
        "zh": "处理语音时出错了，请再试一次。",
    },
    "hh_join_usage": {
        "en": "Usage: /join PET-XXXX\nAsk your partner for their invite code.",
        "zh": "用法：/join PET-XXXX\n向对方要邀请码。",
    },
    "hh_joined": {
        "en": (
            "Joined shared pantry.\n"
            "Code: {code}\n"
            "Members: {n}/{max}\n"
            "Expiry digests go to everyone. "
            "Optional live alerts: /notify on"
        ),
        "zh": (
            "已加入共享柜子。\n"
            "邀请码：{code}\n"
            "成员：{n}/{max}\n"
            "临期提醒会发给每个人。"
            "可选实时提醒：/notify on"
        ),
    },
    "hh_notify_usage": {
        "en": (
            "Usage: /notify on  or  /notify off\n"
            "Turns partner alerts for voice / Open / Used on or off.\n"
            "Expiry digests always go to every household member."
        ),
        "zh": (
            "用法：/notify on  或  /notify off\n"
            "开关对方语音入库 / 开封 / 用完时的提醒。\n"
            "临期 digest 始终会发给每位成员。"
        ),
    },
    "hh_notify_on": {
        "en": "Partner change alerts: ON.",
        "zh": "对方变更提醒：已开启。",
    },
    "hh_notify_off": {
        "en": "Partner change alerts: OFF (digests still arrive).",
        "zh": "对方变更提醒：已关闭（digest 仍会收到）。",
    },
    "hh_status": {
        "en": (
            "Shared pantry\n"
            "Invite code: {code}\n"
            "Members: {n}/{max} (free plan ≤{free})\n"
            "Your partner alerts: {alerts}\n\n"
            "Share the code · /notify on|off · /leave"
        ),
        "zh": (
            "共享柜子\n"
            "邀请码：{code}\n"
            "成员：{n}/{max}（免费 ≤{free} 人）\n"
            "你的对方提醒：{alerts}\n\n"
            "分享邀请码 · /notify on|off · /leave"
        ),
    },
    "hh_alerts_on": {"en": "ON", "zh": "开"},
    "hh_alerts_off": {"en": "OFF", "zh": "关"},
    "hh_created": {
        "en": (
            "Created a shared pantry (free for 2 people).\n"
            "Invite code: {code}\n"
            "Partner runs: /join {code}\n"
            "Both get expiry digests. Optional live alerts: /notify on"
        ),
        "zh": (
            "已创建共享柜子（免费 2 人）。\n"
            "邀请码：{code}\n"
            "对方发送：/join {code}\n"
            "双方都会收到临期提醒。可选实时提醒：/notify on"
        ),
    },
    "hh_tables_missing": {
        "en": "Household tables may be missing. Ask admin to run the SQL in README.",
        "zh": "家庭共享表可能还没建。请管理员执行 README 里的 SQL。",
    },
    "hh_error": {
        "en": "Household error: {detail}",
        "zh": "家庭共享出错：{detail}",
    },
    "partner_voice": {
        "en": "Household update: voice logged {n} item(s) — {preview}{more}.",
        "zh": "家庭动态：语音入库 {n} 项 — {preview}{more}。",
    },
    "partner_used": {
        "en": "Household update: Used on an item (id {id}…).",
        "zh": "家庭动态：用完了一项（id {id}…）。",
    },
    "partner_open": {
        "en": "Household update: Opened −1 (id {id}…).",
        "zh": "家庭动态：开封 −1（id {id}…）。",
    },
    "partner_delete": {
        "en": "Household update: someone deleted an inventory row.",
        "zh": "家庭动态：有人删了一条库存。",
    },
    "saved_one": {
        "en": "Saved: {line}",
        "zh": "已保存：{line}",
    },
    "saved_many": {
        "en": "Saved {count} items:\n{items}",
        "zh": "已保存 {count} 项：\n{items}",
    },
    "saved_line": {
        "en": "{cat}{brand} {flavor}, expires {best_by}, quantity {qty}",
        "zh": "{cat}{brand} {flavor}，保质期 {best_by}，数量 {qty}",
    },
    "saved_footer": {
        "en": (
            "\n\nTap Fix, then send a brand name, a number (qty), or a category "
            "(罐头/can/冻干…).\n"
            "Open −1 = opened one pack/can. Delete removes the row."
        ),
        "zh": (
            "\n\n点 Fix，然后发品牌名、数量或品类（罐头/can/冻干…）。\n"
            "开封 −1 = 刚打开一罐/袋。Delete 删除整行。"
        ),
    },
    "btn_fix": {"en": "Fix", "zh": "修正"},
    "btn_open": {"en": "Open −1", "zh": "开封 −1"},
    "btn_delete": {"en": "Delete", "zh": "删除"},
    "digest_7": {
        "en": "⏰ Expiring within 7 days:",
        "zh": "⏰ 7 天内到期：",
    },
    "digest_8n": {
        "en": "⏰ Expiring in 8–{n} days:",
        "zh": "⏰ 8–{n} 天内到期：",
    },
    "digest_buttons_hint": {
        "en": (
            "Use buttons for the first {n} items, or send:\n"
            "/used <item_id>\n"
            "(copy id from the line under each item above.)"
        ),
        "zh": (
            "前 {n} 项可用按钮，或发送：\n"
            "/used <item_id>\n"
            "（从上面每项下方的 id 复制。）"
        ),
    },
    "eat_today_intro": {
        "en": "No near-expiry items today.\nToday’s picks (open lots first) — tap Open or Used:",
        "zh": "今天没有临期项。\n今日推荐（开封份优先）— 点开封或用完：",
    },
    "eat_today_footer": {
        "en": "\nOr /today anytime.",
        "zh": "\n也可以随时发 /today。",
    },
    "lang_need_sql": {
        "en": "Could not save language: {detail}\nRun the telegram_users.lang SQL in README if missing.",
        "zh": "无法保存语言：{detail}\n若缺列，请在 README 执行 telegram_users.lang SQL。",
    },
}


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


def t(lang: Optional[str], key: str, **kwargs: Any) -> str:
    """Translate UI string; inventory content should be passed in already as spoken."""
    code = normalize_lang(lang)
    entry = _MESSAGES.get(key) or {}
    template = entry.get(code) or entry.get(DEFAULT_LANG) or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, ValueError):
            return template
    return template


def language_prompt(lang: str) -> str:
    lang = normalize_lang(lang)
    if lang == "zh":
        return (
            "当前语言：中文\n"
            "点下面按钮切换，或发送：\n"
            "/language en\n"
            "/language zh\n\n"
            "这只影响你自己看到的系统回复；家人可以选不同语言。\n"
            "语音里说的品牌/口味仍按你说的原文入库。"
        )
    return (
        "Current language: English\n"
        "Tap a button below, or send:\n"
        "/language en\n"
        "/language zh\n\n"
        "This only changes system replies for you — partners can choose differently.\n"
        "What you say in a voice note is still saved as spoken (not translated)."
    )


def language_set_confirm(lang: str) -> str:
    lang = normalize_lang(lang)
    if lang == "zh":
        return (
            "好的，已切换为中文。之后系统回复用中文；"
            "语音内容仍按你说的原文记入库存。"
        )
    return (
        "Got it — switched to English. System replies will be in English; "
        "voice content is still saved as you spoke it."
    )


def welcome_message(lang: str, *, is_start: bool, dashboard_url: str = "") -> str:
    lang = normalize_lang(lang)
    if lang == "zh":
        return _welcome_zh(is_start=is_start, dashboard_url=dashboard_url)
    return _welcome_en(is_start=is_start, dashboard_url=dashboard_url)


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
        "Log cat/dog food, litter, and meds with your voice — English or Chinese, whatever’s easy.\n"
        "I’ll reply in your chosen language; what you say is saved as spoken."
        if is_start
        else "Pet Pantry cheat sheet 🐾\nSpeak EN or ZH. Replies follow /language; records keep your words."
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
        "/language — English / 中文 (yours only; doesn’t change saved brands)\n"
        f"{_dash_block_en(dashboard_url)}\n"
        "\n"
        "Send /help anytime for this cheat sheet ✨"
    )


def _welcome_zh(*, is_start: bool, dashboard_url: str) -> str:
    hello = (
        "嗨，我是 Pet Pantry 🐾\n"
        "帮你用语音记猫狗粮、猫砂和药——中英文都行。\n"
        "系统回复跟你选的语言；语音里说的品牌口味仍按原文入库。"
        if is_start
        else "Pet Pantry 使用小抄 🐾\n中英文都能说。回复跟 /language；记录保留你说的原文。"
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
        "/language — English / 中文（只影响你；不改已存品牌原文）\n"
        f"{_dash_block_zh(dashboard_url)}\n"
        "\n"
        "再发 /help 随时回来看这张小抄 ✨"
    )

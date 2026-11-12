"""Kichkina Ibrohim JARVIS v1 launcher.

Keeps the existing bot.py intact. Adds safe natural-language actions for
Telegram texts and transcribed voice notes addressed to "Jarvis".

Railway start command: python jarvis_launcher.py
No new third-party dependencies; existing bot.py and requirements.txt are used.
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

LOG = logging.getLogger("KichkinaIbrohim.JARVIS")
TZ = ZoneInfo("Asia/Tashkent")
_WAKE = re.compile(
    r"^\s*(?:(?:hey|эй)\s+)?(?:jarvis|жарвис|джарвис)\b[\s,.:;!?—–-]*",
    re.IGNORECASE,
)
ACTIONS = {
    "chat", "task_add", "tasks_list", "reminder_add", "reminders_list",
    "expense_add", "income_add", "finance_report", "unsupported",
}


def strip_wake_word(text):
    """Return message after wake phrase, or None if JARVIS wasn't addressed."""
    match = _WAKE.match(text or "")
    return text[match.end():].strip() if match else None


def validate_plan(raw):
    """Whitelist/validate AI-proposed actions; never execute arbitrary code."""
    if not isinstance(raw, dict) or raw.get("action") not in ACTIONS:
        raise ValueError("Unknown JARVIS action")
    action = raw["action"]
    params = raw.get("params") or {}
    if not isinstance(params, dict):
        raise ValueError("Invalid action parameters")

    if action == "task_add":
        title = str(params.get("title") or "").strip()
        if not 1 <= len(title) <= 500:
            raise ValueError("Task title is missing or too long")
        return action, [title]

    if action == "reminder_add":
        at = str(params.get("at") or "").strip()
        note = str(params.get("note") or "").strip()
        datetime.strptime(at, "%Y-%m-%d %H:%M")
        if not 1 <= len(note) <= 500:
            raise ValueError("Reminder text is missing or too long")
        return action, [at, note]

    if action in ("expense_add", "income_add"):
        amount_str = str(params.get("amount") or "").replace(" ", "").replace(",", ".")
        try:
            amount = Decimal(amount_str)
        except InvalidOperation as exc:
            raise ValueError("Invalid money amount") from exc
        if not amount.is_finite() or not (0 < amount <= Decimal("1000000000000")):
            raise ValueError("Invalid money amount")
        note = str(params.get("note") or "Изоҳсиз").strip()
        if len(note) > 500:
            raise ValueError("Money note too long")
        return action, [str(amount), note]

    return action, []


def parse_json(text):
    """Reject non-JSON plans rather than silently perform a wrong action."""
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I)
    return json.loads(raw)


async def make_plan(legacy, message):
    now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    instructions = (
        "You are an intent router for a private Uzbek/Russian Telegram assistant. "
        "Return ONLY one JSON object with keys action and params. "
        "Use one action from: task_add, tasks_list, reminder_add, reminders_list, "
        "expense_add, income_add, finance_report, chat, unsupported. "
        "task_add only when the user explicitly wants to SAVE a task/to-do, "
        "not when they want you to actually CREATE a document. "
        "reminder_add only when the user explicitly requests a reminder; "
        "params must be {\"at\":\"YYYY-MM-DD HH:MM\",\"note\":\"...\"}. "
        "Interpret 'tomorrow'/эртага/завтра relative to the stated Asia/Tashkent time. "
        "If date/time is unclear return chat, do not invent one. "
        "For task_add use {\"title\":\"...\"}. "
        "For expense_add and income_add use {\"amount\":\"25000\",\"note\":\"...\"}; "
        "ONLY accept amounts explicitly given in Uzbek soum/UZS. "
        "Logging income or expenses is NOT sending or transferring money. "
        "For a payment/transfer, social account manipulation, phone control, "
        "surveillance or actions with no connected implementation, choose unsupported. "
        "For ordinary questions, greetings, unclear requests, or document/search requests "
        "choose chat. Do not claim actions were completed. "
        f"Current local date and time Asia/Tashkent: {now}."
    )
    resp = await asyncio.wait_for(
        legacy.AI.responses.create(
            model=legacy.MODEL,
            instructions=instructions,
            input=message[:2000],
        ),
        timeout=45,
    )
    return validate_plan(parse_json(resp.output_text))


async def execute_action(legacy, update, context, action, args):
    """Call existing, tested handlers: same DB/Telegram messaging as slash commands."""
    handlers = {
        "task_add": legacy.task_command,
        "tasks_list": legacy.tasks_command,
        "reminder_add": legacy.remind_command,
        "reminders_list": legacy.reminders_command,
        "expense_add": legacy.expense_command,
        "income_add": legacy.income_command,
        "finance_report": legacy.report_command,
    }
    old_args = context.args
    context.args = args
    try:
        await handlers[action](update, context)
    finally:
        context.args = old_args


def install(legacy):
    """Enhance both chat() and voice_handler() through their shared dispatch function."""
    original_dispatch = legacy.dispatch_user_text

    async def jarvis_dispatch(update, context, text):
        if update.effective_chat.type != "private" or not legacy._is_owner(update):
            await update.effective_message.reply_text(
                "🔐 JARVIS фақат бот эгасининг шахсий Telegram чатида ишлайди. "
                "Railway'да BOT_OWNER_ID ни /myid билан текширинг."
            )
            return
        if not text:
            await update.effective_message.reply_text(
                "🤖 JARVIS тайёр. Масалан: «Жарвис, эртага соат 09:00 да "
                "йиғилишни эслат», «Жарвис, 25000 сўм такси харажатини ёз», "
                "«Жарвис, 5 та слайд тайёрла»."
            )
            return

        # A reminder such as "эслат: Excel тайёрла" must NOT produce
        # a spreadsheet instead of saving the reminder.
        local_action_intent = any(word in text.lower() for word in (
            "эслат", "eslat", "remind", "напомн", "вазифа", "vazifa",
            "задач", "task", "харажат", "xarajat", "расход", "expense",
            "кирим", "kirim", "доход", "income", "чиқим", "chiqim",
            "финанс", "молиявий",
        ))

        # Keep established file, news, rate, Instagram and file-follow-up tools.
        if not local_action_intent and (
            legacy._agent_kind(text)
            or legacy._file_followup_kind(text)
            or legacy._is_file_read_request(text)
            or legacy._is_instagram_story_count(text)
            or legacy._is_currency_request(text)
            or legacy._is_news_request(text)
            or legacy._is_music_request(text)
            or legacy._is_book_request(text)
        ):
            await original_dispatch(update, context, text)
            return

        try:
            action, args = await make_plan(legacy, text)
        except Exception:
            LOG.exception("JARVIS action planning failed")
            await update.effective_message.reply_text(
                "JARVIS буйруқни аниқ таснифлай олмади, шунинг учун ҳеч қандай "
                "вазифа ёки молиявий ёзув қўшилмади. Илтимос, буйруқни қайта ёзинг."
            )
            return
        if action == "unsupported":
            await update.effective_message.reply_text(
                "Ҳозир бу ҳаракат учун уланган воситам йўқ. "
                "Уни бажардим деб айтмайман."
            )
        elif action == "chat":
            await original_dispatch(update, context, text)
        else:
            try:
                await execute_action(legacy, update, context, action, args)
            except Exception:
                LOG.exception("JARVIS action failed: %s", action)
                await update.effective_message.reply_text(
                    "JARVIS буйруқни бажара олмади. Railway Logs'ни текширинг."
                )

    async def extended_dispatch(update, context, text):
        wake_text = strip_wake_word(text)
        if wake_text is None:
            await original_dispatch(update, context, text)
        else:
            await jarvis_dispatch(update, context, wake_text)

    legacy.dispatch_user_text = extended_dispatch


def main():
    import bot as legacy

    # Avoid exposing the Telegram bot token in INFO-level httpx request URLs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    install(legacy)
    legacy.main()


if __name__ == "__main__":
    main()

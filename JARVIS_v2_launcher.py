"""Kichkina Ibrohim JARVIS v2 launcher (meeting + web + Instagram routes).

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
    "expense_add", "income_add", "finance_report", "web_search",
    "instagram_post_draft", "instagram_stories_count", "meeting_start",
    "meeting_note", "meeting_summary", "meeting_end", "unsupported",
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

    if action in ("web_search", "instagram_post_draft"):
        query = str(params.get("query") or "").strip()
        if not 2 <= len(query) <= 2000:
            raise ValueError("Search or post topic missing")
        return action, [query]

    if action in ("meeting_start", "meeting_note"):
        field = "topic" if action == "meeting_start" else "note"
        value = str(params.get(field) or "").strip()
        if action == "meeting_start" and not value:
            value = "Йиғилиш"
        if not 1 <= len(value) <= 4000:
            raise ValueError("Meeting topic/note is missing or too long")
        return action, [value]

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
        "expense_add, income_add, finance_report, web_search, instagram_post_draft, "
        "instagram_stories_count, meeting_start, meeting_note, meeting_summary, meeting_end, "
        "chat, unsupported. "
        "Choose meeting_start to start a meeting notes session; params {\"topic\":\"...\"}. "
        "Choose meeting_note only when the user EXPLICITLY asks to record a note/decision; "
        "params {\"note\":\"...\"}; never invent notes. "
        "Choose meeting_summary for request to make meeting minutes or meeting protocol. "
        "Choose meeting_end when user explicitly ends the meeting. "
        "Choose web_search for public website information or live Google/Chrome searches; "
        "params {\"query\":\"user request\"}. This does NOT control user's Chrome. "
        "Choose instagram_post_draft when user explicitly requests an Instagram post draft; "
        "params {\"query\":\"post topic\"}. It does NOT publish. "
        "Choose instagram_stories_count only for current Instagram story count. "
        "For opening/controlling the user's device Chrome, logging into sites, Instagram messages, "
        "following accounts, liking posts, or unsupported actions, choose unsupported. "
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
    if action in ("meeting_start", "meeting_note", "meeting_summary", "meeting_end"):
        await run_meeting(legacy, update, context, action, args)
        return
    if action == "web_search":
        await legacy._web_answer(update, args[0], mode="search")
        return
    if action == "instagram_post_draft":
        await legacy.instagram_post_command(update, context, topic=args[0])
        return
    if action == "instagram_stories_count":
        await legacy.instagram_stories_command(update, context)
        return

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


# --- JARVIS v2: meeting journal stored in the existing PostgreSQL database ---

async def ensure_meeting_tables(legacy):
    conn = await legacy.connect()
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS jarvis_meetings (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                chat_id BIGINT NOT NULL,
                topic TEXT NOT NULL,
                started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                ended_at TIMESTAMPTZ
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS jarvis_meeting_notes (
                id BIGSERIAL PRIMARY KEY,
                meeting_id BIGINT NOT NULL REFERENCES jarvis_meetings(id),
                note TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
    finally:
        await conn.close()


async def _latest_meeting(legacy, user_id, active_only=True):
    conn = await legacy.connect()
    try:
        return await conn.fetchrow(
            "SELECT id, topic FROM jarvis_meetings "
            "WHERE user_id=$1 AND ($2::boolean = false OR ended_at IS NULL) "
            "ORDER BY id DESC LIMIT 1",
            user_id, active_only,
        )
    finally:
        await conn.close()


async def run_meeting(legacy, update, context, action, args):
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    msg = update.effective_message

    if action == "meeting_start":
        active = await _latest_meeting(legacy, uid)
        if active:
            await msg.reply_text(
                f"📝 Йиғилиш режими аллақачон фаол (#{active['id']}). "
                "«Жарвис, қайд қил: ...» деб гапиринг ёки йиғилишни якунланг."
            )
            return
        conn = await legacy.connect()
        try:
            row = await conn.fetchrow(
                "INSERT INTO jarvis_meetings (user_id,chat_id,topic) "
                "VALUES ($1,$2,$3) RETURNING id", uid, chat_id, args[0],
            )
        finally:
            await conn.close()
        await msg.reply_text(
            f"🟢 Йиғилиш режими бошланди (#{row['id']}): {args[0]}\n"
            "Қайдларни матн ёки Telegram овозли хабар билан "
            "«Жарвис, қайд қил: ...» деб юборинг. "
            "Телефон микрофонини ўзимча тингламайман."
        )
        return

    active = await _latest_meeting(legacy, uid)
    if action == "meeting_note":
        if not active:
            await msg.reply_text("Аввал «Жарвис, йиғилишни бошла» деб айтинг.")
            return
        conn = await legacy.connect()
        try:
            await conn.execute(
                "INSERT INTO jarvis_meeting_notes (meeting_id,note) VALUES ($1,$2)",
                active["id"], args[0],
            )
        finally:
            await conn.close()
        await msg.reply_text("✅ Йиғилиш қайди сақланди.")
        return

    if action == "meeting_end":
        if not active:
            await msg.reply_text("Фаол йиғилиш йўқ.")
            return
        conn = await legacy.connect()
        try:
            await conn.execute(
                "UPDATE jarvis_meetings SET ended_at=NOW() WHERE id=$1 AND user_id=$2",
                active["id"], uid,
            )
        finally:
            await conn.close()
        await msg.reply_text(
            "✅ Йиғилиш якунланди. «Жарвис, охирги йиғилиш баённомасини "
            "Word файл қилиб бер» деб сўрашингиз мумкин."
        )
        return

    if action == "meeting_summary":
        meeting = await _latest_meeting(legacy, uid, active_only=False)
        if not meeting:
            await msg.reply_text("Баённома учун ҳали йиғилиш қайдлари йўқ.")
            return
        conn = await legacy.connect()
        try:
            rows = await conn.fetch(
                "SELECT note FROM jarvis_meeting_notes WHERE meeting_id=$1 "
                "ORDER BY id LIMIT 100", meeting["id"],
            )
        finally:
            await conn.close()
        if not rows:
            await msg.reply_text("Бу йиғилишда қайдлар ҳали сақланмаган.")
            return
        source = f"Йиғилиш: {meeting['topic']}\n" + "\n".join(
            f"{i+1}. {row['note']}" for i, row in enumerate(rows)
        )
        await msg.reply_text("📝 Қайдлар асосида Word баённома тайёрлаяпман...")
        # Reuse the existing document builder: no AI-generated executable code.
        content = await asyncio.wait_for(
            legacy._agent_content(
                "Қуйидаги ҳақиқий йиғилиш қайдларига таяниб расмий баённома DOCX тайёрла. "
                "Мажлис санаси, қатнашчилар, қарорлар, масъуллар ёки муддатлар "
                "кўрсатилмаган бўлса уларни ўйлаб топма, етишмайдиганини изоҳла.",
                "docx", source[:18000],
            ),
            timeout=110,
        )
        data = legacy._agent_docx(content)
        sent = await msg.reply_document(
            document=data,
            filename=f"JARVIS_yigilish_{meeting['id']}.docx",
            caption="✅ Йиғилиш қайдлари асосида баённома тайёрланди.",
        )
        if sent and getattr(sent, "document", None):
            context.user_data["last_document"] = {
                "kind": "docx", "file_id": sent.document.file_id,
                "filename": f"JARVIS_yigilish_{meeting['id']}.docx",
            }
        return


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
                "«Жарвис, 5 та слайд тайёрла», «Жарвис, йиғилишни бошла», "
                "«Жарвис, Google'дан маълумот қидир»."
            )
            return

        # A reminder such as "эслат: Excel тайёрла" must NOT produce
        # a spreadsheet instead of saving the reminder.
        local_action_intent = any(word in text.lower() for word in (
            "эслат", "eslat", "remind", "напомн", "вазифа", "vazifa",
            "задач", "task", "харажат", "xarajat", "расход", "expense",
            "кирим", "kirim", "доход", "income", "чиқим", "chiqim",
            "финанс", "молиявий", "йиғилиш", "йигилиш", "yigilish",
            "uchrashuv", "мажлис", "meeting", "протокол", "баённома",
            "қайд", "кайд", "qayd", "record note", "chrome", "хром", "браузер",
            "интернетдан қидир", "internetdan qidir", "гугл", "google",
            "instagram", "инстаграм", "insta", "сторис", "stories",
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

    old_post_init = legacy.post_init

    async def jarvis_post_init(app):
        await old_post_init(app)
        try:
            await ensure_meeting_tables(legacy)
        except Exception:
            LOG.exception("Could not initialize JARVIS meeting tables")

    legacy.post_init = jarvis_post_init


def main():
    import bot as legacy

    # Avoid exposing the Telegram bot token in INFO-level httpx request URLs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    install(legacy)
    legacy.main()


if __name__ == "__main__":
    main()

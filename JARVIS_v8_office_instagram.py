"""JARVIS v8 add-on: two real task routers, Office and Instagram.

Works with the existing Kichkina Ibrohim bot on Railway:
    python JARVIS_v8_office_instagram.py

This module wraps JARVIS_v8_launcher.py and existing bot.py. It does not
modify their code, access user accounts, or require new credentials.

Office: generates DOCX, XLSX with optional charts, PPTX, PDF, from actual user
instructions and previously attached documents using the existing document agent.
Instagram: makes approval-gated post drafts through the existing Instagram
handler; generates editable XLSX editorial calendars; provides planning help.
Actual Instagram publication/insights require a separately configured Meta/
Make.com connection. Approval sends a draft to Make.com, not proof of posting.

Commands for the owner in private Telegram chat:
    Жарвис, агент Офис: Excel жадвал тайёрла: Сана,Сони;Душанба,12
    Жарвис, агент Офис: Word ҳисобот тайёрла: ...
    Жарвис, агент Офис: PowerPoint 5 та слайд тайёрла: ...
    Жарвис, агент Офис: PDF ҳужжат тайёрла: ...
    Жарвис, агент Инстаграм: 7 кунлик контент режа тайёрла: ...
    Жарвис, агент Инстаграм: пост тайёрла: ...
    Жарвис, агент Инстаграм: аккаунт статистикаси бўйича ҳисобот тайёрла

No command alters an Instagram account without an explicit confirmation.
Neither this file nor an attached source file contains access tokens.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

import JARVIS_v8_launcher as v8

LOG = logging.getLogger("KichkinaIbrohim.OfficeInstagram")

# Keep whole word boundaries: avoid matching arbitrary mentions of an agent.
AGENT_CALL = re.compile(
    r"(?is)^\s*(?:(?:агент|agent)\s+)?"
    r"(?P<name>microsoft\s+office|ms\s+office|office|офис|instagram|инстаграм|инста)"
    r"(?=$|\s|[:\-—])\s*[:\-—]?\s*(?P<task>.*)$"
)
OFFICE_FORMATS = (
    ("xlsx", re.compile(r"(?i)(?:\bexcel\b|\bxlsx\b|эксел|ексел|жадвал|диаграмма|таблиц|spreadsheet|contingency\s+table)")),
    ("pptx", re.compile(r"(?i)(?:\bpptx\b|\bpowerpoint\b|презентац|слайд|тақдимот|такдимот|taqdimot)")),
    ("pdf", re.compile(r"(?i)(?:\bpdf\b|пдф|пдфга)")),
    ("docx", re.compile(r"(?i)(?:\bword\b|\bdocx\b|ворд|ҳужжат|хужжат|маъруза|маълумотнома|документ|отчёт|ҳисобот|хисобот)")),
)
CALENDAR_WORD = re.compile(r"(?i)(?:режа|контент.?план|календар|контент|7\s*кун|14\s*кун|30\s*кун|ҳафталик|хафталик|недельн|content\s*plan)")
REPORT_WORD = re.compile(r"(?i)(?:ҳисобот|хисобот|отчёт|аналитик|статистик|insights|report|analytics)")
POST_WORD = re.compile(r"(?i)(?:пост|эълон|элон|caption|post|реклама|матн|описани|рилс|reels|стори|story|stories|сторис)")

OFFICE_DESC = (
    "Microsoft Office ҳужжат агенти: Word, Excel, PowerPoint ва PDF файлларини "
    "фойдаланувчи маълумотлари асосида тайёрлаш, файлларни таҳлил қилиш; "
    "асоссиз статистикани ўйлаб топмаслик."
)
INSTAGRAM_DESC = (
    "Instagram контент агенти: пост матни, контент календар, контент ғоялари, "
    "ҳисобот лойиҳаси. Эълон қилиш фақат алоҳида тасдиқ ва уланган "
    "Make.com/Meta тизими орқали; аккаунтга тўғридан-тўғри кирмайди."
)


def parse_special_agent(text: str):
    """Return (office|instagram, task) if this is an explicit agent call."""
    cleaned = v8.v2.strip_wake_word(text or "")
    if cleaned is None:
        return None
    m = AGENT_CALL.match(cleaned)
    if not m:
        return None
    name = m.group("name").strip().casefold()
    kind = "instagram" if name in {"instagram", "инстаграм", "инста"} else "office"
    return kind, (m.group("task") or "").strip()


def office_format(task: str):
    for kind, exp in OFFICE_FORMATS:
        if exp.search(task):
            return kind
    return None


def instagram_action(task: str):
    if REPORT_WORD.search(task):
        return "report"
    if CALENDAR_WORD.search(task):
        return "calendar"
    if POST_WORD.search(task):
        return "post"
    return "help"


async def office_run(legacy, update, context, task: str):
    """Produce a real document by using legacy's tested file-rendering pipeline."""
    msg = update.effective_message
    kind = office_format(task)
    if not task or kind is None:
        await msg.reply_text(
            "📂 Офис агенти тайёр. Қайси файл кераклигини айт:\n"
            "• «Жарвис, агент Офис: Word ҳисобот тайёрла: ...»\n"
            "• «Жарвис, агент Офис: Excel жадвал тайёрла: ...»\n"
            "• «Жарвис, агент Офис: PowerPoint 5 та слайд тайёрла: ...»\n"
            "• «Жарвис, агент Офис: PDF ҳужжат тайёрла: ...»\n"
            "Агар манба файли бўлса, аввал уни Telegram'га юбор."
        )
        return
    # Keep kind explicit. Prior attached source files are read by legacy agent.
    task = task[:3500]
    preamble = {
        "docx": "Word DOCX ҳужжатни файл сифатида тайёрла. ",
        "xlsx": "Excel XLSX файл ярат, диаграммани фақат ҳақиқий рақамлар бўлса қўш. ",
        "pptx": "PowerPoint PPTX слайдлар тайёрла. ",
        "pdf": "PDF ҳужжатни файл сифатида тайёрла. ",
    }[kind]
    await legacy.agent_dispatch(update, context, preamble + task, force_kind=kind)


async def instagram_run(legacy, update, context, task: str):
    """Plan/draft only, with the existing approval-gated Make.com handler."""
    msg = update.effective_message
    action = instagram_action(task)
    if action == "calendar":
        # It creates a real Excel document, not an AI promise of a file.
        prompt = (
            "Instagram Business учун таҳрирланадиган Excel контент-календар тайёрла. "
            "Жадвал устунлари: Кун/сана, Мавзу, Формат (пост/сторис/рилс), "
            "Ғоя/қисқа матн, Хештеглар, Ҳолати. "
            "Фойдаланувчи айтган кунлар сонини сақла; агар айтмаган бўлса 7 кун. "
            "Саналар берилмаган бўлса, кун рақамларини ёз; аниқ саналарни ўйлаб топма. "
            "Аккаунт статистикаси, натижалар, аудитория сонлари ёки тасдиқланмаган "
            "фактларни ўйлаб топма. Тасдиқланмагунча 'лойиҳа' ҳолатини қўй. "
            "Топшириқ: " + task[:2200]
        )
        await legacy.agent_dispatch(update, context, prompt, force_kind="xlsx")
        return
    if action == "report":
        # Existing document agent reads owner-uploaded CSV/XLSX/DOCX data.
        prompt = (
            "Instagram фаолияти ҳақида Word ҳисобот тайёрла. "
            "Фақат илова қилинган манба файлларда ёки топшириқда мавжуд "
            "рақамлардан фойдалан. Insights маълумотлари бўлмаса, "
            "«Аккаунт статистикаси уланмаган» деб очиқ ёз, ҳеч қандай "
            "қамров ёки лайк сонини ўйлаб топма. Мазмун: " + task[:2500]
        )
        await legacy.agent_dispatch(update, context, prompt, force_kind="docx")
        return
    if action == "post":
        # Existing Instagram handler shows approval buttons; clicking approval
        # only sends the draft to Make, which might later publish if configured.
        await legacy.instagram_post_command(update, context, topic=task[:2600])
        return
    await msg.reply_text(
        "📸 Instagram агенти тайёр. Мен пост лойиҳасини ва контент режасини "
        "тайёрлай оламан, ҳисоботни эса сен берган статистика асосида тузаман.\n"
        "• «Жарвис, агент Инстаграм: 7 кунлик контент режа тайёрла: ...»\n"
        "• «Жарвис, агент Инстаграм: пост тайёрла: ...»\n"
        "• «Жарвис, агент Инстаграм: статистика бўйича ҳисобот тайёрла»\n"
        "⚠️ Аккаунтга кириш ёки постни чиқариш ҳали тўлиқ уланмаган. "
        "Постни тасдиқласанг, мавжуд Make.com интеграциясига юборишга уринади."
    )


async def run_captured_if_voice_mode(legacy, update, context, work):
    """Preserve JARVIS v8's opt-in spoken reply mode for our new commands."""
    on = bool(context.user_data.get("jarvis_v8_voice_on")) and not context.user_data.get("_v8_handling_voice")
    if not on:
        await work(update)
        return
    proxy = v8.CapturedUpdate(update)
    await work(proxy)
    answer = v8.voice_excerpt(proxy.replies)
    if answer:
        await v8.speak(legacy, update.effective_message, answer)


def install(legacy):
    """Extend v8 rather than replacing any of the v2-v8 functionality."""
    v8.install(legacy)
    prior_dispatch = legacy.dispatch_user_text
    prior_post_init = legacy.post_init

    async def dispatch_with_agents(update, context, text):
        parsed = parse_special_agent(text)
        if parsed is None:
            return await prior_dispatch(update, context, text)
        if update.effective_chat.type != "private" or not legacy._is_owner(update):
            await update.effective_message.reply_text("🔐 Агентлар фақат бот эгасининг шахсий чатида ишлайди.")
            return
        kind, task = parsed

        async def perform(target_update):
            try:
                if kind == "office":
                    await office_run(legacy, target_update, context, task)
                else:
                    await instagram_run(legacy, target_update, context, task)
            except asyncio.TimeoutError:
                await target_update.effective_message.reply_text("⚠️ Агент топшириғи вақти тугади. Кейинроқ синаб кўр.")
            except Exception as exc:
                LOG.error("special agent failed: %s (%s)", kind, type(exc).__name__)
                await target_update.effective_message.reply_text("⚠️ Агентда хато бўлди. Railway Logs'ни текшир.")
        await run_captured_if_voice_mode(legacy, update, context, perform)

    async def post_init_agents(app):
        await prior_post_init(app)
        # Only create records for the owner, never for other Telegram users.
        raw = str(getattr(legacy, "OWNER_ID", "") or "").strip()
        if not raw.isdigit():
            LOG.warning("Owner ID is not configured; special agents not registered")
            return
        try:
            user_id = int(raw)
            for name, purpose in (("Офис", OFFICE_DESC), ("Инстаграм", INSTAGRAM_DESC)):
                if not await v8.get_agent(legacy, user_id, name):
                    await v8.save_agent(legacy, user_id, name, purpose)
        except Exception as exc:
            # Do not prevent bot startup on a transient DB failure.
            LOG.warning("Could not register special agents (%s)", type(exc).__name__)

    legacy.dispatch_user_text = dispatch_with_agents
    legacy.post_init = post_init_agents


def main():
    import bot as legacy
    logging.getLogger("httpx").setLevel(logging.WARNING)
    install(legacy)
    legacy.main()


if __name__ == "__main__":
    main()

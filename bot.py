
import os
import io
import re
import asyncio
import base64
import logging
import json
import urllib.request
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
import tempfile
import zipfile
from pathlib import Path
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from xml.sax.saxutils import escape

import asyncpg
from openai import AsyncOpenAI, BadRequestError
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.chart import BarChart, Reference
from pptx.util import Inches as PInches, Pt as PPt
from pptx.dml.color import RGBColor as PRGBColor
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pypdf import PdfWriter
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from docx import Document
from openpyxl import Workbook, load_workbook
from pypdf import PdfReader
from pptx import Presentation
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("KichkinaIbrohim")

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
DB_URL = os.environ["DATABASE_URL"]
AI = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
SEARCH_MODEL = os.getenv("OPENAI_SEARCH_MODEL", MODEL)
TZ = ZoneInfo("Asia/Tashkent")
MAX_FILE = 15 * 1024 * 1024
VOICE_MODEL = os.getenv("VOICE_MODEL", "gpt-transcribe")
OWNER_ID = os.getenv("BOT_OWNER_ID", "").strip()
AGENT_MAX_INPUT = 22000

SYSTEM = """
Сен Kichkina Ibrohim номли Telegram AI ёрдамчисан.
Ўзбек (кирилл ва лотин), рус ва инглиз тилларида сўров тилида жавоб бер.
Мавзу: расмий ҳужжатлар, китоблар, мусиқа, фан, технология, янгиликлар,
ўқиш, қонун, турмуш, саёҳат ва бошқа умумий маълумотлар.
Ҳеч қачон маълумотни ўйлаб топма; янги факт ва валюта курслари учун
изланиш/манба талаб этилади. Изланиш ишламаса, буни ошкора айт.
Telegram'да файл тайёрлаш вазифаси дастур функциялари билан бажарилади;
файл яратишни шу суҳбатдаги дастур бажаради. Файлни ўзинг яратганингни даъво қилма. Файлни юборишни AI матни билан эмас, фақат Telegram reply_document билан бажар. sandbox:/ каби файл ҳаволаларини ҳеч қачон тўқиб чиқарма.
Instagram аккаунтига тўғридан-тўғри кириш имконияти йўқ;
Make.com орқали конфигурация қилинган интеграция мавжуд бўлиши мумкин.
Китоб/қўшиқ ҳуқуқларини ҳурмат қил: пират юклаб олиш, тўлиқ ҳимояланган
қўшиқ сўзлари ёки китоб матнларини таклиф қилма. Қисқа мазмун ва
қонуний/расмий манба ҳаволаларини таклиф қил.
"""

HELP = """
🤖 Kichkina Ibrohim — универсал AI агент

💬 Оддий матн ёки ОВОЗ билан топшириқ беринг:
«Пахтакор тумани ҳақида 5 слайдли PPTX тайёрла»
«Шу Word файлни ўқиб, PDF ҳисобот тайёрла»
«Бугунги Ўзбекистон янгиликлари»
«100 доллар неча сўм?»
«Менга тарихий китоблар тавсия қил»
«Ўзбек қўшиқларини тавсия қил»

📁 Файллар:
/makeword матн — Word (DOCX)
/makeexcel матн — Excel ва диаграмма
/makepdf матн — PDF
/makeslides матн — PowerPoint (PPTX)
/mergepdf — аввал юборилган PDF файлларни бирлаштириш
/readfile — юборилган файл мазмунини таҳлил қилиш
/clearfiles — вақтинча сақланган файлларни тозалаш

🌐 Маълумотлар:
/search савол — интернетдан маълумот
/news мавзу — янги хабарлар, манбалари билан
/rate [USD/EUR/RUB/KZT] — Марказий банк расмий курси
/convert 100 USD — сўмга ҳисоблаш
/books мавзу — китоблар ва қисқача мазмун
/music мавзу — қўшиқчилар, қўшиқлар, расмий ҳаволалар

📸 Instagram:
/instapost мавзу — пост матни ва тасдиқлаш
/stories — фаол сторилар (алоҳида Make сценарийси керак)
/myid — Telegram ID (эгаси учун)

🗓 Режалар:
/task матн; /tasks; /done ID
/remind 2026-12-01 09:00 Йиғилиш; /reminders
/income 100000 Маош; /expense 25000 Такси; /report

🎤 Ўзбекча/русча ОВОЗЛИ ХАБАР юборинг — бот уни таниб,
матн кўринишида қайтариб, топшириқни бажаради.\n📎 Тайёр файл алоҳида Telegram ҳужжати сифатида келади.
📎 PDF, DOCX, XLSX, PPTX, TXT, CSV ва расмлар юбориш мумкин.
⚠️ Скан PDF учун алоҳида OCR керак; Instagram постини
эълон қилиш ва сторини санаш учун Make.com интеграцияси керак.
"""


async def connect():
    return await asyncpg.connect(DB_URL, timeout=15)


async def init_db():
    conn = await connect()
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                title TEXT NOT NULL,
                done BOOLEAN DEFAULT FALSE
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                chat_id BIGINT NOT NULL,
                note TEXT NOT NULL,
                due_at TIMESTAMPTZ NOT NULL,
                sent BOOLEAN DEFAULT FALSE
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS finance (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                kind TEXT NOT NULL,
                amount NUMERIC NOT NULL,
                note TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
    finally:
        await conn.close()


async def get_history(uid):
    conn = await connect()
    try:
        rows = await conn.fetch(
            """
            SELECT role, content FROM chat_history
            WHERE user_id=$1 ORDER BY id DESC LIMIT 20
            """,
            uid,
        )
        return [
            {"role": r["role"], "content": r["content"]}
            for r in reversed(rows)
        ]
    finally:
        await conn.close()


async def save_history(uid, role, content):
    conn = await connect()
    try:
        await conn.execute(
            """
            INSERT INTO chat_history(user_id,role,content)
            VALUES($1,$2,$3)
            """,
            uid, role, content[:18000],
        )
    finally:
        await conn.close()


async def send_text(message, text):
    text = text or "Жавоб топилмади."
    for i in range(0, len(text), 3900):
        await message.reply_text(text[i:i + 3900])


async def converse(update, question, image=None, search=False):
    uid = update.effective_user.id
    try:
        try:
            old = await get_history(uid)
        except Exception:
            log.exception("History error")
            old = []

        if image is not None:
            encoded = base64.b64encode(image).decode("ascii")
            content = [
                {"type": "input_text", "text": question},
                {
                    "type": "input_image",
                    "image_url": "data:image/jpeg;base64," + encoded,
                },
            ]
        else:
            content = question

        kwargs = {
            "model": MODEL,
            "instructions": SYSTEM,
            "input": old + [{"role": "user", "content": content}],
        }
        if search:
            kwargs["tools"] = [{"type": "web_search_preview"}]

        try:
            response = await AI.responses.create(**kwargs)
            answer = response.output_text or "Жавоб топилмади."
        except Exception:
            if not search:
                raise
            log.exception("Web search error")
            kwargs.pop("tools", None)
            response = await AI.responses.create(**kwargs)
            answer = (
                (response.output_text or "Жавоб топилмади.")
                + "\n\nИнтернет қидируви ишламади."
            )

        if re.search(r"sandbox:/[^\s)]+", answer, re.I):
            log.warning("Model returned a nonfunctional sandbox reference; suppressed")
            answer = (
                "⚠️ Бу Telegram'да юклаб олинадиган ҳақиқий файл эмас. "
                "Ҳужжат тайёрлаш учун мавзусини кўрсатиб: "
                "«5 та слайд тайёрла» ёки «Word ҳужжат тайёрла» деб ёзинг. "
                "Файл тайёр бўлса, уни Telegram'га алоҳида файл қилиб юбораман."
            )
        await send_text(update.effective_message, answer)

        try:
            await save_history(uid, "user", question)
            await save_history(uid, "assistant", answer)
        except Exception:
            log.exception("Save error")

    except Exception:
        log.exception("AI error")
        await update.effective_message.reply_text(
            "AI хизматида хатолик. Railway Logs'ни текширинг."
        )


async def start(update, context):
    await update.message.reply_text(HELP)


# --- Live information: web search, culture, news and Central Bank rates ---

CBU_API = "https://cbu.uz/uz/arkhiv-kursov-valyut/json/"
CURRENCY_NAMES = {
    "доллар": "USD", "долларов": "USD", "dollar": "USD", "dollars": "USD", "usd": "USD", "$": "USD",
    "евро": "EUR", "euro": "EUR", "eur": "EUR",
    "рубл": "RUB", "rubl": "RUB", "ruble": "RUB", "rub": "RUB",
    "тенге": "KZT", "тенгэ": "KZT", "teng": "KZT", "kzt": "KZT",
    "юан": "CNY", "yuan": "CNY", "cny": "CNY",
    "фунт": "GBP", "gbp": "GBP", "йен": "JPY", "jpy": "JPY",
}


def _currency_code(text):
    t = (text or "").lower()
    for word, code in CURRENCY_NAMES.items():
        if word in t:
            return code
    for word in re.findall(r"[A-Za-z]{3}", text or ""):
        if word.upper() in ("USD", "EUR", "RUB", "KZT", "CNY", "GBP", "JPY"):
            return word.upper()
    return None


def _is_currency_request(text):
    t = (text or "").lower()
    if not _currency_code(t):
        return False
    return any(w in t for w in (
        "курс", "қурc", "kurs", "exchange", "неча", "канча", "қанча",
        "сколько", "сум", "сўм", "som", "uzs", "айирбош", "перевод", "конверт"
    ))


def _is_news_request(text):
    t = (text or "").lower()
    return any(x in t for x in (
        "янгилик", "yangilik", "новост", "news", "сўнгги хабар", "свежие события",
        "latest", "сегодня в мире", "бугун дунёда"
    ))


def _is_music_request(text):
    t = (text or "").lower()
    return any(x in t for x in (
        "қўшиқ", "кушик", "qo'shiq", "qoshiq", "мусиқа", "музыка", "music",
        "песн", "song", "хонанда", "певец", "певиц", "альбом", "трек", "track"
    ))


def _is_book_request(text):
    t = (text or "").lower()
    return any(x in t for x in (
        "китоб", "kitob", "книга", "книг", "books", "book", "роман", "муаллиф", "автор"
    ))


def _get_cbu_rates():
    request = urllib.request.Request(
        CBU_API, headers={"User-Agent": "KichkinaIbrohimBot/3.0", "Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=14) as response:
        rows = json.load(response)
    if not isinstance(rows, list):
        raise ValueError("CBU returned unexpected data")
    return {r["Ccy"].upper(): r for r in rows if isinstance(r, dict) and r.get("Ccy")}


def _currency_amount(text):
    # Number before/after ISO code or currency word: 100 USD, 100 доллар.
    pat = r"(?:USD|EUR|RUB|KZT|CNY|GBP|JPY|доллар(?:ов)?|евро|рубл[ьяей]*|тенге|\$)"
    s = (text or "").replace("\u00a0", " ")
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*" + pat, s, re.I)
    if not match:
        match = re.search(pat + r"\s*(\d+(?:[.,]\d+)?)", s, re.I)
    if not match:
        return None
    try:
        value = Decimal(match.group(1).replace(",", "."))
        return value if value > 0 and value <= Decimal("1000000000") else None
    except InvalidOperation:
        return None


def _format_currency_rate(row):
    nominal = Decimal(str(row.get("Nominal", "1")).replace(" ", ""))
    rate = Decimal(str(row["Rate"]).replace(" ", "").replace(",", "."))
    if nominal <= 0 or rate <= 0:
        raise ValueError("Invalid rate")
    date = str(row.get("Date") or "сана кўрсатилмаган")
    return (rate / nominal, date, nominal)


async def rate_reply(update, text, show_all=False):
    await update.effective_message.reply_text("💱 Марказий банк курсларини текширяпман...")
    try:
        rates = await asyncio.to_thread(_get_cbu_rates)
        code = _currency_code(text)
        selected = ("USD", "EUR", "RUB", "KZT") if show_all or not code else (code,)
        lines = ["💱 Ўзбекистон Марказий банкининг расмий курслари:"]
        for c in selected:
            if c not in rates:
                lines.append(f"{c}: маълумот топилмади")
                continue
            one, date, nominal = _format_currency_rate(rates[c])
            lines.append(f"1 {c} = {one:,.2f} сўм (амал қилиш санаси: {date})")
        amount = _currency_amount(text)
        if amount is not None and code in rates:
            one, _, _ = _format_currency_rate(rates[code])
            lines.append(f"\n{amount:,.2f} {code} ≈ {(amount * one):,.2f} сўм")
        lines.append("\nМанба: https://cbu.uz/uz/arkhiv-kursov-valyut/")
        lines.append("Эслатма: банкларнинг сотиб олиш/сотиш курслари фарқ қилиши мумкин.")
        await update.effective_message.reply_text("\n".join(lines))
    except (HTTPError, URLError, ValueError, KeyError, InvalidOperation, TimeoutError):
        log.exception("CBU request failed")
        await update.effective_message.reply_text("Марказий банкдан ҳозир курс олиб бўлмади. https://cbu.uz/uz/arkhiv-kursov-valyut/")


async def rates_command(update, context):
    await rate_reply(update, " ".join(context.args), show_all=not bool(context.args))


async def convert_command(update, context):
    query = " ".join(context.args).strip()
    if not query or _currency_code(query) is None or _currency_amount(query) is None:
        await update.effective_message.reply_text("Масалан: /convert 100 USD ёки /convert 250 EUR")
        return
    await rate_reply(update, query)


async def myid_command(update, context):
    await update.effective_message.reply_text(
        f"Сизнинг Telegram ID: {update.effective_user.id}\n"
        "Instagram'ни фақат ўзингиз бошқариш учун Railway Variables'га BOT_OWNER_ID қўшинг."
    )


def _is_owner(update):
    return OWNER_ID.isdecimal() and str(update.effective_user.id) == OWNER_ID


async def _web_answer(update, question, *, mode="search"):
    """Only claim live sources if hosted search really succeeds."""
    ask = (question or "").strip()[:2000]
    if not ask:
        await update.effective_message.reply_text("Қандай мавзуни қидирай? Масалан: /news Ўзбекистон")
        return
    await update.effective_message.reply_text("🌐 Интернетдан маълумот қидиряпман...")
    today = datetime.now(TZ).date().isoformat()
    search_prompt = (
        f"Бугунги сана: {today}. Фойдаланувчининг тилида жавоб бер. "
        "Манбаларнинг ҳаволалари ва хабар саналарини кўрсат, "
        "ўйлаб топилган ҳавола/сана ёзма. Текширилмаган янгиликни факт сифатида айтма. "
        "Қисқача, мазмунли ва иложи бўлса 3-6 асосий пункт билан ёз."
    )
    if mode == "music":
        search_prompt += " Мусиқа/қўшиқ учун ижрочи, альбом, расмий манба ва қонуний тинглаш ҳаволаларини бер. Тўлиқ қўшиқ матнини берма."
    elif mode == "books":
        search_prompt += " Китоб номи, муаллифи, жанри, қисқача мазмун ва қонуний манбани бер. Муаллифлик ҳуқуқини ҳурмат қил."
    search_error = None
    for tool_type in ("web_search", "web_search_preview"):
        try:
            resp = await asyncio.wait_for(
                AI.responses.create(
                    model=SEARCH_MODEL,
                    instructions=search_prompt,
                    input=ask,
                    tools=[{"type": tool_type}],
                    tool_choice="required",
                ),
                timeout=85,
            )
            # Search tool output is authoritative for whether search was attempted.
            if not any(getattr(x, "type", "") == "web_search_call" for x in getattr(resp, "output", [])):
                raise ValueError("no actual web search occurred")
            answer = resp.output_text or "Маълумот топилмади."
            links = []
            for item in getattr(resp, "output", []):
                for part in getattr(item, "content", []) or []:
                    for annotation in getattr(part, "annotations", []) or []:
                        if getattr(annotation, "type", "") == "url_citation":
                            uri = getattr(annotation, "url", "")
                            if uri.startswith("https://") and uri not in links:
                                links.append(uri)
            if links:
                answer += "\n\n🔗 Текширилган манбалар:\n" + "\n".join(links[:5])
            await send_text(update.effective_message, answer)
            return
        except Exception as exc:
            search_error = exc
            log.warning("Web search (%s) unavailable: %s", tool_type, type(exc).__name__)
    log.error("All web search methods failed: %r", search_error)
    await update.effective_message.reply_text(
        "Ҳозир жонли интернет қидируви ишламади. Шунинг учун янги хабарларни ёки расмий ҳаволаларни ўйлаб топмайман. "
        "Railway Logs ва OpenAI API web_search рухсатларини текширинг."
    )


async def news_command(update, context):
    await _web_answer(update, " ".join(context.args) or "Ўзбекистон ва жаҳоннинг сўнгги муҳим янгиликлари", mode="news")


async def music_command(update, context):
    await _web_answer(update, " ".join(context.args) or "Ўзбекистондаги машҳур ва янги қўшиқлар", mode="music")


async def books_command(update, context):
    topic = " ".join(context.args) or "Мени қизиқтириши мумкин бўлган 5 та яхши китоб тавсия қил"
    if any(w in topic.lower() for w in ("янги", "2026", "охирги", "муаллиф", "сотиб", "ссылка", "ҳавола", "скач")):
        await _web_answer(update, topic, mode="books")
    else:
        await converse(update, topic)


async def readfile_command(update, context):
    await analyze_recent_file(update, context, "Юборилган файл(лар)ни ўқи, асосий маълумот ва рақамларни тушунтир")


async def clearfiles_command(update, context):
    for key in ("agent_files", "agent_photo"):
        context.user_data.pop(key, None)
    await update.effective_message.reply_text("🧹 Юборилган файлларнинг вақтинчалик нусхалари тозаланди.")


async def information_dispatch(update, context, text):
    """Natural language commands should use the real tool before AI chatter."""
    t = (text or "").lower()
    # News and currency always require real external sources.
    if _is_currency_request(text):
        await rate_reply(update, text)
        return True
    if _is_news_request(text):
        await _web_answer(update, text, mode="news")
        return True
    if _is_music_request(text) and not _agent_kind(text):
        await _web_answer(update, text, mode="music")
        return True
    if _is_book_request(text) and not _agent_kind(text):
        if any(w in t for w in ("янги", "2026", "сотиб", "ҳавола", "ссылка", "yangi", "latest")):
            await _web_answer(update, text, mode="books")
        else:
            await converse(update, text)
        return True
    return False


def _file_followup_kind(text):
    """Short follow-ups like 'Slayd fayl qani?' must not go to free chat."""
    t = (text or "").lower().strip()
    if len(t) > 170:
        return None
    if not any(x in t for x in (
        "қани", "qani", "где", "where", "кани", "қайерда", "qayerda",
        "файлни юбор", "faylni yubor", "файл ташла", "fayl tashla",
        "скинь файл", "отправь файл", "файл йўқ", "fayl yo'q",
        "yoqku fayl", "yo'qku fayl", "йўқку файл", "файл қани", "fayl qani",
    )):
        return None
    if any(x in t for x in ("слайд", "slayd", "pptx", "powerpoint", "презентац", "тақдимот")):
        return "pptx"
    if any(x in t for x in ("word", "ворд", "docx", "ҳужжат", "hujjat")):
        return "docx"
    if any(x in t for x in ("excel", "эксел", "xlsx", "жадвал", "jadval")):
        return "xlsx"
    if any(x in t for x in ("pdf", "пдф")):
        return "pdf"
    if any(x in t for x in ("файл", "fayl", "file")):
        return "last"
    return None


async def _artifact_followup_dispatch(update, context, text):
    """Resend a REAL Telegram document or regenerate the last matching task."""
    kind = _file_followup_kind(text)
    if not kind:
        return False
    last_doc = context.user_data.get("last_document") or {}
    last = context.user_data.get("last_agent_request") or {}
    if kind == "last":
        kind = last_doc.get("kind") or last.get("kind") or "last"
    if last_doc.get("kind") == kind and last_doc.get("file_id"):
        await update.effective_message.reply_document(
            document=last_doc["file_id"],
            caption="📎 Мана олдин тайёрланган файл.",
        )
        return True

    prompt = last.get("prompt") if last.get("kind") == kind else None
    if not prompt:
        try:
            history = await get_history(update.effective_user.id)
            for entry in reversed(history):
                previous = str(entry.get("content", ""))
                previous_kind = _agent_kind(previous)
                if entry.get("role") == "user" and previous_kind and (previous_kind == kind or kind == "last"):
                    prompt = previous
                    kind = previous_kind
                    break
        except Exception:
            log.exception("Cannot retrieve previous document request")
    if not prompt:
        await update.effective_message.reply_text(
            "📎 Ҳақиқий файл ҳали тайёрланмаган. "
            "Мавзусини ёзинг, масалан: «Пахтакор тумани ҳақида 5 та слайд тайёрла»."
        )
        return True
    await update.effective_message.reply_text("📎 Олдинги топшириқ бўйича файлни тайёрлаяпман...")
    await agent_dispatch(update, context, prompt, force_kind=kind)
    return True


async def dispatch_user_text(update, context, text):
    """Single action router for typed and transcribed Telegram messages."""
    if _is_instagram_story_count(text):
        await instagram_stories_command(update, context)
        return
    if await _artifact_followup_dispatch(update, context, text):
        return
    if _is_file_read_request(text):
        await analyze_recent_file(update, context, text)
        return
    if await information_dispatch(update, context, text):
        return
    if await agent_dispatch(update, context, text):
        return
    await converse(update, text)


async def chat(update, context):
    await dispatch_user_text(update, context, update.effective_message.text or "")


async def search_command(update, context):
    await _web_answer(update, " ".join(context.args), mode="search")


async def photo_handler(update, context):
    try:
        photo = update.message.photo[-1]
        if photo.file_size and photo.file_size > MAX_FILE:
            await update.message.reply_text(
                "Расм 15 MB дан кичик бўлсин."
            )
            return
        file = await photo.get_file()
        data = bytes(await file.download_as_bytearray())
        context.user_data["agent_photo"] = data
        caption = update.message.caption or "Расмни таҳлил қил."
        if not await agent_dispatch(update, context, caption):
            await converse(update, caption, image=data)
    except Exception:
        log.exception("Photo error")
        await update.message.reply_text("Расмда хатолик.")


async def _transcribe_recording(data, filename):
    """Transcribe Uzbek, Russian and other supported languages without translating them."""
    if not data:
        raise ValueError("empty audio recording")
    audio = io.BytesIO(data)
    audio.name = filename
    try:
        result = await asyncio.wait_for(
            AI.audio.transcriptions.create(
                model=VOICE_MODEL,
                file=audio,
                prompt=(
                    "Ушбу ёзув ўзбекча (кирилл/лотин) ёки русча бўлиши мумкин. "
                    "Пахтакор тумани, ИИВ, маҳалла, маъруза, ҳисобот, PPTX, Word, "
                    "Excel, Instagram, доллар, курс, қўшиқ, китоб. "
                    "Гапни эшитилган тилида айнан матнга кўчир."
                ),
            ),
            timeout=95,
        )
    except BadRequestError:
        # Some providers may not support a prompt for a configured transcription model.
        audio.seek(0)
        result = await asyncio.wait_for(
            AI.audio.transcriptions.create(model=VOICE_MODEL, file=audio),
            timeout=95,
        )
    return (getattr(result, "text", "") or "").strip()


async def voice_handler(update, context):
    msg = update.effective_message
    recording = msg.voice or msg.audio
    if not recording:
        return
    if recording.file_size and recording.file_size > MAX_FILE:
        await msg.reply_text("Овозли файл 15 MB дан кичик бўлсин.")
        return
    await msg.reply_text("🎤 Овозли хабарни эшитиб, ўзбекча/русча матнга айлантиряпман...")
    try:
        telegram_file = await recording.get_file()
        data = bytes(await telegram_file.download_as_bytearray())
        # Telegram voice notes are OGG/Opus; extension-bearing filenames matter.
        filename = getattr(recording, "file_name", None) or "voice.ogg"
        text = await _transcribe_recording(data, filename)
        if not text:
            await msg.reply_text("Овоз тушунарли эмас. Илтимос, қисқароқ ва аниқроқ ёзиб юборинг.")
            return
        await send_text(msg, "🎤 Тушунганим: " + text[:1400])
        await dispatch_user_text(update, context, text)
    except Exception:
        log.exception("Voice transcription/dispatch error")
        await msg.reply_text(
            "Овозни танишда хатолик. Railway Logs'да аниқ сабаб кўринади. "
            "OpenAI API калити, баланс ва VOICE_MODEL=gpt-transcribe эканини текширинг."
        )


async def document_handler(update, context):
    item = update.message.document
    if item.file_size and item.file_size > MAX_FILE:
        await update.message.reply_text(
            "Файл 15 MB дан кичик бўлсин."
        )
        return

    try:
        file = await item.get_file()
        data = bytes(await file.download_as_bytearray())
        stream = io.BytesIO(data)
        name = (item.file_name or "").lower()
        if name.endswith((".ogg", ".oga", ".mp3", ".m4a", ".wav", ".webm", ".mp4")):
            await update.message.reply_text("🎤 Аудио файлини матнга айлантиряпман...")
            transcript = await _transcribe_recording(data, name)
            if not transcript:
                await update.message.reply_text("Овозли файлдан матн олинмади.")
                return
            await send_text(update.message, "🎤 Тушунганим: " + transcript[:1400])
            await dispatch_user_text(update, context, transcript)
            return
        if name.endswith((".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".csv")):
            attachments = context.user_data.setdefault("agent_files", [])
            attachments.append({"name": item.file_name or "file", "data": data})
            del attachments[:-3]
        if name.endswith(".pptx"):
            prs = Presentation(stream)
            content = "\n".join(shape.text for slide in prs.slides for shape in slide.shapes if shape.has_text_frame)
            if update.message.caption:
                await agent_dispatch(update, context, update.message.caption)
            else:
                await update.message.reply_text("Файл қабул қилинди. Нима қилишимни ёзинг: таҳрирлаш, таҳлил ёки янги файл яратиш.")
            return

        if name.endswith(".pdf"):
            reader = PdfReader(stream)
            content = "\n".join(
                p.extract_text() or ""
                for p in reader.pages[:30]
            )
        elif name.endswith(".docx"):
            doc = Document(stream)
            parts = [p.text for p in doc.paragraphs]
            for table in doc.tables:
                for row in table.rows:
                    parts.append(
                        " | ".join(c.text for c in row.cells)
                    )
            content = "\n".join(parts)
        elif name.endswith(".xlsx"):
            wb = load_workbook(
                stream, read_only=True, data_only=True
            )
            parts = []
            for ws in wb.worksheets[:5]:
                parts.append("Варақ: " + ws.title)
                for row in ws.iter_rows(
                    max_row=150,
                    max_col=20,
                    values_only=True,
                ):
                    parts.append(
                        " | ".join(
                            str(v) if v is not None else ""
                            for v in row
                        )
                    )
            wb.close()
            content = "\n".join(parts)
        elif name.endswith((".txt", ".csv")):
            content = data.decode(
                "utf-8-sig", errors="replace"
            )
        else:
            await update.message.reply_text(
                "PDF, DOCX, XLSX, TXT ёки CSV юборинг."
            )
            return

        if not content.strip():
            await update.message.reply_text(
                "Матн топилмади. Скан PDF учун OCR керак."
            )
            return

        if not update.message.caption:
            await update.message.reply_text("📎 Файл сақланди. Энди нима тайёрлашимни ёзинг. Масалан: «Шу файлдан 5 та слайд тайёрла».")
            return
        if await agent_dispatch(update, context, update.message.caption):
            return
        question = (
            update.message.caption
            or "Ушбу ҳужжатни таҳлил қил."
        )
        await converse(
            update,
            question + "\n\n" + content[:16000],
        )
    except Exception:
        log.exception("Document error")
        await update.message.reply_text(
            "Ҳужжатни ўқишда хатолик."
        )


async def task_command(update, context):
    title = " ".join(context.args).strip()
    if not title:
        await update.message.reply_text(
            "Масалан: /task Ҳисобот тайёрлаш"
        )
        return

    conn = await connect()
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO tasks(user_id,title)
            VALUES($1,$2) RETURNING id
            """,
            update.effective_user.id, title,
        )
    finally:
        await conn.close()
    await update.message.reply_text(
        f"Вазифа қўшилди: #{row['id']}"
    )


async def tasks_command(update, context):
    conn = await connect()
    try:
        rows = await conn.fetch(
            """
            SELECT id,title,done FROM tasks
            WHERE user_id=$1 ORDER BY id DESC LIMIT 30
            """,
            update.effective_user.id,
        )
    finally:
        await conn.close()

    result = "\n".join(
        ("✅" if r["done"] else "⬜")
        + f" #{r['id']} {r['title']}"
        for r in rows
    )
    await send_text(
        update.message, result or "Вазифалар йўқ."
    )


async def done_command(update, context):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "Масалан: /done 1"
        )
        return

    conn = await connect()
    try:
        result = await conn.execute(
            """
            UPDATE tasks SET done=TRUE
            WHERE user_id=$1 AND id=$2
            """,
            update.effective_user.id,
            int(context.args[0]),
        )
    finally:
        await conn.close()

    await update.message.reply_text(
        "Бажарилди."
        if result.endswith("1")
        else "Вазифа топилмади."
    )


async def remind_command(update, context):
    text = " ".join(context.args)
    match = re.match(
        r"^(\d{4}-\d{2}-\d{2})\s+"
        r"(\d{2}:\d{2})\s+(.+)$",
        text, re.S,
    )
    if not match:
        await update.message.reply_text(
            "Масалан: /remind 2026-12-01 09:00 Йиғилиш"
        )
        return

    try:
        due = datetime.strptime(
            match.group(1) + " " + match.group(2),
            "%Y-%m-%d %H:%M",
        ).replace(tzinfo=TZ)
    except ValueError:
        await update.message.reply_text(
            "Сана нотўғри."
        )
        return

    if due <= datetime.now(TZ):
        await update.message.reply_text(
            "Келажакдаги вақтни киритинг."
        )
        return

    conn = await connect()
    try:
        await conn.execute(
            """
            INSERT INTO reminders
            (user_id,chat_id,note,due_at)
            VALUES($1,$2,$3,$4)
            """,
            update.effective_user.id,
            update.effective_chat.id,
            match.group(3), due,
        )
    finally:
        await conn.close()
    await update.message.reply_text("Эслатма сақланди.")


async def reminders_command(update, context):
    conn = await connect()
    try:
        rows = await conn.fetch(
            """
            SELECT id,note,due_at FROM reminders
            WHERE user_id=$1 AND sent=FALSE
            ORDER BY due_at LIMIT 20
            """,
            update.effective_user.id,
        )
    finally:
        await conn.close()

    text = "\n".join(
        f"#{r['id']} "
        f"{r['due_at'].astimezone(TZ):%Y-%m-%d %H:%M}"
        f" — {r['note']}"
        for r in rows
    )
    await send_text(
        update.message, text or "Эслатмалар йўқ."
    )


async def reminder_worker(app):
    while True:
        try:
            conn = await connect()
            try:
                rows = await conn.fetch("""
                    SELECT id,chat_id,note FROM reminders
                    WHERE sent=FALSE AND due_at<=NOW()
                    ORDER BY due_at LIMIT 20
                """)
                for row in rows:
                    try:
                        await app.bot.send_message(
                            row["chat_id"],
                            "⏰ Эслатма: " + row["note"],
                        )
                        await conn.execute(
                            """
                            UPDATE reminders SET sent=TRUE
                            WHERE id=$1
                            """,
                            row["id"],
                        )
                    except Exception:
                        log.exception("Reminder send error")
            finally:
                await conn.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Reminder worker error")
        await asyncio.sleep(30)


async def finance_command(update, context, kind):
    if not context.args:
        await update.message.reply_text(
            "Масалан: /expense 25000 Такси"
        )
        return

    try:
        amount = Decimal(
            context.args[0].replace(",", ".")
        )
        if not amount.is_finite() or amount <= 0:
            raise ValueError()
    except Exception:
        await update.message.reply_text(
            "Суммани тўғри киритинг."
        )
        return

    note = " ".join(context.args[1:]) or "Изоҳсиз"
    conn = await connect()
    try:
        await conn.execute(
            """
            INSERT INTO finance(user_id,kind,amount,note)
            VALUES($1,$2,$3,$4)
            """,
            update.effective_user.id,
            kind, amount, note,
        )
    finally:
        await conn.close()
    await update.message.reply_text(
        f"Сақланди: {amount} сўм."
    )


async def income_command(update, context):
    await finance_command(update, context, "income")


async def expense_command(update, context):
    await finance_command(update, context, "expense")


async def report_command(update, context):
    conn = await connect()
    try:
        rows = await conn.fetch(
            """
            SELECT kind,COALESCE(SUM(amount),0) AS total
            FROM finance WHERE user_id=$1 GROUP BY kind
            """,
            update.effective_user.id,
        )
    finally:
        await conn.close()

    totals = {r["kind"]: r["total"] for r in rows}
    income = totals.get("income", Decimal(0))
    expense = totals.get("expense", Decimal(0))

    await update.message.reply_text(
        "📊 Молиявий ҳисобот\n\n"
        f"Кирим: {income:,.0f} сўм\n"
        f"Чиқим: {expense:,.0f} сўм\n"
        f"Қолдиқ: {income-expense:,.0f} сўм"
    )


async def makeword(update, context):
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text(
            "Масалан: /makeword Ҳисобот матни"
        )
        return

    doc = Document()
    doc.add_heading("Kichkina Ibrohim", 0)
    doc.add_paragraph(text)

    stream = io.BytesIO()
    doc.save(stream)
    stream.seek(0)

    await update.message.reply_document(
        document=stream,
        filename="hujjat.docx",
    )


async def makeexcel(update, context):
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text(
            "Масалан: /makeexcel Исм,Сони;Али,5"
        )
        return

    wb = Workbook()
    ws = wb.active
    ws.title = "Маълумотлар"

    for line in text.split(";"):
        ws.append([
            value.strip() for value in line.split(",")
        ])

    stream = io.BytesIO()
    wb.save(stream)
    stream.seek(0)

    await update.message.reply_document(
        document=stream,
        filename="jadval.xlsx",
    )


async def makepdf(update, context):
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text(
            "Масалан: /makepdf Ҳисобот матни"
        )
        return

    font_path = (
        "/usr/share/fonts/truetype/dejavu/"
        "DejaVuSans.ttf"
    )
    font_name = "Helvetica"

    if os.path.exists(font_path):
        if "DejaVu" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(
                TTFont("DejaVu", font_path)
            )
        font_name = "DejaVu"

    style = ParagraphStyle(
        "Custom",
        fontName=font_name,
        fontSize=11,
        leading=16,
    )

    stream = io.BytesIO()
    pdf = SimpleDocTemplate(stream, pagesize=A4)
    story = [
        Paragraph(escape(line) or " ", style)
        for line in text.split("\n")
    ]
    pdf.build(story)
    stream.seek(0)

    await update.message.reply_document(
        document=stream,
        filename="hujjat.pdf",
    )


async def makeslides(update, context):
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text(
            "Масалан: /makeslides Мавзу;Слайд1;Слайд2"
        )
        return

    parts = [
        p.strip() for p in text.split(";") if p.strip()
    ]
    prs = Presentation()

    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = parts[0]
    slide.placeholders[1].text = "Kichkina Ibrohim"

    for part in parts[1:]:
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = part
        slide.placeholders[1].text = part

    stream = io.BytesIO()
    prs.save(stream)
    stream.seek(0)

    await update.message.reply_document(
        document=stream,
        filename="taqdimot.pptx",
    )


# Commands share the same structured AI agent as natural-language prompts.
async def professional_word(update, context):
    prompt = " ".join(context.args).strip()
    if not prompt:
        await update.effective_message.reply_text("Масалан: /makeword Пахтакор тумани бўйича маъруза тайёрла")
        return
    await agent_dispatch(update, context, "Word DOCX файл қилиб тайёрла: " + prompt)


async def professional_excel(update, context):
    prompt = " ".join(context.args).strip()
    if not prompt:
        await update.effective_message.reply_text("Масалан: /makeexcel 2025 ва 2026 йил жиноятчилик рақамлари бўйича диаграмма")
        return
    await agent_dispatch(update, context, "Excel XLSX жадвал ва диаграмма қилиб тайёрла: " + prompt)


async def professional_pdf(update, context):
    prompt = " ".join(context.args).strip()
    if not prompt:
        await update.effective_message.reply_text("Масалан: /makepdf Хавфсиз муҳит бўйича ҳисобот")
        return
    await agent_dispatch(update, context, "PDF ҳужжат тайёрла: " + prompt)


async def professional_slides(update, context):
    prompt = " ".join(context.args).strip()
    if not prompt:
        await update.effective_message.reply_text("Масалан: /makeslides Пахтакор туманида хавфсиз муҳит бўйича 5 слайд")
        return
    await agent_dispatch(update, context, "PowerPoint PPTX слайд тайёрла: " + prompt)


async def instagram_post_command(update, context, topic=None):
    if not _is_owner(update):
        await update.effective_message.reply_text(
            "🔐 Instagram бошқаруви фақат бот эгаси учун. "
            "Telegram'да /myid ни босинг ва Railway Variables'га BOT_OWNER_ID қўшинг."
        )
        return
    if update.effective_chat.type != "private":
        await update.message.reply_text("Бу буйруқни ботга шахсий чатда юборинг.")
        return

    topic = (topic if topic is not None else " ".join(context.args)).strip()
    if not topic:
        await update.message.reply_text(
            "Масалан: /instapost Янги маҳсулотимиз ҳақида пост"
        )
        return

    try:
        response = await AI.responses.create(
            model=MODEL,
            instructions=(
                "Instagram Business аккаунти учун тайёр пост матнини ёз. "
                "Мавзу тилида ёз, аниқ ва жозибали бўлсин. "
                "Асоссиз фактларни ўйлаб топма. "
                "Сарлавҳа, қисқа матн ва мос хештеглар бер."
            ),
            input=topic,
        )
        caption = (response.output_text or "").strip()
        if not caption:
            raise ValueError("AI returned empty caption")
        caption = caption[:3500]
        context.user_data["instagram_draft"] = caption
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Тасдиқлаш", callback_data="ig:approve"),
            InlineKeyboardButton("❌ Рад этиш", callback_data="ig:reject"),
        ]])
        await update.message.reply_text(
            "📸 Instagram пост лойиҳаси:\n\n" + caption +
            "\n\nТасдиқласангиз, матн Make.com'га юборилади. "
            "Ҳозирча Instagram'да эълон қилинмайди.",
            reply_markup=keyboard,
        )
    except Exception:
        log.exception("Instagram draft error")
        await update.message.reply_text("Пост тайёрлашда хатолик юз берди.")


def _send_instagram_webhook(url, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        if not 200 <= resp.status < 300:
            raise RuntimeError(f"Webhook HTTP status: {resp.status}")


async def instagram_approval(update, context):
    query = update.callback_query
    await query.answer()
    if not _is_owner(update):
        await query.message.reply_text("🔒 Бу Instagram тасдиғи фақат бот эгаси учун.")
        return
    if query.message.chat.type != "private":
        return
    draft = context.user_data.get("instagram_draft")
    if not draft:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("Лойиҳа топилмади. /instapost билан қайта тайёрланг.")
        return

    if query.data == "ig:reject":
        context.user_data.pop("instagram_draft", None)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("❌ Пост рад этилди.")
        return

    if context.user_data.get("instagram_sending"):
        await query.message.reply_text("Юбориш жараёни кетмоқда, кутиб туринг.")
        return
    url = os.getenv("MAKE_WEBHOOK_URL", "").strip()
    if not url.startswith("https://hook.") or ".make.com/" not in url:
        await query.message.reply_text("MAKE_WEBHOOK_URL тўғри созланмаган.")
        return

    context.user_data["instagram_sending"] = True
    try:
        await asyncio.to_thread(
            _send_instagram_webhook,
            url,
            {
                "event": "instagram_post_approved",
                "caption": draft,
                "telegram_user_id": update.effective_user.id,
                "approved_at": datetime.now(TZ).isoformat(),
            },
        )
        context.user_data.pop("instagram_draft", None)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            "✅ Пост матни Make.com'га юборилди. "
            "Бу Instagram'да эълон қилинганини англатмайди."
        )
    except Exception:
        log.exception("Instagram webhook error")
        await query.message.reply_text(
            "Make.com'га юборишда хатолик. Кейинроқ яна тасдиқлаб кўринг."
        )
    finally:
        context.user_data["instagram_sending"] = False



# ---- Read-only file analysis and Instagram active-story checking ----

def _is_file_read_request(text):
    t = (text or "").lower()
    subject = any(x in t for x in (
        "файл", "ҳужжат", "хужжат", "document", "документ", "pdf", "пдф",
        "word", "ворд", "excel", "эксел", "презентац", "тақдимот",
    ))
    reading = any(x in t for x in (
        "ичини", "ичида", "мазмуни", "ўрган", "урган", "ўқи", "уки",
        "очиб", "таҳлил қил", "тахлил қил", "анализ", "прочитай",
        "изучи", "содержим", "read file", "open file", "summariz",
    ))
    creation = any(x in t for x in (
        "тайёрла", "ярат", "ясаб", "қилиб бер", "килиб бер", "юбор",
        "создай", "сделай", "generate", "create", "конверт", "ўзгартир",
    ))
    return subject and reading and not creation


async def analyze_recent_file(update, context, instruction):
    if not context.user_data.get("agent_files"):
        await update.effective_message.reply_text(
            "📎 Ҳали файл юборилмаган. PDF, Word, Excel, PPTX ёки TXT "
            "файлини менга юборинг. Уни ўқиб, мазмунини таҳлил қиламан."
        )
        return
    sources = _extract_agent_sources(context)
    if not sources.strip():
        await update.effective_message.reply_text(
            "Файлдан ўқиладиган матн топилмади. "
            "Скан PDF бўлса, матнли нусхасини ёки расмларини юборинг."
        )
        return
    await update.effective_message.reply_text("📖 Файлни ўрганиб, мазмунини текширяпман...")
    try:
        result = await asyncio.wait_for(
            AI.responses.create(
                model=MODEL,
                instructions=(
                    "Сен файлни таҳлил қиладиган ишончли ёрдамчисан. "
                    "Юборилган манбага таян. Мавжуд фактлар ва рақамларни сақла, "
                    "файлда йўқ маълумотни қўшма. Фойдаланувчи тилида "
                    "қисқача мазмун, асосий фактлар ва етишмайдиган маълумотларни айт. "
                    "Янги файл яратганингни даъво қилма."
                ),
                input=(
                    f"СЎРОВ: {instruction[:1000]}\n\n"
                    f"ФАЙЛ МАЗМУНИ:\n{sources[:AGENT_MAX_INPUT]}"
                ),
            ),
            timeout=90,
        )
        await send_text(update.effective_message, result.output_text or "Матн таҳлил қилинмади.")
    except Exception:
        log.exception("Attachment analysis error")
        await update.effective_message.reply_text(
            "Файлни таҳлил қилишда хатолик юз берди. Railway Logs'ни текширинг."
        )


def _is_instagram_story_count(text):
    t = (text or "").lower()
    platform = any(x in t for x in (
        "instagram", "инстаграм", "insta", "профилим", "profilim",
    ))
    stories = any(x in t for x in (
        "stories", "story", "сторис", "стори", "истор", "ҳикоя",
        "istori", "istoriya", "istorya", "istoriyalar", "hikoya", "hikoyalar",
    ))
    count = any(x in t for x in (
        "нечта", "қанча", "канча", "сони", "ҳисоб", "хисоб",
        "сколько", "количество", "count", "how many", "санаб", "sanab", "nechta", "qancha",
    ))
    return platform and stories and count


def _make_hook_is_valid(url):
    parsed = urlparse(url)
    host = parsed.hostname or ""
    return parsed.scheme == "https" and host.startswith("hook.") and host.endswith(".make.com") and bool(parsed.path.strip("/"))


def _read_make_story_count(url, telegram_user_id):
    payload = json.dumps({
        "event": "instagram_active_stories_count",
        "telegram_user_id": telegram_user_id,
    }).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        raw = response.read(120000).decode("utf-8")
    result = json.loads(raw)
    # Make: Instagram for Business (Facebook login) -> List stories ->
    # Webhooks Response. Response JSON: {"count": <number>}.
    if not isinstance(result, dict):
        raise ValueError("Make response must be JSON object")
    count = result.get("count")
    if isinstance(count, str) and count.isdecimal():
        count = int(count)
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        stories = result.get("stories")
        if isinstance(stories, list):
            count = len(stories)
        else:
            raise ValueError("Make response lacks numeric count")
    return count


async def instagram_stories_command(update, context):
    if not _is_owner(update):
        await update.effective_message.reply_text(
            "🔐 /stories фақат бот эгаси учун. /myid орқали BOT_OWNER_ID ни созланг."
        )
        return
    if update.effective_chat.type != "private":
        await update.effective_message.reply_text("Бу буйруқни ботга шахсий чатда юборинг.")
        return
    url = os.getenv("MAKE_STORIES_WEBHOOK_URL", "").strip()
    if not _make_hook_is_valid(url):
        await update.effective_message.reply_text(
            "📸 Instagram сториларини ҳозир санай олмайман: "
            "MAKE_STORIES_WEBHOOK_URL ҳали уланмаган.\n\n"
            "Make.com'да алоҳида Webhooks → Instagram for Business "
            "(Facebook login) → List stories → Webhook response "
            "сценарийсини созлаш керак. Бу фақат ҳозирги фаол "
            "сториларни санайди, архивдагиларни эмас."
        )
        return
    await update.effective_message.reply_text("🔎 Instagram'даги фаол сториларни текширяпман...")
    try:
        count = await asyncio.to_thread(
            _read_make_story_count, url, update.effective_user.id
        )
        await update.effective_message.reply_text(
            f"📸 Instagram аккаунтингизда ҳозир {count} та фаол сторис бор. "
            "Бу ҳисобга архивдагилар кирмайди."
        )
    except Exception:
        log.exception("Instagram story count failed")
        await update.effective_message.reply_text(
            "Instagram сториларини санаб бўлмади. Make сценарийсида "
            "Instagram for Business → List stories ва Webhooks Response "
            "созланганини текширинг. Жавоб JSON кўринишида "
            "{\"count\": 0} каби қайтиши керак."
        )


# ---- AI document agent: Telegram text -> structured content -> file ----
# Content is generated by AI; file layout is generated locally, never by arbitrary AI code.

def _agent_kind(text):
    t = (text or "").lower()
    # A question about Excel/PowerPoint/book must not accidentally create files.
    intent = any(x in t for x in (
        "тайёрла", "тайёрлаб", "ярат", "ясаб", "қилиб бер", "килиб бер",
        "юбор", "слайд тайёр", "слайд қилиб", "слайд ясаб", "слайд ярат",
        "та слайд", "та слайдли", "презентация тайёр", "ҳужжат тайёр", "маъруза тайёр",
        "сделай", "создай", "подготов", "create", "generate", "файл қилиб",
        "word қилиб", "excel қилиб", "pdf қилиб", "pptx тайёр", "docx тайёр", "xlsx тайёр",
        "пост тайёрла", "пост ёз", "instagram post", "инстаграм пост",
        "tayyorla", "tayyorlab", "yarat", "yasab", "qilib ber", "yubor",
        "hujjat tayyorla", "slayd tayyorla", "fayl qilib",
    ))
    if not intent:
        return None
    if any(w in t for w in ("instagram", "инстаграм", "инста пост", "instapost")) and any(w in t for w in ("пост", "post", "caption", "эълон")):
        return "instagram"
    if any(w in t for w in ("pptx", "powerpoint", "презентац", "слайд", "инфографик", "taqdimot", "тақдимот", "презентация", "slayd", "infografika")):
        return "pptx"
    if any(w in t for w in ("xlsx", "excel", "эксел", "жадвал", "jadval", "диаграмма", "формула", "ҳисоб-китоб")):
        return "xlsx"
    if any(w in t for w in ("pdf", "пдф")):
        return "pdf"
    if any(w in t for w in ("docx", "word", "ворд", "маъруза", "билдирги", "маълумотнома", "расмий ҳужжат", "ҳисобот тайёрла", "ҳужжат тайёрла", "документ тайёрла", "ариза тайёрла")):
        return "docx"
    return None


def _extract_agent_sources(context):
    pieces = []
    for entry in context.user_data.get("agent_files", [])[-3:]:
        name, data = entry["name"], entry["data"]
        stream = io.BytesIO(data)
        try:
            if name.lower().endswith(".docx"):
                doc = Document(stream)
                content = "\n".join([p.text for p in doc.paragraphs] + [" | ".join(c.text for c in row.cells) for tab in doc.tables for row in tab.rows])
            elif name.lower().endswith(".pdf"):
                content = "\n".join(p.extract_text() or "" for p in PdfReader(stream).pages[:25])
            elif name.lower().endswith(".xlsx"):
                wb = load_workbook(stream, read_only=True, data_only=True)
                content = "\n".join(f"Варақ: {ws.title}\n" + "\n".join(" | ".join(str(x) if x is not None else "" for x in row) for row in ws.iter_rows(max_row=150, max_col=16, values_only=True)) for ws in wb.worksheets[:3])
                wb.close()
            elif name.lower().endswith(".pptx"):
                prs = Presentation(stream)
                content = "\n".join(sh.text for slide in prs.slides for sh in slide.shapes if sh.has_text_frame)
            elif name.lower().endswith((".txt", ".csv")):
                content = data.decode("utf-8-sig", errors="replace")
            else:
                continue
            pieces.append(f"ФАЙЛ: {name}\n{content[:12000]}")
        except Exception:
            log.exception("Agent source read error: %s", name)
    return "\n\n".join(pieces)[:AGENT_MAX_INPUT]


def _agent_json(text):
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        a, b = cleaned.find("{"), cleaned.rfind("}")
        if a >= 0 and b > a:
            return json.loads(cleaned[a:b+1])
        raise


async def _agent_content(prompt, kind, sources):
    schema = {
        "docx": '{"title":"...","subtitle":"...","sections":[{"heading":"...","paragraphs":["..."],"bullets":["..."]}],"notes":["..."]}',
        "pdf": '{"title":"...","subtitle":"...","sections":[{"heading":"...","paragraphs":["..."],"bullets":["..."]}],"notes":["..."]}',
        "pptx": '{"title":"...","slides":[{"title":"...","bullets":["..."],"chart":{"title":"...","categories":["2025","2026"],"values":[10,12]}}],"notes":["..."]}',
        "xlsx": '{"title":"...","headers":["Номи","2025","2026"],"rows":[["Жами",125,177]],"chart":true,"notes":["..."]}',
    }[kind]
    instructions = (
        "Сен расмий ўзбек ва рус ҳужжатлари учун контент тайёрлайдиган агентсан. "
        "Фақат тўғри JSON объект қайтар, markdown эмас. JSON схемаси: " + schema + "\n"
        "Фойдаланувчи тилида ёз. Мавзу ва мақсадга мос мазмун тайёрла. "
        "Фақат фойдаланувчи ёки илова қилинган файллар берган сонларни факт сифатида ишлат. "
        "Агар 2025–2026 йил статистикаси йўқ бўлса, ҳеч қачон тахминий сон ёзма; "
        "ўрнига тушунтирувчи матн ёз ва notes да етишмаётган маълумотни кўрсат. "
        "Слайд сонини фойдаланувчи айтганидек бажар; агар айтмаган бўлса 5 та слайд. "
        "Жадвалда маълумот йўқ бўлса, фақат сарлавҳа ва бўш қатор қолдир. "
        "Диаграмма учун фақат ҳақиқий рақамли қаторлардан фойдалан. "
        "Ҳужжатларда пухта, мантиқий ва батафсил матн ёз. "
        "Илова қилинган файлдаги маълумотни ўзгартирма, ўйлаб топма."
    )
    resp = await AI.responses.create(
        model=MODEL, instructions=instructions,
        input=f"ТОПШИРИҚ:\n{prompt[:3500]}\n\nМАНБАЛАР:\n{sources or 'Файл юборилмаган.'}",
    )
    result = _agent_json(resp.output_text or "")
    if not isinstance(result, dict):
        raise ValueError("AI did not return JSON object")
    return result


def _agent_docx(content):
    doc = Document()
    sec = doc.sections[0]
    sec.top_margin = Inches(.8)
    sec.bottom_margin = Inches(.75)
    normal = doc.styles["Normal"]
    normal.font.name = "DejaVu Sans"
    normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(8)
    title = doc.add_heading(str(content.get("title") or "Ҳужжат"), 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if content.get("subtitle"):
        sub = doc.add_paragraph(str(content["subtitle"]))
        sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for section in content.get("sections", [])[:30]:
        if section.get("heading"):
            doc.add_heading(str(section["heading"]), level=1)
        for para in section.get("paragraphs", [])[:30]:
            doc.add_paragraph(str(para))
        for bullet in section.get("bullets", [])[:25]:
            doc.add_paragraph(str(bullet), style="List Bullet")
    if content.get("notes"):
        doc.add_heading("Изоҳлар", level=2)
        for note in content["notes"][:12]:
            doc.add_paragraph(str(note), style="List Bullet")
    output = io.BytesIO()
    doc.save(output)
    output.seek(0)
    return output


def _agent_xlsx(content):
    wb = Workbook()
    ws = wb.active
    ws.title = "Маълумотлар"
    headers = [str(x)[:100] for x in content.get("headers", [])[:20]]
    rows = content.get("rows", [])[:300]
    if not headers:
        headers = ["Кўрсаткич", "Қиймат"]
    ws.append(headers)
    for row in rows:
        if not isinstance(row, list):
            continue
        safe = []
        for val in row[:len(headers)]:
            if isinstance(val, str) and val.startswith(("=", "+", "-", "@")):
                # Prevent untrusted source values from becoming executable spreadsheet formulas.
                val = "'" + val
            safe.append(val if isinstance(val, (str, int, float, bool, type(None))) else str(val))
        ws.append(safe)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for cell in ws[1]:
        cell.fill = PatternFill("solid", fgColor="17365D")
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(wrap_text=True)
    for col in ws.columns:
        letter = col[0].column_letter
        ws.column_dimensions[letter].width = min(42, max(15, max(len(str(c.value or "")) for c in list(col)[:60]) + 3))
    ws.row_dimensions[1].height = 30
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            if cell.row % 2 == 0:
                cell.fill = PatternFill("solid", fgColor="EDF3FA")
    if content.get("chart") and ws.max_row >= 3 and ws.max_column >= 2:
        numeric_cols = [i for i in range(2, ws.max_column+1) if sum(isinstance(ws.cell(r,i).value, (int,float)) for r in range(2, ws.max_row+1)) >= 2]
        if numeric_cols:
            chart = BarChart()
            chart.title = str(content.get("title", "Таққослаш"))[:90]
            chart.y_axis.title = "Қиймат"
            chart.x_axis.title = headers[0]
            for i in numeric_cols[:4]:
                chart.add_data(Reference(ws, min_col=i, min_row=1, max_row=ws.max_row), titles_from_data=True)
            chart.set_categories(Reference(ws, min_col=1, min_row=2, max_row=ws.max_row))
            chart.width, chart.height = 18, 9
            ws.add_chart(chart, f"A{ws.max_row+4}")
    if content.get("notes"):
        notes = wb.create_sheet("Изоҳлар")
        for note in content["notes"][:30]:
            notes.append([str(note)])
        notes.column_dimensions["A"].width = 90
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output


def _slide_text(slide, text, left, top, width, height, size=19, color=(34,47,67), bold=False):
    tb = slide.shapes.add_textbox(PInches(left), PInches(top), PInches(width), PInches(height))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.clear()
    for i, line in enumerate(text.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = line
        p.font.size = PPt(size)
        p.font.bold = bold
        p.font.color.rgb = PRGBColor(*color)
    return tb


def _agent_pptx(content, photo=None):
    prs = Presentation()
    prs.slide_width = PInches(13.333)
    prs.slide_height = PInches(7.5)
    slides = content.get("slides") or [{"title": content.get("title", "Тақдимот"), "bullets": ["Маълумотлар киритилмаган"]}]
    for index, item in enumerate(slides[:20]):
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        background = slide.background.fill
        background.solid()
        background.fore_color.rgb = PRGBColor(247, 249, 252)
        bar = slide.shapes.add_shape(1, 0, 0, prs.slide_width, PInches(.17))
        bar.fill.solid()
        bar.fill.fore_color.rgb = PRGBColor(26, 76, 136)
        bar.line.fill.background()
        _slide_text(slide, str(item.get("title") or content.get("title") or "Тақдимот"), .75, .5, 11.9, 1.0, 30, (23,54,93), True)
        chart_data = item.get("chart") if isinstance(item.get("chart"), dict) else None
        chart_ok = False
        if chart_data:
            cats, vals = chart_data.get("categories", []), chart_data.get("values", [])
            chart_ok = bool(cats and len(cats) == len(vals) and all(isinstance(v, (int,float)) for v in vals))
        bullets = [str(x) for x in item.get("bullets", [])[:9]]
        body_width = 5.7 if chart_ok else 11.5
        _slide_text(slide, "\n\n".join("• " + b for b in bullets), .9, 1.75, body_width, 4.8, 19)
        if chart_ok:
            data = CategoryChartData()
            data.categories = [str(c) for c in cats[:15]]
            data.add_series(str(chart_data.get("title", "Кўрсаткич")), vals[:15])
            chart = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, PInches(6.9), PInches(2), PInches(5.5), PInches(4.1), data).chart
            chart.has_legend = False
        if photo and index == 0 and not chart_ok:
            try:
                slide.shapes.add_picture(io.BytesIO(photo), PInches(9.1), PInches(3.0), width=PInches(3.3))
            except Exception:
                log.exception("Photo cannot be embedded")
        _slide_text(slide, f"{index+1} / {len(slides[:20])}", 11.65, 7.05, 1.0, .25, 11, (108,121,137))
    output = io.BytesIO()
    prs.save(output)
    output.seek(0)
    return output


def _agent_pdf(content):
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    font = "Helvetica"
    if os.path.exists(font_path):
        if "AgentDejaVu" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("AgentDejaVu", font_path))
        font = "AgentDejaVu"
    title_style = ParagraphStyle("AgentTitle", fontName=font, fontSize=17, leading=24, spaceAfter=16)
    head_style = ParagraphStyle("AgentHead", fontName=font, fontSize=13, leading=19, spaceBefore=12, spaceAfter=8)
    body_style = ParagraphStyle("AgentBody", fontName=font, fontSize=10, leading=16, spaceAfter=9)
    story = [Paragraph(escape(str(content.get("title") or "Ҳужжат")), title_style)]
    for section in content.get("sections", [])[:30]:
        if section.get("heading"):
            story.append(Paragraph(escape(str(section["heading"])), head_style))
        for para in section.get("paragraphs", [])[:30]:
            story.append(Paragraph(escape(str(para)), body_style))
        for bullet in section.get("bullets", [])[:25]:
            story.append(Paragraph("• " + escape(str(bullet)), body_style))
    for note in content.get("notes", [])[:12]:
        story.append(Paragraph("Изоҳ: " + escape(str(note)), body_style))
    output = io.BytesIO()
    SimpleDocTemplate(output, pagesize=A4).build(story)
    output.seek(0)
    return output


async def mergepdf_command(update, context):
    files = [e for e in context.user_data.get("agent_files", []) if e["name"].lower().endswith(".pdf")]
    if len(files) < 2:
        await update.message.reply_text("Аввал камида 2 та PDF файл юборинг, кейин /mergepdf ёзинг.")
        return
    try:
        writer = PdfWriter()
        for entry in files:
            writer.append(io.BytesIO(entry["data"]))
        out = io.BytesIO()
        writer.write(out)
        writer.close()
        out.seek(0)
        await update.message.reply_document(document=out, filename="birlashtirilgan.pdf", caption="✅ PDF файллар бирлаштирилди.")
    except Exception:
        log.exception("Merge PDF error")
        await update.message.reply_text("PDF файлларни бирлаштиришда хатолик. Шифрланган PDF бўлиши мумкин.")


async def agent_dispatch(update, context, prompt, force_kind=None):
    kind = force_kind or _agent_kind(prompt)
    if not kind:
        return False
    if kind == "instagram":
        # Keep actual Telegram context, including per-user draft and approval state.
        await instagram_post_command(update, context, topic=prompt)
        return True
    if kind == "pdf" and any(x in prompt.lower() for x in ("бирлаштир", "merge", "объедин")):
        await mergepdf_command(update, context)
        return True
    context.user_data["last_agent_request"] = {"kind": kind, "prompt": prompt}
    try:
        await save_history(update.effective_user.id, "user", prompt)
    except Exception:
        log.exception("Could not persist agent request; proceeding")
    await update.effective_message.reply_text("⏳ Топшириқ қабул қилинди. Ҳужжат тайёрлаяпман...")
    try:
        sources = _extract_agent_sources(context)
        data = await asyncio.wait_for(_agent_content(prompt, kind, sources), timeout=110)
        if kind == "docx":
            output, name = _agent_docx(data), "KichkinaIbroxim_hujjat.docx"
        elif kind == "xlsx":
            output, name = _agent_xlsx(data), "KichkinaIbroxim_jadval.xlsx"
        elif kind == "pptx":
            output, name = _agent_pptx(data, context.user_data.get("agent_photo")), "KichkinaIbroxim_taqdimot.pptx"
        else:
            output, name = _agent_pdf(data), "KichkinaIbroxim_hujjat.pdf"
        notes = [str(n) for n in data.get("notes", [])[:4]]
        caption = "✅ Файл тайёр."
        if notes:
            caption += "\n⚠️ " + " | ".join(notes)[:750]
        sent = await update.effective_message.reply_document(
            document=output, filename=name, caption=caption[:1000]
        )
        if sent and getattr(sent, "document", None):
            context.user_data["last_document"] = {
                "kind": kind,
                "file_id": sent.document.file_id,
                "filename": name,
            }
    except asyncio.TimeoutError:
        log.exception("Agent timeout")
        await update.effective_message.reply_text("Топшириқ вақти тугади. Қисқароқ топшириқ ёки кичикроқ файл билан қайта уриниб кўринг.")
    except Exception:
        log.exception("Document agent error")
        await update.effective_message.reply_text("Файл тайёрлашда хатолик. Railway Logs'ни текширинг.")
    return True

async def post_init(app):
    await init_db()
    app.bot_data["reminder_task"] = asyncio.create_task(
        reminder_worker(app)
    )


async def post_shutdown(app):
    task = app.bot_data.get("reminder_task")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def error_handler(update, context):
    log.error(
        "Telegram handler error: %s",
        context.error,
        exc_info=context.error,
    )


def main():
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    commands = {
        "start": start,
        "help": start,
        "search": search_command,
        "task": task_command,
        "tasks": tasks_command,
        "done": done_command,
        "remind": remind_command,
        "reminders": reminders_command,
        "income": income_command,
        "expense": expense_command,
        "report": report_command,
        "makeword": professional_word,
        "makeexcel": professional_excel,
        "makepdf": professional_pdf,
        "makeslides": professional_slides,
        "news": news_command,
        "rate": rates_command,
        "convert": convert_command,
        "books": books_command,
        "music": music_command,
        "song": music_command,
        "myid": myid_command,
        "readfile": readfile_command,
        "clearfiles": clearfiles_command,
        "instapost": instagram_post_command,
        "stories": instagram_stories_command,
        "mergepdf": mergepdf_command,
    }

    for name, handler in commands.items():
        app.add_handler(CommandHandler(name, handler))

    app.add_handler(
        MessageHandler(filters.PHOTO, photo_handler)
    )
    app.add_handler(
        MessageHandler(filters.VOICE | filters.AUDIO, voice_handler)
    )
    app.add_handler(
        MessageHandler(filters.Document.ALL, document_handler)
    )
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            chat,
        )
    )

    app.add_handler(CallbackQueryHandler(instagram_approval, pattern=r"^ig:(approve|reject)$"))

    app.add_error_handler(error_handler)

    log.info("Kichkina Ibrohim ishga tushmoqda...")
    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()

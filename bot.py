
import os
import io
import re
import asyncio
import base64
import logging
import json
import urllib.request
import tempfile
import zipfile
from pathlib import Path
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from xml.sax.saxutils import escape

import asyncpg
from openai import AsyncOpenAI
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
TZ = ZoneInfo("Asia/Tashkent")
MAX_FILE = 15 * 1024 * 1024
AGENT_MAX_INPUT = 22000

SYSTEM = """ Сен Kichkina Ibrohim номли шахсий AI ёрдамчисан. Ўзбек кирилл, ўзбек лотин ва рус тилларида ишла. Фойдаланувчи қайси тилда ёзса, ўша тилда жавоб бер. Аввалги суҳбатларни ҳисобга ол. Маълумотларни ўйлаб топма. Бажармаган амалингни бажардим деб айтма. """

HELP = """ 🤖 Kichkina Ibrohim AI /start - бошлаш /help - ёрдам /search савол - интернет қидируви /task матн - вазифа қўшиш /tasks - вазифалар /done ID - вазифани якунлаш /remind 2026-12-01 09:00 Йиғилиш /reminders - эслатмалар /income 100000 Маош /expense 25000 Такси /report - молиявий ҳисобот /makeword матн - Word /makeexcel Исм,Сони;Али,5 - Excel /makepdf матн - PDF /makeslides Мавзу;Слайд1;Слайд2 - PowerPoint /instapost мавзу - Instagram учун пост лойиҳаси /mergepdf - юборилган PDF файлларни бирлаштириш Оддий хабар билан ҳам топшириқ беринг: «Пахтакор тумани бўйича 5 та слайд тайёрла» «Маъруза тайёрла ва Word қилиб юбор» «Жадвал ва диаграмма тайёрла» Расм, овоз, PDF, Word ва Excel юбориш мумкин. Google Calendar, Instagram, YouTube ва банк интеграциялари ҳали уланмаган. """


async def connect():
    return await asyncpg.connect(DB_URL, timeout=15)


async def init_db():
    conn = await connect()
    try:
        await conn.execute(""" CREATE TABLE IF NOT EXISTS chat_history ( id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW() ) """)
        await conn.execute(""" CREATE TABLE IF NOT EXISTS tasks ( id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL, title TEXT NOT NULL, done BOOLEAN DEFAULT FALSE ) """)
        await conn.execute(""" CREATE TABLE IF NOT EXISTS reminders ( id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL, chat_id BIGINT NOT NULL, note TEXT NOT NULL, due_at TIMESTAMPTZ NOT NULL, sent BOOLEAN DEFAULT FALSE ) """)
        await conn.execute(""" CREATE TABLE IF NOT EXISTS finance ( id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL, kind TEXT NOT NULL, amount NUMERIC NOT NULL, note TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW() ) """)
    finally:
        await conn.close()


async def get_history(uid):
    conn = await connect()
    try:
        rows = await conn.fetch(
            """ SELECT role, content FROM chat_history WHERE user_id=$1 ORDER BY id DESC LIMIT 20 """,
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
            """ INSERT INTO chat_history(user_id,role,content) VALUES($1,$2,$3) """,
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


async def chat(update, context):
    if await agent_dispatch(update, context, update.message.text):
        return
    await converse(update, update.message.text)


async def search_command(update, context):
    question = " ".join(context.args).strip()
    if not question:
        await update.message.reply_text(
            "Масалан: /search Ўзбекистон янгиликлари"
        )
        return
    await converse(update, question, search=True)


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


async def voice_handler(update, context):
    try:
        voice = update.message.voice
        if voice.file_size and voice.file_size > MAX_FILE:
            await update.message.reply_text(
                "Овозли хабар 15 MB дан кичик бўлсин."
            )
            return
        file = await voice.get_file()
        audio = io.BytesIO(
            bytes(await file.download_as_bytearray())
        )
        audio.name = "voice.ogg"
        result = await AI.audio.transcriptions.create(
            model="whisper-1",
            file=audio,
        )
        if not await agent_dispatch(update, context, result.text):
            await converse(update, result.text)
    except Exception:
        log.exception("Voice error")
        await update.message.reply_text("Овозда хатолик.")


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
        if name.endswith((".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".csv")):
            attachments = context.user_data.setdefault("agent_files", [])
            attachments.append({"name": item.file_name or "file", "data": data})
            del attachments[:-5]
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
            """ INSERT INTO tasks(user_id,title) VALUES($1,$2) RETURNING id """,
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
            """ SELECT id,title,done FROM tasks WHERE user_id=$1 ORDER BY id DESC LIMIT 30 """,
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
            """ UPDATE tasks SET done=TRUE WHERE user_id=$1 AND id=$2 """,
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
            """ INSERT INTO reminders (user_id,chat_id,note,due_at) VALUES($1,$2,$3,$4) """,
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
            """ SELECT id,note,due_at FROM reminders WHERE user_id=$1 AND sent=FALSE ORDER BY due_at LIMIT 20 """,
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
                rows = await conn.fetch(""" SELECT id,chat_id,note FROM reminders WHERE sent=FALSE AND due_at<=NOW() ORDER BY due_at LIMIT 20 """)
                for row in rows:
                    try:
                        await app.bot.send_message(
                            row["chat_id"],
                            "⏰ Эслатма: " + row["note"],
                        )
                        await conn.execute(
                            """ UPDATE reminders SET sent=TRUE WHERE id=$1 """,
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
            """ INSERT INTO finance(user_id,kind,amount,note) VALUES($1,$2,$3,$4) """,
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
            """ SELECT kind,COALESCE(SUM(amount),0) AS total FROM finance WHERE user_id=$1 GROUP BY kind """,
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


async def instagram_post_command(update, context):
    if update.effective_chat.type != "private":
        await update.message.reply_text("Бу буйруқни ботга шахсий чатда юборинг.")
        return

    topic = " ".join(context.args).strip()
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



# ---- AI document agent: Telegram text -> structured content -> file ----
# Content is generated by AI; file layout is generated locally, never by arbitrary AI code.

def _agent_kind(text):
    t = text.lower()
    if any(w in t for w in ("instagram", "инстаграм", "инста пост", "instapost")) and any(w in t for w in ("пост", "post", "caption", "эълон")):
        return "instagram"
    if any(w in t for w in ("pptx", "powerpoint", "презентац", "слайд", "инфографик", "taqdimot")):
        return "pptx"
    if any(w in t for w in ("xlsx", "excel", "эксел", "жадвал", "jadval", "диаграмма", "формула", "ҳисоб-китоб")):
        return "xlsx"
    if any(w in t for w in ("pdf", "пдф")):
        return "pdf"
    if any(w in t for w in ("docx", "word", "ворд", "маъруза", "билдирги", "маълумотнома", "расмий ҳужжат", "ҳисобот тайёрла", "ҳужжат тайёрла")):
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


async def agent_dispatch(update, context, prompt):
    kind = _agent_kind(prompt)
    if not kind:
        return False
    if kind == "instagram":
        # Existing approval flow is preserved; do not publish directly.
        class Args:
            args = prompt.split()
        await instagram_post_command(update, Args())
        return True
    if kind == "pdf" and any(x in prompt.lower() for x in ("бирлаштир", "merge", "объедин")):
        await mergepdf_command(update, context)
        return True
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
        await update.effective_message.reply_document(document=output, filename=name, caption=caption[:1000])
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
        "makeword": makeword,
        "makeexcel": makeexcel,
        "makepdf": makepdf,
        "makeslides": makeslides,
        "instapost": instagram_post_command,
        "mergepdf": mergepdf_command,
    }

    for name, handler in commands.items():
        app.add_handler(CommandHandler(name, handler))

    app.add_handler(
        MessageHandler(filters.PHOTO, photo_handler)
    )
    app.add_handler(
        MessageHandler(filters.VOICE, voice_handler)
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

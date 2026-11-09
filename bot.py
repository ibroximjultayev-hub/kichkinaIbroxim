
import os
import io
import re
import asyncio
import base64
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from xml.sax.saxutils import escape

import asyncpg
from openai import AsyncOpenAI
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
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
log = logging.getLogger("kichkina_ibrohim")

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
DB_URL = os.environ["DATABASE_URL"]
AI = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
TZ = ZoneInfo("Asia/Tashkent")
MAX_FILE = 15 * 1024 * 1024

SYSTEM = """
Сен Kichkina Ibrohim номли шахсий AI ёрдамчисан.
Ўзбек кирилл, ўзбек лотин ва рус тилларида ишла.
Фойдаланувчи қайси тилда ёзса, ўша тилда жавоб бер.
Ҳужжатлар, ҳисоботлар, қонунчилик, таҳлил,
режалаштириш ва кундалик вазифаларда ёрдам бер.
Аввалги суҳбатларни ҳисобга ол.
Фактларни ўйлаб топма.
Бажармаган амалингни бажардим деб айтма.
"""

HELP = """
🤖 Kichkina Ibrohim AI

Менга матн, расм, овоз ёки ҳужжат юборинг.

/start — бошлаш
/help — буйруқлар
/search савол — интернет қидируви
/task матн — вазифа қўшиш
/tasks — вазифалар
/done ID — вазифани якунлаш
/remind 2026-12-01 09:00 Матн
/reminders — эслатмалар
/income 100000 Маош
/expense 25000 Такси
/report — молиявий ҳисобот
/makeword матн — Word яратиш
/makeexcel Исм,Сони;Али,5 — Excel
/makepdf матн — PDF
/makeslides Мавзу;Слайд1;Слайд2 — PowerPoint

Instagram, YouTube, Google Calendar ва банк
ҳисобларига тўғридан-тўғри уланиш
ҳали созланмаган.
"""


async def connect():
    return await asyncpg.connect(DB_URL)


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
                done BOOLEAN NOT NULL DEFAULT FALSE
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                chat_id BIGINT NOT NULL,
                note TEXT NOT NULL,
                due_at TIMESTAMPTZ NOT NULL,
                sent BOOLEAN NOT NULL DEFAULT FALSE
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


async def get_history(uid):
    conn = await connect()
    try:
        rows = await conn.fetch(
            """
            SELECT role,content FROM chat_history
            WHERE user_id=$1
            ORDER BY id DESC LIMIT 20
            """,
            uid,
        )
        return [
            {"role": r["role"], "content": r["content"]}
            for r in reversed(rows)
        ]
    finally:
        await conn.close()


async def send_text(message, text):
    text = text or "Жавоб олинмади."
    for i in range(0, len(text), 3900):
        await message.reply_text(text[i:i + 3900])


async def ask_ai(uid, question, image=None, search=False):
    try:
        old = await get_history(uid)
    except Exception:
        log.exception("History read error")
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

    args = {
        "model": MODEL,
        "instructions": SYSTEM,
        "input": old + [{"role": "user", "content": content}],
    }
    if search:
        args["tools"] = [{"type": "web_search_preview"}]

    try:
        response = await AI.responses.create(**args)
        return response.output_text or "Жавоб олинмади."
    except Exception:
        if not search:
            raise
        log.exception("Web search failed")
        args.pop("tools", None)
        response = await AI.responses.create(**args)
        return (
            (response.output_text or "Жавоб олинмади.")
            + "\n\nЭслатма: интернет қидируви ишламади."
        )


async def converse(update, question, image=None, search=False):
    uid = update.effective_user.id
    try:
        answer = await ask_ai(
            uid, question[:18000], image, search
        )
    except Exception:
        log.exception("AI error")
        await update.effective_message.reply_text(
            "AI хизматида хатолик. Railway Logs'ни текширинг."
        )
        return

    await send_text(update.effective_message, answer)

    try:
        await save_history(uid, "user", question)
        await save_history(uid, "assistant", answer)
    except Exception:
        log.exception("History save error")


async def start(update, context):
    await update.message.reply_text(HELP)


async def chat(update, context):
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
        file = await update.message.photo[-1].get_file()
        if file.file_size and file.file_size > MAX_FILE:
            await update.message.reply_text(
                "Расм 15 MB дан кичик бўлсин."
            )
            return
        data = bytes(await file.download_as_bytearray())
        await converse(
            update,
            update.message.caption or "Расмни таҳлил қил.",
            image=data,
        )
    except Exception:
        log.exception("Photo error")
        await update.message.reply_text(
            "Расмни таҳлил қилиб бўлмади."
        )


async def voice_handler(update, context):
    try:
        file = await update.message.voice.get_file()
        if file.file_size and file.file_size > MAX_FILE:
            await update.message.reply_text(
                "Овозли хабар 15 MB дан кичик бўлсин."
            )
            return
        data = bytes(await file.download_as_bytearray())
        audio = io.BytesIO(data)
        audio.name = "voice.ogg"
        result = await AI.audio.transcriptions.create(
            model="whisper-1", file=audio
        )
        await converse(update, result.text)
    except Exception:
        log.exception("Voice error")
        await update.message.reply_text(
            "Овозни тушунишда хатолик."
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

        if name.endswith(".pdf"):
            reader = PdfReader(stream)
            content = "\n".join(
                page.extract_text() or ""
                for page in reader.pages[:30]
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
                "Ўқиладиган матн топилмади. "
                "Скан PDF учун OCR керак."
            )
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
            WHERE user_id=$1
            ORDER BY id DESC LIMIT 30
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
            "Сана ёки вақт нотўғри."
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

    await update.message.reply_text(
        "⏰ Эслатма сақланди."
    )


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
        update.message,
        text or "Эслатмалар йўқ.",
    )


async def reminder_worker(app):
    while True:
        try:
            conn = await connect()
            try:
                rows = await conn.fetch("""
                    SELECT id,chat_id,note
                    FROM reminders
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
        if (
            not amount.is_finite()
            or amount <= 0
            or amount > Decimal("1000000000000")
        ):
            raise ValueError()
    except (InvalidOperation, ValueError):
        await update.message.reply_text(
            "Суммани тўғри киритинг."
        )
        return

    note = " ".join(context.args[1:]) or "Изоҳсиз"
    conn = await connect()
    try:
        await conn.execute(
            """
            INSERT INTO finance
            (user_id,kind,amount,note)
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
            FROM finance WHERE user_id=$1
            GROUP BY kind
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
            value.strip()
            for value in line.split(",")
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
        Paragraph(
            escape(line) or " ",
            style,
        )
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
        slide.shapes.titl

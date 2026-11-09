import asyncio
import base64
import io
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import asyncpg
from docx import Document
from openai import AsyncOpenAI
from openpyxl import Workbook, load_workbook
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from xml.sax.saxutils import escape

logging.basicConfig(level=logging.INFO)
log = logging.getLogger('kichkina_ibrohim')
TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
DB_URL = os.environ['DATABASE_URL']
client = AsyncOpenAI(api_key=os.environ['OPENAI_API_KEY'])
MODEL = os.getenv('OPENAI_MODEL', 'gpt-4.1-mini')
TZ = ZoneInfo(os.getenv('BOT_TIMEZONE', 'Asia/Tashkent'))
MAX_FILE_BYTES = 15 * 1024 * 1024
MAX_INPUT_CHARS = 18000
SYSTEM = '''Сен Kichkina Ibrohim номли шахсий AI ёрдамчисан. Фойдаланувчи қайси тилда ёзса, ўша тилда (ўзбек кирилл/лотин ёки рус) жавоб бер. Аниқ ва фойдали бўл. Суҳбат контекстини ҳисобга ол. Қонун ва фактларни ўйлаб топма. Ҳақиқатан бажармаган ташқи амални бажардим дема. Молиявий ёки бошқа муҳим ташқи амаллар учун тасдиқ талаб қилинади.'''

async def db():
    return await asyncpg.connect(DB_URL)

async def init_db():
    conn = await db()
    try:
        await conn.execute('''CREATE TABLE IF NOT EXISTS chat_history (
            id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL, role TEXT NOT NULL,
            content TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW())''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS tasks (
            id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL, title TEXT NOT NULL,
            done BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMPTZ DEFAULT NOW())''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS reminders (
            id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL, chat_id BIGINT NOT NULL,
            note TEXT NOT NULL, due_at TIMESTAMPTZ NOT NULL,
            sent BOOLEAN NOT NULL DEFAULT FALSE)''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS finance (
            id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL,
            kind TEXT NOT NULL, amount NUMERIC(16,2) NOT NULL,
            note TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW())''')
    finally:
        await conn.close()

async def save(user_id, role, content):
    conn = await db()
    try:
        await conn.execute('INSERT INTO chat_history (user_id,role,content) VALUES ($1,$2,$3)', user_id, role, content[:MAX_INPUT_CHARS])
    finally:
        await conn.close()

async def history(user_id):
    conn = await db()
    try:
        rows = await conn.fetch('SELECT role,content FROM chat_history WHERE user_id=$1 ORDER BY id DESC LIMIT 20', user_id)
        return [{'role': r['role'], 'content': r['content']} for r in reversed(rows)]
    finally:
        await conn.close()

async def reply_long(message, text):
    for i in range(0, len(text), 3900):
        await message.reply_text(text[i:i + 3900])

async def ask_ai(user_id, question, image_bytes=None, mime='image/jpeg', search=False):
    try:
        old = await history(user_id)
    except Exception:
        log.exception('History unavailable')
        old = []
    if image_bytes is not None:
        encoded = base64.b64encode(image_bytes).decode('ascii')
        user_input = [{'type': 'input_text', 'text': question},
                      {'type': 'input_image', 'image_url': f'data:{mime};base64,{encoded}'}]
    else:
        user_input = question
    kwargs = dict(model=MODEL, instructions=SYSTEM,
                  input=old + [{'role': 'user', 'content': user_input}])
    if search:
        kwargs['tools'] = [{'type': 'web_search_preview'}]
    try:
        response = await client.responses.create(**kwargs)
    except Exception:
        if not search:
            raise
        log.exception('Web search unavailable, falling back to model')
        kwargs.pop('tools', None)
        response = await client.responses.create(**kwargs)
        return (response.output_text or 'Жавоб олинмади.') + '\n\n(Интернет қидируви ишламади; жавоб модел маълумотларига асосланган.)'
    return response.output_text or 'Жавоб олинмади.'

async def converse(update, question, image_bytes=None, mime='image/jpeg', search=False):
    uid = update.effective_user.id
    try:
        answer = await ask_ai(uid, question[:MAX_INPUT_CHARS], image_bytes, mime, search)
    except Exception:
        log.exception('AI request failed')
        await update.effective_message.reply_text('AI хизматида хатолик. Кейинроқ уриниб кўринг.')
        return
    try:
        await save(uid, 'user', question)
        await save(uid, 'assistant', answer)
    except Exception:
        log.exception('Save failed')
    await reply_long(update.effective_message, answer)

HELP = '''Ассалому алайкум! Мен Kichkina Ibrohim 🤖

Матн, расм, овоз ва PDF/Word/Excel файл юборинг.
/search савол — интернетдан қидириш (мавжуд бўлса)
/task вазифа — вазифа қўшиш
/tasks — вазифалар рўйхати
/done ID — вазифани тугатиш
/remind 2026-12-01 09:00 Матн — эслатма (Тошкент вақти)
/reminders — эслатмалар
/income 100000 Маош — кирим ёзиш
/expense 25000 Такси — чиқим ёзиш
/report — молиявий ва вазифалар ҳисоботи
/makeword матн — Word яратиш
/makeexcel сарлавҳа1,сарлавҳа2;қиймат1,қиймат2 — Excel яратиш
/makepdf матн — PDF яратиш
/makeslides сарлавҳа;1-слайд матни;2-слайд матни — PowerPoint яратиш

Instagram, YouTube, Google Calendar ва банк ҳисобларига тўғридан-тўғри уланиш ҳали созланмаган.'''

async def start(update, context):
    await update.message.reply_text(HELP)

async def text_chat(update, context):
    await converse(update, update.message.text)

async def search_cmd(update, context):
    q = ' '.join(context.args).strip()
    if not q:
        await update.message.reply_text('Масалан: /search Ўзбекистонда бугунги янгиликлар')
        return
    await converse(update, 'Интернетдан текшириб, манбалар билан жавоб бер: ' + q, search=True)

async def photo(update, context):
    try:
        obj = await update.message.photo[-1].get_file()
        if obj.file_size and obj.file_size > MAX_FILE_BYTES:
            await update.message.reply_text('Расм 15 MB дан кичик бўлсин.')
            return
        data = bytes(await obj.download_as_bytearray())
        await converse(update, update.message.caption or 'Ушбу расмни таҳлил қил.', data)
    except Exception:
        log.exception('Photo failed')
        await update.message.reply_text('Расмни таҳлил қилиб бўлмади.')

async def voice(update, context):
    try:
        obj = await update.message.voice.get_file()
        if obj.file_size and obj.file_size > MAX_FILE_BYTES:
            await update.message.reply_text('Овозли хабар 15 MB дан кичик бўлсин.')
            return
        data = bytes(await obj.download_as_bytearray())
        audio = io.BytesIO(data)
        audio.name = 'voice.ogg'
        transcription = await client.audio.transcriptions.create(model='whisper-1', file=audio)
        await converse(update, transcription.text)
    except Exception:
        log.exception('Voice failed')
        await update.message.reply_text('Овозли хабарни ўқиб бўлмади.')

async def document(update, context):
    doc = update.message.document
    if doc.file_size and doc.file_size > MAX_FILE_BYTES:
        await update.message.reply_text('Файл 15 MB дан кичик бўлсин.')
        return
    name = (doc.file_name or '').lower()
    try:
        obj = await doc.get_file()
        data = bytes(await obj.download_as_bytearray())
        stream = io.BytesIO(data)
        if name.endswith('.pdf'):
            reader = PdfReader(stream)
            content = '\n'.join(page.extract_text() or '' for page in reader.pages[:30])
        elif name.endswith('.docx'):
            d = Document(stream)
            content = '\n'.join(p.text for p in d.paragraphs)
            for table in d.tables:
                content += '\n' + '\n'.join(' | '.join(c.text for c in row.cells) for row in table.rows)
        elif name.endswith('.xlsx'):
            wb = load_workbook(stream, read_only=True, data_only=True)
            content = '\n'.join(f'{ws.title}:\n' + '\n'.join(' | '.join(str(v) if v is not None else '' for v in row) for row in ws.iter_rows(max_row=150, max_col=20, values_only=True)) for ws in wb.worksheets[:5])
            wb.close()
        elif name.endswith(('.txt', '.csv')):
            content = data.decode('utf-8-sig', errors='replace')
        else:
            await update.message.reply_text('PDF, DOCX, XLSX, TXT ёки CSV юборинг.')
            return
        if not content.strip():
            await update.message.reply_text('Файлда ўқиладиган матн топилмади (скан PDF учун OCR керак).')
            return
        question = update.message.caption or 'Ушбу ҳужжатни қисқача таҳлил қил.'
        await converse(update, f'{question}\n\nФайл: {doc.file_name}\nМатн:\n{content[:MAX_INPUT_CHARS - 1500]}')
    except Exception:
        log.exception('Document failed')
        await update.message.reply_text('Файлни ўқишда хатолик юз берди.')

async def task_add(update, context):
    title = ' '.join(context.args).strip()
    if not title:
        await update.message.reply_text('Масалан: /task Ҳисоботни тайёрлаш')
        return
    conn = await db()
    try:
        row = await conn.fetchrow('INSERT INTO tasks(user_id,title) VALUES($1,$2) RETURNING id', update.effective_user.id, title)
        await update.message.reply_text(f'Вазифа қўшилди: #{row["id"]}')
    finally:
        await conn.close()

async def tasks_cmd(update, context):
    conn = await db()
    try:
        rows = await conn.fetch('SELECT id,title,done FROM tasks WHERE user_id=$1 ORDER BY id DESC LIMIT 30', update.effective_user.id)
    finally:
        await conn.close()
    await reply_long(update.message, '\n'.join(f'{"✅" if r["done"] else "⬜"} #{r["id"]} {r["title"]}' for r in rows) or 'Вазифалар йўқ.')

async def done_cmd(update, context):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text('Масалан: /done 12')
        return
    conn = await db()
    try:
        result = await conn.execute('UPDATE tasks SET done=TRUE WHERE user_id=$1 AND id=$2', update.effective_user.id, int(context.args[0]))
    finally:
        await conn.close()
    await update.message.reply_text('Бажарилди.' if result.endswith('1') else 'Бундай вазифа топилмади.')

async def remind_cmd(update, context):
    match = re.match(r'^/remind(?:@\w+)?\s+(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s+(.+)$', update.message.text, re.S)
    if not match:
        await update.message.reply_text('Масалан: /remind 2026-12-01 09:00 Йиғилиш')
        return
    try:
        local = datetime.strptime(match.group(1) + ' ' + match.group(2), '%Y-%m-%d %H:%M').replace(tzinfo=TZ)
    except ValueError:
        await update.message.reply_text('Сана ёки вақт нотўғри.')
        return
    if local <= datetime.now(TZ):
        await update.message.reply_text('Келажакдаги вақтни киритинг.')
        return
    conn = await db()
    try:
        await conn.execute('INSERT INTO reminders(user_id,chat_id,note,due_at) VALUES($1,$2,$3,$4)', update.effective_user.id, update.effective_chat.id, match.group(3)[:1000], local)
    finally:
        await conn.close()
    await update.message.reply_text(f'Эслатма сақланди: {local:%Y-%m-%d %H:%M} (Тошкент вақти).')

async def reminders_cmd(update, context):
    conn = await db()
    try:
        rows = await conn.fetch('SELECT id,note,due_at FROM reminders WHERE user_id=$1 AND sent=FALSE ORDER BY due_at LIMIT 20', update.effective_user.id)
    finally:
        await conn.close()
    await reply_long(update.message, '\n'.join(f'#{r["id"]} {r["due_at"].astimezone(TZ):%Y-%m-%d %H:%M} — {r["note"]}' for r in rows) or 'Фаол эслатмалар йўқ.')

async def reminder_worker(app):
    while True:
        try:
            conn = await db()
            try:
                rows = await conn.fetch('''UPDATE reminders SET sent=TRUE WHERE id IN
                    (SELECT id FROM reminders WHERE sent=FALSE AND due_at <= NOW() ORDER BY due_at LIMIT 30 FOR UPDATE SKIP LOCKED)
                    RETURNING chat_id,note''')
            finally:
                await conn.close()
            for row in rows:
                try:
                    await app.bot.send_message(row['chat_id'], '⏰ Эслатма: ' + row['note'])
                except Exception:
                    log.exception('Reminder delivery failed')
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception('Reminder worker error')
        await asyncio.sleep(30)

async def finance_cmd(update, context, kind):
    if len(context.args) < 1:
        await update.message.reply_text(f'Масалан: /{kind} 25000 Такси')
        return
    try:
        amount = float(context.args[0].replace(',', '.'))
        if amount <= 0 or amount > 1e12:
            raise ValueError()
    except ValueError:
        await update.message.reply_text('Сумма мусбат рақам бўлиши керак.')
        return
    note = ' '.join(context.args[1:]) or 'Изоҳсиз'
    conn = await db()
    try:
        await conn.execute('INSERT INTO finance(user_id,kind,amount,note) VALUES($1,$2,$3,$4)', update.effective_user.id, kind, amount, note[:1000])
    finally:
        await conn.close()
    await update.message.reply_text(f'{"Кирим" if kind == "income" else "Чиқим"} сақланди: {amount:,.0f} сўм.')

async def income(update, context):
    await finance_cmd(update, context, 'income')

async def expense(update, context):
    await finance_cmd(update, context, 'expense')

async def report(update, context):
    conn = await db()
    try:
        rows = await conn.fetch('SELECT kind,COALESCE(SUM(amount),0) total FROM finance WHERE user_id=$1 GROUP BY kind', update.effective_user.id)
        pending = await conn.fetchval('SELECT COUNT(*) FROM tasks WHERE user_id=$1 AND done=FALSE', update.effective_user.id)
        completed = await conn.fetchval('SELECT COUNT(*) FROM tasks WHERE user_id=$1 AND done=TRUE', update.effective_user.id)
    finally:
        await conn.close()
    sums = {r['kind']: r['total'] for r in rows}
    inc, exp = sums.get('income', 0), sums.get('expense', 0)
    await update.message.reply_text(f'📊 Умумий ҳисобот\nКирим: {inc:,.0f} сўм\nЧиқим: {exp:,.0f} сўм\nФарқ: {inc-exp:,.0f} сўм\nОчиқ вазифалар: {pending}\nБажарилган: {completed}\n\nБанк ҳисоблари уланмаган; фақат қўлда киритилган маълумотлар.')

async def makeword(update, context):
    text = ' '.join(context.args).strip()
    if not text:
        await update.message.reply_text('Масалан: /makeword Ҳисобот матни')
        return
    doc = Document()
    for line in text.split('\n'):
        doc.add_paragraph(line)
    out = io.BytesIO()
    doc.save(out)
    out.seek(0)
    out.name = 'kichkina_ibrohim.docx'
    await update.message.reply_document(out)

async def makeexcel(update, context):
    text = ' '.join(context.args).strip()
    if not text:
        await update.message.reply_text('Масалан: /makeexcel Исм,Сони;Али,5;Вали,7')
        return
    wb = Workbook()
    ws = wb.active
    for line in text.split(';')[:200]:
        ws.append([v.strip() for v in line.split(',')[:30]])
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    out.name = 'kichkina_ibrohim.xlsx'
    await update.message.reply_document(out)

async def makepdf(update, context):
    text = ' '.join(context.args).strip()
    if not text:
        await update.message.reply_text('Масалан: /makepdf Ҳисобот матни')
        return
    out = io.BytesIO()
    font_path = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    if not os.path.exists(font_path):
        await update.message.reply_text('PDF учун Unicode шрифт топилмади. Railway Docker муҳитига DejaVuSans ўрнатиш керак.')
        return
    if 'DejaVu' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('DejaVu', font_path))
    style = ParagraphStyle('Uzbek', parent=getSampleStyleSheet()['Normal'], fontName='DejaVu', fontSize=10, leading=16)
    story = [Paragraph(escape(line), style) for line in text.split('\n') if line.strip()]
    SimpleDocTemplate(out, pagesize=A4).build(story or [Spacer(1, 10)])
    out.seek(0)
    out.name = 'kichkina_ibrohim.pdf'
    await update.message.reply_document(out)

async def makeslides(update, context):
    from pptx import Presentation
    text = ' '.join(context.args).strip()
    if not text:
        await update.message.reply_text('Масалан: /makeslides Ҳисобот;Биринчи слайд;Иккинчи слайд')
        return
    parts = text.split(';')[:20]
    prs = Presentation()
    title_slide = prs.slides.add_slide(prs.slide_layouts[0])
    title_slide.shapes.title.text = parts[0]
    title_slide.placeholders[1].text = 'Kichkina Ibrohim'
    for i, part in enumerate(parts[1:], 1):
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = f'Слайд {i}'
        slide.placeholders[1].text = part
    out = io.BytesIO()
    prs.save(out)
    out.seek(0)
    out.name = 'kichkina_ibrohim.pptx'
    await update.message.reply_document(out)

async def on_error(update, context):
    log.error('Handler error: %s', context.error, exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text('Хатолик юз берди. Кейинроқ қайта уриниб кўринг.')
        except Exception:
            pass

async def post_init(app):
    await init_db()
    app.bot_data['reminder_task'] = asyncio.create_task(reminder_worker(app))

async def post_shutdown(app):
    task = app.bot_data.get('reminder_task')
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    await client.close()

def main():
    app = (ApplicationBuilder().token(TOKEN).post_init(post_init).post_shutdown(post_shutdown).build())
    for name, handler in [
        ('start', start), ('help', start), ('search', search_cmd),
        ('task', task_add), ('tasks', tasks_cmd), ('done', done_cmd),
        ('remind', remind_cmd), ('reminders', reminders_cmd),
        ('income', income), ('expense', expense), ('report', report),
        ('makeword', makeword), ('makeexcel', makeexcel),
        ('makepdf', makepdf), ('makeslides', makeslides),
    ]:
        app.add_handler(CommandHandler(name, handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo))
    app.add_handler(MessageHandler(filters.VOICE, voice))
    app.add_handler(MessageHandler(filters.Document.ALL, document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_chat))
    app.add_error_handler(on_error)
    app.run_polling()

if __name__ == '__main__':
    main()

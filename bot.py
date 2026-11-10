
import OS
import io
import qayta
asyncio import qilish
base64 ni import qilish
import jurnalini yuritish
datetime dan datetime import qilish
o'nlik kasr importidan o'nlik
zoneinfo dan ZoneInfo import qiling
xml.sax.saxutils faylidan import escape

asyncpg ni import qilish
openay import AsyncOpenAI dan
telegram.ext importidan (
    Ilovalar quruvchisi,
    Buyruq boshqaruvchisi,
    Xabar boshqaruvchisi,
    filtrlar,
)
docx import hujjatidan
openpyxl import ish daftaridan, load_workbook
pypdf dan import PdfReader
pptx import taqdimotidan
reportlab.platypus dan SimpleDocTemplate, Paragrafni import qiling
reportlab.lib.pagesizes dan A4 faylini import qiling
reportlab.lib.styles dan ParagraphStyle ni import qiling
reportlab.pdfbase dan import pdfmetrics
reportlab.pdfbase.ttfonts dan TTFont ni import qiling

logging.basicConfig(daraja=logging.INFO)
log = logging.getLogger("KichkinaIbrohim")

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
DB_URL = os.environ["DATABASE_URL"]
AI = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
TZ = ZoneInfo("Osiyo/Toshkent")
MAX_FILE = 15 * 1024 * 1024

TIZIM = """
Sen Kichkina Ibrohim nomli shaxsiy AI yordamchisan.
O'zbek kirill, o'zbek lotin va rus tillarida ishla.
Foydalanuvchi qaysi tilda yozsa, o'sha tilda javob ber.
Dastlabki tekshiruvlarni sharhga ol.
Kunlarni o'ylab topma.
Baxarmagan amalingni bajardim deb aytma.
"""

YORDAM = """
🤖 Kichkina Ibrohim AI

/start - boshlash
/help - yordam
/qidiruv savoli - internet qidiruvi

/task matn - vazifa qo'shish
/tasks - vazifalar
/done ID - vazifani yoqish

/eslatamiz 2026-12-01 09:00 Yigilish
/eslatmalar - eslatmalar

/income 100000 Maosh
/expense 25000 Taksi
/report - hisobot

/makeword матн - Word
/makeexcel Ism,Soni;Ali,5 - Excel
/makepdf matn - PDF
/makeslides Mavzu;Slayd1;Slayd2 - PowerPoint

Rasm, ovoz, PDF, Word va Excel yuklash mumkin.
Google Taqvim, Instagram, YouTube va bank
integratsiyalari quroli ulamagan.
"""


async def connect():
    return asyncpg.connect(DB_URL, timeout=15) ni kuting


async def init_db():
    conn = kutish conn()
    sinab ko'ring:
        conn.execute("") ni kuting
            AGAR JADVAL YARATING AGAR MAVJUD BO'LMASA chat_history (
                id Katta Seriyali Asosiy Kalit,
                foydalanuvchi_id BIGINT NULL EMAS,
                rol matni NULL emas,
                kontent matni NULL emas,
                created_at TIMESTAMPTZ STANDART HOZIR()
            )
        "")
        conn.execute("") ni kuting
            Agar mavjud bo'lmasa, jadval yaratish vazifalari (
                id Katta Seriyali Asosiy Kalit,
                foydalanuvchi_id BIGINT NULL EMAS,
                sarlavha matni NULL emas,
                BOOLEAN DEFAULT FALSE bajarildi
            )
        "")
        conn.execute("") ni kuting
            Agar mavjud bo'lmasa, jadval yaratish eslatmalari (
                id Katta Seriyali Asosiy Kalit,
                foydalanuvchi_id BIGINT NULL EMAS,
                chat_id BIGINT NULL EMAS,
                matn NULL emasligini eslatma,
                due_at TIMESTAMPTZ NULL EMAS,
                BOOLEAN DEFAULT FALSE yuborildi
            )
        "")
        conn.execute("") ni kuting
            AGAR MAVJUD BO'LMASA, JADVAL YARATING (
                id Katta Seriyali Asosiy Kalit,
                foydalanuvchi_id BIGINT NULL EMAS,
                turdagi MATN NULL emas,
                MIQDORI RAQAMLI EMAS, NULL EMAS,
                matn NULL emasligini eslatma,
                created_at TIMESTAMPTZ STANDART HOZIR()
            )
        "")
    nihoyat:
        conn.close() ni kuting


async def get_history(uid):
    conn = kutish conn()
    sinab ko'ring:
        qatorlar = kutish ulanish.yig'ish()
            """
            Chat_historydan rol, kontentni tanlang
            QAYERDA user_id=$1 BUYURTMA ID DESCRIPTION LIMIT 20
            """,
            uid,
        )
        qaytish [
            {"role": r["role"], "content": r["content"]}
            reversed(rows) da r uchun
        ]
    nihoyat:
        conn.close() ni kuting


async def save_history(uid, role, content):
    conn = kutish conn()
    sinab ko'ring:
        conn.execute() ni kuting
            """
            chat_history(user_id,role,content) ga INSERT INTO
            QIYMATLAR($1,$2,$3)
            """,
            uid, rol, kontent[:18000],
        )
    nihoyat:
        conn.close() ni kuting


async def send_text(xabar, matn):
    text = text or "Javob topildi."
    i uchun diapazonda(0, len(text), 3900):
        kuting xabar.reply_text(matn[i:i + 3900])


async def converse(yangilash, savol, rasm=yo'q, qidiruv=noto'g'ri):
    uid = update.effective_user.id
    sinab ko'ring:
        sinab ko'ring:
            eski = kutish get_history(uid)
        istisnodan tashqari:
            log.exception("Tarix xatosi")
            eski = []

        agar rasm "Yo'q" bo'lmasa:
            kodlangan = base64.b64encode(rasm).decode("ascii")
            tarkib = [
                {"turi": "kiritish_matni", "matn": savol},
                {
                    "turi": "kiritish_rasmi",
                    "image_url": "ma'lumotlar:image/jpeg;base64," + kodlangan,
                },
            ]
        boshqa:
            kontent = savol

        kwargs = {
            "model": MODEL,
            "ko'rsatmalar": TIZIM,
            "kiritish": eski + [{"role": "foydalanuvchi", "content": content}],
        }
        agar qidiruv bo'lsa:
            kwargs["vositalar"] = [{"turi": "web_search_preview"}]

        sinab ko'ring:
            javob = AI.responses.create(**kwargs) ni kuting
            javob = respond.output_text yoki "Javob topildi".
        istisnodan tashqari:
            agar qidiruv bo'lmasa:
                ko'tarish
            log.exception("Veb qidiruv xatosi")
            kwargs.pop("asboblar", Yo'q)
            javob = AI.responses.create(**kwargs) ni kuting
            javob = (
                (response.output_text yoki "Javob topildi.")
                + "\n\nInternet qidiruvi ishlamadi."
            )

        kuting send_text(yangilash.effective_message, answer)

        sinab ko'ring:
            kutish save_history(uid, "foydalanuvchi", savol)
            kutish save_history(uid, "yordamchi", javob)
        istisnodan tashqari:
            log.exception("Saqlashda xato")

    istisnodan tashqari:
        log.exception("AI xatosi")
        yangilanishni kuting.effective_message.reply_text()
            "AI xizmatida xatolik. Railway Logs'ni tekshiring."
        )


async def start(update, context):
    yangilanishni kuting.xabar.javob_matni(YORDAM)


async def chat(yangilash, kontekst):
    suhbatni kutish(yangilash, yangilash.message.text)


async def search_command(yangilash, kontekst):
    savol = "".join(context.args).strip()
    agar savol bo'lmasa:
        yangilanishni kuting.xabar.javob_matn()
            "Masalan: /search O'zbekiston yangiliklari"
        )
        qaytish
    converse(yangilash, savol, qidiruv=rost) ni kuting


async def photo_handler(yangilash, kontekst):
    sinab ko'ring:
        rasm = yangilash.xabar.rasm[-1]
        agar photo.file_size va photo.file_size > MAX_FILE bo'lsa:
            yangilanishni kuting.xabar.javob_matn()
                "Rasm 15 MB dan kichik bo'lsin."
            )
            qaytish
        fayl = fotosuratni kuting.get_file()
        ma'lumotlar = baytlar(faylni yuklab olish_as_bytearray() ni kuting)
        suhbatni kuting (
            yangilash,
            update.message.caption yoki "Rasmni tasdiq qil.",
            rasm = ma'lumotlar,
        )
    istisnodan tashqari:
        log.exception("Foto xatosi")
        await update.message.reply_text("Rasmda xatolik.")


async def voice_handler(yangilash, kontekst):
    sinab ko'ring:
        ovoz = yangilash.xabar.ovoz
        agar voice.file_size va voice.file_size > MAX_FILE bo'lsa:
            yangilanishni kuting.xabar.javob_matn()
                "Ovozli xabar 15 MB dan kichik bo'lsin."
            )
            qaytish
        fayl = voice.get_file() ni kuting
        audio = io.BytesIO(
            baytlar(faylni yuklab olish_as_bytearray() ni kuting)
        )
        audio.name = "ovoz.ogg"
        natija = kutish AI.audio.transcriptions.create(
            model="pichirlash-1",
            fayl=audio,
        )
        converse(yangilash, natija.matn) ni kuting
    istisnodan tashqari:
        log.exception("Ovoz xatosi")
        await update.message.reply_text("Ovozda xatolik.")


async def document_handler(yangilash, kontekst):
    element = yangilash.xabar.hujjat
    agar item.file_size va item.file_size > MAX_FILE bo'lsa:
        yangilanishni kuting.xabar.javob_matn()
            "Fayl 15 MB dan kichik bo'lsin."
        )
        qaytish

    sinab ko'ring:
        fayl = elementni kuting.get_file()
        ma'lumotlar = baytlar(faylni yuklab olish_as_bytearray() ni kuting)
        oqim = io.BaytlarIO(ma'lumotlar)
        name = (element.file_name yoki "").pastki()

        agar name.endswith(".pdf") bo'lsa:
            o'quvchi = PdfReader(oqim)
            tarkib = "\n".qo'shilish()
                p.extract_text() yoki ""
                reader.pages ichida p uchun[:30]
            )
        elif name.endswith(".docx"):
            doc = Hujjat(oqim)
            qismlar = [doc.paragraphs ichidagi p uchun p.text]
            doc.tables faylidagi jadval uchun:
                table.rows ichidagi qator uchun:
                    qismlar.append(
                        " | ".join(c.text for c in c in row.cells)
                    )
            tarkib = "\n".join(qismlar)
        elif name.endswith(".xlsx"):
            wb = yuklash_ish daftari(
                oqim, faqat o'qish = rost, faqat ma'lumotlar = rost
            )
            qismlar = []
            wb.worksheets faylidagi ws uchun[:5]:
                parts.append("Varaq: " + ws.title)
                ws.iter_rows() dagi qator uchun
                    max_row=150,
                    max_col=20,
                    values_only=True,
                ):
                    qismlar.append(
                        " | ".qo'shilish(
                            str(v) agar v bo'lmasa, boshqa hech kim ""
                            qatorda v uchun
                        )
                    )
            wb.close()
            tarkib = "\n".join(qismlar)
        elif name.endswith((".txt", ".csv"):
            tarkib = ma'lumotlar.dekod()
                "utf-8-sign", xatolar="almashtirish"
            )
        boshqa:
            yangilanishni kuting.xabar.javob_matn()
                "PDF, DOCX, XLSX, TXT yoki CSV yuboring."
            )
            qaytish

        agar content.strip() bo'lmasa:
            yangilanishni kuting.xabar.javob_matn()
                "Matn topildi. Skan PDF uchun OCR kerak."
            )
            qaytish

        savol = (
            yangilash.xabar.sarlavhasi
            yoki "Ushbu hujjatni qo'ying."
        )
        suhbatni kuting (
            yangilash,
            savol + "\n\n" + kontent[:16000],
        )
    istisnodan tashqari:
        log.exception("Hujjat xatosi")
        yangilanishni kuting.xabar.javob_matn()
            "Hujjatni o'qishda xatolik."
        )


async def task_command(yangilash, kontekst):
    sarlavha = "".join(context.args).strip()
    agar sarlavha bo'lmasa:
        yangilanishni kuting.xabar.javob_matn()
            "Masalan: /vazifa Hussobot tayyorlash"
        )
        qaytish

    conn = kutish conn()
    sinab ko'ring:
        qator = kutish ulanish.fetchrow()
            """
            INSERT INTO vazifalari(foydalanuvchi_identifikatori, sarlavha)
            VALUES($1,$2) QAYTARILAYOTGAN identifikator
            """,
            yangilash.effective_user.id, sarlavha,
        )
    nihoyat:
        conn.close() ni kuting
    yangilanishni kuting.xabar.javob_matn()
        f"Vazifa qo'shildi: #{row['id']}"
    )


async def tasks_command(yangilash, kontekst):
    conn = kutish conn()
    sinab ko'ring:
        qatorlar = kutish ulanish.yig'ish()
            """
            SELECT id, sarlavha, bajarilgan vazifalar FROM
            QAYERDA user_id=$1 BUYURTMA ID DESCRIPTION LIMIT 30
            """,
            yangilash.effective_user.id,
        )
    nihoyat:
        conn.close() ni kuting

    natija = "\n".qo'shilish(
        ("✅" agar r["bajarilgan"] bo'lsa, aks holda "⬜")
        + f" #{r['id']} {r['title']}"
        qatorlar ichida r uchun
    )
    kuting send_text()
        update.message, result or "Vazifalar yo'q."
    )


async def done_command(yangilash, kontekst):
    agar context.args bo'lmasa yoki context.args[0].isdigit() bo'lmasa:
        yangilanishni kuting.xabar.javob_matn()
            "Масалан: /done 1"
        )
        qaytish

    conn = kutish conn()
    sinab ko'ring:
        natija = kutish conn.execute()
            """
            Vazifalarni YANGILASH SET done=TRUE
            QAYERDA user_id=$1 VA id=$2
            """,
            yangilash.effective_user.id,
            int(context.args[0]),
        )
    nihoyat:
        conn.close() ni kuting

    yangilanishni kuting.xabar.javob_matn()
        "Bajarildi."
        agar natija.endswith("1") bo'lsa
        else "Vazifa topildi".
    )


async def remind_command(yangilash, kontekst):
    matn = "".join(context.args)
    moslik = qayta.mosch()
        r"^(\d{4}-\d{2}-\d{2})\s+"
        r"(\d{2}:\d{2})\s+(.+)$",
        matn, re.S,
    )
    agar mos kelmasa:
        yangilanishni kuting.xabar.javob_matn()
            "Masalan: /eslatma 2026-12-01 09:00 Yigilish"
        )
        qaytish

    sinab ko'ring:
        tufayli = sana vaqti.strptime(
            match.group(1) + "" + match.group(2),
            "%Y-%m-%d %H:%M",
        ).almashtirish(tzinfo=TZ)
    ValueError bundan mustasno:
        yangilanishni kuting.xabar.javob_matn()
            "Сана нотўғри."
        )
        qaytish

    agar kerak bo'lsa <= datetime.now(TZ):
        yangilanishni kuting.xabar.javob_matn()
            "Kelajakdagi vaqtni kiritishing."
        )
        qaytish

    conn = kutish conn()
    sinab ko'ring:
        conn.execute() ni kuting
            """
            Eslatmalarni INSERT INTO ga joylashtiring
            (foydalanuvchi_identifikatori, chat_identifikatori, eslatma, sana_vaqti)
            QIYMATLAR($1,$2,$3,$4)
            """,
            yangilash.effective_user.id,
            yangilash.effective_chat.id,
            match.group(3), tufayli,
        )
    nihoyat:
        conn.close() ni kuting
    await update.message.reply_text("Eslatma saqlandi.")


async def reminders_command(yangilash, kontekst):
    conn = kutish conn()
    sinab ko'ring:
        qatorlar = kutish ulanish.yig'ish()
            """
            FROM eslatmalaridan identifikator, eslatma, sana_vazifasini tanlang
            QAYERDA user_id=$1 VA sent=FALSE
            BUYURTMA MUDDATI BO'YICHA LIMIT 20
            """,
            yangilash.effective_user.id,
        )
    nihoyat:
        conn.close() ni kuting

    matn = "\n".qo'shilish(
        f"#{r['id']} "
        f"{r['due_at'].astimzone(TZ):%Y-%m-%d %H:%M}"
        f" — {r['note']}"
        qatorlar ichida r uchun
    )
    kuting send_text()
        update.message, text yoki "Eslatlar yo'q."
    )


async def reminder_worker(ilova):
    rost bo'lsa-da:
        sinab ko'ring:
            conn = kutish conn()
            sinab ko'ring:
                qatorlar = kutish conn.fetch("""
                    SELECT id, chat_id, eslatma FROM eslatmalari
                    QAYERDA sent=FALSE VA due_at<=NOW()
                    BUYURTMA MUDDATI BO'YICHA LIMIT 20
                "")
                qatorlar qatori uchun:
                    sinab ko'ring:
                        app.bot.send_message() ni kuting
                            qator["chat_id"],
                            "⏰ Eslatma: " + qator["eslatma"],
                        )
                        conn.execute() ni kuting
                            """
                            YANGILASH eslatmalari SET sent=ROST
                            QAYERDA id=$1
                            """,
                            qator["id"],
                        )
                    istisnodan tashqari:
                        log.exception("Eslatma yuborishda xato")
            nihoyat:
                conn.close() ni kuting
        asyncio.CanceledErrordan tashqari:
            ko'tarish
        istisnodan tashqari:
            log.exception("Eslatma ishchisi xatosi")
        asyncio.sleep(30) ni kuting


async def finance_command(yangilash, kontekst, tur):
    agar context.args bo'lmasa:
        yangilanishni kuting.xabar.javob_matn()
            "Masalan: /xarajati 25000 taksi"
        )
        qaytish

    sinab ko'ring:
        miqdor = O'nlik(
            context.args[0].replace(",", ".")
        )
        agar amount.is_finite() bo'lmasa yoki amount <= 0 bo'lsa:
            ValueError() ni ko'tarish
    istisnodan tashqari:
        yangilanishni kuting.xabar.javob_matn()
            "Summani yordam olishing."
        )
        qaytish

    note = " ".join(context.args[1:]) yoki "Izohsiz"
    conn = kutish conn()
    sinab ko'ring:
        conn.execute() ni kuting
            """
            INSERT INTO finance(foydalanuvchi_identifikatori,turmush,miqdor,eslatma)
            QIYMATLAR($1,$2,$3,$4)
            """,
            yangilash.effective_user.id,
            turi, miqdori, eslatmasi,
        )
    nihoyat:
        conn.close() ni kuting
    yangilanishni kuting.xabar.javob_matn()
        f"Soqlandi: {sum} so'm."
    )


async def income_command(yangilash, kontekst):
    finance_command(yangilash, kontekst, "daromad") ni kuting


async def expensive_command(yangilash, kontekst):
    finance_command(yangilash, kontekst, "xarajat") ni kuting


async def report_command(yangilash, kontekst):
    conn = kutish conn()
    sinab ko'ring:
        qatorlar = kutish ulanish.yig'ish()
            """
            SELECT kind, COALESCE(SUM(amount),0) AS jami
            FROM moliya WHERE user_id=$1 GROUP BY tur
            """,
            yangilash.effective_user.id,
        )
    nihoyat:
        conn.close() ni kuting

    jami = {r["turdagi"]: qatorlardagi r uchun r["jami"]}
    daromad = totals.get("daromad", o'nlik kasr(0))
    xarajat = totals.get("xarajat", O'nlik kasr(0))

    yangilanishni kuting.xabar.javob_matn()
        "📊 Moliyaviy o'rnatish\n\n"
        f"Kirim: {income:,.0f} so'm\n"
        f"Chiqim: {xarajat:,.0f} so'm\n"
        f"Qoldiq: {income-expense:,.0f} so'm"
    )


async def makeword(yangilash, kontekst):
    matn = "".join(context.args).strip()
    agar matn bo'lmasa:
        yangilanishni kuting.xabar.javob_matn()
            "Masalan: /makeword Hisobot matni"
        )
        qaytish

    doc = Hujjat()
    doc.add_heading("Kichkina Ibrohim", 0)
    doc.add_paragraph(matn)

    oqim = io.BytesIO()
    doc.save(oqim)
    oqim.seek(0)

    yangilanishni kuting.xabar.javob_hujjat()
        hujjat=oqim,
        fayl nomi="hujjat.docx",
    )


async def makeexcel(yangilash, kontekst):
    matn = "".join(context.args).strip()
    agar matn bo'lmasa:
        yangilanishni kuting.xabar.javob_matn()
            "Masalan: /makeexcel Ism,Soni;Ali,5"
        )
        qaytish

    wb = Ish daftari()
    ws = wb.active
    ws.title = "Ma'lumotlar"

    matndagi satr uchun.split(";"):
        ws.append([
            line.split(",") dagi qiymat uchun value.strip() funksiyasi
        ])

    oqim = io.BytesIO()
    wb.save(oqim)
    oqim.seek(0)

    yangilanishni kuting.xabar.javob_hujjat()
        hujjat=oqim,
        fayl nomi="jadval.xlsx",
    )


async def makepdf(yangilash, kontekst):
    matn = "".join(context.args).strip()
    agar matn bo'lmasa:
        yangilanishni kuting.xabar.javob_matn()
            "Masalan: /makepdf Hisobot matni"
        )
        q

import os
import logging
import asyncpg

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from openai import AsyncOpenAI

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]

client = AsyncOpenAI(
    api_key=os.environ["OPENAI_API_KEY"]
)

SYSTEM_PROMPT = """
Сен Kichkina Ibrohim номли универсал AI ёрдамчисан.

Ўзбек тилида кирилл ва лотин ёзувларида,
шунингдек рус тилида мулоқот қил.

Фойдаланувчининг тилида жавоб бер.
Саволларга аниқ, тушунарли ва фойдали жавоб бер.

Таржима, таҳлил, матн ёзиш ва маслаҳат беришда ёрдам бер.
Ҳужжатлар, қонунчилик, Word, Excel ва PowerPoint
бўйича ёрдам беришга тайёр бўл.

Аввалги суҳбатлардан берилган маълумотларни ҳисобга ол.
Маълумотни билмасанг, ўйлаб топма.
Ўзингда мавжуд бўлмаган имкониятни бор деб айтма.
"""


async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
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
    finally:
        await conn.close()


async def save_message(user_id, role, content):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(
            """
            INSERT INTO chat_history
                (user_id, role, content)
            VALUES ($1, $2, $3)
            """,
            user_id,
            role,
            content,
        )
    finally:
        await conn.close()


async def get_history(user_id):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch(
            """
            SELECT role, content
            FROM chat_history
            WHERE user_id = $1
            ORDER BY id DESC
            LIMIT 20
            """,
            user_id,
        )

        return [
            {
                "role": row["role"],
                "content": row["content"],
            }
            for row in reversed(rows)
        ]
    finally:
        await conn.close()


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text(
        "Ассалому алайкум!\n\n"
        "Мен Kichkina Ibrohim AI ёрдамчисиман.\n"
        "Мен билан ўзбекча ёки русча суҳбатлашинг!\n\n"
        "Аввалги суҳбатларимизни ҳам ҳисобга оламан."
    )


async def chat(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    question = update.message.text
    user_id = update.effective_user.id

    try:
        history = await get_history(user_id)
    except Exception:
        logging.exception("History read error")
        history = []

    messages = history + [
        {
            "role": "user",
            "content": question,
        }
    ]

    try:
        response = await client.responses.create(
            model="gpt-4.1-mini",
            instructions=SYSTEM_PROMPT,
            input=messages,
        )

        answer = response.output_text

        if not answer:
            answer = "Ҳозир жавоб тайёрлай олмадим."

    except Exception:
        logging.exception("AI error")
        await update.message.reply_text(
            "Ҳозир жавоб беришда хатолик юз берди. "
            "Кейинроқ уриниб кўринг."
        )
        return

    try:
        await save_message(user_id, "user", question)
        await save_message(user_id, "assistant", answer)
    except Exception:
        logging.exception("Database save error")

    for i in range(0, len(answer), 4000):
        await update.message.reply_text(
            answer[i:i + 4000]
        )


async def post_init(application):
    await init_db()


def main():
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            chat,
        )
    )

    print("Kichkina Ibrohim ishga tushdi!")
    app.run_polling()


if __name__ == "__main__":
    main()
    

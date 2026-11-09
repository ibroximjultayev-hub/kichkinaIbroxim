

import asyncpg
import os
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
from openai import AsyncOpenAI

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

SYSTEM_PROMPT = """
Сен Kichkina Ibrohim номли универсал AI ёрдамчисан.

Ўзбек тилида кирилл ва лотин ёзувларида,
шунингдек рус тилида мулоқот қил.

Фойдаланувчининг тилида жавоб бер.
Саволларга аниқ, тушунарли ва фойдали жавоб бер.
Таржима, таҳлил, матн ёзиш ва маслаҳат беришда ёрдам бер.
Ҳужжатлар, қонунчилик, Word, Excel ва PowerPoint
бўйича ёрдам беришга тайёр бўл.
Ўзингда мавжуд бўлмаган имкониятни бор деб айтма.
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Ассалому алайкум! Мен Kichkina Ibrohim AI ёрдамчисиман.\n\n"
        "Мен билан ўзбекча кирилл, лотин ёки рус тилида суҳбатлашинг!"
    )

async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question = update.message.text

    try:
        response = await client.responses.create(
            model="gpt-4.1-mini",
            instructions=SYSTEM_PROMPT,
            input=question
        )

        answer = response.output_text

        for i in range(0, len(answer), 4000):
            await update.message.reply_text(answer[i:i+4000])

    except Exception:
        logging.exception("AI error")
        await update.message.reply_text(
            "Ҳозир жавоб беришда хатолик юз берди. Кейинроқ уриниб кўринг."
        )

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, chat)
    )

    print("Kichkina Ibrohim ishga tushdi!")
    app.run_polling()

if __name__ == "__main__":
    main()

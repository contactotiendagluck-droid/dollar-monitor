import os
import json
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes
)

# Importamos funciones ya existentes de tu scraper
from dollar_scraper_advanced import (
    scrape_all, build_summary_message, now_ba_str
)

TZ_BA = ZoneInfo("America/Argentina/Buenos_Aires")
SUBS_FILE = "subscribers.json"

from flask import Flask
import threading

def keep_alive():
    app = Flask(__name__)

    @app.get("/")
    def home():
        return "Bot OK"

    # Render usa el puerto 10000 si está definido, sino 8080
    import os
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)

# Lanzamos el server en un thread para no bloquear el bot
threading.Thread(target=keep_alive, daemon=True).start()

# ---------------- Persistencia de suscriptores ---------------- #
def load_subs() -> set[int]:
    if os.path.exists(SUBS_FILE):
        try:
            with open(SUBS_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_subs(subs: set[int]) -> None:
    with open(SUBS_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(subs)), f)

SUBS = load_subs()

# ---------------- UI (botones) ---------------- #
def menu_markup(is_subscribed: bool) -> InlineKeyboardMarkup:
    if is_subscribed:
        buttons = [
            [InlineKeyboardButton("🔕 Desuscribirme", callback_data="unsub")],
            [InlineKeyboardButton("📨 Pedir ahora",   callback_data="now")],
        ]
    else:
        buttons = [
            [InlineKeyboardButton("🔔 Suscribirme (cada 10 min)", callback_data="sub")],
            [InlineKeyboardButton("📨 Pedir ahora",               callback_data="now")],
        ]
    return InlineKeyboardMarkup(buttons)

# ---------------- Helpers asíncronos ---------------- #
async def get_snapshot_text() -> str:
    """
    Ejecuta el scraping en un thread para no bloquear el loop async del bot.
    """
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, scrape_all)
    return build_summary_message(data)

# ---------------- Handlers ---------------- #
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    await update.message.reply_text(
        "Menú de opciones:",
        reply_markup=menu_markup(cid in SUBS),
    )

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    await update.message.reply_text(
        "Menú de opciones:",
        reply_markup=menu_markup(cid in SUBS),
    )

async def cmd_dolar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = await get_snapshot_text()
        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cid = query.message.chat_id

    if query.data == "sub":
        SUBS.add(cid); save_subs(SUBS)
        await query.edit_message_text(
            "✅ Quedaste **suscrito**. Te envío el estado cada 10 minutos.\n"
            "También podés usar /dolar cuando quieras.",
            reply_markup=menu_markup(True),
        )
    elif query.data == "unsub":
        SUBS.discard(cid); save_subs(SUBS)
        await query.edit_message_text(
            "✅ Te **desuscribiste**. No te enviaré más actualizaciones automáticas.\n"
            "Podés volver a suscribirte desde /menu.",
            reply_markup=menu_markup(False),
        )
    elif query.data == "now":
        try:
            text = await get_snapshot_text()
            await query.message.reply_text(text)
        except Exception as e:
            await query.message.reply_text(f"❌ Error: {e}")

# ---------------- Job cada 10 minutos ---------------- #
async def job_broadcast(context: ContextTypes.DEFAULT_TYPE):
    if not SUBS:
        return
    try:
        text = await get_snapshot_text()
    except Exception as e:
        print(f"[job] Error scrapeando: {e}")
        return

    for chat_id in list(SUBS):
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            print(f"[job] Error enviando a {chat_id}: {e}")

# ---------------- Main ---------------- #
if __name__ == "__main__":
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or "PON_AQUI_TU_TOKEN"
    app = ApplicationBuilder().token(TOKEN).build()

    # Comandos
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu",  cmd_menu))
    app.add_handler(CommandHandler("dolar", cmd_dolar))

    # Botones
    app.add_handler(CallbackQueryHandler(on_button))

    # Tarea periódica: cada 10 minutos (600s). Primer envío a los 30s.
    app.job_queue.run_repeating(job_broadcast, interval=600, first=30)

    print("🤖 Bot en vivo. Usá /start o /menu para suscribirte.")
    print("ℹ️ Recordá haber corrido al menos una vez:  python -m playwright install chromium")
    app.run_polling()

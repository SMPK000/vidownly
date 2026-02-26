import os, re, sqlite3, subprocess
from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, PreCheckoutQueryHandler,
    ContextTypes, filters
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 7425677220
FREE_LIMIT = 2

PRICES = {
    "sd": 10,
    "hd": 20,
    "audio": 5,
    "subtitle": 10
}

LEGAL_TEXT = (
    "Vidownly is a technical tool.\n"
    "Users are fully responsible for the content they access.\n"
    "Vidownly does not host or store any media.\n"
    "By using this bot, you confirm you have legal rights to the content."
)

# ================= DATABASE =================
db = sqlite3.connect("vidownly.db", check_same_thread=False)
cur = db.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    downloads INTEGER,
    last_date TEXT,
    is_admin INTEGER
)
""")
db.commit()

def get_user(uid):
    today = str(date.today())
    cur.execute("SELECT downloads, last_date, is_admin FROM users WHERE user_id=?", (uid,))
    row = cur.fetchone()

    if not row:
        cur.execute(
            "INSERT INTO users VALUES (?,?,?,?)",
            (uid, 0, today, 1 if uid == ADMIN_ID else 0)
        )
        db.commit()
        return 0, uid == ADMIN_ID

    downloads, last_date, is_admin = row
    if last_date != today:
        downloads = 0
        cur.execute(
            "UPDATE users SET downloads=?, last_date=? WHERE user_id=?",
            (0, today, uid)
        )
        db.commit()

    return downloads, bool(is_admin)

def inc_download(uid):
    cur.execute("UPDATE users SET downloads = downloads + 1 WHERE user_id=?", (uid,))
    db.commit()

def is_supported(text):
    return bool(re.search(r"(youtube|youtu|instagram|tiktok|twitter|x\.com|facebook|soundcloud)", text.lower()))

# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(LEGAL_TEXT)
    await update.message.reply_text(
        "👋 Welcome to Vidownly\n"
        "Send a video or audio link to download directly in Telegram."
    )

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text(
        "👑 Admin Panel\n"
        f"Free limit: {FREE_LIMIT}/day\n\n"
        f"SD: {PRICES['sd']}⭐\n"
        f"HD: {PRICES['hd']}⭐\n"
        f"Audio: {PRICES['audio']}⭐\n"
        f"Subtitle: {PRICES['subtitle']}⭐"
    )

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.replace("/support", "").strip()
    if not msg:
        await update.message.reply_text("Write your message after /support")
        return
    await context.bot.send_message(
        ADMIN_ID,
        f"📩 Support message\nFrom: {update.effective_user.id}\n\n{msg}"
    )
    await update.message.reply_text("✅ Message sent.")

# ================= PAYMENTS =================
async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    item = q.data
    if item not in PRICES:
        return

    prices = [LabeledPrice(label=item, amount=PRICES[item])]
    await q.message.reply_invoice(
        title="Vidownly Download",
        description=f"Purchase {item}",
        payload=item,
        provider_token="",
        currency="XTR",
        prices=prices
    )

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Payment successful. Processing...")

# ================= DOWNLOAD =================
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid = update.effective_user.id
    downloads, is_admin = get_user(uid)

    if not is_supported(text):
        return

    if downloads >= FREE_LIMIT and not is_admin:
        kb = [
            [InlineKeyboardButton("⭐ SD Video", callback_data="sd")],
            [InlineKeyboardButton("⭐ HD Video", callback_data="hd")],
            [InlineKeyboardButton("⭐ Audio", callback_data="audio")],
            [InlineKeyboardButton("⭐ Subtitle", callback_data="subtitle")]
        ]
        await update.message.reply_text(
            "Free limit reached. Choose an option:",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    await update.message.reply_text("⏳ Downloading...")

    try:
        filename = "media.mp4"
        subprocess.run(["yt-dlp", "-f", "mp4", "-o", filename, text], check=True)
        await update.message.reply_video(open(filename, "rb"))
        os.remove(filename)
        inc_download(uid)
    except Exception:
        await update.message.reply_text("❌ Download failed.")

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("support", support))
    app.add_handler(CallbackQueryHandler(buy))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, paid))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.run_polling()

if __name__ == "__main__":
    main()

import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

from config import settings

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("vidownly")

BASE_DIR = Path(__file__).resolve().parent.parent
LANG_DIR = BASE_DIR / "languages"
DB_PATH = BASE_DIR / settings.db_path

DEFAULT_TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "welcome": "Welcome to <b>Vidownly</b>.\n\nChoose a language to begin.",
        "terms": (
            "Before using this service, please read and accept the following terms:\n\n"
            "• Vidownly is a technical tool that processes media and links provided by users.\n"
            "• Users are solely responsible for the content they access, upload, download, or share.\n"
            "• Users must comply with copyright laws and platform terms.\n"
            "• Vidownly does not claim ownership of third-party content.\n"
            "• By continuing, you confirm that you have the rights and permissions to use the content you provide."
        ),
        "accept": "Accept Terms",
        "language": "Language",
        "menu": "Main Menu",
        "profile": "Profile",
        "buy": "Buy Credits",
        "support": "Support",
        "howto": "Send a Telegram file or a direct media URL you have rights to use.",
        "send_input": "Send a file, or use the menu below.",
        "admin_only": "Admin only.",
        "not_accepted": "Please accept the terms first.",
        "lang_set": "Language set to {lang}.",
        "profile_text": (
            "<b>Your profile</b>\n\n"
            "ID: <code>{user_id}</code>\n"
            "Username: @{username}\n"
            "Language: {language}\n"
            "Joined: {joined}\n"
            "Free left today: {free_left}\n"
            "Paid credits: {paid_credits}\n"
            "Premium until: {premium_until}"
        ),
        "support_text": "Send your message. It will be forwarded anonymously to support.",
        "admin_panel": "<b>Admin Panel</b>\n\nChoose an action:",
        "stats_text": (
            "<b>Stats</b>\n\n"
            "Users: {users}\n"
            "Accepted users: {accepted}\n"
            "Downloads: {downloads}\n"
            "Payments: {payments}\n"
            "Revenue Stars: {revenue}\n"
        ),
        "invoice_title": "{plan} Plan",
        "invoice_desc": "Unlock {plan} access in Vidownly.",
        "payment_ok": "Payment received. Your access was updated.",
        "purchase_menu": "Choose a plan:",
        "free_plan": "Free plan is active for you.",
    }
}


def load_texts() -> dict[str, dict[str, str]]:
    texts = dict(DEFAULT_TEXTS)
    if LANG_DIR.exists():
        for file in LANG_DIR.glob("*.json"):
            try:
                with file.open("r", encoding="utf-8") as f:
                    texts[file.stem] = json.load(f)
            except Exception:
                logger.exception("Failed to load language file: %s", file)
    return texts


TEXTS = load_texts()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def ensure_dirs() -> None:
    LANG_DIR.mkdir(parents=True, exist_ok=True)


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    ensure_dirs()
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                language TEXT DEFAULT 'en',
                joined_at TEXT,
                accepted_terms INTEGER DEFAULT 0,
                free_left INTEGER DEFAULT 3,
                free_reset_at TEXT,
                paid_credits INTEGER DEFAULT 0,
                premium_until TEXT,
                banned INTEGER DEFAULT 0,
                referred_by INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                purpose TEXT NOT NULL,
                stars INTEGER NOT NULL,
                telegram_charge_id TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS support_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                answered INTEGER DEFAULT 0
            )
            """
        )
        conn.commit()


def get_setting(key: str, default: str = "") -> str:
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting_db(key: str, value: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        conn.commit()


def get_user(user_id: int) -> sqlite3.Row | None:
    with db() as conn:
        return conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()


def upsert_user(user_id: int, username: str, full_name: str) -> None:
    existing = get_user(user_id)
    with db() as conn:
        if existing:
            conn.execute(
                """
                UPDATE users
                SET username = ?, full_name = ?
                WHERE user_id = ?
                """,
                (username, full_name, user_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO users(user_id, username, full_name, language, joined_at, accepted_terms, free_left, free_reset_at, paid_credits, premium_until, banned, referred_by)
                VALUES(?, ?, ?, ?, ?, 0, ?, ?, 0, NULL, 0, NULL)
                """,
                (
                    user_id,
                    username,
                    full_name,
                    settings.default_language,
                    now_utc().isoformat(),
                    settings.free_downloads_per_day,
                    now_utc().isoformat(),
                ),
            )
        conn.commit()


def set_user_language(user_id: int, language: str) -> None:
    with db() as conn:
        conn.execute("UPDATE users SET language = ? WHERE user_id = ?", (language, user_id))
        conn.commit()


def set_terms_accepted(user_id: int, accepted: bool = True) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE users SET accepted_terms = ? WHERE user_id = ?",
            (1 if accepted else 0, user_id),
        )
        conn.commit()


def update_free_quota_if_needed(user_id: int) -> int:
    user = get_user(user_id)
    if not user:
        return settings.free_downloads_per_day

    free_reset_at = user["free_reset_at"]
    free_left = int(user["free_left"] or 0)

    try:
        reset_time = datetime.fromisoformat(free_reset_at)
    except Exception:
        reset_time = now_utc() - timedelta(days=1)

    if now_utc() - reset_time >= timedelta(hours=settings.free_download_reset_hours):
        free_left = settings.free_downloads_per_day
        with db() as conn:
            conn.execute(
                "UPDATE users SET free_left = ?, free_reset_at = ? WHERE user_id = ?",
                (free_left, now_utc().isoformat(), user_id),
            )
            conn.commit()

    return free_left


def consume_free_slot(user_id: int) -> int:
    free_left = update_free_quota_if_needed(user_id)
    if free_left <= 0:
        return 0

    with db() as conn:
        conn.execute(
            "UPDATE users SET free_left = free_left - 1 WHERE user_id = ?",
            (user_id,),
        )
        conn.commit()

    return free_left - 1


def add_paid_credits(user_id: int, credits: int) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE users SET paid_credits = paid_credits + ? WHERE user_id = ?",
            (credits, user_id),
        )
        conn.commit()


def get_lang(user_id: int) -> str:
    user = get_user(user_id)
    if not user:
        return settings.default_language
    return user["language"] or settings.default_language


def t(user_id: int, key: str, **kwargs: Any) -> str:
    lang = get_lang(user_id)
    data = TEXTS.get(lang, TEXTS["en"])
    text = data.get(key) or TEXTS["en"].get(key) or key
    return text.format(**kwargs)


def lang_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("English", callback_data="lang_en"),
            InlineKeyboardButton("فارسی", callback_data="lang_fa"),
        ],
        [
            InlineKeyboardButton("العربية", callback_data="lang_ar"),
            InlineKeyboardButton("Türkçe", callback_data="lang_tr"),
        ],
        [
            InlineKeyboardButton("Русский", callback_data="lang_ru"),
            InlineKeyboardButton("Español", callback_data="lang_es"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


def main_keyboard(user_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("👤 Profile", callback_data="menu_profile"),
            InlineKeyboardButton("⭐ Buy", callback_data="menu_buy"),
        ],
        [
            InlineKeyboardButton("🌍 Language", callback_data="menu_language"),
            InlineKeyboardButton("🛟 Support", callback_data="menu_support"),
        ],
    ]
    if user_id == settings.admin_id:
        buttons.append([InlineKeyboardButton("👑 Admin", callback_data="menu_admin")])
    return InlineKeyboardMarkup(buttons)


async def ensure_user(update: Update) -> None:
    if not update.effective_user:
        return
    u = update.effective_user
    username = u.username or ""
    full_name = (u.full_name or "").strip()
    upsert_user(u.id, username, full_name)


async def show_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user(update)
    user = update.effective_user
    if not user or not update.message:
        return

    accepted = get_user(user.id)["accepted_terms"] if get_user(user.id) else 0
    if not accepted:
        await update.message.reply_text(
            f"{TEXTS['en']['welcome']}\n\n{TEXTS['en']['terms']}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("✅ Accept Terms", callback_data="accept_terms")],
                    [InlineKeyboardButton("🌍 Choose Language", callback_data="menu_language")],
                ]
            ),
        )
        return

    await update.message.reply_text(
        t(user.id, "welcome"),
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(user.id),
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user(update)
    if not update.effective_user:
        return

    user_id = update.effective_user.id
    payload = context.args[0] if context.args else ""
    if payload.startswith("ref_"):
        ref_id = payload.replace("ref_", "").strip()
        if ref_id.isdigit() and int(ref_id) != user_id:
            with db() as conn:
                conn.execute(
                    "UPDATE users SET referred_by = COALESCE(referred_by, ?) WHERE user_id = ?",
                    (int(ref_id), user_id),
                )
                conn.commit()

    await show_start(update, context)


async def accept_terms_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user:
        return
    await query.answer()
    set_terms_accepted(query.from_user.id, True)
    await query.edit_message_text(
        "Terms accepted.\n\nChoose your language.",
        reply_markup=lang_keyboard(),
    )


async def language_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("Choose your language.", reply_markup=lang_keyboard())
        return

    if update.message and update.effective_user:
        await update.message.reply_text("Choose your language.", reply_markup=lang_keyboard())


async def set_language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user:
        return

    await query.answer()
    language = query.data.replace("lang_", "")
    set_user_language(query.from_user.id, language)
    await query.edit_message_text(
        t(query.from_user.id, "lang_set", lang=language),
        reply_markup=main_keyboard(query.from_user.id),
    )


async def menu_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user:
        return
    await query.answer()
    user = get_user(query.from_user.id)
    if not user:
        return
    premium_until = user["premium_until"] or "—"
    username = user["username"] or "anonymous"
    text = t(
        query.from_user.id,
        "profile_text",
        user_id=query.from_user.id,
        username=username,
        language=user["language"] or settings.default_language,
        joined=user["joined_at"] or "—",
        free_left=user["free_left"] or 0,
        paid_credits=user["paid_credits"] or 0,
        premium_until=premium_until,
    )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=main_keyboard(query.from_user.id))


async def menu_buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user:
        return
    await query.answer()
    text = t(query.from_user.id, "purchase_menu")
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"SD • {settings.price_sd} ⭐", callback_data="buy_sd")],
            [InlineKeyboardButton(f"HD • {settings.price_hd} ⭐", callback_data="buy_hd")],
            [InlineKeyboardButton(f"Full HD • {settings.price_fullhd} ⭐", callback_data="buy_fullhd")],
            [InlineKeyboardButton(f"Audio • {settings.price_audio} ⭐", callback_data="buy_audio")],
            [InlineKeyboardButton(f"Subtitle • {settings.price_subtitle} ⭐", callback_data="buy_subtitle")],
            [InlineKeyboardButton(f"Weekly • {settings.price_weekly} ⭐", callback_data="buy_weekly")],
            [InlineKeyboardButton(f"Monthly • {settings.price_monthly} ⭐", callback_data="buy_monthly")],
            [InlineKeyboardButton("⬅️ Back", callback_data="menu_back")],
        ]
    )
    await query.edit_message_text(text, reply_markup=keyboard)


async def send_star_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE, plan: str, stars: int, credits: int = 1) -> None:
    if not update.callback_query or not update.callback_query.from_user:
        return

    chat_id = update.callback_query.message.chat_id
    payload = f"plan:{plan}:credits:{credits}:user:{update.callback_query.from_user.id}"
    await context.bot.send_invoice(
        chat_id=chat_id,
        title=t(update.callback_query.from_user.id, "invoice_title", plan=plan),
        description=t(update.callback_query.from_user.id, "invoice_desc", plan=plan),
        payload=payload,
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=plan, amount=stars)],
    )


async def buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user:
        return
    await query.answer()
    mapping = {
        "buy_sd": ("SD", settings.price_sd, 1),
        "buy_hd": ("HD", settings.price_hd, 1),
        "buy_fullhd": ("Full HD", settings.price_fullhd, 1),
        "buy_audio": ("Audio", settings.price_audio, 1),
        "buy_subtitle": ("Subtitle", settings.price_subtitle, 1),
        "buy_weekly": ("Weekly", settings.price_weekly, 7),
        "buy_monthly": ("Monthly", settings.price_monthly, 30),
    }
    if query.data not in mapping:
        return
    plan, stars, credits = mapping[query.data]
    await send_star_invoice(update, context, plan, stars, credits)


async def pre_checkout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.pre_checkout_query
    if not query:
        return
    await query.answer(ok=True)


async def payment_success_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.successful_payment or not update.effective_user:
        return

    sp = message.successful_payment
    payload = sp.invoice_payload or ""
    credits = 1
    parts = payload.split(":")
    if "credits" in parts:
        try:
            credits = int(parts[parts.index("credits") + 1])
        except Exception:
            credits = 1

    add_paid_credits(update.effective_user.id, credits)

    with db() as conn:
        conn.execute(
            """
            INSERT INTO payments(user_id, purpose, stars, telegram_charge_id, status, created_at)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (
                update.effective_user.id,
                payload,
                sp.total_amount,
                sp.telegram_payment_charge_id,
                "paid",
                now_utc().isoformat(),
            ),
        )
        conn.commit()

    await message.reply_text(t(update.effective_user.id, "payment_ok"), reply_markup=main_keyboard(update.effective_user.id))


async def support_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user(update)
    if update.message and update.effective_user:
        await update.message.reply_text(t(update.effective_user.id, "support_text"))


async def forward_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    text = update.message.text or update.message.caption or ""
    if not text:
        return

    with db() as conn:
        conn.execute(
            """
            INSERT INTO support_messages(user_id, message, created_at, answered)
            VALUES(?, ?, ?, 0)
            """,
            (update.effective_user.id, text, now_utc().isoformat()),
        )
        conn.commit()

    admin_text = (
        f"Support message from <code>{update.effective_user.id}</code>\n"
        f"Username: @{update.effective_user.username or 'anonymous'}\n\n"
        f"{text}"
    )
    try:
        await context.bot.send_message(
            chat_id=settings.admin_id,
            text=admin_text,
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        logger.exception("Failed to forward support message")

    await update.message.reply_text("Message sent.")


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or update.effective_user.id != settings.admin_id:
        if update.message:
            await update.message.reply_text(t(update.effective_user.id if update.effective_user else 0, "admin_only"))
        return

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Stats", callback_data="admin_stats")],
            [InlineKeyboardButton("Broadcast", callback_data="admin_broadcast")],
            [InlineKeyboardButton("Prices", callback_data="admin_prices")],
            [InlineKeyboardButton("Free Access", callback_data="admin_free")],
            [InlineKeyboardButton("Users", callback_data="admin_users")],
            [InlineKeyboardButton("Support Inbox", callback_data="admin_support")],
        ]
    )
    if update.message:
        await update.message.reply_text(t(update.effective_user.id, "admin_panel"), parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user or query.from_user.id != settings.admin_id:
        return
    await query.answer()

    if query.data == "admin_stats":
        with db() as conn:
            users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
            accepted = conn.execute("SELECT COUNT(*) AS c FROM users WHERE accepted_terms = 1").fetchone()["c"]
            downloads = conn.execute("SELECT COUNT(*) AS c FROM payments").fetchone()["c"]
            payments = conn.execute("SELECT COUNT(*) AS c FROM payments WHERE status = 'paid'").fetchone()["c"]
            revenue = conn.execute("SELECT COALESCE(SUM(stars), 0) AS s FROM payments WHERE status = 'paid'").fetchone()["s"]

        await query.edit_message_text(
            t(
                settings.admin_id,
                "stats_text",
                users=users,
                accepted=accepted,
                downloads=downloads,
                payments=payments,
                revenue=revenue,
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="menu_admin")]]),
        )
        return

    if query.data == "admin_broadcast":
        context.user_data["awaiting_broadcast"] = True
        await query.edit_message_text(
            "Send the broadcast message now.\nYou can send text, photo, or video.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="menu_admin")]]),
        )
        return

    if query.data == "admin_prices":
        text = (
            f"Current prices:\n"
            f"SD: {settings.price_sd} ⭐\n"
            f"HD: {settings.price_hd} ⭐\n"
            f"Full HD: {settings.price_fullhd} ⭐\n"
            f"Audio: {settings.price_audio} ⭐\n"
            f"Subtitle: {settings.price_subtitle} ⭐\n"
            f"Weekly: {settings.price_weekly} ⭐\n"
            f"Monthly: {settings.price_monthly} ⭐\n\n"
            f"Use settings in .env to change them for now."
        )
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="menu_admin")]]))
        return

    if query.data == "admin_free":
        text = f"Free downloads per day: {settings.free_downloads_per_day}"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="menu_admin")]]))
        return

    if query.data == "admin_users":
        await query.edit_message_text(
            "User management will be added in the next step.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="menu_admin")]]),
        )
        return

    if query.data == "admin_support":
        await query.edit_message_text(
            "Support inbox is forwarded to the admin chat.\nReply routing will be added in the next step.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="menu_admin")]]),
        )
        return


async def menu_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user:
        return
    await query.answer()
    await query.edit_message_text(
        t(query.from_user.id, "welcome"),
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(query.from_user.id),
    )


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    user = get_user(update.effective_user.id)
    if not user:
        return

    if not user["accepted_terms"]:
        await update.message.reply_text(t(update.effective_user.id, "not_accepted"), reply_markup=lang_keyboard())
        return

    if user["banned"]:
        await update.message.reply_text("You are banned.")
        return

    if update.message.text and update.message.text.startswith(("http://", "https://")):
        await update.message.reply_text(
            "At this stage, Vidownly accepts Telegram uploads and authorized direct media links only.\n"
            "The next step will connect the processing engine."
        )
        return

    # Telegram file upload flow
    if update.message.video or update.message.document or update.message.audio or update.message.photo:
        remaining_free = update_free_quota_if_needed(update.effective_user.id)
        if remaining_free > 0:
            remaining_after = consume_free_slot(update.effective_user.id)
            status = f"Free processing started. Free left today: {remaining_after}"
        else:
            paid_credits = int(user["paid_credits"] or 0)
            if paid_credits <= 0:
                await update.message.reply_text(
                    "Free quota is used up.\nBuy credits from the menu with Telegram Stars.",
                    reply_markup=main_keyboard(update.effective_user.id),
                )
                return
            with db() as conn:
                conn.execute(
                    "UPDATE users SET paid_credits = paid_credits - 1 WHERE user_id = ?",
                    (update.effective_user.id,),
                )
                conn.commit()
            status = "Paid credit used. Processing started."

        file_id = (
            update.message.video.file_id
            if update.message.video
            else update.message.document.file_id
            if update.message.document
            else update.message.audio.file_id
            if update.message.audio
            else update.message.photo[-1].file_id
        )

        with db() as conn:
            conn.execute(
                """
                INSERT INTO payments(user_id, purpose, stars, telegram_charge_id, status, created_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (update.effective_user.id, f"media:{file_id}", 0, "", "processed", now_utc().isoformat()),
            )
            conn.commit()

        await update.message.reply_text(
            f"{status}\n\nReceived media file_id:\n<code>{file_id}</code>\n\n"
            "Processing engine will be attached in the next step.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_keyboard(update.effective_user.id),
        )
        return

    await update.message.reply_text(
        t(update.effective_user.id, "send_input"),
        reply_markup=main_keyboard(update.effective_user.id),
    )


async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user:
        return
    await query.answer()

    if query.data == "menu_profile":
        return await menu_profile(update, context)
    if query.data == "menu_buy":
        return await menu_buy(update, context)
    if query.data == "menu_language":
        return await language_menu(update, context)
    if query.data == "menu_support":
        await query.edit_message_text(t(query.from_user.id, "support_text"), reply_markup=main_keyboard(query.from_user.id))
        return
    if query.data == "menu_admin":
        if query.from_user.id == settings.admin_id:
            return await admin_panel(update, context)
        await query.edit_message_text(t(query.from_user.id, "admin_only"))
        return
    if query.data == "menu_back":
        return await menu_back(update, context)


async def broadcast_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if update.effective_user.id != settings.admin_id:
        return

    if not context.user_data.get("awaiting_broadcast"):
        return

    context.user_data["awaiting_broadcast"] = False

    with db() as conn:
        ids = [row["user_id"] for row in conn.execute("SELECT user_id FROM users").fetchall()]

    sent = 0
    for uid in ids:
        try:
            if update.message.text:
                await context.bot.send_message(uid, update.message.text)
            elif update.message.photo:
                await context.bot.send_photo(uid, update.message.photo[-1].file_id, caption=update.message.caption or "")
            elif update.message.video:
                await context.bot.send_video(uid, update.message.video.file_id, caption=update.message.caption or "")
            sent += 1
        except Exception:
            continue

    await update.message.reply_text(f"Broadcast finished. Sent to {sent} users.")


def build_app() -> Application:
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is missing. Add it to .env or Render environment variables.")

    app = ApplicationBuilder().token(settings.bot_token).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("profile", menu_profile))
    app.add_handler(CommandHandler("buy", menu_buy))
    app.add_handler(CommandHandler("support", support_entry))
    app.add_handler(CommandHandler("admin", admin_panel))

    app.add_handler(CallbackQueryHandler(accept_terms_callback, pattern="^accept_terms$"))
    app.add_handler(CallbackQueryHandler(set_language_callback, pattern="^lang_"))
    app.add_handler(CallbackQueryHandler(menu_router, pattern="^menu_"))
    app.add_handler(CallbackQueryHandler(buy_callback, pattern="^buy_"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))

    app.add_handler(PreCheckoutQueryHandler(pre_checkout_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, payment_success_handler))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_media))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL | filters.AUDIO, handle_media))

    app.add_handler(MessageHandler(filters.ALL, broadcast_pending), group=1)

    return app


async def post_init(_: Application) -> None:
    init_db()
    logger.info("Database initialized.")


def main() -> None:
    init_db()
    app = build_app()
    app.post_init = post_init
    logger.info("Vidownly starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

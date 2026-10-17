import logging
import os
import sqlite3

import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.environ["BOT_TOKEN"]
DB_PATH = os.getenv("DB_PATH", "alerts.db")
PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"

COINS = {
    "btc": "bitcoin",
    "bitcoin": "bitcoin",
    "eth": "ethereum",
    "ethereum": "ethereum",
    "sol": "solana",
    "solana": "solana",
}

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)


def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS watches (
            chat_id INTEGER NOT NULL,
            coin TEXT NOT NULL,
            threshold REAL NOT NULL,
            baseline REAL NOT NULL,
            PRIMARY KEY (chat_id, coin)
        )
    """)
    return conn


async def get_prices(coins):
    ids = ",".join(sorted(set(coins)))
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            PRICE_URL,
            params={"ids": ids, "vs_currencies": "usd"},
        )
        response.raise_for_status()
        data = response.json()

    return {
        coin: float(data[coin]["usd"])
        for coin in coins
        if coin in data and "usd" in data[coin]
    }


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Welcome to Web3 Price Alerts!\n\n"
        "/price btc - current BTC price\n"
        "/watch btc 5 - alert on a 5% move\n"
        "/watchlist - show your alerts\n"
        "/unwatch btc - remove an alert\n"
        "/help - show commands\n\n"
        "Supported coins: BTC, ETH, SOL.\n"
        "Alerts are informational, not financial advice."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0].lower() not in COINS:
        await update.effective_message.reply_text(
            "Usage: /price btc\nSupported: BTC, ETH, SOL"
        )
        return

    coin = COINS[context.args[0].lower()]
    try:
        prices = await get_prices([coin])
        if coin not in prices:
            raise ValueError("Price unavailable")
        await update.effective_message.reply_text(
            f"{coin.upper()}: ${prices[coin]:,.6f} USD"
        )
    except (httpx.HTTPError, ValueError, KeyError):
        log.exception("Price lookup failed")
        await update.effective_message.reply_text(
            "Couldn't fetch the price right now. Try again shortly."
        )


async def watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.effective_message.reply_text(
            "Usage: /watch btc 5\n"
            "The number is the percentage move that triggers an alert."
        )
        return

    name = context.args[0].lower()
    if name not in COINS:
        await update.effective_message.reply_text(
            "Supported coins: BTC, ETH, SOL."
        )
        return

    try:
        threshold = float(context.args[1])
        if not 0.1 <= threshold <= 100:
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text(
            "Choose a threshold between 0.1 and 100 percent."
        )
        return

    coin = COINS[name]
    try:
        prices = await get_prices([coin])
        if coin not in prices:
            raise ValueError("Price unavailable")
        baseline = prices[coin]
        conn = db()
        try:
            conn.execute(
                """INSERT INTO watches
                   (chat_id, coin, threshold, baseline)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(chat_id, coin) DO UPDATE SET
                   threshold=excluded.threshold,
                   baseline=excluded.baseline""",
                (update.effective_chat.id, coin, threshold, baseline),
            )
            conn.commit()
        finally:
            conn.close()

        await update.effective_message.reply_text(
            f"Watching {coin.upper()} from ${baseline:,.6f} USD.\n"
            f"I'll alert you after a {threshold:g}% move up or down."
        )
    except (httpx.HTTPError, ValueError, KeyError, sqlite3.Error):
        log.exception("Could not create watch")
        await update.effective_message.reply_text(
            "Couldn't fetch the price or save the alert. Try again."
        )


async def watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = db()
    try:
        rows = conn.execute(
            """SELECT coin, threshold, baseline FROM watches
               WHERE chat_id=? ORDER BY coin""",
            (update.effective_chat.id,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        await update.effective_message.reply_text("Your watchlist is empty.")
        return

    lines = [
        f"{coin.upper()}: +/-{threshold:g}% from ${baseline:,.6f}"
        for coin, threshold, baseline in rows
    ]
    await update.effective_message.reply_text("\n".join(lines))


async def unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0].lower() not in COINS:
        await update.effective_message.reply_text("Usage: /unwatch btc")
        return

    coin = COINS[context.args[0].lower()]
    conn = db()
    try:
        cursor = conn.execute(
            "DELETE FROM watches WHERE chat_id=? AND coin=?",
            (update.effective_chat.id, coin),
        )
        conn.commit()
        removed = cursor.rowcount > 0
    finally:
        conn.close()

    await update.effective_message.reply_text(
        f"Stopped watching {coin.upper()}."
        if removed else f"No active alert for {coin.upper()}."
    )


async def check_watches(context: ContextTypes.DEFAULT_TYPE):
    conn = db()
    try:
        rows = conn.execute(
            "SELECT chat_id, coin, threshold, baseline FROM watches"
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return

    try:
        prices = await get_prices([row[1] for row in rows])
    except (httpx.HTTPError, ValueError, KeyError):
        log.warning("Price check failed; will retry next interval.")
        return

    for chat_id, coin, threshold, baseline in rows:
        current = prices.get(coin)
        if current is None or baseline <= 0:
            continue

        change = (current - baseline) / baseline * 100
        if abs(change) >= threshold:
            direction = "UP" if change > 0 else "DOWN"
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"🚨 {coin.upper()} moved {direction} {change:+.2f}%\n"
                        f"Reference: ${baseline:,.6f}\n"
                        f"Current: ${current:,.6f}\n"
                        "Reference reset to the latest price."
                    ),
                )
                conn = db()
                try:
                    conn.execute(
                        """UPDATE watches SET baseline=?
                           WHERE chat_id=? AND coin=?""",
                        (current, chat_id, coin),
                    )
                    conn.commit()
                finally:
                    conn.close()
            except Exception:
                log.exception("Could not deliver alert for %s", coin)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Unhandled Telegram handler error", exc_info=context.error)


def main():
    db().close()
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("watch", watch))
    app.add_handler(CommandHandler("watchlist", watchlist))
    app.add_handler(CommandHandler("unwatch", unwatch))
    app.add_error_handler(on_error)

    app.job_queue.run_repeating(check_watches, interval=60, first=10)
    log.info("Bot started; price checks run every 60 seconds")
    app.run_polling()


if __name__ == "__main__":
    main()

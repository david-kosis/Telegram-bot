# Web3 Telegram Price Alerts

A read-only Telegram bot that checks Bitcoin, Ethereum, and Solana prices through CoinGecko and sends percentage-move alerts.

## Commands

- `/start` or `/help` — show instructions
- `/price btc` — get the current price in USD
- `/watch btc 5` — alert after a 5% rise or fall from the current reference price
- `/watchlist` — list your active alerts
- `/unwatch btc` — remove a price alert

Supported aliases: BTC/Bitcoin, ETH/Ethereum, SOL/Solana. Thresholds must be between 0.1% and 100%.

## Run locally

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export BOT_TOKEN="YOUR_BOTFATHER_TOKEN"
python bot.py
```

On Windows PowerShell, set the token with `$env:BOT_TOKEN="YOUR_BOTFATHER_TOKEN"`.

## Deploy as a cloud worker

Use a continuously running background worker on a hosting provider such as Render or Railway.

- Build command: `pip install -r requirements.txt`
- Start command: `python bot.py`
- Required secret/environment variable: `BOT_TOKEN`
- Optional variable: `DB_PATH`, set to a file path on a persistent mounted disk if the host uses an ephemeral filesystem.

SQLite is suitable for a single worker instance. Use a managed database if you scale to multiple instances. Do not deploy multiple polling instances using the same Telegram bot token.

## Security and limitations

- Never commit the BotFather token or an `.env` file.
- This bot does not connect to wallets, sign transactions, trade, or withdraw funds.
- CoinGecko requests can be rate-limited or unavailable; alerts are polling-based and not guaranteed real-time.
- Alerts are informational and are not financial advice.

# Pump.fun Python Telegram Bot

Single-file Telegram bot for trading [Pump.fun](https://pump.fun) tokens via [PumpPortal](https://pumpportal.fun).

**Repo:** https://github.com/spanda6z/pumpfun-python-telegram-bot  
**Public** · Python 3.11 · Railway-ready

## Features

- Paste a mint → Buy / Sell buttons
- `/buy` `/sell` `/panic` `/positions` `/wallet` `/settings` `/history` `/invite`
- Paper trade mode (default)
- Referral links (`/invite`)
- Activity channel posts on buy/sell
- Owner-only access (`TELEGRAM_ALLOWED_USER_IDS`)

## Local run

```bash
git clone https://github.com/spanda6z/pumpfun-python-telegram-bot.git
cd pumpfun-python-telegram-bot
pip install -r requirements.txt
cp .env.example .env
# edit .env
python single_file_bot.py
```

## Deploy on Railway

1. https://railway.app → **New Project** → **Deploy from GitHub**
2. Select **spanda6z/pumpfun-python-telegram-bot**
3. Add variables (see `.env.example`)
4. Deploy — long-running worker (no public URL needed)

Keep `PAPER_TRADE=true` until you verify the flow.

## Safety

This can spend real SOL. You are responsible for losses. Never commit `.env` or private keys.

## License

MIT

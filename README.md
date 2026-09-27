# Pump.fun Python Telegram Bot

**New dedicated public repository** (not the TypeScript bot).

https://github.com/spanda6z/pumpfun-python-telegram-bot

## What this is

Python single-file Telegram bot for Pump.fun via PumpPortal:

- Paste mint → buy/sell
- Paper trade (default)
- Referrals (`/invite`)
- Activity channel broadcasts
- Railway deploy (Dockerfile included)

## Get the full bot source

The complete `single_file_bot.py` is available here:

https://github.com/spanda6z/pumpfun-telegram-bot/blob/main/python/single_file_bot.py

**Copy it into this repo as `single_file_bot.py`**, then either:

```bash
# Local
pip install -r requirements.txt
cp .env.example .env   # fill secrets
python single_file_bot.py
```

or on Railway use `run_bot.py` (payload chunks) **or** change Dockerfile to:

```dockerfile
CMD ["python", "-u", "single_file_bot.py"]
```

## Deploy on Railway

1. https://railway.app → New Project → Deploy from GitHub
2. Select **spanda6z/pumpfun-python-telegram-bot**
3. Variables from `.env.example`
4. Deploy as a **worker** (no public domain required)

Keep `PAPER_TRADE=true` until verified.

## Other repos (do not confuse)

| Repo | What |
|------|------|
| **This one** | New Python bot (public) |
| `pumpfun-telegram-bot` | Existing TypeScript bot |
| `pumpfun-telegram-bot-public` | Earlier mirror attempt |

## License

MIT — trade at your own risk.

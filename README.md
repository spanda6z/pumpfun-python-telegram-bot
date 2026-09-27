# Pump.fun Python Telegram Bot

https://github.com/spanda6z/pumpfun-python-telegram-bot

## Required file

This repo must contain **`single_file_bot.py`**.

If the Docker build fails with "single_file_bot.py: not found", copy it from:

https://github.com/spanda6z/pumpfun-telegram-bot/blob/main/python/single_file_bot.py

(Raw → save as `single_file_bot.py` in this repo root.)

## Railway

1. Deploy this repo from GitHub
2. Set variables (see `.env.example`)
3. Keep `PAPER_TRADE=true` until verified

## Local

```bash
pip install -r requirements.txt
cp .env.example .env
python single_file_bot.py
```

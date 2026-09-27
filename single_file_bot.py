# ==============================================================
# PUMP.FUN TELEGRAM BOT - COMMUNITY / SPACE VERSION
# ==============================================================
# Shared wallet for the whole space (not owner-only).
# PUBLIC_ACCESS=true (default) => anyone can use the bot.
# WARNING: Keep PAPER_TRADE=true until verified. Shared wallet = shared risk.
# ==============================================================

from __future__ import annotations

import os
import re
import logging
from datetime import datetime
from typing import Optional, Tuple

import base58
import httpx
from dotenv import load_dotenv
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pumpbot")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
PUBLIC_ACCESS = os.getenv("PUBLIC_ACCESS", "true").lower() in ("1", "true", "yes", "on")
ALLOWED_USERS = [
    int(x.strip())
    for x in os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").split(",")
    if x.strip().isdigit()
]
ADMIN_USERS = [
    int(x.strip())
    for x in os.getenv("TELEGRAM_ADMIN_USER_IDS", "").split(",")
    if x.strip().isdigit()
] or list(ALLOWED_USERS)

RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com").strip()
PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY", "").strip()
PAPER_TRADE = os.getenv("PAPER_TRADE", "true").lower() in ("1", "true", "yes", "on")
BUY_SIZE_SOL = float(os.getenv("BUY_SIZE_SOL", "0.5"))
SLIPPAGE_PCT = int(os.getenv("SLIPPAGE_PCT", "15"))
PRIORITY_FEE_SOL = float(os.getenv("PRIORITY_FEE_SOL", "0.0005"))
PUMPPORTAL_API = "https://pumpportal.fun/api/trade-local"
BOT_USERNAME = os.getenv("BOT_USERNAME", "").strip()
ACTIVITY_CHANNEL_ID = int(os.getenv("ACTIVITY_CHANNEL_ID", "0") or "0")
BROADCAST_ENABLED = os.getenv("BROADCAST_ENABLED", "true").lower() in ("1", "true", "yes", "on")
MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

KEYPAIR: Optional[Keypair] = None
if PRIVATE_KEY:
    try:
        KEYPAIR = Keypair.from_base58_string(PRIVATE_KEY)
    except Exception as e:
        log.error("Invalid WALLET_PRIVATE_KEY: %s", e)

positions: dict = {}
trade_history: list = []
config = {
    "buy_amount": BUY_SIZE_SOL,
    "slippage": SLIPPAGE_PCT,
    "priority_fee": PRIORITY_FEE_SOL,
    "auto_buy": False,
    "paper": PAPER_TRADE,
}
pending_set: dict = {}
referrals: dict = {}
user_referred_by: dict = {}
_bot_app = None


def _is_allowed(user_id: int) -> bool:
    if PUBLIC_ACCESS:
        return True
    if not ALLOWED_USERS:
        return True
    return user_id in ALLOWED_USERS


def _is_admin(user_id: int) -> bool:
    if not ADMIN_USERS:
        return True
    return user_id in ADMIN_USERS


def access_control(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if user is None or not _is_allowed(user.id):
            if update.message:
                await update.message.reply_text("Unauthorized. This bot is restricted.")
            elif update.callback_query:
                await update.callback_query.answer("Unauthorized", show_alert=True)
            return
        return await func(update, context)
    return wrapper


def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if user is None or not _is_allowed(user.id):
            if update.message:
                await update.message.reply_text("Unauthorized.")
            elif update.callback_query:
                await update.callback_query.answer("Unauthorized", show_alert=True)
            return
        if not _is_admin(user.id):
            msg = "Only admins can change settings or panic sell."
            if update.message:
                await update.message.reply_text(msg)
            elif update.callback_query:
                await update.callback_query.answer(msg, show_alert=True)
            return
        return await func(update, context)
    return wrapper


async def post_to_channel(text: str) -> None:
    if not BROADCAST_ENABLED or not ACTIVITY_CHANNEL_ID or _bot_app is None:
        return
    try:
        await _bot_app.bot.send_message(
            chat_id=ACTIVITY_CHANNEL_ID,
            text=text,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
    except Exception as e:
        log.warning("Channel post failed: %s", e)


async def build_tx(mint: str, action: str, amount: str, denom_sol: bool, slippage: int) -> VersionedTransaction:
    if KEYPAIR is None:
        raise RuntimeError("Wallet not loaded")
    payload = {
        "publicKey": str(KEYPAIR.pubkey()),
        "action": action,
        "mint": mint,
        "amount": str(amount),
        "denominatedInSol": "true" if denom_sol else "false",
        "slippage": str(slippage),
        "priorityFee": str(config["priority_fee"]),
        "pool": "auto",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(PUMPPORTAL_API, data=payload)
        if r.status_code != 200:
            raise RuntimeError(f"PumpPortal {r.status_code}: {r.text[:300]}")
        return VersionedTransaction.from_bytes(r.content)


async def broadcast(tx: VersionedTransaction) -> str:
    if config["paper"]:
        fake = "PAPER_" + base58.b58encode(bytes(tx.message)[:12]).decode()[:16]
        log.info("[PAPER] would broadcast tx -> %s", fake)
        return fake
    if KEYPAIR is None:
        raise RuntimeError("Wallet not loaded")
    signed = VersionedTransaction(tx.message, [KEYPAIR])
    raw_b58 = base58.b58encode(bytes(signed)).decode()
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "sendTransaction",
        "params": [
            raw_b58,
            {"encoding": "base58", "skipPreflight": False, "preflightCommitment": "confirmed", "maxRetries": 3},
        ],
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(RPC_URL, json=payload)
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"RPC error: {data['error']}")
        return data["result"]


async def get_sol_balance() -> float:
    if KEYPAIR is None:
        return 0.0
    payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [str(KEYPAIR.pubkey())]}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(RPC_URL, json=payload)
            return r.json().get("result", {}).get("value", 0) / 1e9
    except Exception as e:
        log.warning("balance fetch failed: %s", e)
        return 0.0


async def execute_buy(mint: str, sol_amount: float, user_id: int = 0) -> Tuple[Optional[str], Optional[str]]:
    mint = mint.strip()
    if mint in positions:
        return None, "Already holding this token (shared space wallet)"
    if sol_amount <= 0:
        return None, "Amount must be > 0"
    try:
        tx = await build_tx(mint, "buy", str(sol_amount), True, int(config["slippage"]))
        sig = await broadcast(tx)
        positions[mint] = {
            "entry_sol": sol_amount,
            "size_sol": sol_amount,
            "peak": sol_amount,
            "opened_at": datetime.utcnow().isoformat(),
            "last_tx": sig,
            "by_user": user_id,
        }
        trade_history.append(
            {"side": "buy", "mint": mint, "amount": sol_amount, "sig": sig, "ts": datetime.utcnow().isoformat(), "user": user_id}
        )
        log.info("BUY user=%s %s %.4f SOL -> %s", user_id, mint[:8], sol_amount, sig)
        mode = "PAPER" if config["paper"] else "LIVE"
        await post_to_channel(f"BUY ({mode}) `{mint[:6]}...{mint[-4:]}` | {sol_amount} SOL\nby `{user_id}`\nTX: `{sig}`")
        return sig, None
    except Exception as e:
        log.exception("buy failed")
        return None, str(e)


async def execute_sell(mint: str, pct: float, user_id: int = 0) -> Tuple[Optional[str], Optional[str]]:
    mint = mint.strip()
    if mint not in positions:
        return None, "No open position for this mint"
    if pct <= 0 or pct > 100:
        return None, "pct must be 1-100"
    try:
        slip = int(config["slippage"] * 1.5)
        tx = await build_tx(mint, "sell", f"{pct}%", False, slip)
        sig = await broadcast(tx)
        pos = positions[mint]
        sold_sol = pos["size_sol"] * (pct / 100.0)
        if pct >= 99.9:
            positions.pop(mint, None)
        else:
            pos["size_sol"] = max(0.0, pos["size_sol"] - sold_sol)
            pos["last_tx"] = sig
        trade_history.append(
            {"side": "sell", "mint": mint, "amount": sold_sol, "sig": sig, "ts": datetime.utcnow().isoformat(), "pct": pct, "user": user_id}
        )
        log.info("SELL user=%s %s %.0f%% -> %s", user_id, mint[:8], pct, sig)
        mode = "PAPER" if config["paper"] else "LIVE"
        await post_to_channel(f"SELL ({mode}) `{mint[:6]}...{mint[-4:]}` | {pct}%\nby `{user_id}`\nTX: `{sig}`")
        return sig, None
    except Exception as e:
        log.exception("sell failed")
        return None, str(e)


def solscan(sig: str) -> str:
    return sig if sig.startswith("PAPER_") else f"https://solscan.io/tx/{sig}"


def token_keyboard(mint: str) -> InlineKeyboardMarkup:
    amt = config["buy_amount"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Buy {amt}", callback_data=f"buy:{mint}:{amt}"),
         InlineKeyboardButton("Buy 0.5", callback_data=f"buy:{mint}:0.5"),
         InlineKeyboardButton("Buy 1.0", callback_data=f"buy:{mint}:1.0")],
        [InlineKeyboardButton("Sell 25%", callback_data=f"sell:{mint}:25"),
         InlineKeyboardButton("Sell 50%", callback_data=f"sell:{mint}:50"),
         InlineKeyboardButton("Sell 100%", callback_data=f"sell:{mint}:100")],
        [InlineKeyboardButton("Chart", url=f"https://dexscreener.com/solana/{mint}"),
         InlineKeyboardButton("Rugcheck", url=f"https://rugcheck.xyz/tokens/{mint}")],
        [InlineKeyboardButton("Menu", callback_data="menu")],
    ])


def position_keyboard(mint: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("25%", callback_data=f"sell:{mint}:25"),
         InlineKeyboardButton("50%", callback_data=f"sell:{mint}:50"),
         InlineKeyboardButton("100%", callback_data=f"sell:{mint}:100")],
        [InlineKeyboardButton("Menu", callback_data="menu")],
    ])


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Positions", callback_data="positions"),
         InlineKeyboardButton("Wallet", callback_data="wallet"),
         InlineKeyboardButton("Settings", callback_data="settings")],
        [InlineKeyboardButton("History", callback_data="history"),
         InlineKeyboardButton("Panic", callback_data="panic_confirm")],
    ])


def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Buy: {config['buy_amount']}", callback_data="set:buy_amount"),
         InlineKeyboardButton(f"Slip: {config['slippage']}%", callback_data="set:slippage")],
        [InlineKeyboardButton(f"Fee: {config['priority_fee']}", callback_data="set:priority_fee"),
         InlineKeyboardButton(f"Auto: {'ON' if config['auto_buy'] else 'OFF'}", callback_data="toggle:auto_buy")],
        [InlineKeyboardButton(f"Paper: {'ON' if config['paper'] else 'OFF'}", callback_data="toggle:paper")],
        [InlineKeyboardButton("Menu", callback_data="menu")],
    ])


@access_control
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if context.args and context.args[0].startswith("ref_"):
        try:
            referrer_id = int(context.args[0].replace("ref_", "", 1))
            if user_id not in user_referred_by and referrer_id != user_id:
                user_referred_by[user_id] = referrer_id
                referrals.setdefault(referrer_id, []).append(user_id)
                try:
                    await context.bot.send_message(
                        chat_id=referrer_id,
                        text=f"New referral! Total friends: {len(referrals[referrer_id])}",
                    )
                except Exception:
                    pass
        except ValueError:
            pass
    pubkey = str(KEYPAIR.pubkey()) if KEYPAIR else "NOT SET"
    mode = "PAPER" if config["paper"] else "LIVE"
    access = "PUBLIC (space)" if PUBLIC_ACCESS else "whitelist"
    text = (
        f"*Pump.fun Space Bot*\n\n"
        f"Shared wallet: `{pubkey[:6]}...{pubkey[-4:]}`\n"
        f"Open positions: *{len(positions)}*\n"
        f"Mode: {mode} | Access: {access}\n\n"
        f"Anyone in the space can paste a mint and trade.\n"
        f"Invite: /invite"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())


@access_control
async def cmd_invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not BOT_USERNAME:
        await update.message.reply_text("Admin must set BOT_USERNAME in Railway env (without @).")
        return
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    count = len(referrals.get(user_id, []))
    await update.message.reply_text(
        f"*Your invite link*\n\n`{link}`\n\nFriends joined: *{count}*",
        parse_mode="Markdown",
    )


@access_control
async def cmd_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bal = await get_sol_balance()
    pubkey = str(KEYPAIR.pubkey()) if KEYPAIR else "?"
    text = f"*Shared space wallet*\n\n`{pubkey}`\nBalance: *{bal:.4f} SOL*\nOpen positions: *{len(positions)}*"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())


@access_control
async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not positions:
        await update.message.reply_text("No open positions.", reply_markup=main_keyboard())
        return
    lines = ["*Open positions (shared)*\n"]
    for i, (mint, pos) in enumerate(positions.items(), 1):
        lines.append(
            f"{i}. `{mint[:6]}...{mint[-4:]}`\n   Entry: {pos['entry_sol']} | Size: {pos['size_sol']:.3f} | by `{pos.get('by_user', '?')}`"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_keyboard())


@admin_only
async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"*Settings*\n\nBuy: `{config['buy_amount']}` SOL\nSlippage: `{config['slippage']}`%\n"
        f"Fee: `{config['priority_fee']}`\nAuto: `{'ON' if config['auto_buy'] else 'OFF'}`\n"
        f"Paper: `{'ON' if config['paper'] else 'OFF'}`"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=settings_keyboard())


@access_control
async def cmd_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage: /buy <mint> <sol>")
        return
    mint, amount = context.args[0], float(context.args[1])
    uid = update.effective_user.id
    msg = await update.message.reply_text("Buying...")
    sig, err = await execute_buy(mint, amount, uid)
    if err:
        await msg.edit_text(f"Error: {err}")
    else:
        await msg.edit_text(
            f"Bought *{amount}* SOL of `{mint[:8]}...`\nTX: {solscan(sig)}",
            parse_mode="Markdown",
            reply_markup=position_keyboard(mint),
        )


@access_control
async def cmd_sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage: /sell <mint> <pct>")
        return
    mint, pct = context.args[0], float(context.args[1])
    uid = update.effective_user.id
    msg = await update.message.reply_text("Selling...")
    sig, err = await execute_sell(mint, pct, uid)
    if err:
        await msg.edit_text(f"Error: {err}")
    else:
        await msg.edit_text(
            f"Sold *{pct}%* of `{mint[:8]}...`\nTX: {solscan(sig)}",
            parse_mode="Markdown",
            reply_markup=main_keyboard(),
        )


@admin_only
async def cmd_panic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not positions:
        await update.message.reply_text("No positions to sell.")
        return
    uid = update.effective_user.id
    results = []
    for mint in list(positions.keys()):
        sig, err = await execute_sell(mint, 100, uid)
        results.append(f"{'OK' if sig else 'FAIL'} `{mint[:6]}...` {sig or err}")
    await update.message.reply_text("*Panic sell*\n" + "\n".join(results), parse_mode="Markdown", reply_markup=main_keyboard())


@access_control
async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not trade_history:
        await update.message.reply_text("No trades yet.", reply_markup=main_keyboard())
        return
    lines = ["*Last trades (space)*\n"]
    for t in trade_history[-15:][::-1]:
        lines.append(f"{t['side'].upper()} `{t['mint'][:6]}...` {t.get('amount', 0):.3f} u:`{t.get('user', '?')}`")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_keyboard())


@access_control
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    uid = query.from_user.id

    if data == "menu":
        await query.edit_message_text("Main menu", reply_markup=main_keyboard())
        return
    if data == "positions":
        if not positions:
            await query.edit_message_text("No open positions.", reply_markup=main_keyboard())
        else:
            lines = ["*Open positions (shared)*\n"]
            for mint, pos in positions.items():
                lines.append(f"- `{mint[:6]}...{mint[-4:]}` - {pos['size_sol']:.3f} SOL (by `{pos.get('by_user', '?')}`)")
            await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_keyboard())
        return
    if data == "wallet":
        bal = await get_sol_balance()
        pubkey = str(KEYPAIR.pubkey()) if KEYPAIR else "?"
        await query.edit_message_text(f"*Shared wallet*\n`{pubkey}`\nBalance: *{bal:.4f} SOL*", parse_mode="Markdown", reply_markup=main_keyboard())
        return
    if data == "settings":
        if not _is_admin(uid):
            await query.answer("Admins only", show_alert=True)
            return
        text = (
            f"*Settings*\n\nBuy: `{config['buy_amount']}` SOL\nSlippage: `{config['slippage']}`%\n"
            f"Fee: `{config['priority_fee']}`\nAuto: `{'ON' if config['auto_buy'] else 'OFF'}`\n"
            f"Paper: `{'ON' if config['paper'] else 'OFF'}`"
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=settings_keyboard())
        return
    if data == "history":
        if not trade_history:
            await query.edit_message_text("No trades yet.", reply_markup=main_keyboard())
        else:
            lines = ["*Last trades*\n"] + [f"{t['side'].upper()} `{t['mint'][:6]}...` {t.get('amount', 0):.3f} u:`{t.get('user', '?')}`" for t in trade_history[-10:][::-1]]
            await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_keyboard())
        return
    if data == "panic_confirm":
        if not _is_admin(uid):
            await query.answer("Admins only", show_alert=True)
            return
        await query.edit_message_text(
            "Sell ALL shared positions at 100%?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("YES - sell all", callback_data="panic_go")],
                [InlineKeyboardButton("Cancel", callback_data="menu")],
            ]),
        )
        return
    if data == "panic_go":
        if not _is_admin(uid):
            await query.answer("Admins only", show_alert=True)
            return
        if not positions:
            await query.edit_message_text("No positions.", reply_markup=main_keyboard())
            return
        results = []
        for mint in list(positions.keys()):
            sig, err = await execute_sell(mint, 100, uid)
            results.append(f"{'OK' if sig else 'FAIL'} `{mint[:6]}...`")
        await query.edit_message_text("*Panic done*\n" + "\n".join(results), parse_mode="Markdown", reply_markup=main_keyboard())
        return
    if data.startswith("toggle:"):
        if not _is_admin(uid):
            await query.answer("Admins only", show_alert=True)
            return
        key = data.split(":", 1)[1]
        if key in ("auto_buy", "paper"):
            config[key] = not config[key]
            await query.edit_message_text(
                f"Updated. Paper=`{'ON' if config['paper'] else 'OFF'}` Auto=`{'ON' if config['auto_buy'] else 'OFF'}`",
                reply_markup=settings_keyboard(),
            )
        return
    if data.startswith("set:"):
        if not _is_admin(uid):
            await query.answer("Admins only", show_alert=True)
            return
        key = data.split(":", 1)[1]
        pending_set[uid] = key
        await query.edit_message_text(f"Send new value for *{key}* (number):", parse_mode="Markdown")
        return
    if data.startswith("buy:"):
        _, mint, amount_s = data.split(":", 2)
        amount = float(amount_s)
        await query.edit_message_text(f"Buying {amount} SOL of `{mint[:8]}...`...")
        sig, err = await execute_buy(mint, amount, uid)
        if err:
            await query.edit_message_text(f"Error: {err}", reply_markup=token_keyboard(mint))
        else:
            await query.edit_message_text(f"Bought *{amount}* SOL\nTX: {solscan(sig)}", parse_mode="Markdown", reply_markup=position_keyboard(mint))
        return
    if data.startswith("sell:"):
        _, mint, pct_s = data.split(":", 2)
        pct = float(pct_s)
        await query.edit_message_text(f"Selling {pct}% of `{mint[:8]}...`...")
        sig, err = await execute_sell(mint, pct, uid)
        if err:
            await query.edit_message_text(f"Error: {err}", reply_markup=main_keyboard())
        else:
            await query.edit_message_text(f"Sold *{pct}%*\nTX: {solscan(sig)}", parse_mode="Markdown", reply_markup=main_keyboard())
        return


@access_control
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    uid = update.effective_user.id
    if uid in pending_set:
        if not _is_admin(uid):
            pending_set.pop(uid, None)
            await update.message.reply_text("Admins only.")
            return
        key = pending_set.pop(uid)
        try:
            if key == "buy_amount":
                config["buy_amount"] = float(text)
            elif key == "slippage":
                config["slippage"] = int(float(text))
            elif key == "priority_fee":
                config["priority_fee"] = float(text)
            await update.message.reply_text(f"Set `{key}` = `{text}`", parse_mode="Markdown", reply_markup=settings_keyboard())
        except ValueError:
            await update.message.reply_text("Invalid number.")
        return
    if MINT_RE.match(text):
        short = f"`{text[:6]}...{text[-4:]}`"
        await update.message.reply_text(
            f"*Token detected*\n\nMint: {short}\n\nChoose an action:",
            parse_mode="Markdown",
            reply_markup=token_keyboard(text),
        )


def main():
    global _bot_app
    if not BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN not set")
    if not KEYPAIR:
        raise SystemExit("WALLET_PRIVATE_KEY not set or invalid")

    log.info("Starting SPACE bot")
    log.info("  Wallet: %s", KEYPAIR.pubkey())
    log.info("  Mode: %s", "PAPER" if config["paper"] else "LIVE")
    log.info("  Access: %s", "PUBLIC (all users)" if PUBLIC_ACCESS else f"whitelist {ALLOWED_USERS}")
    log.info("  Admins: %s", ADMIN_USERS or "(none = everyone can admin)")

    app = Application.builder().token(BOT_TOKEN).build()
    _bot_app = app
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("invite", cmd_invite))
    app.add_handler(CommandHandler("wallet", cmd_wallet))
    app.add_handler(CommandHandler("positions", cmd_positions))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("buy", cmd_buy))
    app.add_handler(CommandHandler("sell", cmd_sell))
    app.add_handler(CommandHandler("panic", cmd_panic))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

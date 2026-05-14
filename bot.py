"""
Options Trade Logger Bot
Logs trades as Telegram messages — no external DB needed.
All trade history lives in a dedicated Telegram channel/chat.
"""

import os
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, CallbackQueryHandler,
    filters, ContextTypes
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Conversation states
(
    TICKER, DIRECTION, STRATEGY, STRIKE, EXPIRY,
    PREMIUM, CONTRACTS, NOTES,
    CLOSE_SEARCH, CLOSE_PNL, CLOSE_NOTES
) = range(11)

# Temp trade storage per user (in memory, only during entry flow)
user_trades: dict = {}

# ── Helpers ─────────────────────────────────────────────────────────────────

def fmt_trade_message(trade: dict, status: str = "OPEN") -> str:
    emoji = "🟢" if status == "OPEN" else ("🔴" if trade.get("pnl", 0) < 0 else "✅")
    direction_emoji = "📈" if trade["direction"] == "BUY" else "📉"
    
    lines = [
        f"{emoji} *#{trade['id']} {trade['ticker']} — {status}*",
        f"{direction_emoji} {trade['direction']} · {trade['strategy']}",
        f"Strike: `{trade['strike']}`   Expiry: `{trade['expiry']}`",
        f"Premium: `${trade['premium']}`   Contracts: `{trade['contracts']}`",
        f"Cost Basis: `${trade['cost_basis']}`",
    ]
    if trade.get("notes"):
        lines.append(f"📝 _{trade['notes']}_")
    if status != "OPEN":
        pnl = trade.get("pnl", 0)
        pnl_str = f"+${pnl}" if pnl >= 0 else f"-${abs(pnl)}"
        lines.append(f"P&L: `{pnl_str}`")
        if trade.get("close_notes"):
            lines.append(f"📝 Close: _{trade['close_notes']}_")
    lines.append(f"⏱ {trade['timestamp']}")
    lines.append(f"#options #{trade['ticker'].lower()} #{trade['strategy'].lower().replace(' ', '_')}")
    return "\n".join(lines)


def make_id() -> str:
    return datetime.now().strftime("%y%m%d%H%M%S")


# ── /start ───────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *Options Trade Logger*\n\n"
        "Commands:\n"
        "/open — Log a new trade\n"
        "/close — Mark a trade closed + P&L\n"
        "/summary — Weekly P&L snapshot\n"
        "/help — Show this menu\n\n"
        "Every trade is saved as a pinnable message here. "
        "Search by ticker or strategy using Telegram's built-in search."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ── /open flow ───────────────────────────────────────────────────────────────

async def open_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_trades[uid] = {"id": make_id()}
    await update.message.reply_text("🎯 Ticker? (e.g. `SPY`, `AAPL`)", parse_mode="Markdown")
    return TICKER

async def got_ticker(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_trades[uid]["ticker"] = update.message.text.strip().upper()
    kb = [[
        InlineKeyboardButton("📈 BUY", callback_data="BUY"),
        InlineKeyboardButton("📉 SELL", callback_data="SELL"),
    ]]
    await update.message.reply_text("Direction?", reply_markup=InlineKeyboardMarkup(kb))
    return DIRECTION

async def got_direction(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    user_trades[uid]["direction"] = query.data
    strategies = ["Iron Condor", "Calendar Spread", "Naked Call", "Naked Put",
                  "Bull Call Spread", "Bear Put Spread", "Covered Call", "Cash-Secured Put", "Other"]
    kb = [[InlineKeyboardButton(s, callback_data=s)] for s in strategies]
    await query.edit_message_text("Strategy?", reply_markup=InlineKeyboardMarkup(kb))
    return STRATEGY

async def got_strategy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    user_trades[uid]["strategy"] = query.data
    await query.edit_message_text("Strike price(s)? (e.g. `450/460` or `450C`)", parse_mode="Markdown")
    return STRIKE

async def got_strike(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_trades[uid]["strike"] = update.message.text.strip()
    await update.message.reply_text("Expiry date? (e.g. `2025-06-20` or `20Jun25`)")
    return EXPIRY

async def got_expiry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_trades[uid]["expiry"] = update.message.text.strip()
    await update.message.reply_text("Premium per contract? (e.g. `1.45`)")
    return PREMIUM

async def got_premium(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        user_trades[uid]["premium"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("⚠️ Enter a number e.g. `1.45`", parse_mode="Markdown")
        return PREMIUM
    await update.message.reply_text("Number of contracts?")
    return CONTRACTS

async def got_contracts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        contracts = int(update.message.text.strip())
        user_trades[uid]["contracts"] = contracts
        premium = user_trades[uid]["premium"]
        user_trades[uid]["cost_basis"] = round(premium * contracts * 100, 2)
    except ValueError:
        await update.message.reply_text("⚠️ Enter a whole number e.g. `1`", parse_mode="Markdown")
        return CONTRACTS
    await update.message.reply_text("Notes? (entry thesis, IV rank, etc.) — or /skip")
    return NOTES

async def got_notes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in user_trades:
        await update.message.reply_text("⚠️ Session expired. Please start again with /open")
        return ConversationHandler.END
    user_trades[uid]["notes"] = update.message.text.strip()
    return await _save_open_trade(update, ctx)

async def skip_notes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in user_trades:
        await update.message.reply_text("⚠️ Session expired. Please start again with /open")
        return ConversationHandler.END
    user_trades[uid]["notes"] = ""
    return await _save_open_trade(update, ctx)

async def _save_open_trade(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    trade = user_trades.get(uid)
    if not trade:
        await update.message.reply_text("⚠️ Session expired. Please start again with /open")
        return ConversationHandler.END
    trade["timestamp"] = datetime.now().strftime("%d %b %Y %H:%M MYT")
    msg = fmt_trade_message(trade, "OPEN")
    try:
        sent = await update.message.reply_text(msg, parse_mode="Markdown")
        user_trades[uid]["open_msg_id"] = sent.message_id
        await update.message.reply_text(
            f"✅ Trade `#{trade['id']}` logged!\n\nPin this message to track it, "
            f"or use Telegram search with `#{trade['ticker'].lower()}` to find it later.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error saving trade: {e}")
        await update.message.reply_text(f"⚠️ Error saving trade: {e}")
    finally:
        user_trades.pop(uid, None)
    return ConversationHandler.END


# ── /close flow ──────────────────────────────────────────────────────────────

async def close_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Enter the trade ID to close (shown as `#ID` in the trade message):",
        parse_mode="Markdown"
    )
    return CLOSE_SEARCH

async def got_close_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    trade_id = update.message.text.strip().lstrip("#")
    ctx.user_data["closing_id"] = trade_id
    await update.message.reply_text(
        f"Closing trade `#{trade_id}`.\n\nP&L amount? (e.g. `+85` or `-42`)",
        parse_mode="Markdown"
    )
    return CLOSE_PNL

async def got_close_pnl(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    raw = update.message.text.strip().replace("$", "").replace("+", "")
    try:
        ctx.user_data["closing_pnl"] = float(raw)
    except ValueError:
        await update.message.reply_text("⚠️ Enter a number e.g. `+85` or `-42`", parse_mode="Markdown")
        return CLOSE_PNL
    await update.message.reply_text("Close notes? (what happened, lessons) — or /skip")
    return CLOSE_NOTES

async def got_close_notes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["closing_notes"] = update.message.text.strip()
    return await _save_close(update, ctx)

async def skip_close_notes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["closing_notes"] = ""
    return await _save_close(update, ctx)

async def _save_close(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    trade_id = ctx.user_data.get("closing_id", "?")
    pnl = ctx.user_data.get("closing_pnl", 0)
    close_notes = ctx.user_data.get("closing_notes", "")
    timestamp = datetime.now().strftime("%d %b %Y %H:%M MYT")
    pnl_str = f"+${pnl}" if pnl >= 0 else f"-${abs(pnl)}"
    status = "WIN ✅" if pnl >= 0 else "LOSS 🔴"
    msg = (
        f"🔒 *CLOSED Trade #{trade_id}*\n"
        f"P&L: `{pnl_str}` — {status}\n"
        + (f"📝 _{close_notes}_\n" if close_notes else "")
        + f"⏱ Closed: {timestamp}\n"
        f"#closed #options"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")
    await update.message.reply_text(
        "✅ Close logged! Reply this message to the original open trade to link them.",
    )
    return ConversationHandler.END


# ── /summary ─────────────────────────────────────────────────────────────────

async def summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📊 *How to view your summary:*\n\n"
        "Since trades are stored as messages, use Telegram's search:\n\n"
        "• Search `#options` → all trades\n"
        "• Search `#closed` → closed trades\n"
        "• Search `#spy` → SPY trades only\n"
        "• Search `#iron_condor` → IC trades\n\n"
        "💡 *Tip:* Pin open trades so they're always visible at the top of this chat.",
        parse_mode="Markdown"
    )


# ── Cancel ───────────────────────────────────────────────────────────────────

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    open_conv = ConversationHandler(
        entry_points=[CommandHandler("open", open_start)],
        states={
            TICKER:    [MessageHandler(filters.TEXT & ~filters.COMMAND, got_ticker)],
            DIRECTION: [CallbackQueryHandler(got_direction)],
            STRATEGY:  [CallbackQueryHandler(got_strategy)],
            STRIKE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, got_strike)],
            EXPIRY:    [MessageHandler(filters.TEXT & ~filters.COMMAND, got_expiry)],
            PREMIUM:   [MessageHandler(filters.TEXT & ~filters.COMMAND, got_premium)],
            CONTRACTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_contracts)],
            NOTES:     [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_notes),
                CommandHandler("skip", skip_notes),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    close_conv = ConversationHandler(
        entry_points=[CommandHandler("close", close_start)],
        states={
            CLOSE_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_close_id)],
            CLOSE_PNL:    [MessageHandler(filters.TEXT & ~filters.COMMAND, got_close_pnl)],
            CLOSE_NOTES:  [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_close_notes),
                CommandHandler("skip", skip_close_notes),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(open_conv)
    app.add_handler(close_conv)

    logger.info("Bot running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

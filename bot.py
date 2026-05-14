"""
Options Trade Logger Bot v2
Telegram bot → Google Sheets (Service Account)
Single sheet, one row per trade.
"""

import os
import json
import logging
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, CallbackQueryHandler,
    filters, ContextTypes
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN       = os.environ["BOT_TOKEN"]
SPREADSHEET_ID  = os.environ["SPREADSHEET_ID"]   # from the Sheets URL
SHEET_NAME      = os.environ.get("SHEET_NAME", "Trades")
GOOGLE_CREDS    = os.environ["GOOGLE_CREDS_JSON"] # full service account JSON as a string

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Column order in the sheet (A→R)
HEADERS = [
    "ID", "Date", "Ticker", "Direction", "Strategy",
    "Strike", "Expiry", "Premium", "Contracts", "Cost Basis",
    "Status", "Close Date", "Close PnL", "PnL %",
    "Notes", "Close Notes", "Win/Loss", "Days Held"
]

# ── Google Sheets client ─────────────────────────────────────────────────────

def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDS)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SPREADSHEET_ID)
    try:
        ws = sh.worksheet(SHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=SHEET_NAME, rows=1000, cols=len(HEADERS))
        ws.append_row(HEADERS)
        # Basic header formatting
        ws.format("A1:R1", {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.2},
        })
    return ws


def find_trade_row(ws, trade_id: str):
    """Return 1-based row index for a trade ID, or None."""
    col_a = ws.col_values(1)  # ID column
    for i, val in enumerate(col_a):
        if val == trade_id:
            return i + 1
    return None


# ── Conversation states ──────────────────────────────────────────────────────

(
    TICKER, DIRECTION, STRATEGY, STRIKE, EXPIRY,
    PREMIUM, CONTRACTS, NOTES,
    CLOSE_ID, CLOSE_PNL, CLOSE_NOTES
) = range(11)

user_trades: dict = {}


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_id() -> str:
    return datetime.now().strftime("%y%m%d%H%M%S")


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ── /start ───────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📒 *Options Trade Logger v2*\n\n"
        "All trades sync to Google Sheets in real time.\n\n"
        "Commands:\n"
        "/open — Log a new trade\n"
        "/close — Close a trade + log P&L\n"
        "/status — Show all open trades\n"
        "/help — This menu",
        parse_mode="Markdown"
    )


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
    strategies = [
        "Iron Condor", "Calendar Spread", "Bull Call Spread", "Bear Put Spread",
        "Naked Call", "Naked Put", "Covered Call", "Cash-Secured Put", "Other"
    ]
    kb = [[InlineKeyboardButton(s, callback_data=s)] for s in strategies]
    await query.edit_message_text("Strategy?", reply_markup=InlineKeyboardMarkup(kb))
    return STRATEGY

async def got_strategy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    user_trades[uid]["strategy"] = query.data
    await query.edit_message_text("Strike(s)? (e.g. `450/460` or `450C`)", parse_mode="Markdown")
    return STRIKE

async def got_strike(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_trades[uid]["strike"] = update.message.text.strip()
    await update.message.reply_text("Expiry? (e.g. `2025-06-20`)")
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
        user_trades[uid]["cost_basis"] = round(user_trades[uid]["premium"] * contracts * 100, 2)
    except ValueError:
        await update.message.reply_text("⚠️ Enter a whole number e.g. `1`", parse_mode="Markdown")
        return CONTRACTS
    await update.message.reply_text("Notes? (IVR, thesis, etc.) — or /skip")
    return NOTES

async def got_notes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in user_trades:
        await update.message.reply_text("⚠️ Session expired. Start again with /open")
        return ConversationHandler.END
    user_trades[uid]["notes"] = update.message.text.strip()
    return await _save_open_trade(update, ctx)

async def skip_notes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in user_trades:
        await update.message.reply_text("⚠️ Session expired. Start again with /open")
        return ConversationHandler.END
    user_trades[uid]["notes"] = ""
    return await _save_open_trade(update, ctx)

async def _save_open_trade(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    trade = user_trades.get(uid)
    if not trade:
        await update.message.reply_text("⚠️ Session expired. Start again with /open")
        return ConversationHandler.END
    try:
        ws = get_sheet()
        row = [
            trade["id"],                    # A: ID
            now_str(),                      # B: Date
            trade["ticker"],                # C: Ticker
            trade["direction"],             # D: Direction
            trade["strategy"],              # E: Strategy
            trade["strike"],                # F: Strike
            trade["expiry"],                # G: Expiry
            trade["premium"],               # H: Premium
            trade["contracts"],             # I: Contracts
            trade["cost_basis"],            # J: Cost Basis
            "OPEN",                         # K: Status
            "",                             # L: Close Date
            "",                             # M: Close PnL
            "",                             # N: PnL %
            trade["notes"],                 # O: Notes
            "",                             # P: Close Notes
            "",                             # Q: Win/Loss
            "",                             # R: Days Held
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")
        await update.message.reply_text(
            f"✅ Trade #{trade['id']} logged to Sheets!\n\n"
            f"{trade['ticker']} {trade['direction']} · {trade['strategy']}\n"
            f"Strike: {trade['strike']} · Expiry: {trade['expiry']}\n"
            f"Premium: ${trade['premium']} × {trade['contracts']} = ${trade['cost_basis']}"
        )
    except Exception as e:
        logger.error(f"Sheets error: {e}")
        await update.message.reply_text(f"⚠️ Failed to write to Sheets: {e}")
    finally:
        user_trades.pop(uid, None)
    return ConversationHandler.END


# ── /close flow ──────────────────────────────────────────────────────────────

async def close_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Enter the Trade ID to close:\n_(shown in the confirmation message when you opened it)_",
        parse_mode="Markdown"
    )
    return CLOSE_ID

async def got_close_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["closing_id"] = update.message.text.strip().lstrip("#")
    await update.message.reply_text("P&L amount? (e.g. `+85` or `-42`)", parse_mode="Markdown")
    return CLOSE_PNL

async def got_close_pnl(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip().replace("$", "").replace("+", "")
    try:
        ctx.user_data["closing_pnl"] = float(raw)
    except ValueError:
        await update.message.reply_text("⚠️ Enter a number e.g. `+85`", parse_mode="Markdown")
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
    trade_id    = ctx.user_data.get("closing_id", "")
    pnl         = ctx.user_data.get("closing_pnl", 0)
    close_notes = ctx.user_data.get("closing_notes", "")
    close_date  = now_str()

    try:
        ws = get_sheet()
        row_idx = find_trade_row(ws, trade_id)
        if not row_idx:
            await update.message.reply_text(f"⚠️ Trade ID `{trade_id}` not found in Sheets.", parse_mode="Markdown")
            return ConversationHandler.END

        # Read cost basis to compute PnL %
        cost_basis_val = ws.cell(row_idx, 10).value  # col J
        try:
            cost_basis = float(cost_basis_val)
            pnl_pct = round((pnl / cost_basis) * 100, 1) if cost_basis else ""
        except (TypeError, ValueError):
            pnl_pct = ""

        # Read open date to compute days held
        open_date_val = ws.cell(row_idx, 2).value  # col B
        try:
            open_dt = datetime.strptime(open_date_val, "%Y-%m-%d %H:%M")
            days_held = (datetime.now() - open_dt).days
        except (TypeError, ValueError):
            days_held = ""

        win_loss = "WIN" if pnl >= 0 else "LOSS"

        # Batch update the close columns
        ws.update(f"K{row_idx}:R{row_idx}", [[
            "CLOSED",       # K: Status
            close_date,     # L: Close Date
            pnl,            # M: Close PnL
            pnl_pct,        # N: PnL %
            ws.cell(row_idx, 15).value,  # O: Notes (unchanged)
            close_notes,    # P: Close Notes
            win_loss,       # Q: Win/Loss
            days_held,      # R: Days Held
        ]])

        pnl_str = f"+${pnl}" if pnl >= 0 else f"-${abs(pnl)}"
        pnl_pct_str = f" ({pnl_pct}%)" if pnl_pct != "" else ""
        emoji = "✅" if pnl >= 0 else "🔴"

        close_msg = (
            f"{emoji} Trade #{trade_id} closed!\n\n"
            f"P&L: {pnl_str}{pnl_pct_str}\n"
            f"Days held: {days_held}"
        )
        if close_notes:
            close_msg += f"\nNotes: {close_notes}"
        await update.message.reply_text(close_msg)
    except Exception as e:
        logger.error(f"Sheets close error: {e}")
        await update.message.reply_text(f"⚠️ Failed to update Sheets: {e}")

    return ConversationHandler.END


# ── /status ──────────────────────────────────────────────────────────────────

async def status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ws = get_sheet()
        all_rows = ws.get_all_records()
        open_trades = [r for r in all_rows if str(r.get("Status", "")).upper() == "OPEN"]

        if not open_trades:
            await update.message.reply_text("📭 No open trades.")
            return

        lines = [f"📂 *{len(open_trades)} Open Trade(s):*\n"]
        for t in open_trades:
            lines.append(
                f"• `#{t['ID']}` *{t['Ticker']}* {t['Direction']} {t['Strategy']}\n"
                f"  Strike `{t['Strike']}` · Exp `{t['Expiry']}` · Cost `${t['Cost Basis']}`"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"⚠️ Could not read Sheets: {e}")


# ── Cancel ───────────────────────────────────────────────────────────────────

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_trades.pop(update.effective_user.id, None)
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
            NOTES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_notes),
                CommandHandler("skip", skip_notes),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    close_conv = ConversationHandler(
        entry_points=[CommandHandler("close", close_start)],
        states={
            CLOSE_ID:    [MessageHandler(filters.TEXT & ~filters.COMMAND, got_close_id)],
            CLOSE_PNL:   [MessageHandler(filters.TEXT & ~filters.COMMAND, got_close_pnl)],
            CLOSE_NOTES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_close_notes),
                CommandHandler("skip", skip_close_notes),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(open_conv)
    app.add_handler(close_conv)

    logger.info("Bot running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

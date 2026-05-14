# Options Trade Logger — Telegram Bot

Logs option trades as Telegram messages. No database. All history searchable via Telegram's built-in search.

## Setup (10 mins)

### 1. Create your bot
1. Open Telegram → search `@BotFather`
2. Send `/newbot`, follow prompts
3. Copy the **bot token** (looks like `123456:ABC-DEF...`)

### 2. Deploy free on Railway
1. Push this folder to a GitHub repo
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Select your repo
4. Add environment variable:
   - Key: `BOT_TOKEN`
   - Value: your token from step 1
5. Deploy — done. Railway free tier = 500hrs/month (enough for a bot)

### Alternative: Render (also free)
1. Push to GitHub
2. [render.com](https://render.com) → New Web Service → connect repo
3. Build command: `pip install -r requirements.txt`
4. Start command: `python bot.py`
5. Add env var `BOT_TOKEN`

---

## Bot Commands

| Command | Action |
|---------|--------|
| `/open` | Log a new trade (guided flow) |
| `/close` | Mark trade closed + log P&L |
| `/summary` | Search tips for reviewing history |
| `/cancel` | Cancel current flow |

---

## Trade Flow Example

**Opening a trade:**
```
/open
→ Ticker: SPY
→ Direction: SELL
→ Strategy: Iron Condor
→ Strike: 545/550/560/565
→ Expiry: 2025-05-30
→ Premium: 1.20
→ Contracts: 1
→ Notes: IVR 45, targeting 50% profit
```

**Output message (auto-tagged for search):**
```
🟢 #250514123456 SPY — OPEN
📉 SELL · Iron Condor
Strike: 545/550/560/565   Expiry: 2025-05-30
Premium: $1.20   Contracts: 1
Cost Basis: $120.0
📝 IVR 45, targeting 50% profit
⏱ 14 May 2025 22:30 MYT
#options #spy #iron_condor
```

**Closing a trade:**
```
/close
→ Trade ID: 250514123456
→ P&L: +60
→ Notes: hit 50% target at day 4
```

---

## Finding Trades (Telegram Search)

- `#options` — all trades
- `#closed` — closed trades only  
- `#spy` — all SPY trades
- `#iron_condor` — all IC trades
- `#aapl` — AAPL trades

**Tip:** Pin open trades to the top of the chat so you can track them at a glance.

---

## Running Locally (optional)

```bash
pip install -r requirements.txt
export BOT_TOKEN="your_token_here"
python bot.py
```

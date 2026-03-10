# 🚗 Copart Monitor

Automatically monitors Copart US for new car listings matching your criteria and sends Telegram notifications. Runs every 3 hours via GitHub Actions. A second workflow tracks active auction bids every 30 minutes and alerts you when a lot you're watching is closing or over budget.

## How It Works

```
GitHub Actions (every 3h)
        │
        ▼
Copart API (all lots, no license filter)
        │ fail/empty
        ▼
Playwright fallback
        │
        ▼
Filter: makes / models / damage / year / odometer
        │
        ▼
Compare against state.json (seen lots)
        │
        ▼
New lots? ──▶  Send Telegram alert
               ✅ No License Required  OR  🔑 Broker Required
        │
        ▼
Commit state.json + watchlist.json to repo

─────────────────────────────────────────────

GitHub Actions (every 30 min)
        │
        ▼
Check watchlist.json for active lots
        │
        ▼
Fetch current bid from Copart API
        │
        ▼
Bid ≤ target? ──▶  🟢 Bid Update alert
≤ 10 min left? ──▶  🚨 Closing Soon alert
Sold/closed?   ──▶  🔴 Auction Closed alert
```

---

## Setup

### 1. Fork or clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/copart-monitor.git
cd copart-monitor
```

### 2. Create a Telegram Bot

1. Open Telegram and message **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the **Bot Token** (looks like `123456789:ABCdef...`)
4. Send any message to your new bot to start the chat
5. Get your **Chat ID** by visiting:
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
   Look for `"chat":{"id":XXXXXXXXX}` in the response

### 3. Add GitHub Secrets

Go to your repo → **Settings** → **Secrets and variables** → **Actions** → **Secrets**

| Secret | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Your bot token from BotFather |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |

### 4. Add GitHub Variables

Go to **Settings** → **Secrets and variables** → **Actions** → **Variables**

These are the only values you'll ever need to change — no code edits required.

| Variable | Example | Description |
|---|---|---|
| `COPART_MAKES` | `Toyota` | Comma-separated makes |
| `COPART_MODELS` | `RAV4,RAV4 HYBRID,RAV4 PRIME,RAV4 ADVENTURE,RAV4 XSE,RAV4 PLUG-IN HYBRID` | Comma-separated models to match |
| `COPART_YEAR_MIN` | `2023` | Oldest year to include |
| `COPART_YEAR_MAX` | `2027` | Newest year to include |
| `COPART_MAX_ODOMETER` | `40000` | Max mileage |
| `COPART_DAMAGE_TYPES` | `REAR END,SIDE,HAIL,MINOR DENT/SCRATCHES,NORMAL WEAR,VANDALISM` | Damage types to include |
| `COPART_MAX_PAGES` | `11` | Pages to fetch per run (100 lots/page) |

**To add a second make/model** — just extend the variables, no code changes needed:
```
COPART_MAKES  →  Toyota,Hyundai
COPART_MODELS →  RAV4,RAV4 HYBRID,RAV4 PRIME,RAV4 ADVENTURE,RAV4 XSE,RAV4 PLUG-IN HYBRID,SONATA,SONATA HYBRID
```

**Confirmed damage type names:**
`FRONT END` · `REAR END` · `SIDE` · `HAIL` · `ALL OVER` · `MINOR DENT/SCRATCHES` · `NORMAL WEAR` · `VANDALISM`

### 5. Initialise state files

Make sure both files exist in the repo root containing only `{}`:

- `state.json` → `{}`
- `watchlist.json` → `{}`

### 6. Test the connection

1. Go to **Actions** → **Copart Monitor** → **Run workflow**
2. Enable **"Send a test Telegram message only"** → **Run**
3. You should receive a message in Telegram ✅

### 7. First real run

1. **Actions** → **Copart Monitor** → **Run workflow** → **Run**
2. The first run is a **silent baseline** — saves all current lots, sends no notifications
3. Every subsequent run notifies you only about genuinely new listings

---

## Telegram Message Format

### New listing alert
```
🚗 2024 TOYOTA RAV4
✅ No License Required        ← or 🔑 Broker Required

📅 Sale: Mar 11, 2025 03:00 PM UTC
📍 PA - PHILADELPHIA EAST
🔧 Damage: REAR END
🛣 Odometer: 11,518 mi
💲 Est. Value: $14,200
🔢 Lot: 75359235

[View on Copart]
```

### Bid update alert
```
🟢 BID UPDATE  |  ✅ NLR
🚗 2024 Toyota RAV4
💰 Current Bid: $3,300
🎯 Your Target: $6,000
✅ $2,700 under target
⏱ 47 min left
🔧 REAR END  |  11,518 mi
[View Lot]
```

---

## Project Structure

```
copart-monitor/
├── .github/workflows/
│   ├── monitor.yml          # Runs every 3 hours — new listing alerts
│   └── auction_tracker.yml  # Runs every 30 min — bid tracking alerts
├── copart_api.py            # Copart API client (confirmed browser payload)
├── copart_playwright.py     # Playwright fallback scraper
├── auction_tracker.py       # Bid monitoring logic
├── monitor.py               # Main entry point
├── notifier.py              # Telegram message formatting & sending
├── state_manager.py         # Seen-lots tracking (state.json)
├── requirements.txt
├── state.json               # Auto-committed: tracks seen lot numbers
├── watchlist.json           # Auto-committed: tracks lots being bid on
└── README.md
```

---

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Set environment variables
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHAT_ID="your_chat_id"
export COPART_MAKES="Toyota"
export COPART_MODELS="RAV4,RAV4 HYBRID,RAV4 PRIME"
export COPART_YEAR_MIN="2023"
export COPART_YEAR_MAX="2027"
export COPART_MAX_ODOMETER="40000"
export COPART_DAMAGE_TYPES="REAR END,SIDE,HAIL"

# Test Telegram connection
python monitor.py --test-telegram

# Dry run (see what would be found — no notifications, no state changes)
python monitor.py --dry-run

# Normal run
python monitor.py
```

---

## Schedule

| Workflow | Schedule | Purpose |
|---|---|---|
| `monitor.yml` | Every 3 hours | New listing detection |
| `auction_tracker.yml` | Every 30 minutes | Bid tracking on watchlisted lots |

To change the schedule, edit the `cron` expression in the relevant workflow file:

```yaml
- cron: "0 */3 * * *"    # Every 3 hours (default)
- cron: "0 */1 * * *"    # Every hour
- cron: "0 9,17 * * *"   # Twice daily at 9am and 5pm UTC
```

> ⚠️ GitHub Actions free tier allows ~2,000 minutes/month. The monitor (every 3h) uses ~240 min/month; the auction tracker (every 30min) uses ~720 min/month — combined ~960 min/month, well within free limits.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| No lots found | Check `COPART_MAKES` and `COPART_MODELS` spelling — values are case-insensitive |
| Telegram not sending | Re-check token and chat ID; run the test workflow |
| All lots show 🔑 Broker | NLR detection reads Copart's `lfd` feature field — verify the lot page shows "No License Required" |
| API always failing | Copart may have updated their API — Playwright fallback handles it automatically |
| `state.json` not committing | Ensure workflow has `permissions: contents: write` (already set) |
| Too many notifications | Lower `COPART_MAX_PAGES` or tighten `COPART_DAMAGE_TYPES` |
| Auction tracker not alerting | Confirm `watchlist.json` is not empty and the lot auction is still active |

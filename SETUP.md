# Belmont Ops Agent — Setup Checklist

Single source of truth for any remaining integration setup.
Run `/diag` in Telegram anytime to see live status.
Run `/next` in Telegram to get the single next action with reasoning.

---

## Live Status (as of 2026-05-25)

### Working (no action needed)
- JobTread (9 tools, real Belmont data)
- Meta Ads (5 tools, "Belmmont & Co." ad account connected)
- Weather (open-meteo, Red Deer 3-day forecast)
- Telegram bot + security filter (only Jacob's chat ID accepted)
- Agent LLM (Claude via Anthropic API)
- All scheduled jobs (morning brief, daily win, etc.)
- All quick commands (/jobs, /estimates, /quote, /promise, /lesson, etc.)
- Lead auto-scoring on /newlead webhook
- Photo/receipt vision processing
- Sunday mode with "override" bypass

### Needs Setup (in priority order)

---

## #1 — ZEP MEMORY (highest leverage, free tier)

**Why first:** Without this, every conversation starts cold. The agent has no recall of past clients, decisions, lessons, or commitments. This is the single biggest force multiplier.

**Cost:** Free. Zep Cloud free tier = 10K events/month + 1 user. Belmont fits easily.

**Steps:**
1. Go to https://app.getzep.com/signup
2. Sign up (Google sign-in works)
3. Create a project (name it "belmont" or anything)
4. Settings → **Project API Keys** → Create API Key
5. Copy the key (starts with `z_...`)
6. Tell Claude Code or set yourself in Railway:
   - Service: **pure-charisma** (Telegram handler)
   - Variable name: `ZEP_API_KEY`
   - Value: paste the key
7. Railway will auto-redeploy. Confirm with `/diag` — `zep_memory` should turn green.

**Result:** Agent now remembers every conversation. /promises, /decisions, /lessons, /wins, /network commands start populating with real data.

---

## #2 — QBO (8 finance tools, your money data)

**Why second:** Unlocks all real finance numbers — invoices, P&L, cash flow, expense logging. Currently `/money` and `/brief` show "QBO not connected".

**Cost:** Free (your existing QBO subscription).

**Path A (Easiest — OAuth Playground, ~5 min):**
1. Go to https://developer.intuit.com/app/developer/playground
2. Sign in with your Intuit account (same one your real QBO uses)
3. Select your existing app from the dropdown ("Belmont Ops Agent")
4. Check scope: **Accounting** (= `com.intuit.quickbooks.accounting`)
5. The Playground will show its redirect URI. If you get a redirect URI mismatch, copy the URI it shows and add it to your app's Development tab redirect URI list at https://developer.intuit.com/app/developer/myapps
6. Click **Get authorization code** → company picker appears
7. **Important:** Pick your REAL Belmont & Co. company (not "no sandbox" — the playground works against production with dev keys for personal use)
8. Click **Authorize**
9. Back on Playground, click **Get tokens** / **Exchange for Tokens**
10. Copy three values: **Access Token**, **Refresh Token**, **Realm ID**
11. Send all three to Claude Code, or set in Railway (service: **belmont-ops**):
    - `QBO_ACCESS_TOKEN` = access token value
    - `QBO_REFRESH_TOKEN` = refresh token value
    - `QBO_REALM_ID` = realm/company id value

**Path B (Production keys — formal, ~50 min):**
- Only needed if Path A doesn't work or you want production-grade keys
- See https://developer.intuit.com/app/developer/myapps → your app → Production tab
- Requires Intuit's compliance checklist (privacy policy URL, security questionnaire, etc.)

**Result:** /money shows real receivables. /brief includes overdue invoices. /expense logs to QBO directly. P&L queries work.

**Refresh policy:** Refresh tokens last ~100 days. The agent auto-refreshes on every API call. You'll need to redo this OAuth flow every 3 months or so. Set a calendar reminder.

---

## #3 — META PAGE TOKEN (3 page tools)

**Why third:** Unlocks Facebook page posting, page insights, page post listing. Your ads already work — this just adds the page side.

**Cost:** Free.

**Steps:**
1. Go to https://developers.facebook.com/tools/explorer
2. Top right: select your app (the Belmont app)
3. Click **Generate Access Token**
4. Click **Add a Permission** → add ALL of these:
   - `pages_read_engagement`
   - `pages_manage_posts`
   - `pages_read_user_content`
   - `pages_show_list`
5. Click **Generate Access Token** again
6. Authorize the popup → it will return a long token string
7. **Important:** This is a short-lived (1 hour) token by default. To get a long-lived token:
   - Use the access token debugger: https://developers.facebook.com/tools/debug/accesstoken/
   - Paste your token, click **Extend Access Token**
   - For permanent: go through the page access token endpoint with the long-lived user token
   - Or generate via business.facebook.com → System Users (these tokens don't expire)
8. Send the page token to Claude Code, or set in Railway (service: **belmont-ops**):
   - `META_PAGE_TOKEN` = the page token

**Result:** /brief includes page insights. Can post to Facebook via agent.

---

## #4 — GOOGLE CALENDAR + GMAIL (2 tools)

**Why fourth:** Surfaces your daily schedule and urgent emails in the morning brief. Big productivity win, but not blocking the rest of the business.

**Cost:** Free.

**Steps:**
1. Go to https://console.cloud.google.com
2. Create new project (or use existing): name it "Belmont Ops"
3. Enable APIs:
   - APIs & Services → Library → search "Google Calendar API" → Enable
   - APIs & Services → Library → search "Gmail API" → Enable
4. APIs & Services → **OAuth consent screen**:
   - User type: External
   - App name: Belmont Ops Agent
   - User support email: your email
   - Developer contact: your email
   - Save and continue
   - Scopes: add `https://www.googleapis.com/auth/calendar.readonly` and `https://www.googleapis.com/auth/gmail.readonly`
   - Test users: add your Gmail address
5. APIs & Services → **Credentials** → Create Credentials → OAuth client ID
   - Application type: Desktop app
   - Name: Belmont Ops
   - Download the JSON
6. Send the **Client ID** and **Client Secret** values to Claude Code
7. Claude Code will run a one-time OAuth flow to get refresh tokens, then set:
   - `GOOGLE_CLIENT_ID`
   - `GOOGLE_CLIENT_SECRET`
   - `GOOGLE_CALENDAR_TOKEN`
   - `GOOGLE_CALENDAR_REFRESH_TOKEN`
   - `GMAIL_TOKEN`
   - `GMAIL_REFRESH_TOKEN`

**Result:** Morning brief includes today's calendar + urgent emails.

---

## #5 — OPENAI WHISPER (voice memos, optional)

**Why optional:** Voice memos are a huge productivity boost when you're driving between jobs, but you can still type. Skip if you don't use voice messages.

**Cost:** Pay-as-you-go. Whisper is ~$0.006/min. For typical use, expect $1-3/month.

**Steps:**
1. Go to https://platform.openai.com/api-keys
2. Sign in / sign up
3. Add a payment method (required for API access)
4. Create new secret key
5. Copy the key (starts with `sk-...`)
6. Send to Claude Code or set in Railway (service: **pure-charisma**):
   - `OPENAI_API_KEY` = your key

**Result:** Send voice memo to Telegram → agent transcribes via Whisper, then processes the transcript like any other message.

---

## Fresh Railway API Token (for Claude Code to set vars directly)

If you want Claude Code to set env vars in Railway directly (instead of you doing it via Railway dashboard):

1. Go to https://railway.app/account/tokens
2. Click **New Token**
3. Name: "Claude Code Setup"
4. Copy the token
5. Send to Claude Code with the credentials above

Without this, you'll need to paste each env var into the Railway dashboard yourself:
- Project: belmont-ops
- Service: belmont-ops (MCP server) OR pure-charisma (Telegram handler)
- Variables tab → add each var → save → service auto-redeploys

---

## Quick Test Commands After Setup

After fixing each integration, verify in Telegram:

```
/diag       — full health report, every integration
/next       — single next action with reasoning
/brief      — morning brief (should show what's connected)
/money      — QBO test (after QBO setup)
/ads        — Meta ads test (already working)
/weather    — weather test (already working)
/jobs       — JobTread test (already working)
/quote 600sqft composite deck   — estimating test (already working)
```

---

## After Everything Is Green

Daily ongoing maintenance: **none**.

Quarterly ongoing maintenance:
- Re-auth QBO OAuth (~5 min, every 3 months when refresh token expires)
- Verify Meta page token still valid (or use a System User token from business.facebook.com which doesn't expire)

That's the total maintenance burden. The agent is built to run without your attention once configured.

---

## File Map (for future Claude Code sessions)

```
belmont-ops/
├── mcp_server/
│   ├── main.py          # 28 MCP tools (JobTread, QBO, Meta, Google, Weather)
│   ├── briefing.py      # Morning briefing generator
│   └── requirements.txt
├── telegram_handler/
│   ├── main.py          # FastAPI webhook + quick commands
│   ├── agent.py         # Claude tool-use loop
│   ├── scheduler.py     # APScheduler cron jobs
│   ├── state.py         # Shared snooze state
│   └── requirements.txt
├── agents/
│   └── prompts.py       # Orchestrator + 5 specialist prompts
├── memory/
│   └── zep_memory.py    # Zep Cloud integration
├── SETUP.md             # This file
└── qbo_oauth.js         # Node OAuth helper (deprecated, use Playground instead)
```

---

Last updated: 2026-05-25

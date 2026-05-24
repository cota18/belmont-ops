# BELMONT OPS — RAILWAY DEPLOYMENT GUIDE

## Step 1: Create two Railway services

Go to railway.com and create a new project called "belmont-ops"

Add Service 1: "belmont-mcp"
- Source: this repo, root dir = mcp_server/
- Start command: uvicorn main:app --host 0.0.0.0 --port $PORT
- Add all env vars from .env.example (MCP section)

Add Service 2: "belmont-telegram"
- Source: this repo, root dir = telegram_handler/
- Start command: uvicorn main:app --host 0.0.0.0 --port $PORT
- Add all env vars from .env.example (all of them)
- Set MCP_SERVER_URL = Railway URL of the belmont-mcp service (e.g. https://belmont-mcp.railway.app)
- Set JACOB_CHAT_ID = your Telegram chat ID (send /start to the bot, it logs the ID)
- Set SELF_URL = Railway URL of this service (e.g. https://belmont-telegram.railway.app)

## Step 2: Environment variables to set in Railway

### belmont-mcp service:
JOBTREAD_API_KEY
QBO_ACCESS_TOKEN
QBO_REALM_ID
QBO_CLIENT_ID
QBO_CLIENT_SECRET
QBO_REFRESH_TOKEN
META_ACCESS_TOKEN
META_PAGE_ID
META_AD_ACCOUNT_ID
MCP_SERVER_SECRET (generate a random 32-char string)

### belmont-telegram service:
ANTHROPIC_API_KEY
TELEGRAM_TOKEN
ZEP_API_KEY
MCP_SERVER_URL (the belmont-mcp Railway URL)
MCP_SERVER_SECRET (same secret as above)
JACOB_CHAT_ID (your Telegram chat ID)
SELF_URL (the belmont-telegram Railway URL)

## Step 3: Register Telegram webhook

Once belmont-telegram is deployed and you have its URL, run:
https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url=https://{belmont-telegram-url}/webhook

## Step 4: Get your Telegram chat ID

Send any message to your bot, then check:
https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates

Find "chat":{"id": XXXXXX} — that's your JACOB_CHAT_ID.
Set it in Railway env vars and redeploy.

## Step 5: Test

Send "status" to the bot. Should respond with agent status.
Send "what jobs do I have active" — routes to project agent.
Send "what invoices are overdue" — routes to finance agent.

## QBO Token Refresh (Important)

QBO access tokens expire every 60 days. Set a calendar reminder.
When expired: go to developer.intuit.com, refresh manually, update QBO_ACCESS_TOKEN in Railway.
The agent will auto-refresh within a session but needs the refresh token to stay current.
Phase 2 will add automatic OAuth refresh via a background job.

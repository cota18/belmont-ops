"""
BELMONT OPS - TELEGRAM WEBHOOK HANDLER
Receives messages from Jacob, routes to the right agent,
handles Sunday mode, quick commands, photo/receipt vision, voice.
"""

import os
import asyncio
import httpx
import tempfile
import base64
from datetime import datetime
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent import run_agent
from memory.mem0_memory import (
    ensure_user, ensure_session, load_memory,
    save_exchange, get_session_id, save_fact, get_all_memories
)

app = FastAPI(title="Belmont Telegram Handler")

from state import set_snooze, clear_snooze, is_snoozed, get_snooze_deadline
from templates import (
    list_templates, get_template,
    list_sops, get_sop,
    list_pricing, get_pricing
)

# ── In-memory conversation buffer ─────────────────────────────────────────────
# Stores the last N message pairs per chat_id for within-session recall.
# Resets on redeploy — Zep handles cross-session long-term memory.
_MAX_HISTORY = 8  # last 8 turns (16 messages) — enough context without bloat
_conversation_buffers: dict[str, list] = {}

def get_history(chat_id: str) -> list:
    return _conversation_buffers.get(str(chat_id), [])

def add_to_history(chat_id: str, user_msg: str, assistant_msg: str):
    key = str(chat_id)
    if key not in _conversation_buffers:
        _conversation_buffers[key] = []
    buf = _conversation_buffers[key]
    buf.append({"role": "user", "content": user_msg})
    buf.append({"role": "assistant", "content": assistant_msg})
    # Keep only the last _MAX_HISTORY * 2 messages
    if len(buf) > _MAX_HISTORY * 2:
        _conversation_buffers[key] = buf[-(  _MAX_HISTORY * 2):]

@app.on_event("startup")
async def startup():
    # Startup env var validation — visible in Railway logs
    print("=" * 60)
    print("BELMONT TELEGRAM HANDLER — STARTUP VALIDATION")
    print("=" * 60)
    required = {
        "ANTHROPIC_API_KEY": "Agent LLM (Claude)",
        "TELEGRAM_TOKEN": "Bot connection",
        "JACOB_CHAT_ID": "Security filter (only Jacob)",
        "MCP_SERVER_URL": "Tool routing",
        "MCP_SERVER_SECRET": "Tool authentication",
    }
    optional = {
        "ZEP_API_KEY": "Long-term memory (free tier covers usage)",
        "OPENAI_API_KEY": "Voice memo transcription (Whisper)",
        "SELF_URL": "Self-trigger for scheduled tasks",
    }
    missing_required = []
    for var, purpose in required.items():
        present = bool(os.getenv(var, "").strip())
        print(f"{'OK ' if present else 'XX '} {var}: {purpose}")
        if not present:
            missing_required.append(var)
    print("-" * 60)
    print("Optional integrations:")
    for var, purpose in optional.items():
        v = os.getenv(var, "").strip()
        if v and v not in ("PENDING",):
            print(f"OK  {var}: {purpose}")
        else:
            print(f"-- {var}: {purpose} (not configured)")
    print("=" * 60)
    if missing_required:
        print(f"WARNING: {len(missing_required)} REQUIRED env var(s) missing")
    print("=" * 60)

    from scheduler import start_scheduler
    start_scheduler()


@app.get("/diagnostic")
async def diagnostic():
    """Health check for Telegram-handler-side integrations (Anthropic, Zep, OpenAI)."""
    from datetime import datetime
    report = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "service": "telegram_handler",
        "integrations": {},
        "summary": {"green": 0, "yellow": 0, "red": 0}
    }

    def mark(name: str, status: str, detail: str, fix: str = ""):
        report["integrations"][name] = {"status": status, "detail": detail, "fix": fix}
        report["summary"][status] = report["summary"].get(status, 0) + 1

    # ── ANTHROPIC ─────────────────────────────────────────────────────────
    ant = os.getenv("ANTHROPIC_API_KEY", "")
    if not ant:
        mark("anthropic", "red", "ANTHROPIC_API_KEY not set — agent cannot respond",
             "Get key at console.anthropic.com, set on Railway")
    elif len(ant) < 20:
        mark("anthropic", "red", "ANTHROPIC_API_KEY looks malformed",
             "Regenerate at console.anthropic.com")
    else:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": ant,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json"
                    },
                    json={
                        "model": "claude-sonnet-4-5",
                        "max_tokens": 5,
                        "messages": [{"role": "user", "content": "hi"}]
                    }
                )
            if r.status_code == 200:
                mark("anthropic", "green", f"Key valid ({ant[:8]}...{ant[-4:]})")
            else:
                mark("anthropic", "red", f"API returned {r.status_code}",
                     "Check key validity at console.anthropic.com")
        except Exception as e:
            mark("anthropic", "yellow", f"Cannot verify: {str(e)[:100]}", "")

    # ── MEM0 MEMORY ───────────────────────────────────────────────────────
    mem0_key = os.getenv("MEM0_API_KEY", "")
    if not mem0_key:
        mark("memory", "red", "MEM0_API_KEY not set — no long-term memory",
             "Sign up FREE at app.mem0.ai → Settings → API Keys → add as MEM0_API_KEY on Railway")
    else:
        try:
            from mem0 import AsyncMemoryClient
            m = AsyncMemoryClient(api_key=mem0_key)
            # Quick test: get all memories (lightweight call)
            mems = await asyncio.to_thread(m.get_all, user_id="jacob_belmont")
            count = len(mems) if mems else 0
            mark("memory", "green", f"mem0 connected — {count} memories stored for jacob_belmont")
        except Exception as e:
            err = str(e)[:150].lower()
            if "401" in err or "unauthorized" in err or "invalid" in err:
                mark("memory", "red", "401 Unauthorized — MEM0_API_KEY invalid",
                     "Regenerate key at app.mem0.ai → Settings → API Keys")
            else:
                mark("memory", "yellow", f"mem0 check failed: {str(e)[:100]}",
                     "Check MEM0_API_KEY at app.mem0.ai")

    # ── OPENAI (voice transcription) ──────────────────────────────────────
    oai = os.getenv("OPENAI_API_KEY", "")
    if not oai:
        mark("openai_voice", "yellow", "OPENAI_API_KEY not set — voice memos disabled",
             "Optional. Get key at platform.openai.com/api-keys to enable Whisper")
    else:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {oai}"}
                )
            if r.status_code == 200:
                mark("openai_voice", "green", "Voice memos enabled — Whisper ready")
            else:
                mark("openai_voice", "red", f"OpenAI returned {r.status_code}",
                     "Check key at platform.openai.com")
        except Exception as e:
            mark("openai_voice", "yellow", f"Cannot verify: {str(e)[:100]}", "")

    # ── TELEGRAM ──────────────────────────────────────────────────────────
    tg = os.getenv("TELEGRAM_TOKEN", "")
    chat = os.getenv("JACOB_CHAT_ID", "").strip().strip("'\"")
    if not tg:
        mark("telegram", "red", "TELEGRAM_TOKEN not set", "Set in Railway from BotFather")
    elif not chat:
        mark("telegram", "red", "JACOB_CHAT_ID not set", "Set Jacob's Telegram user ID")
    elif not chat.isdigit():
        mark("telegram", "red", f"JACOB_CHAT_ID looks malformed: {chat!r}",
             "Check Railway value for stray quotes/whitespace — should be digits only")
    else:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"https://api.telegram.org/bot{tg}/getMe")
            if r.status_code == 200:
                bot = r.json().get("result", {})
                mark("telegram", "green", f"Bot @{bot.get('username', '?')} connected, chat {chat}")
            else:
                mark("telegram", "red", f"Bot API returned {r.status_code}", "")
        except Exception as e:
            mark("telegram", "yellow", f"Cannot verify: {str(e)[:100]}", "")

    # ── MCP SERVER REACHABLE ─────────────────────────────────────────────
    mcp_url = os.getenv("MCP_SERVER_URL", "")
    if not mcp_url:
        mark("mcp_server", "red", "MCP_SERVER_URL not set — no tools available",
             "Set to the MCP server Railway URL")
    else:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(mcp_url.rstrip("/"))
            if r.status_code == 200:
                tools = r.json().get("tools", "?")
                mark("mcp_server", "green", f"MCP reachable, {tools} tools registered")
            else:
                mark("mcp_server", "red", f"MCP returned {r.status_code}", "")
        except Exception as e:
            mark("mcp_server", "red", f"Cannot reach MCP: {str(e)[:100]}", "")

    s = report["summary"]
    report["overall"] = (
        "ALL GREEN" if s.get("red", 0) == 0 and s.get("yellow", 0) == 0
        else f"{s.get('red', 0)} broken, {s.get('yellow', 0)} partial, {s.get('green', 0)} working"
    )
    return report

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
JACOB_CHAT_ID = os.getenv("JACOB_CHAT_ID", "").strip().strip("'\"")

# ─────────────────────────────────────────────
# COMMAND + ROUTING TABLES
# ─────────────────────────────────────────────

QUICK_COMMANDS = {
    "/jobs": "List all active jobs from JobTread. Show name, status, and key info. Be concise and direct.",
    "/estimates": "List all open estimates from JobTread. Show name, total value, status, and age in days. Include total pipeline value.",
    "/money": "Pull a QuickBooks snapshot: total accounts receivable, any overdue invoices, and month-to-date revenue. Use real numbers.",
    "/ads": "Get Meta ad performance for the last 7 days: total spend, impressions, clicks, top campaign. Be direct with the numbers.",
    "/brief": "Generate a full morning briefing now: schedule, open estimates with pipeline total, active jobs, money owed, urgent emails.",
    "/status": "Check system health. Confirm MCP server is responding by calling one lightweight tool. Report Railway service status.",
    "/recap": "Give me a full business snapshot: active jobs count, open pipeline value, total receivables, any overdue invoices, and the top 3 things I should focus on this week.",
    "/subs": "List all subcontractors stored in memory for Belmont. Show name, trade, rate, and last job worked together. If none are stored yet, say so and explain how to add them.",
    "/pipeline": "Pull all open estimates from JobTread. Calculate total pipeline value, average estimate size, and which ones are oldest. Rank by age and flag any over 14 days.",
    "/receipt": "Jacob is about to send a photo of a receipt. Tell him: 'Ready — send the photo and I'll read it and log it to QuickBooks for you.'",
    "/exit": "Check my exit tracker. Based on current QBO revenue data, how am I tracking toward the $8K/month net income target for 6 consecutive months? What's the gap and what's the fastest path to closing it?",
    "/weather": "Call weather_red_deer_forecast for the next 3 days. Flag any outdoor-work risk (deck, framing, concrete, roof) and tell me what to reschedule.",
    "/promises": "Search Zep memory for commitments I've made in the last 14 days (anything I said I'd do by a date). List them with status: kept, pending, or dropped. Be direct — call out anything I've ghosted.",
    "/decisions": "Search Zep memory for major business decisions I've logged. Show last 10 with the reasoning I gave at the time. Useful for reviewing my own thinking.",
    "/lessons": "Search Zep memory for lessons logged from past jobs. Pull the top 8 most relevant ones. These are my hard-earned rules — surface them.",
    "/network": "Search Zep memory for all builders, subs, vendors, and referral sources I've mentioned. Group by role. Flag anyone I haven't talked to in 60+ days as 'gone cold'.",
    "/wins": "Search Zep memory for daily wins I've logged in the last 14 days. Summarize momentum in 2-3 sentences. Be honest — if I've been dropping the ball, say so.",
    "/leads": "Check Gmail right now for any Squarespace form submissions in the last 48 hours. Extract lead details, log to memory, and draft a reply for each one.",
}

# Estimate templates — quick ballparks. Detailed estimates still go through the estimating agent.
ESTIMATE_TEMPLATE_PROMPT = (
    "Jacob wants a fast ballpark estimate. Use the Central Alberta 2026 cost knowledge "
    "in your system prompt. Pick the right tier from the input. Output format:\n\n"
    "PROJECT: [type]\n"
    "ASSUMPTIONS: [scope assumptions in 1 line]\n"
    "BREAKDOWN:\n"
    "- Materials: $X\n"
    "- Labour: $X\n"
    "- Subs: $X\n"
    "- Contingency (10-15%): $X\n"
    "- GST (5%): $X\n"
    "TOTAL RANGE: $low - $high CAD\n"
    "CONFIDENCE: low/medium/high based on detail given\n"
    "ASK: 1-3 questions Jacob should clarify before quoting client.\n\n"
    "Be specific. Use real Belmont numbers. No fluff.\n\n"
    "Input: "
)

BJJ_LOG_KEYWORDS = ["/bjj", "trained bjj", "bjj session", "rolled today", "mat time"]
SUB_ADD_KEYWORDS = ["add sub", "new sub", "add subcontractor", "new subcontractor"]

ASYNC_KEYWORDS = [
    "follow up", "followup", "follow-up", "all invoices", "all jobs",
    "outreach sequence", "email sequence", "full estimate", "bid package",
    "cash flow forecast", "weekly report", "morning brief", "research"
]

ROUTING_MAP = {
    "finance": [
        "invoice", "invoices", "payment", "paid", "overdue", "cash flow",
        "profit", "loss", "p&l", "balance sheet", "qbo", "quickbooks",
        "collect", "collection", "receivable", "bill", "expense"
    ],
    "project": [
        "job", "jobs", "project", "projects", "budget", "estimate",
        "jobtread", "site", "schedule", "timeline", "subcontractor",
        "progress", "on track", "behind", "complete", "close"
    ],
    "sales": [
        "lead", "leads", "prospect", "outreach", "follow up", "pipeline",
        "hubspot", "crm", "referral", "cold email", "sequence", "qualify"
    ],
    "estimating": [
        "estimate", "estimating", "cost", "how much", "price", "scope",
        "deck", "reno", "renovation", "addition", "custom home", "sqft",
        "materials", "labour", "takeoff", "bid"
    ],
    "comms": [
        "write", "draft", "email", "post", "instagram", "facebook",
        "caption", "proposal", "cover letter", "update", "client email",
        "message", "copy", "social"
    ]
}


def route_to_agent(message: str) -> str:
    msg_lower = message.lower()
    scores = {agent: 0 for agent in ROUTING_MAP}
    for agent, keywords in ROUTING_MAP.items():
        for kw in keywords:
            if kw in msg_lower:
                scores[agent] += 1
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "orchestrator"
    top_two = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:2]
    if top_two[0][1] > 0 and top_two[1][1] > 0 and top_two[0][1] == top_two[1][1]:
        return "orchestrator"
    return best


def is_async_task(message: str) -> bool:
    return any(kw in message.lower() for kw in ASYNC_KEYWORDS)


# ─────────────────────────────────────────────
# TELEGRAM HELPERS
# ─────────────────────────────────────────────

async def send_telegram(chat_id, text: str):
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    async with httpx.AsyncClient(timeout=30) as client:
        for chunk in chunks:
            await client.post(
                f"{TELEGRAM_API}/sendMessage",
                json={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"}
            )


async def send_typing(chat_id):
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            f"{TELEGRAM_API}/sendChatAction",
            json={"chat_id": chat_id, "action": "typing"}
        )


async def transcribe_voice(file_id: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{TELEGRAM_API}/getFile", params={"file_id": file_id})
            file_path = resp.json()["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
        async with httpx.AsyncClient(timeout=60) as client:
            audio_bytes = (await client.get(file_url)).content
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name
        async with httpx.AsyncClient(timeout=60) as client:
            with open(tmp_path, "rb") as f:
                resp = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY', '')}"},
                    files={"file": ("voice.ogg", f, "audio/ogg")},
                    data={"model": "whisper-1", "language": "en"}
                )
        os.unlink(tmp_path)
        if resp.status_code == 200:
            return resp.json().get("text", "").strip()
        # Show the actual API error so it's diagnosable
        err_body = resp.text[:300] if resp.text else "no response body"
        return f"[Voice transcription failed ({resp.status_code}): {err_body}]"
    except Exception as e:
        return f"[Voice transcription error: {e}]"


# ─────────────────────────────────────────────
# BACKGROUND AGENT RUNNER
# ─────────────────────────────────────────────

async def process_message_async(chat_id: str, user_message: str, agent_type: str,
                                 vision_content: list = None):
    session_id = await get_session_id(agent_type, str(chat_id))
    await ensure_session(session_id, agent_type)
    memory_ctx = await load_memory(session_id, query=user_message)
    history = get_history(str(chat_id))
    try:
        result = await run_agent(
            agent_type=agent_type,
            message=user_message,
            memory_context=memory_ctx,
            chat_id=str(chat_id),
            vision_content=vision_content,
            conversation_history=history
        )
    except Exception as e:
        result = f"Agent error: {e}"
    # Save to both in-memory buffer (instant recall) and Zep (long-term)
    add_to_history(str(chat_id), user_message, result)
    await save_exchange(session_id, user_message, result)
    await send_telegram(chat_id, result)


# ─────────────────────────────────────────────
# HEALTH
# ─────────────────────────────────────────────

@app.get("/")
async def health():
    return {"status": "Belmont Telegram Handler online", "version": "2.0"}


# ─────────────────────────────────────────────
# WEBHOOK
# ─────────────────────────────────────────────

@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": True})

    message = body.get("message") or body.get("edited_message")
    if not message:
        return JSONResponse({"ok": True})

    chat_id = message["chat"]["id"]

    # Security: only process Jacob's messages
    if JACOB_CHAT_ID and str(chat_id) != str(JACOB_CHAT_ID):
        return JSONResponse({"ok": True})

    user_text = message.get("text", "").strip()
    vision_content = None

    # ── Photo / Receipt Processing ────────────────────────────────────────────
    photos = message.get("photo")
    if photos:
        await send_typing(chat_id)
        file_id = photos[-1]["file_id"]
        caption = message.get("caption", "").strip()
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                file_info = await client.get(
                    f"{TELEGRAM_API}/getFile", params={"file_id": file_id}
                )
                file_path = file_info.json()["result"]["file_path"]
                file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
                img_bytes = (await client.get(file_url)).content

            img_b64 = base64.b64encode(img_bytes).decode()

            # Always use smart receipt-first detection.
            # Claude will decide if it's a receipt and act accordingly.
            if caption:
                context_line = f"Jacob sent a photo with caption: '{caption}'\n\n"
            else:
                context_line = "Jacob sent a photo with no caption.\n\n"

            vision_prompt = (
                f"{context_line}"
                "First, look at the image and determine: is this a receipt, bill, or invoice?\n\n"
                "IF YES (it's a receipt/bill/invoice):\n"
                "Extract and confirm these details:\n"
                "  - Vendor/store name\n"
                "  - Total amount (look for TOTAL, GRAND TOTAL, or the final amount)\n"
                "  - Date of purchase\n"
                "  - What was purchased (brief description)\n"
                "  - Category: materials, fuel, tools, equipment, subcontractor, food/entertainment, or other\n\n"
                "Then say: 'Got it — [Vendor] $[amount] on [date]. Which job should I charge this to? "
                "Reply with the job name or number and I'll log it to QuickBooks.'\n\n"
                "IF NO (it's a job site photo, document, or something else):\n"
                "Describe what you see briefly in the context of a construction business. "
                "If it looks like a job site, ask which job it belongs to and offer to log it as a progress note."
            )

            vision_content = [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/jpeg", "data": img_b64
                }},
                {"type": "text", "text": vision_prompt}
            ]
            user_text = vision_prompt  # for routing and memory
        except Exception as e:
            await send_telegram(chat_id, f"Could not process photo: {e}")
            return JSONResponse({"ok": True})

    # ── Voice ─────────────────────────────────────────────────────────────────
    voice = message.get("voice") or message.get("audio")
    if voice and not user_text and not vision_content:
        await send_typing(chat_id)
        user_text = await transcribe_voice(voice.get("file_id"))
        if not user_text or user_text.startswith("[Voice"):
            await send_telegram(chat_id, user_text or "Could not transcribe.")
            return JSONResponse({"ok": True})
        await send_telegram(chat_id, f"Heard: {user_text}")

    if not user_text and not vision_content:
        return JSONResponse({"ok": True})

    await ensure_user()

    # ── Sunday Mode ───────────────────────────────────────────────────────────
    # Bypass entirely if 'override' appears anywhere in the message (case insensitive)
    if datetime.now().weekday() == 6 and "override" not in user_text.lower():
        session_id = await get_session_id("orchestrator", str(chat_id))
        await ensure_session(session_id, "orchestrator")
        await save_exchange(session_id, user_text, "[Saved for Monday — Sunday mode]")
        await send_telegram(chat_id, "It's Sunday. I've saved this for you. Enjoy your family time.")
        return JSONResponse({"ok": True})

    # ── Quick Commands ────────────────────────────────────────────────────────
    text_lower = user_text.strip().lower()

    if text_lower == "/help":
        help_text = (
            "<b>BELMONT OPS — COMMANDS</b>\n\n"
            "<b>Time Snapshots</b>\n"
            "/today — What's on for today\n"
            "/tomorrow — Tomorrow's prep + sleep question\n"
            "/week — Week ahead snapshot\n"
            "/schedule [date or 'week'] — Google Calendar view\n"
            "/brief — Full morning briefing\n"
            "\n<b>Business Data</b>\n"
            "/jobs — Active job list\n"
            "/estimates — Open estimates + pipeline\n"
            "/pipeline — Pipeline by age with flags\n"
            "/money — Cash and receivables\n"
            "/ads — Meta ad performance\n"
            "/recap — Full business snapshot\n"
            "/exit — Exit tracker (TopTick)\n"
            "/weather — 3-day Red Deer forecast\n"
            "\n<b>Estimating + Pricing</b>\n"
            "/pricing [key] — Quick rate reference\n"
            "/gst [amount] — 5% GST math\n"
            "\n<b>Templates + SOPs</b>\n"
            "/template — Email/document templates\n"
            "/sop — Operating procedures\n"
            "\n<b>Capture (explicit memory)</b>\n"
            "/note [anything] — Catch-all, agent categorizes\n"
            "/promise [task by when] — Commitment\n"
            "/decision [what + why] — Major decision\n"
            "/lesson [rule] — Hard-earned rule\n"
            "/idea [text] — Business idea\n"
            "/blocker [text] — What's in the way\n"
            "/risk [text] — Risk flag\n"
            "/opp [text] — Opportunity\n"
            "/expense [vendor amount cat] — Log expense\n"
            "/receipt — Snap a receipt photo to auto-log it\n"
            "/changeorder [job amount desc] — Log a change order\n"
            "/memory — See everything I remember about you\n"
            "/remember [fact] — Force-save a specific fact\n"
            "\n<b>Thinking + Research</b>\n"
            "/think [decision] — Walk through a hard call\n"
            "/research [topic] — Deep web research with sources\n"
            "/lookup [topic] — Quick fact lookup\n"
            "/email [to/subject/body] — Send email from Gmail\n"
            "/ballpark [type + details] — Structured estimate with line items\n"
            "  → deck, garage, kitchen, bathroom, home, basement\n"
            "  → reply 'push to jobtread [name]' to create draft\n"
            "\n<b>Recall</b>\n"
            "/promises /decisions /lessons /wins /network\n"
            "/who [name] — Contact card\n"
            "/followup [name] — Client follow-up draft\n"
            "/review [name] — Draft Google review request (SMS + email)\n"
            "/leads — Check Gmail for new Squarespace leads\n"
            "\n<b>People</b>\n"
            "/subs — Subcontractor list\n"
            "/bjj — Log BJJ session\n"
            "\n<b>Control</b>\n"
            "/snooze [hours] — DND (default 2h, max 24h)\n"
            "/unsnooze — Cancel DND\n"
            "\n<b>System</b>\n"
            "/diag — Full integration health\n"
            "/next — Single next action with reasoning\n"
            "/status — Light system health\n\n"
            "Or just talk to me in plain English. Send photo, voice memo, anything."
        )
        await send_telegram(chat_id, help_text)
        return JSONResponse({"ok": True})

    # /ballpark or /quote -> structured estimate with JobTread push option
    if text_lower.startswith("/ballpark") or text_lower.startswith("/quote"):
        prefix = "/ballpark" if text_lower.startswith("/ballpark") else "/quote"
        project_input = user_text[len(prefix):].strip()
        if not project_input:
            await send_telegram(
                chat_id,
                "<b>Ballpark Estimator</b>\n\n"
                "Format: /ballpark [type] [details]\n\n"
                "Examples:\n"
                "/ballpark deck 16x20 composite with stairs and glass railing\n"
                "/ballpark garage 24x24 detached heated and insulated\n"
                "/ballpark kitchen 180sqft high-end custom cabs Wolf appliances\n"
                "/ballpark bathroom primary ensuite 130sqft curbless heated floor\n"
                "/ballpark home 2400sqft bungalow high-spec\n"
                "/ballpark basement 1100sqft development 2bed 1bath\n\n"
                "After the ballpark, reply \"push to jobtread [customer name]\" to create a draft estimate."
            )
            return JSONResponse({"ok": True})
        user_text = (
            f"Generate a ballpark estimate for this Belmont project using the BALLPARK ESTIMATE FORMAT exactly.\n\n"
            f"Project: {project_input}\n\n"
            f"Use Belmont's 2026 Alberta pricing knowledge. Break out materials vs labour. "
            f"Apply correct contingency (10% reno, 15% addition/garage/custom). Add 5% GST. "
            f"Check margin at midpoint — flag if below standard. "
            f"State 2-3 assumptions that most affect the range. "
            f"End with the JobTread push offer."
        )

    # "push to jobtread [name]" after a ballpark — create draft estimate
    elif text_lower.startswith("push to jobtread") or text_lower.startswith("yes push") or (
        text_lower.startswith("yes ") and "jobtread" in text_lower
    ):
        customer_name = user_text.split(" ")[-1] if len(user_text.split()) > 1 else "New Client"
        # Strip command words to get just the name
        for prefix_word in ["push to jobtread", "yes push to jobtread", "yes jobtread", "push jobtread"]:
            if text_lower.startswith(prefix_word):
                customer_name = user_text[len(prefix_word):].strip() or customer_name
                break
        user_text = (
            f"Jacob wants to push the ballpark estimate from our conversation to JobTread as a draft estimate.\n"
            f"Customer name: {customer_name}\n\n"
            f"Steps:\n"
            f"1. Use jobtread_create_job to create a new job for {customer_name} (use the project type as the job name)\n"
            f"2. The estimate already exists in our conversation — summarize the key line items\n"
            f"3. Confirm the job was created and give Jacob the JobTread job number\n"
            f"4. Tell him what to do next: add contact details, attach drawings if any, convert to formal estimate\n\n"
            f"Keep it fast. Job name should be descriptive: '[Customer] — [Project Type]'"
        )

    # /gst — quick GST calculator (5% in Alberta)
    elif text_lower.startswith("/gst"):
        try:
            import re
            num_match = re.search(r'[\d,]+\.?\d*', user_text[len("/gst"):])
            if not num_match:
                await send_telegram(chat_id, "Format: /gst 47500")
                return JSONResponse({"ok": True})
            amount = float(num_match.group(0).replace(",", ""))
            gst = amount * 0.05
            total = amount + gst
            await send_telegram(
                chat_id,
                f"<b>GST Math (Alberta 5%)</b>\n\n"
                f"Subtotal: ${amount:,.2f}\n"
                f"GST: ${gst:,.2f}\n"
                f"<b>Total: ${total:,.2f}</b>"
            )
            return JSONResponse({"ok": True})
        except Exception as e:
            await send_telegram(chat_id, f"GST calc error: {e}")
            return JSONResponse({"ok": True})

    # /lesson, /decision, /promise — explicit memory logging
    elif text_lower.startswith("/lesson"):
        content = user_text[len("/lesson"):].strip()
        if not content:
            await send_telegram(chat_id, "Format: /lesson [hard-earned rule]\nEx: /lesson Confirm tile lead times >3 weeks before locking schedule")
            return JSONResponse({"ok": True})
        user_text = (
            f"Jacob is logging a hard-earned lesson from his business. Capture this in Zep memory "
            f"explicitly so future sessions can recall it. Lesson: \"{content}\". "
            f"Confirm what was saved in one line."
        )

    elif text_lower.startswith("/decision"):
        content = user_text[len("/decision"):].strip()
        if not content:
            await send_telegram(chat_id, "Format: /decision [what + why]\nEx: /decision Passed on Mitchell job — scope too vague, budget unclear")
            return JSONResponse({"ok": True})
        user_text = (
            f"Jacob is logging a major business decision with reasoning. Store this in Zep "
            f"memory so it's searchable later. Decision: \"{content}\". "
            f"Confirm what was saved in one line."
        )

    elif text_lower.startswith("/promise") or text_lower.startswith("/commit"):
        prefix_len = len("/promise") if text_lower.startswith("/promise") else len("/commit")
        content = user_text[prefix_len:].strip()
        if not content:
            await send_telegram(chat_id, "Format: /promise [what + by when]\nEx: /promise Call Henderson by Wednesday")
            return JSONResponse({"ok": True})
        user_text = (
            f"Jacob is logging a commitment he's making. Store in Zep memory so morning briefs "
            f"can surface this and check status. Commitment: \"{content}\". "
            f"Parse the deadline if mentioned. Confirm what was saved in one line."
        )

    # /who [name] — full memory recall on a contact
    elif text_lower.startswith("/who"):
        name = user_text[len("/who"):].strip()
        if not name:
            await send_telegram(chat_id, "Format: /who [name]\nEx: /who Henderson")
            return JSONResponse({"ok": True})
        user_text = (
            f"Search Zep memory deeply for everything Jacob knows about '{name}'. "
            f"Include: jobs done together, conversations, preferences, budget signals, "
            f"family info, decisions made, communication style. Format as a compact contact card. "
            f"If nothing found, say so and ask Jacob if he wants to add notes about them."
        )

    # /expense — quick expense log (writes to Zep now, QBO when OAuth restored)
    elif text_lower.startswith("/expense"):
        content = user_text[len("/expense"):].strip()
        if not content:
            await send_telegram(
                chat_id,
                "Format: /expense [vendor] [amount] [category] [memo]\n"
                "Ex: /expense Windsor Plywood 487.20 materials Anderson deck framing"
            )
            return JSONResponse({"ok": True})
        user_text = (
            f"Jacob is logging an expense. Parse this input: \"{content}\"\n"
            "Extract: vendor, amount (CAD), category (materials/fuel/tools/subs/other), "
            "memo/job reference. Try qbo_create_expense first. If QBO returns 401 or "
            "is not configured, store the expense details in Zep memory with category "
            "'pending_qbo_sync' so it can be reconciled later. Confirm what was captured."
        )

    # /followup [name] — quick client follow-up draft in Jacob's voice
    elif text_lower.startswith("/followup") or text_lower.startswith("/follow-up"):
        prefix_len = len("/followup") if text_lower.startswith("/followup") else len("/follow-up")
        name = user_text[prefix_len:].strip()
        if not name:
            await send_telegram(chat_id, "Format: /followup [client name]\nEx: /followup Henderson")
            return JSONResponse({"ok": True})
        user_text = (
            f"Draft a follow-up message to {name} in Jacob's voice. Steps:\n"
            f"1. Search Zep memory for context on {name} — what we've talked about, "
            f"any open estimate or job\n"
            f"2. Try jobtread_get_contacts to find their record\n"
            f"3. Try jobtread_get_estimates to see if there's an open quote tied to them\n"
            f"4. Draft a short, direct message that references actual context — not generic "
            f"'just checking in' fluff\n"
            f"5. Under 80 words. Clear next step. Ready to copy-paste.\n"
            f"If you can't find anything, ask Jacob what context to use."
        )

    # /changeorder [job] [amount] [description] — log a change order
    elif text_lower.startswith("/changeorder") or text_lower.startswith("/co "):
        prefix_len = len("/changeorder") if text_lower.startswith("/changeorder") else len("/co ")
        content = user_text[prefix_len:].strip()
        if not content:
            await send_telegram(
                chat_id,
                "Format: /changeorder [job name] [amount] [description]\n"
                "Ex: /changeorder Anderson deck +2400 client added pergola posts\n\n"
                "I'll log it to memory, track the running total for that job, "
                "and remind you to invoice it."
            )
            return JSONResponse({"ok": True})
        user_text = (
            f"Jacob is logging a change order. Raw input: \"{content}\"\n\n"
            "Parse out: job name, amount (positive = added scope, negative = reduction), "
            "and description of what changed.\n\n"
            "Steps:\n"
            "1. Save to memory tagged 'change_order' with today's date, job name, amount, description\n"
            "2. Search memory for previous change orders on this same job — total them up\n"
            "3. Confirm back: job name, this change order amount, running CO total for job\n"
            "4. Remind Jacob: 'Make sure this is captured in a JobTread change order document "
            "and invoiced before the job closes.'\n\n"
            "Keep response under 100 words. Confirm clearly."
        )

    # /review [client name] — draft a personalized Google review request
    elif text_lower.startswith("/review"):
        name = user_text[len("/review"):].strip()
        if not name:
            await send_telegram(
                chat_id,
                "Format: /review [client name]\nEx: /review Henderson\n\n"
                "I'll draft a personalized Google review request based on their job."
            )
            return JSONResponse({"ok": True})
        user_text = (
            f"Draft a Google review request for {name}. Steps:\n"
            f"1. Search memory and JobTread for context on {name}'s project — "
            f"what was built, how it went, anything personal/notable\n"
            f"2. Write a short, warm, specific message (3-4 sentences) that:\n"
            f"   - References their actual project by name\n"
            f"   - Thanks them genuinely\n"
            f"   - Asks for a Google review naturally (not desperately)\n"
            f"   - Includes placeholder: [Google Review Link]\n"
            f"3. Write it as Jacob, first person, casual but professional\n\n"
            f"Also draft an SMS version (under 160 chars) and an email version.\n"
            f"Label each clearly: SMS / Email / WhatsApp"
        )

    # /snooze [hours] — set DND window (capped at 24h to prevent accidents)
    elif text_lower.startswith("/snooze"):
        import re
        m = re.search(r'(\d+)\s*(h|hr|hrs|hour|hours|m|min|mins|minute|minutes)?', user_text[len("/snooze"):])
        if not m:
            hours = 2  # default
        else:
            n = int(m.group(1))
            unit = (m.group(2) or "h").lower()
            hours = n / 60.0 if unit.startswith("m") and not unit.startswith("h") else n
        hours = min(max(hours, 0.25), 24)  # clamp 15min - 24h
        until = set_snooze(str(chat_id), hours)
        await send_telegram(
            chat_id,
            f"Snoozed until {until.strftime('%I:%M %p')}. Scheduled jobs paused. "
            f"Send /unsnooze to resume early."
        )
        return JSONResponse({"ok": True})

    elif text_lower == "/unsnooze":
        clear_snooze(str(chat_id))
        await send_telegram(chat_id, "Snooze cleared. Back to normal.")
        return JSONResponse({"ok": True})

    # /template — email/document template library
    elif text_lower.startswith("/template"):
        key = user_text[len("/template"):].strip()
        if not key:
            await send_telegram(chat_id, list_templates())
        else:
            await send_telegram(chat_id, get_template(key))
        return JSONResponse({"ok": True})

    # /sop — standard operating procedures
    elif text_lower.startswith("/sop"):
        key = user_text[len("/sop"):].strip()
        if not key:
            await send_telegram(chat_id, list_sops())
        else:
            await send_telegram(chat_id, get_sop(key))
        return JSONResponse({"ok": True})

    # /pricing — quick pricing reference
    elif text_lower.startswith("/pricing"):
        key = user_text[len("/pricing"):].strip()
        if not key:
            await send_telegram(chat_id, list_pricing())
        else:
            await send_telegram(chat_id, get_pricing(key))
        return JSONResponse({"ok": True})

    # /today — synthesized day snapshot
    elif text_lower == "/today":
        user_text = (
            "Synthesize Jacob's day right now. Call these tools in parallel and assemble a short brief:\n"
            "- google_calendar_today (if available)\n"
            "- weather_red_deer_forecast (1 day)\n"
            "- jobtread_list_jobs (status=active, top 5 by recency)\n"
            "- Zep search for commitments due today\n\n"
            "Format output as:\n"
            "TODAY ([weekday, date])\n"
            "Weather: [1 line]\n"
            "Schedule: [calendar events or 'no calendar connected']\n"
            "Active jobs to touch: [top 3]\n"
            "Commitments due: [list or 'none tracked']\n"
            "Single most important thing today: [your call]\n\n"
            "Keep total under 200 words. No fluff."
        )

    # /tomorrow — next-day prep
    elif text_lower == "/tomorrow":
        user_text = (
            "Set Jacob up for tomorrow. Pull:\n"
            "- weather_red_deer_forecast for tomorrow\n"
            "- Open estimates 5+ days old\n"
            "- Active jobs needing client update Friday\n"
            "- Commitments due tomorrow from memory\n\n"
            "Format short. End with: 'Sleep on this: [one strategic question Jacob should consider overnight]'"
        )

    # /week — week ahead snapshot
    elif text_lower == "/week":
        user_text = (
            "Generate Jacob's week-ahead snapshot. Pull ALL of these tools:\n"
            "1. google_calendar_week (week_offset=0) — show Mon-Sun schedule\n"
            "2. weather_red_deer_forecast (days=7) — flag outdoor risk days\n"
            "3. jobtread_get_estimates — open estimates, any >14 days old?\n"
            "4. jobtread_list_jobs (active) — budget/schedule risk\n\n"
            "Output format:\n"
            "WEEK OF [date range]\n"
            "Schedule: [list key meetings/site visits by day]\n"
            "Pipeline: $X across N estimates (flag anything >14 days)\n"
            "Active jobs: N jobs — flag any at risk\n"
            "Weather watch: [days with outdoor risk]\n"
            "This week's win: [single most important thing]\n\n"
            "Under 280 words. Push back if Jacob's avoiding something obvious."
        )

    # /idea — quick idea capture
    elif text_lower.startswith("/idea"):
        content = user_text[len("/idea"):].strip()
        if not content:
            await send_telegram(chat_id, "Format: /idea [your idea]\nEx: /idea Partner with high-end realtors for staging consults")
            return JSONResponse({"ok": True})
        user_text = (
            f"Jacob is capturing a business idea. Store in Zep memory tagged 'idea'. "
            f"Idea: \"{content}\". After saving, give ONE honest reaction (1-2 sentences) — "
            f"is this strong, weak, derivative, or worth testing? Don't be sycophantic."
        )

    # /blocker — what's in the way
    elif text_lower.startswith("/blocker"):
        content = user_text[len("/blocker"):].strip()
        if not content:
            await send_telegram(chat_id, "Format: /blocker [what's blocking you]\nEx: /blocker Waiting on Anderson tile selection, holding up framing")
            return JSONResponse({"ok": True})
        user_text = (
            f"Jacob is logging a blocker. Store in Zep tagged 'blocker'. "
            f"Blocker: \"{content}\". After saving, ask one sharp question: "
            f"what's the smallest action that unblocks this in the next 24h?"
        )

    # /risk — risk capture
    elif text_lower.startswith("/risk"):
        content = user_text[len("/risk"):].strip()
        if not content:
            await send_telegram(chat_id, "Format: /risk [the risk]\nEx: /risk Anderson job margin trending below 25%, sub overruns")
            return JSONResponse({"ok": True})
        user_text = (
            f"Jacob is flagging a risk. Store in Zep tagged 'risk'. "
            f"Risk: \"{content}\". Confirm saved in one line and suggest the smallest mitigation."
        )

    # /opportunity — opportunity capture
    elif text_lower.startswith("/opportunity") or text_lower.startswith("/opp"):
        prefix_len = len("/opportunity") if text_lower.startswith("/opportunity") else len("/opp")
        content = user_text[prefix_len:].strip()
        if not content:
            await send_telegram(chat_id, "Format: /opportunity [the opportunity]\nEx: /opp Hendersons want to do a second build on adjacent lot")
            return JSONResponse({"ok": True})
        user_text = (
            f"Jacob is capturing an opportunity. Store in Zep tagged 'opportunity'. "
            f"Opportunity: \"{content}\". Confirm saved and ask one sharp question: "
            f"what's the next move to validate or capture this?"
        )

    # /note — catch-all note (agent picks category)
    elif text_lower.startswith("/note"):
        content = user_text[len("/note"):].strip()
        if not content:
            await send_telegram(chat_id, "Format: /note [anything]\nEx: /note Met a great drywall sub at the supply store, his name is Mike, 403-555-0199")
            return JSONResponse({"ok": True})
        user_text = (
            f"Jacob is logging a general note. Read it carefully and categorize it yourself:\n\n"
            f"\"{content}\"\n\n"
            f"Possible categories: idea, blocker, risk, opportunity, decision, lesson, "
            f"commitment, person/contact, vendor/supplier, material price, family, "
            f"client info, market intel, other. Pick the best fit and store it with that tag in Zep. "
            f"Confirm in one short line what you captured and how to recall it. "
            f"If it's a person, vendor, or material price — auto-store the structured fields too."
        )

    # /research — deep web research on any topic
    elif text_lower.startswith("/research") or text_lower.startswith("/lookup"):
        prefix_len = len("/research") if text_lower.startswith("/research") else len("/lookup")
        topic = user_text[prefix_len:].strip()
        if not topic:
            await send_telegram(
                chat_id,
                "Format: /research [topic]\n\n"
                "Examples:\n"
                "/research current cedar 2x6 prices in Red Deer\n"
                "/research [client name] property at [address]\n"
                "/research Belmont competitors in Central Alberta\n"
                "/lookup new Alberta building code changes 2026"
            )
            return JSONResponse({"ok": True})
        user_text = (
            f"Research topic: \"{topic}\"\n\n"
            f"Use web_search aggressively (multiple searches if needed). "
            f"Pull current information, prices, names, addresses, facts. "
            f"Synthesize the findings into a clean brief Jacob can act on:\n"
            f"- Key findings (3-5 bullet points, specific facts not generalities)\n"
            f"- Sources (cite where each fact came from)\n"
            f"- Recommended next action for Belmont, if any\n\n"
            f"Be direct. If the topic is a person or company, dig into their public footprint. "
            f"If pricing, give actual current numbers with retailer names. No fluff."
        )

    # /schedule — show calendar for a specific date or this week
    elif text_lower.startswith("/schedule") or text_lower == "/cal":
        date_arg = user_text[len("/schedule"):].strip() if text_lower.startswith("/schedule") else ""
        if date_arg.lower() in ("week", "this week", ""):
            user_text = (
                "Pull Jacob's Google Calendar for the full current week using google_calendar_week. "
                "Show each day with events listed under it. Include start times (Edmonton/Mountain time). "
                "If a day has no events, say 'clear'. Call out any scheduling conflicts or tight gaps. "
                "End with one observation about the week's load — light/heavy/balanced."
            )
        else:
            user_text = (
                f"Pull Jacob's Google Calendar for {date_arg} using google_calendar_today with date={date_arg}. "
                "List all events with times (Mountain time). Note any back-to-back blocks or time constraints. "
                "End with how much free time he has and whether he can take on same-day site visits."
            )

    # /email — send a quick email directly from Telegram
    elif text_lower.startswith("/email"):
        email_content = user_text[len("/email"):].strip()
        if not email_content or "\n" not in email_content and len(email_content) < 20:
            await send_telegram(
                chat_id,
                "Format:\n/email\n[To: email@domain.com]\n[Subject: subject here]\n[Body: your message]"
                "\n\nOr natural language:\n/email send Mike at mike@acme.com about the Riverside estimate saying I'll have it to him by Friday"
            )
            return JSONResponse({"ok": True})
        user_text = (
            f"Jacob wants to send an email. Here's the request:\n\n{email_content}\n\n"
            "Parse the recipient, subject, and body from this request. "
            "Draft the email in a professional but direct Belmont voice (not corporate, not casual). "
            "Then use gmail_send to send it. Confirm the send with: 'Sent to [email] — Subject: [subject]'."
        )

    # /think — decision walkthrough (genuinely hard call)
    elif text_lower.startswith("/think"):
        topic = user_text[len("/think"):].strip()
        if not topic:
            await send_telegram(
                chat_id,
                "Format: /think [the decision you're wrestling with]\n"
                "Ex: /think Should I take the Mitchell job, scope is vague but budget is $180K"
            )
            return JSONResponse({"ok": True})
        user_text = (
            f"Jacob has a decision to think through. Topic: \"{topic}\"\n\n"
            f"Walk him through a fast decision framework:\n"
            f"1. What's actually being decided? (state it precisely in one sentence)\n"
            f"2. What's the upside if it works? (concrete, numbers if possible)\n"
            f"3. What's the downside if it doesn't? (concrete, numbers if possible)\n"
            f"4. What's the reversibility? (one-way door or two-way door)\n"
            f"5. What info would change the answer? (and how to get it cheaply)\n"
            f"6. Your honest recommendation, in one sentence. No 'on the other hand'.\n\n"
            f"Use Belmont context. Pull tools if data helps (estimates, jobs, money). "
            f"Be direct. Push back if Jacob's avoiding the obvious answer. "
            f"End by storing the decision-in-progress to Zep so we can revisit later."
        )

    # /diagnostic — full integration health report (both services)
    elif text_lower in ("/diagnostic", "/diag", "/health"):
        await send_typing(chat_id)
        mcp_url = os.getenv("MCP_SERVER_URL", "")
        combined = {"integrations": {}, "summary": {"green": 0, "yellow": 0, "red": 0}}

        # Local (Telegram handler) diagnostic
        try:
            local = await diagnostic()
            for k, v in local.get("integrations", {}).items():
                combined["integrations"][k] = v
                combined["summary"][v["status"]] = combined["summary"].get(v["status"], 0) + 1
        except Exception as e:
            print(f"[diag] local failed: {e}")

        # MCP server diagnostic
        if mcp_url:
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(f"{mcp_url.rstrip('/')}/diagnostic")
                    mcp_report = resp.json()
                for k, v in mcp_report.get("integrations", {}).items():
                    combined["integrations"][k] = v
                    combined["summary"][v["status"]] = combined["summary"].get(v["status"], 0) + 1
            except Exception as e:
                combined["integrations"]["mcp_diagnostic"] = {
                    "status": "red",
                    "detail": f"Could not reach MCP /diagnostic: {e}",
                    "fix": "Check MCP server deployment"
                }
                combined["summary"]["red"] = combined["summary"].get("red", 0) + 1

        s = combined["summary"]
        overall = (
            "ALL GREEN ✅" if s.get("red", 0) == 0 and s.get("yellow", 0) == 0
            else f"{s.get('red', 0)} broken, {s.get('yellow', 0)} partial, {s.get('green', 0)} working"
        )
        lines = [
            "<b>Belmont Agent — Integration Health</b>",
            f"<i>{overall}</i>",
            f"✅ {s.get('green', 0)} green  ⚠️ {s.get('yellow', 0)} yellow  ❌ {s.get('red', 0)} red\n"
        ]
        icon = {"green": "✅", "yellow": "⚠️", "red": "❌"}
        for name, info in combined["integrations"].items():
            lines.append(f"{icon.get(info['status'], '?')} <b>{name}</b>: {info['detail']}")
            if info.get("fix"):
                lines.append(f"   ↳ {info['fix']}")
        await send_telegram(chat_id, "\n".join(lines))
        return JSONResponse({"ok": True})

    # /next — coach mode: tells Jacob the single next action
    elif text_lower in ("/next", "/nextstep"):
        await send_typing(chat_id)
        mcp_url = os.getenv("MCP_SERVER_URL", "")
        all_red = []
        try:
            local = await diagnostic()
            for k, v in local.get("integrations", {}).items():
                if v["status"] == "red":
                    all_red.append((k, v))
        except Exception:
            pass
        if mcp_url:
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(f"{mcp_url.rstrip('/')}/diagnostic")
                for k, v in resp.json().get("integrations", {}).items():
                    if v["status"] == "red":
                        all_red.append((k, v))
            except Exception:
                pass

        if not all_red:
            await send_telegram(
                chat_id,
                "<b>All integrations green.</b>\n\nNothing left to set up. Focus on the business."
            )
            return JSONResponse({"ok": True})

        # Priority order — what gives Jacob the most leverage to fix next
        priority = ["zep_memory", "anthropic", "qbo", "google", "meta_page", "openai_voice", "telegram", "mcp_server"]
        all_red.sort(key=lambda x: priority.index(x[0]) if x[0] in priority else 99)
        next_red = all_red[0]
        name, info = next_red

        priority_explainer = {
            "zep_memory": "Memory is the agent's biggest force multiplier. Without it, every conversation starts cold. Highest ROI fix.",
            "anthropic": "Without this the agent can't think. Critical.",
            "qbo": "Unlocks 8 finance tools + real money data in /brief.",
            "google": "Unlocks Calendar + Gmail in morning brief.",
            "meta_page": "Unlocks page posting + insights (ads already work).",
            "openai_voice": "Nice-to-have for field voice memos. Lower priority."
        }

        msg = (
            f"<b>Next step:</b> fix <b>{name}</b>\n\n"
            f"<b>What's wrong:</b> {info['detail']}\n\n"
            f"<b>How to fix:</b> {info.get('fix', 'see /diag')}\n\n"
            f"<b>Why it matters:</b> {priority_explainer.get(name, 'Surface area improvement.')}\n\n"
            f"{len(all_red) - 1} other items remaining after this. Run /diag anytime to see the full list."
        )
        await send_telegram(chat_id, msg)
        return JSONResponse({"ok": True})

    elif text_lower == "/memory":
        mems = await get_all_memories()
        if mems:
            lines = "\n".join(f"{i+1}. {m}" for i, m in enumerate(mems[:20]))
            await send_telegram(chat_id, f"What I remember about you and Belmont ({len(mems)} total):\n\n{lines}")
        else:
            await send_telegram(chat_id, "No memories stored yet. As we talk I'll automatically remember important facts.")
        return JSONResponse({"ok": True})

    elif text_lower.startswith("/remember "):
        fact = user_text[len("/remember "):].strip()
        if fact:
            await save_fact(fact)
            await send_telegram(chat_id, f"Got it, I'll remember: {fact}")
        else:
            await send_telegram(chat_id, "Format: /remember [fact]\nEx: /remember My lumber supplier is ABC Supply on 67th St")
        return JSONResponse({"ok": True})

    elif text_lower in QUICK_COMMANDS:
        user_text = QUICK_COMMANDS[text_lower]

    elif any(k in text_lower for k in BJJ_LOG_KEYWORDS):
        user_text = (
            f"{user_text}\n\nContext: Jacob tracks BJJ training. Target is 4 sessions/week. "
            "Log this session in memory and report his count for this week."
        )

    elif any(k in text_lower for k in SUB_ADD_KEYWORDS):
        user_text = (
            f"{user_text}\n\nContext: Store this subcontractor in memory under Belmont subs. "
            "Fields to capture: name, trade, phone, rate (hourly or per project), notes. "
            "Confirm what was saved and how to recall it later with /subs."
        )

    # ── Route and Run ─────────────────────────────────────────────────────────
    agent_type = route_to_agent(user_text)

    if is_async_task(user_text) and not vision_content:
        task_desc = user_text[:60] + "..." if len(user_text) > 60 else user_text
        await send_telegram(chat_id, f"On it. Working on: {task_desc}\n\nRouted to: {agent_type} agent.")
        background_tasks.add_task(
            process_message_async, chat_id, user_text, agent_type, None
        )
        return JSONResponse({"ok": True})

    await send_typing(chat_id)
    session_id = await get_session_id(agent_type, str(chat_id))
    await ensure_session(session_id, agent_type)
    memory_ctx = await load_memory(session_id, query=user_text)
    history = get_history(str(chat_id))

    try:
        result = await run_agent(
            agent_type=agent_type,
            message=user_text,
            memory_context=memory_ctx,
            chat_id=str(chat_id),
            vision_content=vision_content,
            conversation_history=history
        )
    except Exception as e:
        result = f"Error: {e}"

    add_to_history(str(chat_id), user_text, result)
    await save_exchange(session_id, user_text, result)
    await send_telegram(chat_id, result)
    return JSONResponse({"ok": True})


# ─────────────────────────────────────────────
# LEAD SCORING
# ─────────────────────────────────────────────

def score_lead(name: str, email: str, phone: str, project: str, message: str) -> dict:
    """
    Score an inbound lead 1-10 based on Belmont Ideal Client Profile signals.
    Returns dict with score, tier, urgency, reasoning, recommended action.

    Belmont ICP:
    - Red Deer / Central AB
    - Minimum $25K, prefer $75K+ renos, $400K+ custom
    - Values craftsmanship, not price shoppers
    - Decision-makers
    """
    text_blob = f"{project} {message}".lower()
    score = 5  # neutral start
    reasons = []

    # ── BUDGET / SCOPE SIGNALS ────────────────────────────────────────────
    high_value_kw = [
        "custom home", "build a home", "new build", "addition", "second storey",
        "second-storey", "ensuite", "primary bath", "master bath",
        "full kitchen", "kitchen reno", "major reno", "whole home"
    ]
    med_value_kw = ["bathroom", "kitchen", "basement", "deck"]
    low_value_kw = ["handyman", "small", "quick fix", "minor", "repair", "patch", "touch up"]

    if any(kw in text_blob for kw in high_value_kw):
        score += 3
        reasons.append("high-value project signal")
    elif any(kw in text_blob for kw in med_value_kw):
        score += 1
        reasons.append("mid-value project type")
    if any(kw in text_blob for kw in low_value_kw):
        score -= 3
        reasons.append("low-value project signal — may not fit ICP")

    # Explicit budget signals
    import re
    budget_match = re.search(r'\$?\s*(\d{1,3}(?:,\d{3})*|\d+)\s*(?:k|K|,000)?', text_blob)
    if budget_match:
        try:
            raw = budget_match.group(1).replace(",", "")
            num = int(raw)
            if "k" in budget_match.group(0).lower() or "000" in budget_match.group(0):
                num *= 1000
            if num >= 100000:
                score += 2
                reasons.append(f"budget ${num:,} stated — strong fit")
            elif num >= 25000:
                score += 1
                reasons.append(f"budget ${num:,} stated — fits minimum")
            elif num < 25000 and num > 1000:
                score -= 2
                reasons.append(f"budget ${num:,} stated — below Belmont minimum")
        except Exception:
            pass

    # ── LOCATION SIGNALS ──────────────────────────────────────────────────
    central_ab = [
        "red deer", "blackfalds", "sylvan lake", "lacombe", "ponoka",
        "innisfail", "olds", "rocky mountain house", "stettler",
        "central alberta", "alberta", "ab "
    ]
    if any(c in text_blob for c in central_ab):
        score += 1
        reasons.append("location in Central AB")
    elif any(x in text_blob for x in ["calgary", "edmonton"]):
        score -= 1
        reasons.append("outside Belmont primary market")

    # ── URGENCY SIGNALS ───────────────────────────────────────────────────
    urgency = "normal"
    if any(kw in text_blob for kw in ["asap", "urgent", "as soon as", "this week", "tomorrow", "right away"]):
        urgency = "high"
        score += 1
        reasons.append("urgency stated")
    elif any(kw in text_blob for kw in ["next year", "down the road", "thinking about", "just curious", "exploring"]):
        urgency = "low"
        score -= 1
        reasons.append("low urgency / exploratory")

    # ── DECISION-MAKER SIGNALS ────────────────────────────────────────────
    if any(kw in text_blob for kw in ["my wife and i", "my husband and i", "we are", "we're looking", "we want", "we'd like"]):
        score += 1
        reasons.append("decision-maker language ('we')")

    # ── PRICE-SHOPPER FLAGS (negative) ────────────────────────────────────
    if any(kw in text_blob for kw in ["cheap", "cheapest", "lowest price", "best price", "discount", "deal"]):
        score -= 2
        reasons.append("price-shopper language — likely poor fit")

    # ── CONTACT QUALITY ───────────────────────────────────────────────────
    if email and phone:
        score += 1
        reasons.append("both phone + email provided")
    elif not (email or phone):
        score -= 2
        reasons.append("no contact info — hard to reach")

    # ── MESSAGE DEPTH ─────────────────────────────────────────────────────
    if message and len(message) > 200:
        score += 1
        reasons.append("detailed message — serious inquiry")
    elif message and len(message) < 20:
        score -= 1
        reasons.append("very short message")

    score = max(1, min(10, score))

    if score >= 8:
        tier = "HOT"
        action = "Call now. Speed-to-lead wins. Don't email first — call."
    elif score >= 6:
        tier = "WARM"
        action = "Call within 1 hour. Email follow-up if no answer."
    elif score >= 4:
        tier = "COOL"
        action = "Email response within 4 hours. Qualify before booking site visit."
    else:
        tier = "COLD"
        action = "Acknowledge politely, ask 2-3 qualifying questions before further effort."

    return {
        "score": score,
        "tier": tier,
        "urgency": urgency,
        "reasons": reasons,
        "recommended_action": action
    }


# ─────────────────────────────────────────────
# LEAD INTAKE WEBHOOK
# ─────────────────────────────────────────────

@app.post("/newlead")
async def new_lead(request: Request, background_tasks: BackgroundTasks):
    """
    Accepts new leads from Squarespace form webhooks or any HTTP POST.
    Point your Squarespace form webhook here.
    Squarespace: Settings > Advanced > External API > Form Webhook URL
    Or use Zapier/Make to forward form submissions here.
    """
    try:
        data = await request.json()
    except Exception:
        try:
            form = await request.form()
            data = dict(form)
        except Exception:
            data = {}

    # Normalize common Squarespace/form field names
    def pick(*keys):
        for k in keys:
            v = data.get(k) or data.get(k.lower()) or data.get(k.upper())
            if v:
                return str(v).strip()
        return ""

    name = pick("name", "Name", "fullName", "full_name") or (
        pick("firstName", "first_name") + " " + pick("lastName", "last_name")
    ).strip()
    email = pick("email", "Email", "emailAddress")
    phone = pick("phone", "Phone", "phoneNumber", "phone_number")
    project = pick("project", "Project", "projectType", "subject", "Subject", "service")
    message = pick("message", "Message", "comments", "Comments", "description", "notes")

    if not name and not email and not phone:
        return JSONResponse({"ok": True, "note": "No lead data found"})

    # ── Score the lead before alerting Jacob ──────────────────────────────
    scoring = score_lead(name, email, phone, project, message)

    # ── Auto-create JobTread contact for HOT/WARM (score >= 6) ───────────
    jobtread_contact_status = ""
    if scoring["score"] >= 6 and name:
        mcp_url = os.getenv("MCP_SERVER_URL", "")
        mcp_secret = os.getenv("MCP_SERVER_SECRET", "")
        if mcp_url and mcp_secret:
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    # Use jobtread_create_job with minimal scope to also create the customer account
                    # (existing tool auto-creates account + location when needed)
                    job_resp = await client.post(
                        f"{mcp_url.rstrip('/')}/mcp/execute",
                        headers={"x-mcp-secret": mcp_secret, "content-type": "application/json"},
                        json={
                            "tool": "jobtread_create_job",
                            "params": {
                                "name": f"Inbound lead — {name}",
                                "customer_name": name,
                                "customer_email": email,
                                "customer_phone": phone,
                                "description": f"Website inquiry: {project}\n\n{message[:500]}"
                            }
                        }
                    )
                    result = job_resp.json()
                    if result.get("success"):
                        jobtread_contact_status = f"\n✅ Auto-created in JobTread: #{result.get('job_number', '?')}"
                    else:
                        jobtread_contact_status = f"\n⚠️ JobTread create failed: {str(result.get('error', ''))[:80]}"
            except Exception as e:
                jobtread_contact_status = f"\n⚠️ JobTread sync error: {str(e)[:80]}"

    # Notify Jacob immediately with score
    tier_emoji = {
        "HOT": "🔥",
        "WARM": "⚡",
        "COOL": "📬",
        "COLD": "❄️"
    }.get(scoring["tier"], "")

    alert = (
        f"<b>{tier_emoji} New Lead — {scoring['tier']} ({scoring['score']}/10)</b>\n\n"
        f"<b>{name or 'Unknown'}</b>\n"
        + (f"Project: {project}\n" if project else "")
        + (f"Email: {email}\n" if email else "")
        + (f"Phone: {phone}\n" if phone else "")
        + (f"Message: {message[:200]}\n" if message else "")
        + f"\n<b>Action:</b> {scoring['recommended_action']}\n"
        + f"<b>Why this score:</b> " + "; ".join(scoring['reasons'][:4])
        + jobtread_contact_status
        + "\n\nDrafting response..."
    )
    await send_telegram(JACOB_CHAT_ID, alert)

    # Trigger agent to draft outreach — pass scoring context so reply matches tier
    prompt = (
        f"New lead from Belmont website (scored {scoring['score']}/10, tier: {scoring['tier']}):\n"
        f"Name: {name}\nEmail: {email}\nPhone: {phone}\n"
        f"Project interest: {project}\nMessage: {message}\n"
        f"Urgency: {scoring['urgency']}\n\n"
        "Draft a personalized first response in Jacob's voice that:\n"
        "1. Acknowledges their specific project\n"
        "2. Establishes Belmont's premium positioning (not the cheapest, the best)\n"
        "3. Proposes a specific next step matching the tier:\n"
        "   - HOT/WARM: direct ask for a 15-min call this week, suggest 2 time windows\n"
        "   - COOL: ask 2-3 qualifying questions, propose a call after they reply\n"
        "   - COLD: polite acknowledgement + qualifying questions, no time ask\n"
        "4. Under 120 words. No fluff.\n\n"
        "Present it ready to copy-paste. Then ask Jacob to confirm or adjust before sending."
    )

    background_tasks.add_task(
        process_message_async, JACOB_CHAT_ID, prompt, "comms"
    )

    return JSONResponse({"ok": True, "lead": name, "score": scoring["score"], "tier": scoring["tier"]})

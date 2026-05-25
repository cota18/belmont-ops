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
from memory.zep_memory import (
    ensure_user, ensure_session, load_memory,
    save_exchange, get_session_id
)

app = FastAPI(title="Belmont Telegram Handler")

from state import set_snooze, clear_snooze, is_snoozed, get_snooze_deadline

@app.on_event("startup")
async def startup():
    from scheduler import start_scheduler
    start_scheduler()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
JACOB_CHAT_ID = os.getenv("JACOB_CHAT_ID", "")

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
    "/exit": "Check my exit tracker. Based on current QBO revenue data, how am I tracking toward the $8K/month net income target for 6 consecutive months? What's the gap and what's the fastest path to closing it?",
    "/weather": "Call weather_red_deer_forecast for the next 3 days. Flag any outdoor-work risk (deck, framing, concrete, roof) and tell me what to reschedule.",
    "/promises": "Search Zep memory for commitments I've made in the last 14 days (anything I said I'd do by a date). List them with status: kept, pending, or dropped. Be direct — call out anything I've ghosted.",
    "/decisions": "Search Zep memory for major business decisions I've logged. Show last 10 with the reasoning I gave at the time. Useful for reviewing my own thinking.",
    "/lessons": "Search Zep memory for lessons logged from past jobs. Pull the top 8 most relevant ones. These are my hard-earned rules — surface them.",
    "/network": "Search Zep memory for all builders, subs, vendors, and referral sources I've mentioned. Group by role. Flag anyone I haven't talked to in 60+ days as 'gone cold'.",
    "/wins": "Search Zep memory for daily wins I've logged in the last 14 days. Summarize momentum in 2-3 sentences. Be honest — if I've been dropping the ball, say so.",
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
        return "[Voice message received — add OPENAI_API_KEY to enable transcription]"
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
    try:
        result = await run_agent(
            agent_type=agent_type,
            message=user_message,
            memory_context=memory_ctx,
            chat_id=str(chat_id),
            vision_content=vision_content
        )
    except Exception as e:
        result = f"Agent error: {e}"
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
        caption = message.get("caption", "Analyze this image and tell me what it is.")
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                file_info = await client.get(
                    f"{TELEGRAM_API}/getFile", params={"file_id": file_id}
                )
                file_path = file_info.json()["result"]["file_path"]
                file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
                img_bytes = (await client.get(file_url)).content

            img_b64 = base64.b64encode(img_bytes).decode()
            is_receipt = any(w in caption.lower() for w in
                             ["receipt", "expense", "invoice", "bill", "cost"])

            no_caption = not message.get("caption")
            if is_receipt:
                vision_prompt = (
                    f"Jacob sent a photo with caption: '{caption}'\n"
                    "This appears to be a receipt or expense document. Extract:\n"
                    "- Vendor/supplier name\n"
                    "- Total amount\n"
                    "- Date\n"
                    "- Category (materials, fuel, tools, food, subcontractor, other)\n"
                    "Confirm the details and offer to log it to QuickBooks as an expense."
                )
            elif no_caption:
                vision_prompt = (
                    "Jacob sent a job site photo with no caption. "
                    "Describe what you see in the context of a construction site. "
                    "Then ask: 'Which job should I log this to?' "
                    "Once he replies with a job name, log it as a progress note in JobTread."
                )
            else:
                vision_prompt = (
                    f"Jacob sent a photo with caption: '{caption}'\n"
                    "Analyze this image in the context of his construction business. "
                    "Be direct and useful."
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
            "<b>Belmont Ops Commands:</b>\n\n"
            "<b>Business</b>\n"
            "/brief — Full morning briefing\n"
            "/jobs — Active job list\n"
            "/estimates — Open estimates + pipeline\n"
            "/pipeline — Pipeline by age with flags\n"
            "/money — Cash and receivables\n"
            "/ads — Meta ad performance\n"
            "/recap — Full business snapshot\n"
            "/exit — Exit tracker (TopTick)\n"
            "/weather — 3-day Red Deer forecast + outdoor work risk\n"
            "\n<b>Estimating</b>\n"
            "/quote [description] — Fast ballpark estimate\n"
            "  e.g. /quote 600sqft composite deck with glass railing\n"
            "/gst [amount] — Quick 5% GST math\n"
            "\n<b>Memory Capture (explicit)</b>\n"
            "/promise [task by when] — Log a commitment\n"
            "/decision [what + why] — Log a major decision\n"
            "/lesson [rule] — Log a hard-earned lesson\n"
            "/who [name] — Recall everything I know about a contact\n"
            "/expense [vendor amount category] — Log expense\n"
            "/followup [name] — Quick client follow-up draft\n"
            "\n<b>Control</b>\n"
            "/snooze [hours] — DND window (default 2h)\n"
            "/unsnooze — Cancel DND\n"
            "\n<b>Memory Recall</b>\n"
            "/promises — What I said I'd do (status check)\n"
            "/decisions — Major decisions logged + reasoning\n"
            "/lessons — Hard-earned rules from past jobs\n"
            "/wins — Daily wins logged, momentum check\n"
            "/network — Builders, subs, vendors, referrals\n"
            "\n<b>People</b>\n"
            "/subs — Subcontractor list\n"
            "/bjj — Log BJJ session\n"
            "\n<b>System</b>\n"
            "/status — System health\n"
            "/help — This menu\n\n"
            "Or ask me anything in plain English.\n"
            "Send a photo with 'receipt' in the caption to log an expense.\n"
            "Send a voice memo and I'll transcribe + handle it."
        )
        await send_telegram(chat_id, help_text)
        return JSONResponse({"ok": True})

    # /quote with text after it -> ballpark estimate
    if text_lower.startswith("/quote"):
        quote_input = user_text[len("/quote"):].strip()
        if not quote_input:
            await send_telegram(
                chat_id,
                "Format: /quote [project description]\n\n"
                "Examples:\n"
                "/quote 600sqft composite deck with glass railing in Red Deer\n"
                "/quote 80sqft master bath reno mid-spec curbless shower\n"
                "/quote 400sqft single-storey addition standard finish"
            )
            return JSONResponse({"ok": True})
        user_text = ESTIMATE_TEMPLATE_PROMPT + quote_input

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

    # /snooze [hours] — set DND window
    elif text_lower.startswith("/snooze"):
        import re
        m = re.search(r'(\d+)\s*(h|hr|hrs|hour|hours|m|min|mins|minute|minutes)?', user_text[len("/snooze"):])
        if not m:
            hours = 2  # default
        else:
            n = int(m.group(1))
            unit = (m.group(2) or "h").lower()
            hours = n / 60.0 if unit.startswith("m") and not unit.startswith("h") else n
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

    elif text_lower in QUICK_COMMANDS:
        user_text = QUICK_COMMANDS[text_lower]

    elif any(k in text_lower for k in BJJ_LOG_KEYWORDS):
        user_text = (
            f"{user_text}\n\nContext: Jacob tracks BJJ training. Target is 4 sessions/week. "
            "Log this session in memory and report his count for this week."
        )

    elif any(k in text_lower for k in SUB_ADD_KEYWORDS):
        user_text = (
            f"{user_text}\n\nContext: Store this subcontractor in Zep memory under Belmont subs. "
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

    try:
        result = await run_agent(
            agent_type=agent_type,
            message=user_text,
            memory_context=memory_ctx,
            chat_id=str(chat_id),
            vision_content=vision_content
        )
    except Exception as e:
        result = f"Error: {e}"

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

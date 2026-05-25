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
}

BJJ_LOG_KEYWORDS = ["/bjj", "trained bjj", "bjj session", "rolled today", "mat time"]

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
            "/brief — Full morning briefing\n"
            "/jobs — Active job list\n"
            "/estimates — Open estimates + pipeline\n"
            "/money — Cash and receivables\n"
            "/ads — Meta ad performance\n"
            "/bjj — Log BJJ session or check weekly count\n"
            "/status — System health\n"
            "/help — This menu\n\n"
            "Or ask me anything in plain English."
        )
        await send_telegram(chat_id, help_text)
        return JSONResponse({"ok": True})

    if text_lower in QUICK_COMMANDS:
        user_text = QUICK_COMMANDS[text_lower]

    elif any(k in text_lower for k in BJJ_LOG_KEYWORDS):
        user_text = (
            f"{user_text}\n\nContext: Jacob tracks BJJ training. Target is 4 sessions/week. "
            "Log this session in memory and report his count for this week."
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

"""
BELMONT OPS - TELEGRAM WEBHOOK HANDLER
Receives messages from Jacob, routes to the right agent,
handles async long-running tasks, sends results back.
"""

import os
import asyncio
import httpx
import tempfile
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
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")

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
    msg_lower = message.lower()
    return any(kw in msg_lower for kw in ASYNC_KEYWORDS)


async def send_telegram(chat_id, text: str):
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    async with httpx.AsyncClient(timeout=30) as client:
        for chunk in chunks:
            await client.post(
                f"{TELEGRAM_API}/sendMessage",
                json={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"}
            )


async def transcribe_voice(file_id: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{TELEGRAM_API}/getFile", params={"file_id": file_id})
            file_path = resp.json()["result"]["file_path"]

        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
        async with httpx.AsyncClient(timeout=60) as client:
            audio_resp = await client.get(file_url)
            audio_bytes = audio_resp.content

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        async with httpx.AsyncClient(timeout=60) as client:
            with open(tmp_path, "rb") as audio_file:
                resp = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY', '')}"},
                    files={"file": ("voice.ogg", audio_file, "audio/ogg")},
                    data={"model": "whisper-1", "language": "en"}
                )
        os.unlink(tmp_path)

        if resp.status_code == 200:
            return resp.json().get("text", "").strip()
        else:
            return "[Voice message received - add OPENAI_API_KEY to enable transcription]"

    except Exception as e:
        return f"[Voice transcription error: {e}]"


async def send_typing(chat_id):
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            f"{TELEGRAM_API}/sendChatAction",
            json={"chat_id": chat_id, "action": "typing"}
        )


async def process_message_async(chat_id: str, user_message: str, agent_type: str):
    session_id = await get_session_id(agent_type, str(chat_id))
    await ensure_session(session_id, agent_type)
    memory_ctx = await load_memory(session_id, query=user_message)
    try:
        result = await run_agent(
            agent_type=agent_type,
            message=user_message,
            memory_context=memory_ctx,
            chat_id=str(chat_id)
        )
    except Exception as e:
        result = f"Agent error: {e}"
    await save_exchange(session_id, user_message, result)
    await send_telegram(chat_id, result)


@app.get("/")
async def health():
    return {"status": "Belmont Telegram Handler online", "version": "2.0"}


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
    user_text = message.get("text", "").strip()

    voice = message.get("voice") or message.get("audio")
    if voice and not user_text:
        await send_typing(chat_id)
        file_id = voice.get("file_id")
        user_text = await transcribe_voice(file_id)
        if not user_text or user_text.startswith("[Voice"):
            await send_telegram(chat_id, user_text or "Could not transcribe voice message.")
            return JSONResponse({"ok": True})
        await send_telegram(chat_id, f"Heard: {user_text}")

    if not user_text:
        return JSONResponse({"ok": True})

    await ensure_user()
    agent_type = route_to_agent(user_text)

    if user_text.startswith("/"):
        await handle_command(chat_id, user_text, background_tasks)
        return JSONResponse({"ok": True})

    if is_async_task(user_text):
        task_description = user_text[:60] + "..." if len(user_text) > 60 else user_text
        ack = f"On it. Working on: {task_description}\n\nRouted to: {agent_type} agent. Will send results when done."
        await send_telegram(chat_id, ack)
        background_tasks.add_task(process_message_async, chat_id, user_text, agent_type)
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
            chat_id=str(chat_id)
        )
    except Exception as e:
        result = f"Error: {e}"

    await save_exchange(session_id, user_text, result)
    await send_telegram(chat_id, result)
    return JSONResponse({"ok": True})


async def handle_command(chat_id, command: str, background_tasks: BackgroundTasks):
    cmd = command.split()[0].lower()

    if cmd == "/status":
        msg = "Belmont Ops Agent v2.0 online.\n\nAgents: Orchestrator, Finance, Project, Sales, Estimating, Communications\nMemory: Zep (active)\nTools: JobTread, QuickBooks Online, Meta\n\nSend any message to get started."
        await send_telegram(chat_id, msg)

    elif cmd == "/morning":
        await send_telegram(chat_id, "Generating your morning brief...")
        background_tasks.add_task(
            process_message_async, chat_id,
            "Give me a complete morning brief: active jobs status, overdue invoices, any urgent items needing attention today.",
            "orchestrator"
        )

    elif cmd == "/jobs":
        background_tasks.add_task(
            process_message_async, chat_id,
            "List all active jobs with current status, budget vs actual, and any flags.",
            "project"
        )

    elif cmd == "/cash":
        background_tasks.add_task(
            process_message_async, chat_id,
            "Give me the full cash position: unpaid receivables, overdue invoices, upcoming bills, and net cash picture.",
            "finance"
        )

    elif cmd == "/help":
        msg = "BELMONT OPS COMMANDS\n\n/status - Agent status\n/morning - Morning brief\n/jobs - Active job summary\n/cash - Cash position\n/help - This menu\n\nOr just talk to me in plain language. I route to the right specialist automatically."
        await send_telegram(chat_id, msg)

    else:
        await send_telegram(chat_id, "Unknown command. Send /help for options.")

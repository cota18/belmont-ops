"""
BELMONT OPS - SCHEDULED PROACTIVE JOBS
Agent initiates these — Jacob doesn't have to ask.
Morning brief calls /briefing on MCP server directly.
Weekly debrief sends questions to Jacob's Telegram.
"""

import os
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import httpx

JACOB_CHAT_ID = os.getenv("JACOB_CHAT_ID")
SELF_URL = os.getenv("SELF_URL", "http://localhost:8000")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "https://belmont-ops-production.up.railway.app")
MCP_SERVER_SECRET = os.getenv("MCP_SERVER_SECRET", "")


async def trigger_agent_task(message: str):
    """Trigger a task on the Telegram handler as if Jacob sent it."""
    if not JACOB_CHAT_ID:
        print("JACOB_CHAT_ID not set — skipping scheduled task")
        return
    async with httpx.AsyncClient(timeout=120) as client:
        payload = {
            "message": {
                "chat": {"id": int(JACOB_CHAT_ID)},
                "text": message
            }
        }
        await client.post(f"{SELF_URL}/webhook", json=payload)


async def morning_brief():
    """Daily morning briefing — 7:00 AM Mountain Time (UTC-6/7).
    Calls /briefing on the MCP server which generates and pushes the full briefing.
    """
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                f"{MCP_SERVER_URL}/briefing",
                headers={"x-mcp-secret": MCP_SERVER_SECRET},
                timeout=60.0
            )
            if resp.status_code == 200:
                print(f"[scheduler] Morning briefing sent: {resp.json().get('status')}")
            else:
                print(f"[scheduler] Briefing endpoint returned {resp.status_code}: {resp.text[:200]}")
                # Fallback: trigger via agent loop
                await trigger_agent_task(
                    "Morning brief: Give me a full status update. "
                    "1) Active jobs — any problems or flags? "
                    "2) Cash: overdue invoices and what needs collection. "
                    "3) Any urgent items I need to act on today. "
                    "Keep it tight. Facts and actions only."
                )
    except Exception as e:
        print(f"[scheduler] Morning brief error: {e}")


async def weekly_job_review():
    """Monday 8:00 AM — Weekly job review."""
    await trigger_agent_task(
        "Weekly project review for all active Belmont jobs. "
        "For each job: status, budget vs actual, progress this week, "
        "any risk flags, and next milestone. Rank by urgency."
    )


async def overdue_invoice_alert():
    """Every Wednesday — flag overdue invoices."""
    await trigger_agent_task(
        "Pull all overdue invoices from QBO. "
        "For any invoice past 30 days, draft a follow-up message I can send. "
        "Flag anything past 60 days as priority collection. "
        "Give me the total amount outstanding."
    )


async def friday_cash_summary():
    """Every Friday 4:00 PM — Weekly cash wrap."""
    await trigger_agent_task(
        "End of week cash summary: "
        "Total receivables outstanding, what came in this week, "
        "what bills are due next week, net cash position. "
        "Anything I need to action before Monday?"
    )


async def friday_debrief():
    """Every Friday 5:00 PM MST — Weekly debrief questions pushed directly."""
    if not TELEGRAM_TOKEN or not JACOB_CHAT_ID:
        print("[scheduler] Telegram credentials not set — skipping debrief")
        return
    debrief_msg = (
        "<b>Weekly Debrief</b>\n\n"
        "Reply to each:\n"
        "1. What moved the needle this week?\n"
        "2. What's the one thing that would make next week a win?\n"
        "3. What needs to happen first Monday morning?\n\n"
        "<i>I'll remember your answers.</i>"
    )
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": JACOB_CHAT_ID, "text": debrief_msg, "parse_mode": "HTML"}
            )
        print("[scheduler] Friday debrief sent")
    except Exception as e:
        print(f"[scheduler] Friday debrief error: {e}")


def start_scheduler():
    """Initialize and start the APScheduler."""
    scheduler = AsyncIOScheduler(timezone="America/Edmonton")

    # Daily morning brief — 7:00 AM Mountain (calls MCP /briefing)
    scheduler.add_job(morning_brief, CronTrigger(hour=7, minute=0, day_of_week="mon-fri"))

    # Weekly job review — Monday 8:00 AM
    scheduler.add_job(weekly_job_review, CronTrigger(hour=8, minute=0, day_of_week="mon"))

    # Overdue invoice alert — Wednesday 9:00 AM
    scheduler.add_job(overdue_invoice_alert, CronTrigger(hour=9, minute=0, day_of_week="wed"))

    # Friday cash summary — Friday 4:00 PM
    scheduler.add_job(friday_cash_summary, CronTrigger(hour=16, minute=0, day_of_week="fri"))

    # Friday debrief questions — Friday 5:00 PM
    scheduler.add_job(friday_debrief, CronTrigger(hour=17, minute=0, day_of_week="fri"))

    scheduler.start()
    print("Scheduler started: morning brief (M-F 7am), job review (Mon 8am), "
          "invoice alert (Wed 9am), cash summary (Fri 4pm), debrief (Fri 5pm)")
    return scheduler

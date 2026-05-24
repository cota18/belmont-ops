"""
BELMONT OPS - SCHEDULED PROACTIVE JOBS
Agent initiates these — Jacob doesn't have to ask.
Morning brief, weekly reviews, overdue invoice alerts.
"""

import os
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import httpx

JACOB_CHAT_ID = os.getenv("JACOB_CHAT_ID")
SELF_URL = os.getenv("SELF_URL", "http://localhost:8000")


async def trigger_agent_task(message: str):
    """Trigger a task on the Telegram handler as if Jacob sent it."""
    if not JACOB_CHAT_ID:
        print("JACOB_CHAT_ID not set — skipping scheduled task")
        return
    # Simulate a Telegram message internally
    async with httpx.AsyncClient(timeout=120) as client:
        payload = {
            "message": {
                "chat": {"id": int(JACOB_CHAT_ID)},
                "text": message
            }
        }
        await client.post(f"{SELF_URL}/webhook", json=payload)


async def morning_brief():
    """Daily morning briefing — 7:00 AM Mountain Time (UTC-6/7)."""
    await trigger_agent_task(
        "Morning brief: Give me a full status update. "
        "1) Active jobs — any problems or flags? "
        "2) Cash: overdue invoices and what needs collection. "
        "3) Any urgent items I need to act on today. "
        "Keep it tight. Facts and actions only."
    )


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


def start_scheduler():
    """Initialize and start the APScheduler."""
    scheduler = AsyncIOScheduler(timezone="America/Edmonton")

    # Daily morning brief — 7:00 AM Mountain
    scheduler.add_job(morning_brief, CronTrigger(hour=7, minute=0, day_of_week="mon-fri"))

    # Weekly job review — Monday 8:00 AM
    scheduler.add_job(weekly_job_review, CronTrigger(hour=8, minute=0, day_of_week="mon"))

    # Overdue invoice alert — Wednesday 9:00 AM
    scheduler.add_job(overdue_invoice_alert, CronTrigger(hour=9, minute=0, day_of_week="wed"))

    # Friday cash summary — Friday 4:00 PM
    scheduler.add_job(friday_cash_summary, CronTrigger(hour=16, minute=0, day_of_week="fri"))

    scheduler.start()
    print("Scheduler started: morning brief (M-F 7am), job review (Mon 8am), invoice alert (Wed 9am), cash summary (Fri 4pm)")
    return scheduler

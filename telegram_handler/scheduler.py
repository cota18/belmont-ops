"""
BELMONT OPS - SCHEDULED PROACTIVE JOBS
All scheduled tasks that run without Jacob asking.
"""

import os
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import httpx

JACOB_CHAT_ID = os.getenv("JACOB_CHAT_ID", "")
SELF_URL = os.getenv("SELF_URL", "http://localhost:8000")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "https://belmont-ops-production.up.railway.app")
MCP_SERVER_SECRET = os.getenv("MCP_SERVER_SECRET", "")

# ── Helpers ───────────────────────────────────────────────────────────────────

async def send_telegram(text: str):
    if not TELEGRAM_TOKEN or not JACOB_CHAT_ID:
        return
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    async with httpx.AsyncClient(timeout=15) as client:
        for chunk in chunks:
            try:
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json={"chat_id": JACOB_CHAT_ID, "text": chunk, "parse_mode": "HTML"}
                )
            except Exception as e:
                print(f"[scheduler] Telegram send error: {e}")


async def call_mcp(client: httpx.AsyncClient, tool: str, params: dict = {}) -> dict:
    try:
        resp = await client.post(
            f"{MCP_SERVER_URL}/mcp/execute",
            json={"tool": tool, "params": params},
            headers={"x-mcp-secret": MCP_SERVER_SECRET, "content-type": "application/json"},
            timeout=20.0
        )
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


async def trigger_agent_task(message: str):
    """Trigger a task on the Telegram handler as if Jacob sent it."""
    if not JACOB_CHAT_ID:
        return
    async with httpx.AsyncClient(timeout=120) as client:
        payload = {
            "message": {
                "chat": {"id": int(JACOB_CHAT_ID)},
                "text": message
            }
        }
        try:
            await client.post(f"{SELF_URL}/webhook", json=payload)
        except Exception as e:
            print(f"[scheduler] trigger_agent_task error: {e}")


# ── MORNING BRIEF ─────────────────────────────────────────────────────────────

async def morning_brief():
    """Daily 7:00 AM Mountain — full briefing via MCP /briefing endpoint."""
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
                print(f"[scheduler] Briefing endpoint {resp.status_code} — falling back to agent")
                await trigger_agent_task(
                    "Morning brief: active jobs status, overdue invoices, urgent items today. "
                    "Facts and actions only."
                )
    except Exception as e:
        print(f"[scheduler] Morning brief error: {e}")


# ── ESTIMATE FOLLOW-UP ENGINE ─────────────────────────────────────────────────

async def estimate_followup_check():
    """Daily 9:00 AM — flag stale estimates and prompt follow-ups."""
    from datetime import datetime
    async with httpx.AsyncClient() as client:
        resp = await call_mcp(client, "jobtread_get_estimates", {})

    nodes = (
        resp.get("organization", {})
        .get("documents", {})
        .get("nodes", [])
    )
    if not nodes:
        return

    now = datetime.now()
    stale = []
    for e in nodes:
        status = str(e.get("status", "")).lower()
        if status in ("accepted", "declined", "expired", "invoiced", "closed"):
            continue
        created = e.get("createdAt", "")
        if not created:
            continue
        try:
            age = (now - datetime.fromisoformat(created[:10])).days
            if age >= 7:
                name = e.get("name") or "Untitled"
                job = (e.get("job") or {}).get("name", "")
                val = float(e.get("price", 0) or 0)
                label = f"{job} / {name}" if job else name
                stale.append((label, val, age))
        except Exception:
            pass

    if not stale:
        return

    lines = [f"<b>Estimates needing follow-up ({len(stale)}):</b>\n"]
    for label, val, age in sorted(stale, key=lambda x: -x[2])[:8]:
        lines.append(f"  {age}d — {label} (${val:,.0f})")

    total = sum(v for _, v, _ in stale)
    lines.append(f"\n<b>${total:,.0f} sitting idle.</b>")
    lines.append("\nReply 'follow up estimates' and I'll draft messages for each one.")

    await send_telegram("\n".join(lines))


# ── MARGIN GUARDIAN ───────────────────────────────────────────────────────────

async def margin_guardian():
    """Monday 8:30 AM — check all active jobs for budget health."""
    async with httpx.AsyncClient() as client:
        jobs_resp = await call_mcp(client, "jobtread_list_jobs", {"status": "active"})

    nodes = (
        jobs_resp.get("organization", {})
        .get("jobs", {})
        .get("nodes", [])
    )
    if not nodes:
        return

    flagged = []
    async with httpx.AsyncClient() as client:
        for job in nodes[:15]:  # cap to avoid timeout
            job_id = job.get("id")
            name = job.get("name") or f"Job {job.get('number', '')}"
            if not job_id:
                continue
            try:
                detail = await call_mcp(client, "jobtread_budget_vs_actual", {"job_id": job_id})
                docs = (
                    detail.get("job", {})
                    .get("documents", {})
                    .get("nodes", [])
                )
                for doc in docs:
                    price = float(doc.get("price", 0) or 0)
                    cost = float(doc.get("cost", 0) or 0)
                    if price > 0:
                        margin_pct = ((price - cost) / price) * 100
                        if margin_pct < 25:  # flag below 25% gross margin
                            flagged.append((name, margin_pct, price))
            except Exception:
                pass

    if not flagged:
        await send_telegram("<b>Margin Guardian:</b> All active jobs above 25% gross margin. Clean.")
        return

    lines = [f"<b>⚠️ Margin Guardian — {len(flagged)} job(s) below 25%:</b>\n"]
    for name, pct, val in sorted(flagged, key=lambda x: x[1]):
        lines.append(f"  {name}: {pct:.1f}% margin (${val:,.0f} contract)")
    lines.append("\nReply 'margin fix [job name]' to get a recovery plan.")
    await send_telegram("\n".join(lines))


# ── WEEKLY JOB REVIEW ─────────────────────────────────────────────────────────

async def weekly_job_review():
    """Monday 8:00 AM — full job review via agent."""
    await trigger_agent_task(
        "Weekly project review for all active Belmont jobs. "
        "For each job: status, budget vs actual, any risk flags, next milestone. "
        "Rank by urgency. Be direct."
    )


# ── OVERDUE INVOICE ALERT ─────────────────────────────────────────────────────

async def overdue_invoice_alert():
    """Wednesday 9:00 AM — overdue invoice report + collection drafts."""
    await trigger_agent_task(
        "Pull all overdue invoices from QBO. "
        "For each one past 30 days, draft a follow-up message I can send. "
        "Flag anything past 60 days as priority. "
        "Give me total outstanding and a list with days overdue."
    )


# ── FRIDAY CASH SUMMARY ───────────────────────────────────────────────────────

async def friday_cash_summary():
    """Friday 4:00 PM — end-of-week cash wrap."""
    await trigger_agent_task(
        "End of week cash summary: total receivables outstanding, "
        "what came in this week, bills due next week, net cash position. "
        "Anything to action before Monday?"
    )


# ── FRIDAY DEBRIEF ────────────────────────────────────────────────────────────

async def friday_debrief():
    """Friday 5:00 PM — weekly reflection prompts."""
    msg = (
        "<b>Weekly Debrief</b>\n\n"
        "1. What moved the needle this week?\n"
        "2. What's the one thing that would make next week a win?\n"
        "3. What needs to happen first Monday morning?\n\n"
        "<i>I'll remember your answers.</i>"
    )
    await send_telegram(msg)


# ── SUNDAY NIGHT RECAP ────────────────────────────────────────────────────────

async def sunday_recap():
    """Sunday 8:00 PM Mountain — pre-week snapshot so Monday starts sharp."""
    from datetime import datetime
    async with httpx.AsyncClient() as client:
        jobs_resp = await call_mcp(client, "jobtread_list_jobs", {"status": "active"})
        estimates_resp = await call_mcp(client, "jobtread_get_estimates", {})
        invoices_resp = await call_mcp(client, "qbo_get_invoices", {"status": "unpaid"})

    # Jobs
    job_nodes = (
        jobs_resp.get("organization", {})
        .get("jobs", {})
        .get("nodes", [])
    )
    active_count = len([j for j in job_nodes if not j.get("closedOn")])

    # Pipeline
    est_nodes = (
        estimates_resp.get("organization", {})
        .get("documents", {})
        .get("nodes", [])
    )
    open_ests = [
        e for e in est_nodes
        if str(e.get("status", "")).lower()
        not in ("accepted", "declined", "expired", "invoiced", "closed")
    ]
    pipeline = sum(float(e.get("price", 0) or 0) for e in open_ests)

    # Receivables
    inv_list = (
        invoices_resp.get("QueryResponse", {})
        .get("Invoice", [])
    )
    ar_total = sum(float(i.get("Balance", 0) or 0) for i in inv_list)

    lines = [
        "<b>Sunday Recap — Week Ahead</b>\n",
        f"Active jobs: <b>{active_count}</b>",
        f"Open pipeline: <b>${pipeline:,.0f}</b> ({len(open_ests)} estimates)",
        f"Money owed to you: <b>${ar_total:,.0f}</b>",
        "",
        "First thing Monday: check your calendar, reply to any stale estimates.",
        "<i>Week starts in the morning. Enjoy the rest of tonight.</i>"
    ]
    await send_telegram("\n".join(lines))


# ── META AD PERFORMANCE ALERT ─────────────────────────────────────────────────

async def meta_performance_check():
    """Tuesday 9:00 AM — weekly Meta ad performance summary with flags."""
    async with httpx.AsyncClient() as client:
        resp = await call_mcp(client, "meta_get_ad_insights", {
            "level": "campaign",
            "date_preset": "last_7d"
        })

    campaigns = resp.get("data", [])
    if not campaigns:
        return

    total_spend = sum(float(c.get("spend", 0) or 0) for c in campaigns)
    total_clicks = sum(int(c.get("clicks", 0) or 0) for c in campaigns)
    total_impressions = sum(int(c.get("impressions", 0) or 0) for c in campaigns)

    ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0
    cpc = (total_spend / total_clicks) if total_clicks > 0 else 0

    flags = []
    if ctr < 0.5:
        flags.append(f"CTR is low ({ctr:.2f}%) — creative may be fatigued")
    if cpc > 5.0:
        flags.append(f"CPC is high (${cpc:.2f}) — audience or bid needs review")

    lines = [
        "<b>Meta Ads — Last 7 Days</b>\n",
        f"Spend: <b>${total_spend:,.2f}</b>",
        f"Impressions: <b>{total_impressions:,}</b>",
        f"Clicks: <b>{total_clicks:,}</b>",
        f"CTR: <b>{ctr:.2f}%</b>  |  CPC: <b>${cpc:.2f}</b>",
    ]

    if flags:
        lines.append("\n<b>Flags:</b>")
        for f in flags:
            lines.append(f"  ⚠️ {f}")
        lines.append("\nReply '/ads' for full breakdown or 'fix my ads' for recommendations.")

    await send_telegram("\n".join(lines))


# ── EXIT METRIC TRACKER ───────────────────────────────────────────────────────

async def exit_tracker():
    """1st of each month — track progress toward TopTick exit."""
    async with httpx.AsyncClient() as client:
        pl_resp = await call_mcp(client, "qbo_get_profit_loss", {"period": "this_month"})

    # Try to extract net income from QBO P&L
    # QBO P&L structure varies — safe fallback
    net_income = None
    try:
        rows = pl_resp.get("Rows", {}).get("Row", [])
        for row in rows:
            if "NetIncome" in str(row) or "Net Income" in str(row):
                cols = row.get("ColData", [])
                for c in cols:
                    val = c.get("value", "")
                    if val and val not in ("", "0"):
                        try:
                            net_income = float(val)
                            break
                        except Exception:
                            pass
    except Exception:
        pass

    # Target: $8,000/month net for 6 consecutive months = exit trigger
    TARGET = 8000
    lines = ["<b>Exit Tracker</b>\n"]

    if net_income is not None:
        pct = min(100, (net_income / TARGET) * 100)
        bar_filled = int(pct / 10)
        bar = "█" * bar_filled + "░" * (10 - bar_filled)
        status = "ON TRACK" if net_income >= TARGET else "NOT YET"
        lines += [
            f"This month: <b>${net_income:,.0f}</b> net",
            f"Target: ${TARGET:,.0f}/month",
            f"[{bar}] {pct:.0f}% — <b>{status}</b>",
        ]
        if net_income >= TARGET:
            lines.append("\nOne more month like this and you're closer to the door.")
        else:
            gap = TARGET - net_income
            lines.append(f"\n${gap:,.0f} gap to target. What's the next lever?")
    else:
        lines.append("QBO data unavailable this month — connect production credentials.")

    lines.append("\n<i>Exit condition: $8K net/month for 6 months with buffer.</i>")
    await send_telegram("\n".join(lines))


# ── START ─────────────────────────────────────────────────────────────────────

def start_scheduler():
    scheduler = AsyncIOScheduler(timezone="America/Edmonton")

    # Daily 7 AM — morning brief (M-F)
    scheduler.add_job(morning_brief, CronTrigger(hour=7, minute=0, day_of_week="mon-fri"))

    # Daily 9 AM — estimate follow-up check (M-F)
    scheduler.add_job(estimate_followup_check, CronTrigger(hour=9, minute=0, day_of_week="mon-fri"))

    # Monday 8 AM — weekly job review
    scheduler.add_job(weekly_job_review, CronTrigger(hour=8, minute=0, day_of_week="mon"))

    # Monday 8:30 AM — margin guardian
    scheduler.add_job(margin_guardian, CronTrigger(hour=8, minute=30, day_of_week="mon"))

    # Tuesday 9 AM — Meta ad performance
    scheduler.add_job(meta_performance_check, CronTrigger(hour=9, minute=0, day_of_week="tue"))

    # Wednesday 9 AM — overdue invoice alert
    scheduler.add_job(overdue_invoice_alert, CronTrigger(hour=9, minute=0, day_of_week="wed"))

    # Friday 4 PM — cash summary
    scheduler.add_job(friday_cash_summary, CronTrigger(hour=16, minute=0, day_of_week="fri"))

    # Friday 5 PM — debrief questions
    scheduler.add_job(friday_debrief, CronTrigger(hour=17, minute=0, day_of_week="fri"))

    # Sunday 8 PM — pre-week recap
    scheduler.add_job(sunday_recap, CronTrigger(hour=20, minute=0, day_of_week="sun"))

    # 1st of each month 7 AM — exit tracker
    scheduler.add_job(exit_tracker, CronTrigger(day=1, hour=7, minute=0))

    scheduler.start()
    print(
        "Scheduler started: morning brief (M-F 7am), estimate follow-up (M-F 9am), "
        "margin guardian (Mon 8:30am), Meta check (Tue 9am), invoice alert (Wed 9am), "
        "cash summary (Fri 4pm), debrief (Fri 5pm), Sunday recap (Sun 8pm), "
        "exit tracker (1st of month)"
    )
    return scheduler

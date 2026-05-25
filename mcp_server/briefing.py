"""
BELMONT OPS - MORNING BRIEFING ENGINE
Generates daily briefing by calling MCP tools directly.
Pushes result to Jacob via Telegram.
"""

import asyncio
import httpx
import os
from datetime import datetime, timezone

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
JACOB_CHAT_ID = os.environ.get("JACOB_CHAT_ID", "")
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "https://belmont-ops-production.up.railway.app")
MCP_SECRET = os.environ.get("MCP_SERVER_SECRET", "")


async def call_tool(client: httpx.AsyncClient, tool: str, params: dict = {}) -> dict:
    try:
        resp = await client.post(
            f"{MCP_SERVER_URL}/mcp/execute",
            json={"tool": tool, "params": params},
            headers={"x-mcp-secret": MCP_SECRET, "content-type": "application/json"},
            timeout=20.0
        )
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


async def send_telegram(client: httpx.AsyncClient, message: str):
    if not TELEGRAM_TOKEN or not JACOB_CHAT_ID:
        print("[briefing] TELEGRAM_TOKEN or JACOB_CHAT_ID not set — cannot send")
        return
    chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
    for chunk in chunks:
        try:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": JACOB_CHAT_ID, "text": chunk, "parse_mode": "Markdown"},
                timeout=10.0
            )
        except Exception as e:
            print(f"[briefing] Telegram send error: {e}")


async def generate_briefing() -> str:
    today_str = datetime.now().strftime("%A, %B %d")
    lines = [f"*Belmont Ops — {today_str}*\n"]

    async with httpx.AsyncClient() as client:

        # ── SCHEDULE ──────────────────────────────────────────────────────────
        cal = await call_tool(client, "google_calendar_today", {})
        if "error" not in cal and cal.get("events"):
            events = cal["events"]
            lines.append("*Today's Schedule:*")
            for e in events:
                start = e.get("start", "")
                if "T" in str(start):
                    try:
                        from datetime import datetime as dt
                        t = dt.fromisoformat(start.replace("Z", "+00:00"))
                        mst_hour = (t.hour - 7) % 24
                        am_pm = "AM" if mst_hour < 12 else "PM"
                        display_hour = mst_hour % 12 or 12
                        time_str = f"{display_hour}:{t.minute:02d} {am_pm}"
                    except Exception:
                        time_str = str(start)[:16]
                else:
                    time_str = "All day"
                lines.append(f"  {time_str} — {e.get('title', 'No title')}")
        else:
            lines.append("*Schedule:* Calendar not connected yet.")

        lines.append("")

        # ── OPEN ESTIMATES ────────────────────────────────────────────────────
        estimates_resp = await call_tool(client, "jobtread_get_estimates", {})
        open_ests = []
        expiring_ests = []

        if "error" not in estimates_resp:
            nodes = (
                estimates_resp
                .get("organization", {})
                .get("documents", {})
                .get("nodes", [])
            )
            from datetime import datetime as dt
            now = dt.now()
            for e in nodes:
                status = str(e.get("status", "")).lower()
                if status not in ("accepted", "declined", "expired", "invoiced", "closed"):
                    open_ests.append(e)
                    created = e.get("createdAt", "")
                    if created:
                        try:
                            created_dt = dt.fromisoformat(created[:10])
                            age = (now - created_dt).days
                            if age >= 7:
                                expiring_ests.append((e, age))
                        except Exception:
                            pass

        if open_ests:
            total_pipeline = sum(float(e.get("price", 0) or 0) for e in open_ests)
            lines.append(f"*Open Estimates ({len(open_ests)}) — Pipeline: ${total_pipeline:,.0f}:*")
            for e in open_ests[:6]:
                name = e.get("name") or "Untitled"
                val = float(e.get("price", 0) or 0)
                job_name = (e.get("job") or {}).get("name", "")
                label = f"{job_name} / {name}" if job_name else name
                lines.append(f"  - {label}: ${val:,.0f}")
        else:
            lines.append("*Estimates:* None open.")

        if expiring_ests:
            lines.append("")
            lines.append("*Follow Up Needed (7+ days old):*")
            for e, age in expiring_ests[:3]:
                name = e.get("name") or "Untitled"
                lines.append(f"  ⚠️ {name} — {age} days old")

        lines.append("")

        # ── ACTIVE JOBS ───────────────────────────────────────────────────────
        jobs_resp = await call_tool(client, "jobtread_list_jobs", {"status": "active"})
        if "error" not in jobs_resp:
            nodes = (
                jobs_resp
                .get("organization", {})
                .get("jobs", {})
                .get("nodes", [])
            )
            active = [j for j in nodes if not j.get("closedOn")]
            if active:
                lines.append(f"*Active Jobs ({len(active)}):*")
                for j in active[:5]:
                    name = j.get("name") or "Untitled"
                    number = j.get("number", "")
                    label = f"#{number} {name}" if number else name
                    location = (j.get("location") or {}).get("name", "")
                    lines.append(f"  - {label}" + (f" — {location}" if location else ""))
            else:
                lines.append("*Jobs:* No active jobs right now.")
        else:
            lines.append("*Jobs:* Unavailable.")

        lines.append("")

        # ── MONEY SNAPSHOT ────────────────────────────────────────────────────
        invoices_resp = await call_tool(client, "qbo_get_invoices", {"status": "unpaid"})
        if "error" not in invoices_resp:
            inv_list = (
                invoices_resp
                .get("QueryResponse", {})
                .get("Invoice", [])
            )
            if inv_list:
                from datetime import datetime as dt
                today = dt.now().date()
                total_ar = sum(float(i.get("Balance", 0) or 0) for i in inv_list)
                overdue = [
                    i for i in inv_list
                    if i.get("DueDate") and dt.fromisoformat(i["DueDate"]).date() < today
                ]
                lines.append(f"*Money Owed to Belmont: ${total_ar:,.0f}*")
                if overdue:
                    overdue_total = sum(float(i.get("Balance", 0) or 0) for i in overdue)
                    lines.append(f"  ⚠️ {len(overdue)} overdue — ${overdue_total:,.0f} — collect these")
            else:
                lines.append("*Receivables:* All clear.")
        else:
            lines.append("*Receivables:* QBO not connected yet.")

        lines.append("")

        # ── WEATHER (Red Deer) ────────────────────────────────────────────────
        weather = await call_tool(client, "weather_red_deer_forecast", {"days": 3})
        if "error" not in weather and weather.get("forecast"):
            f0 = weather["forecast"][0]
            lines.append(
                f"*Today's Weather:* {f0.get('condition', '?')}, "
                f"{f0.get('low_c', '?')}-{f0.get('high_c', '?')}C, "
                f"{f0.get('precip_chance_pct', 0)}% precip"
            )
            risk_flags = weather.get("outdoor_risk_flags", [])
            if risk_flags:
                lines.append("*Outdoor Work Risk:*")
                for r in risk_flags[:3]:
                    lines.append(f"  ⚠️ {r}")
            lines.append("")

        # ── URGENT EMAIL ──────────────────────────────────────────────────────
        email = await call_tool(client, "gmail_urgent", {"max_results": 3})
        if "error" not in email and email.get("emails"):
            msgs = email["emails"]
            lines.append(f"*Unread Emails ({email.get('unread_count', len(msgs))}):*")
            for m in msgs[:3]:
                sender = m["from"].split("<")[0].strip()
                lines.append(f"  - {sender}: {m['subject']}")
        else:
            lines.append("*Email:* Gmail not connected yet.")

        lines.append("")
        lines.append("_Reply with a command or question. /help for options._")

    return "\n".join(lines)


async def main():
    async with httpx.AsyncClient() as client:
        msg = await generate_briefing()
        await send_telegram(client, msg)
    return msg


if __name__ == "__main__":
    asyncio.run(main())

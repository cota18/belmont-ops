"""
BELMONT OPS - MCP TOOL SERVER
Exposes JobTread, QBO, and Meta as MCP-compatible tools.
25 tools: 9 JobTread, 8 QBO, 8 Meta (page + ads manager).
Auth: x-mcp-secret header. JobTread: grantKey in query body.
"""

import os
import json
import httpx
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Belmont MCP Server")


@app.on_event("startup")
async def validate_env_on_startup():
    """Log presence/absence of required env vars on boot for quick Railway log inspection."""
    required = {
        "JOBTREAD_API_KEY": "JobTread tools (9 tools)",
        "META_ACCESS_TOKEN": "Meta ads tools (5 tools)",
        "META_AD_ACCOUNT_ID": "Meta ads queries",
        "MCP_SERVER_SECRET": "MCP authentication",
    }
    optional = {
        "QBO_ACCESS_TOKEN": "QBO tools (8 tools) — needs OAuth",
        "QBO_REFRESH_TOKEN": "QBO auto-refresh",
        "QBO_REALM_ID": "QBO company ID",
        "QBO_CLIENT_ID": "QBO app",
        "QBO_CLIENT_SECRET": "QBO app",
        "META_PAGE_TOKEN": "Meta page tools (3 tools)",
        "META_PAGE_ID": "Meta page tools",
        "GOOGLE_CLIENT_ID": "Google Calendar + Gmail",
        "GOOGLE_CLIENT_SECRET": "Google Calendar + Gmail",
        "GOOGLE_REFRESH_TOKEN": "Google Calendar + Gmail (also accepts GMAIL_TOKEN or GOOGLE_CALENDAR_TOKEN)",
        "GOOGLE_ACCESS_TOKEN": "Google current access token (auto-refreshed)",
        "TELEGRAM_TOKEN": "Briefing push",
        "JACOB_CHAT_ID": "Briefing push",
    }
    print("=" * 60)
    print("BELMONT MCP SERVER — STARTUP VALIDATION")
    print("=" * 60)
    missing_required = []
    for var, purpose in required.items():
        present = bool(os.getenv(var, "").strip())
        status = "OK " if present else "XX "
        print(f"{status} {var}: {purpose}")
        if not present:
            missing_required.append(var)
    print("-" * 60)
    print("Optional integrations:")
    for var, purpose in optional.items():
        v = os.getenv(var, "").strip()
        if v and v not in ("PENDING", "SANDBOX_PENDING"):
            print(f"OK  {var}: {purpose}")
        else:
            print(f"-- {var}: {purpose} (not configured)")
    print("=" * 60)
    if missing_required:
        print(f"WARNING: {len(missing_required)} REQUIRED env var(s) missing — tools will fail")
    else:
        print("All REQUIRED env vars set — core tools operational")
    print("=" * 60)

JOBTREAD_KEY = os.getenv("JOBTREAD_API_KEY")
QBO_TOKEN = os.getenv("QBO_ACCESS_TOKEN")
QBO_REALM = os.getenv("QBO_REALM_ID")
QBO_CLIENT_ID = os.getenv("QBO_CLIENT_ID")
QBO_CLIENT_SECRET = os.getenv("QBO_CLIENT_SECRET")
QBO_REFRESH_TOKEN = os.getenv("QBO_REFRESH_TOKEN")
META_TOKEN = os.getenv("META_ACCESS_TOKEN")
META_PAGE_TOKEN = os.getenv("META_PAGE_TOKEN", "")  # Page Access Token — separate from ads user token
META_PAGE_ID = os.getenv("META_PAGE_ID")
META_AD_ACCOUNT = os.getenv("META_AD_ACCOUNT_ID")
MCP_SECRET = os.getenv("MCP_SERVER_SECRET", "")

# ─────────────────────────────────────────────
# MCP PROTOCOL ENDPOINTS
# ─────────────────────────────────────────────

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
JACOB_CHAT_ID = os.getenv("JACOB_CHAT_ID", "")


@app.get("/")
async def health():
    return {"status": "Belmont MCP Server online", "tools": 31}


@app.get("/diagnostic")
async def diagnostic():
    """
    Full integration health report. Probes every external service.
    Returns red/green per integration with actionable next steps.
    Hit this URL anytime to see exactly what's working and what's not.
    """
    report = {
        "timestamp": "",
        "integrations": {},
        "summary": {"green": 0, "yellow": 0, "red": 0}
    }
    from datetime import datetime
    report["timestamp"] = datetime.utcnow().isoformat() + "Z"

    def mark(name: str, status: str, detail: str, fix: str = ""):
        report["integrations"][name] = {"status": status, "detail": detail, "fix": fix}
        if status == "green":
            report["summary"]["green"] += 1
        elif status == "yellow":
            report["summary"]["yellow"] += 1
        else:
            report["summary"]["red"] += 1

    # ── JOBTREAD ─────────────────────────────────────────────────────────
    if not JOBTREAD_KEY:
        mark("jobtread", "red", "JOBTREAD_API_KEY not set", "Add grant key from JobTread account settings")
    else:
        try:
            test = await jobtread_query({"currentGrant": {"user": {"id": {}, "name": {}}}})
            if "error" in test or not test.get("currentGrant"):
                mark("jobtread", "red", f"API call failed: {test.get('error', 'no data')}", "Re-check grant key in JobTread")
            else:
                user = test.get("currentGrant", {}).get("user", {})
                mark("jobtread", "green", f"Connected as {user.get('name', 'unknown')}")
        except Exception as e:
            mark("jobtread", "red", f"Exception: {e}", "Re-check grant key in JobTread")

    # ── QBO ───────────────────────────────────────────────────────────────
    qbo_token = os.getenv("QBO_ACCESS_TOKEN", "")
    qbo_refresh = os.getenv("QBO_REFRESH_TOKEN", "")
    qbo_realm = os.getenv("QBO_REALM_ID", "")
    qbo_cid = os.getenv("QBO_CLIENT_ID", "")
    qbo_cs = os.getenv("QBO_CLIENT_SECRET", "")

    if not (qbo_cid and qbo_cs):
        mark("qbo", "red", "QBO_CLIENT_ID or QBO_CLIENT_SECRET missing",
             "Get from developer.intuit.com app credentials")
    elif not (qbo_token and qbo_refresh and qbo_realm):
        mark("qbo", "red", "QBO tokens not set — needs OAuth flow",
             "Run OAuth Playground: developer.intuit.com/app/developer/playground")
    elif qbo_token in ("PENDING", "SANDBOX_PENDING"):
        mark("qbo", "red", "QBO_ACCESS_TOKEN is placeholder",
             "Run OAuth Playground to get real tokens")
    else:
        try:
            test = await qbo_request("GET", "companyinfo/" + qbo_realm)
            ci = test.get("CompanyInfo", {})
            mark("qbo", "green", f"Connected to {ci.get('CompanyName', 'company')} (realm {qbo_realm[:8]}...)")
        except Exception as e:
            err = str(e)[:120]
            mark("qbo", "yellow", f"Token issue: {err}", "Run qbo_refresh_token tool or redo OAuth")

    # ── META ADS ──────────────────────────────────────────────────────────
    if not META_TOKEN:
        mark("meta_ads", "red", "META_ACCESS_TOKEN not set", "Get from developers.facebook.com/tools/explorer")
    elif not META_AD_ACCOUNT:
        mark("meta_ads", "yellow", "Token set but META_AD_ACCOUNT_ID missing",
             "Get ad account ID from business.facebook.com")
    else:
        try:
            test = await meta_request(
                f"act_{META_AD_ACCOUNT}",
                params={"fields": "name,account_status,currency"}
            )
            mark("meta_ads", "green", f"Connected to {test.get('name', 'account')}, {test.get('currency', '?')}")
        except Exception as e:
            mark("meta_ads", "red", f"API call failed: {str(e)[:120]}",
                 "Token may be expired — regenerate at Graph Explorer")

    # ── META PAGE ─────────────────────────────────────────────────────────
    if not META_PAGE_TOKEN:
        mark("meta_page", "red", "META_PAGE_TOKEN not set",
             "Graph Explorer: generate token with pages_read_engagement + pages_manage_posts + pages_read_user_content")
    elif not META_PAGE_ID:
        mark("meta_page", "yellow", "Page token set but META_PAGE_ID missing", "Get from page settings")
    else:
        try:
            test = await meta_request(f"{META_PAGE_ID}", params={"fields": "name,fan_count"}, use_page_token=True)
            mark("meta_page", "green", f"Connected to page '{test.get('name', '?')}'")
        except Exception as e:
            mark("meta_page", "red", f"Page API failed: {str(e)[:120]}",
                 "Re-generate page token with full permissions")

    # ── GOOGLE ────────────────────────────────────────────────────────────
    g_cid = os.getenv("GOOGLE_CLIENT_ID", "")
    g_cs = os.getenv("GOOGLE_CLIENT_SECRET", "")
    # Accept any of these var names for the refresh token
    g_refresh = (
        os.getenv("GOOGLE_REFRESH_TOKEN", "") or
        os.getenv("GMAIL_TOKEN", "") or
        os.getenv("GOOGLE_CALENDAR_TOKEN", "")
    )

    if not (g_cid and g_cs):
        mark("google", "red", "GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET not set",
             "Create OAuth credentials at console.cloud.google.com")
    elif not g_refresh or g_refresh in ("PENDING", ""):
        mark("google", "yellow", "No Google refresh token set",
             "Set GOOGLE_REFRESH_TOKEN (or GMAIL_TOKEN / GOOGLE_CALENDAR_TOKEN) on Railway")
    else:
        try:
            test = await execute_google("google_calendar_today", {})
            if "error" in test:
                mark("google", "yellow", f"Token present but Calendar call failed: {test['error'][:80]}",
                     "Re-run scripts/google_oauth.js to refresh tokens")
            else:
                mark("google", "green", f"Calendar connected — {test.get('count', 0)} events today")
        except Exception as eg:
            mark("google", "yellow", f"Token present, validation error: {str(eg)[:80]}", "")

    # ── TELEGRAM ──────────────────────────────────────────────────────────
    tg_token = os.getenv("TELEGRAM_TOKEN", "")
    tg_chat = os.getenv("JACOB_CHAT_ID", "")
    if not tg_token:
        mark("telegram", "red", "TELEGRAM_TOKEN not set on MCP server",
             "Only needed for /briefing push — agent itself works without")
    elif not tg_chat:
        mark("telegram", "yellow", "JACOB_CHAT_ID not set on MCP server",
             "Briefing endpoint cannot deliver")
    else:
        mark("telegram", "green", f"Token + chat ID present (chat {tg_chat})")

    # ── WEATHER (no auth required) ────────────────────────────────────────
    try:
        w = await execute_weather({"days": 1})
        if w.get("forecast"):
            mark("weather", "green", "open-meteo responding")
        else:
            mark("weather", "yellow", "Unexpected response", "")
    except Exception as e:
        mark("weather", "red", f"Failed: {e}", "Check Railway outbound network")

    # Total tool count + final summary
    report["total_tools_registered"] = 31
    report["service"] = "mcp_server"
    s = report["summary"]
    report["overall"] = (
        "ALL GREEN" if s["red"] == 0 and s["yellow"] == 0
        else f"{s['red']} broken, {s['yellow']} partial, {s['green']} working"
    )

    return report


@app.get("/mcp/tools")
async def list_tools():
    """Returns the full tool manifest for Claude Managed Agents."""
    return {
        "tools": [
            # ── JOBTREAD ──────────────────────────────────────────
            {
                "name": "jobtread_list_jobs",
                "description": "List all jobs in JobTread with inferred pipeline stage. Each job includes a '_stage' field: 'New Lead' (no estimates yet), 'Estimating' (draft/sent estimate), 'Construction / In Progress' (approved estimate), or 'Closed'. Use this to sort jobs by pipeline column. Filter by status: active (open jobs), completed (closed), all.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["active", "completed", "all"], "default": "active"}
                    }
                }
            },
            {
                "name": "jobtread_get_job_details",
                "description": "Get full details for a specific job: budget, expenses, progress, contacts, notes, line items.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "job_id": {"type": "string", "description": "JobTread job ID"}
                    },
                    "required": ["job_id"]
                }
            },
            {
                "name": "jobtread_get_estimates",
                "description": "Get all estimates for a job or list all open estimates.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "job_id": {"type": "string", "description": "Optional: filter by job"},
                        "status": {"type": "string", "enum": ["draft", "sent", "approved", "all"], "default": "all"}
                    }
                }
            },
            {
                "name": "jobtread_create_job",
                "description": "Create a new job in JobTread.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "customer_name": {"type": "string"},
                        "customer_email": {"type": "string"},
                        "customer_phone": {"type": "string"},
                        "address": {"type": "string"},
                        "description": {"type": "string"},
                        "estimated_value": {"type": "number"}
                    },
                    "required": ["name", "customer_name"]
                }
            },
            {
                "name": "jobtread_add_note",
                "description": "Add a note or update to a job in JobTread.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "job_id": {"type": "string"},
                        "note": {"type": "string"}
                    },
                    "required": ["job_id", "note"]
                }
            },
            {
                "name": "jobtread_get_contacts",
                "description": "Search contacts/customers in JobTread by name, email, or phone.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "search": {"type": "string", "description": "Name, email, or phone to search"}
                    }
                }
            },
            {
                "name": "jobtread_get_expenses",
                "description": "Get expenses and costs for a job or across all active jobs.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "job_id": {"type": "string", "description": "Optional: specific job"}
                    }
                }
            },
            {
                "name": "jobtread_budget_vs_actual",
                "description": "Compare budget vs actual costs for a job. Returns over/under budget status and variance by category.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "job_id": {"type": "string"}
                    },
                    "required": ["job_id"]
                }
            },
            {
                "name": "jobtread_close_job",
                "description": "Mark a job as complete in JobTread.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "job_id": {"type": "string"},
                        "completion_notes": {"type": "string"}
                    },
                    "required": ["job_id"]
                }
            },
            # ── QUICKBOOKS ONLINE ────────────────────────────────
            {
                "name": "qbo_get_invoices",
                "description": "Get invoices from QuickBooks Online. Filter by status or customer.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["unpaid", "paid", "overdue", "all"], "default": "all"},
                        "customer_name": {"type": "string", "description": "Optional: filter by customer"},
                        "days_overdue_min": {"type": "integer", "description": "Optional: minimum days overdue"}
                    }
                }
            },
            {
                "name": "qbo_create_invoice",
                "description": "Create a new invoice in QuickBooks Online.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "customer_name": {"type": "string"},
                        "line_items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "description": {"type": "string"},
                                    "amount": {"type": "number"},
                                    "quantity": {"type": "number"}
                                }
                            }
                        },
                        "due_date": {"type": "string", "description": "YYYY-MM-DD"},
                        "memo": {"type": "string"}
                    },
                    "required": ["customer_name", "line_items"]
                }
            },
            {
                "name": "qbo_get_profit_loss",
                "description": "Get Profit and Loss report from QuickBooks Online.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "period": {"type": "string", "enum": ["this_month", "last_month", "this_quarter", "ytd", "last_year"], "default": "this_month"}
                    }
                }
            },
            {
                "name": "qbo_get_cash_flow",
                "description": "Get cash flow statement from QuickBooks Online.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "period": {"type": "string", "enum": ["this_month", "last_month", "this_quarter", "ytd"], "default": "this_month"}
                    }
                }
            },
            {
                "name": "qbo_get_balance_sheet",
                "description": "Get balance sheet from QuickBooks Online.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "as_of": {"type": "string", "description": "Date YYYY-MM-DD, defaults to today"}
                    }
                }
            },
            {
                "name": "qbo_get_customers",
                "description": "Search customers in QuickBooks Online.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "search": {"type": "string"},
                        "active_only": {"type": "boolean", "default": True}
                    }
                }
            },
            {
                "name": "qbo_get_unpaid_bills",
                "description": "Get outstanding bills and accounts payable from QuickBooks Online.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "overdue_only": {"type": "boolean", "default": False}
                    }
                }
            },
            {
                "name": "qbo_refresh_token",
                "description": "Refresh the QuickBooks OAuth token. Call this if QBO API calls are returning 401 errors.",
                "input_schema": {"type": "object", "properties": {}}
            },
            {
                "name": "qbo_create_expense",
                "description": "Record an expense or vendor bill in QuickBooks Online. Use for materials, subcontractors, fuel, tools, any business cost.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "vendor_name": {"type": "string", "description": "Vendor or payee name"},
                        "amount": {"type": "number", "description": "Total expense amount in CAD"},
                        "category": {"type": "string", "description": "Expense account name, e.g. 'Materials', 'Subcontractors', 'Fuel', 'Tools & Equipment'"},
                        "date": {"type": "string", "description": "YYYY-MM-DD, defaults to today"},
                        "memo": {"type": "string", "description": "Description or reference"},
                        "payment_type": {"type": "string", "enum": ["Cash", "Check", "CreditCard"], "default": "CreditCard"}
                    },
                    "required": ["vendor_name", "amount"]
                }
            },
            # ── META BUSINESS SUITE ──────────────────────────────
            {
                "name": "meta_get_page_posts",
                "description": "Get recent posts from the Belmont Facebook/Instagram page.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 10}
                    }
                }
            },
            {
                "name": "meta_get_insights",
                "description": "Get engagement metrics and insights for the Belmont social page.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "period": {"type": "string", "enum": ["day", "week", "days_28", "month"], "default": "week"},
                        "metrics": {
                            "type": "array",
                            "items": {"type": "string"},
                            "default": ["reach", "impressions", "engagement", "followers"]
                        }
                    }
                }
            },
            {
                "name": "meta_create_post",
                "description": "Create and publish a post to the Belmont Facebook page.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "Post caption/copy"},
                        "scheduled_time": {"type": "string", "description": "Optional: ISO timestamp to schedule post"}
                    },
                    "required": ["message"]
                }
            },
            {
                "name": "meta_get_campaigns",
                "description": "Get all Facebook/Instagram ad campaigns from Meta Ads Manager. Shows spend, status, objective, and performance.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["ACTIVE", "PAUSED", "ALL"], "default": "ALL"}
                    }
                }
            },
            {
                "name": "meta_get_ad_insights",
                "description": "Get ad performance metrics from Meta Ads Manager: spend, impressions, reach, clicks, CPM, CTR, leads generated.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "level": {"type": "string", "enum": ["campaign", "adset", "ad"], "default": "campaign"},
                        "date_preset": {"type": "string", "enum": ["today", "yesterday", "last_7d", "last_30d", "this_month", "last_month"], "default": "last_30d"}
                    }
                }
            },
            {
                "name": "meta_create_campaign",
                "description": "Create a new Facebook/Instagram ad campaign in Meta Ads Manager.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Campaign name"},
                        "objective": {"type": "string", "enum": ["LEAD_GENERATION", "BRAND_AWARENESS", "REACH", "TRAFFIC", "CONVERSIONS"], "default": "LEAD_GENERATION"},
                        "daily_budget": {"type": "number", "description": "Daily budget in cents (e.g. 2000 = $20.00 CAD)"},
                        "status": {"type": "string", "enum": ["ACTIVE", "PAUSED"], "default": "PAUSED"}
                    },
                    "required": ["name", "daily_budget"]
                }
            },
            {
                "name": "meta_get_ad_account_info",
                "description": "Get the Belmont Meta ad account details: balance, spend limits, currency, account status.",
                "input_schema": {"type": "object", "properties": {}}
            },
            # ── GOOGLE ───────────────────────────────────────────────────────
            {
                "name": "google_calendar_today",
                "description": "Get Jacob's Google Calendar events for today (or any date). Returns meetings, appointments, family events, time blocks.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "description": "Date in YYYY-MM-DD format. Defaults to today."}
                    }
                }
            },
            {
                "name": "google_calendar_week",
                "description": "Get Jacob's Google Calendar events for the current week (Mon-Sun). Use for weekly planning and scheduling.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "week_offset": {"type": "integer", "description": "0=this week, 1=next week, -1=last week. Default 0."}
                    }
                }
            },
            {
                "name": "google_calendar_create_event",
                "description": "Create a new event on Jacob's Google Calendar. Use for scheduling site visits, client meetings, supplier calls, crew check-ins.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Event title/summary"},
                        "start_datetime": {"type": "string", "description": "Start time in YYYY-MM-DDTHH:MM format (24hr, Edmonton/Mountain time)"},
                        "end_datetime": {"type": "string", "description": "End time in YYYY-MM-DDTHH:MM format. Defaults to 1hr after start."},
                        "location": {"type": "string", "description": "Address or place name"},
                        "description": {"type": "string", "description": "Event notes or agenda"},
                        "attendee_emails": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional list of email addresses to invite"
                        }
                    },
                    "required": ["title", "start_datetime"]
                }
            },
            {
                "name": "gmail_urgent",
                "description": "Check Gmail for unread messages in the last 48 hours that look important or time-sensitive. Excludes promotions and social. Returns subject, sender, snippet.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "max_results": {"type": "integer", "description": "Max emails to return. Default 5."}
                    }
                }
            },
            {
                "name": "gmail_send",
                "description": "Send an email from Jacob's Gmail account. Use for client follow-ups, sending estimates, scheduling confirmation, supplier orders.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string", "description": "Recipient email address"},
                        "subject": {"type": "string", "description": "Email subject line"},
                        "body": {"type": "string", "description": "Email body — plain text or simple HTML"},
                        "cc": {"type": "string", "description": "Optional CC email address"}
                    },
                    "required": ["to", "subject", "body"]
                }
            },
            # ── WEATHER ──────────────────────────────────────────────────────
            {
                "name": "weather_red_deer_forecast",
                "description": "Get the 3-day weather forecast for Red Deer, Alberta. Returns daily high/low temp in Celsius, precipitation, wind, and a plain-English summary. Use to flag outdoor work risks (deck, framing, roofing, concrete) when rain, snow, or high wind is incoming.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "days": {"type": "integer", "description": "Days of forecast (1-7). Default 3."}
                    }
                }
            }
        ]
    }


@app.post("/mcp/execute")
async def execute_tool(request: Request, x_mcp_secret: str = Header(None)):
    """Execute a tool call from Claude Managed Agents."""
    if MCP_SECRET and x_mcp_secret != MCP_SECRET:
        raise HTTPException(status_code=401, detail="Invalid MCP secret")

    body = await request.json()
    tool_name = body.get("tool")
    params = body.get("params", {})

    try:
        if tool_name.startswith("jobtread_"):
            result = await execute_jobtread(tool_name, params)
        elif tool_name.startswith("qbo_"):
            result = await execute_qbo(tool_name, params)
        elif tool_name.startswith("meta_"):
            result = await execute_meta(tool_name, params)
        elif tool_name in ("google_calendar_today", "google_calendar_week",
                           "google_calendar_create_event", "gmail_urgent", "gmail_send"):
            result = await execute_google(tool_name, params)
        elif tool_name == "weather_red_deer_forecast":
            result = await execute_weather(params)
        else:
            result = {"error": f"Unknown tool: {tool_name}"}
    except Exception as e:
        result = {"error": str(e), "tool": tool_name}

    return JSONResponse(content=result)


# ─────────────────────────────────────────────
# JOBTREAD TOOLS
# ─────────────────────────────────────────────

_jobtread_org_id: str = None


async def jobtread_query(query: dict) -> dict:
    """Execute a JobTread Pave API query. Auth via grantKey inside the query body."""
    full_query = {"$": {"grantKey": JOBTREAD_KEY}, **query}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.jobtread.com/pave",
            json={"query": full_query}
        )
        if not resp.is_success:
            return {"error": f"JobTread API {resp.status_code}: {resp.text[:400]}"}
        data = resp.json()
        if isinstance(data, dict) and data.get("errors"):
            return {"error": str(data["errors"])}
        print(f"[jobtread] query OK keys={list(data.keys())}")
        return data


async def get_jobtread_org_id() -> str:
    """Fetch and cache the organization ID from the current grant."""
    global _jobtread_org_id
    if _jobtread_org_id:
        return _jobtread_org_id
    result = await jobtread_query({
        "currentGrant": {
            "user": {
                "memberships": {
                    "nodes": {
                        "organization": {"id": {}, "name": {}}
                    }
                }
            }
        }
    })
    nodes = result.get("currentGrant", {}).get("user", {}).get("memberships", {}).get("nodes", [])
    if nodes:
        _jobtread_org_id = nodes[0]["organization"]["id"]
        print(f"[jobtread] Org ID cached: {_jobtread_org_id}")
        return _jobtread_org_id
    raise Exception(f"Could not determine org ID from JobTread grant. Response: {result}")


async def execute_jobtread(tool: str, params: dict) -> dict:

    if tool == "jobtread_list_jobs":
        org_id = await get_jobtread_org_id()
        status = params.get("status", "active")
        jobs_args: dict = {"size": 50}
        if status == "active":
            jobs_args["where"] = ["closedOn", "=", None]
        elif status == "completed":
            jobs_args["where"] = ["closedOn", "!=", None]
        # "all" gets no filter
        raw = await jobtread_query({
            "organization": {
                "$": {"id": org_id},
                "jobs": {
                    "$": jobs_args,
                    "nodes": {
                        "id": {}, "name": {}, "number": {}, "closedOn": {},
                        "createdAt": {},
                        "location": {
                            "id": {}, "name": {}, "address": {},
                            "account": {"id": {}, "name": {}}
                        },
                        # Fetch recent customer-facing documents to infer pipeline stage
                        "documents": {
                            "$": {"size": 5, "where": ["type", "=", "customerOrder"]},
                            "nodes": {"id": {}, "status": {}, "type": {}, "name": {}}
                        }
                    },
                    "nextPage": {}
                }
            }
        })
        # Annotate each job with an inferred pipeline stage based on document status.
        # JobTread's board columns (New Lead, Estimating, Construction, Closed) are UI-only
        # and not exposed as a queryable API field — so we derive stage from activity.
        try:
            jobs = raw.get("organization", {}).get("jobs", {}).get("nodes", [])
            for job in jobs:
                docs = job.get("documents", {}).get("nodes", []) if job.get("documents") else []
                statuses = [d.get("status", "").lower() for d in docs]
                if job.get("closedOn"):
                    job["_stage"] = "Closed"
                elif any(s in ("approved", "accepted", "invoiced") for s in statuses):
                    job["_stage"] = "Construction / In Progress"
                elif any(s in ("sent", "draft", "pending") for s in statuses):
                    job["_stage"] = "Estimating"
                elif docs:
                    job["_stage"] = "Estimating"
                else:
                    job["_stage"] = "New Lead"
        except Exception:
            pass
        return raw

    elif tool == "jobtread_get_job_details":
        return await jobtread_query({
            "job": {
                "$": {"id": params["job_id"]},
                "id": {}, "name": {}, "number": {}, "description": {},
                "closedOn": {}, "createdAt": {},
                "location": {
                    "id": {}, "name": {}, "address": {},
                    "account": {"id": {}, "name": {}}
                },
                "comments": {
                    "nodes": {"id": {}, "message": {}, "createdAt": {}}
                }
            }
        })

    elif tool == "jobtread_get_estimates":
        org_id = await get_jobtread_org_id()
        docs_filter: dict = {"size": 20, "where": ["type", "=", "customerOrder"]}
        if params.get("job_id"):
            docs_filter["where"] = {
                "and": [
                    ["type", "=", "customerOrder"],
                    [["job", "id"], "=", params["job_id"]]
                ]
            }
        return await jobtread_query({
            "organization": {
                "$": {"id": org_id},
                "documents": {
                    "$": docs_filter,
                    "nodes": {
                        "id": {}, "name": {}, "number": {}, "status": {},
                        "price": {}, "cost": {}, "createdAt": {},
                        "job": {"id": {}, "name": {}}
                    }
                }
            }
        })

    elif tool == "jobtread_create_job":
        org_id = await get_jobtread_org_id()
        customer_name = params.get("customer_name", "New Customer")

        # Step 1: Search for existing customer account
        search = await jobtread_query({
            "organization": {
                "$": {"id": org_id},
                "accounts": {
                    "$": {
                        "size": 5,
                        "where": {
                            "and": [
                                ["name", "=", customer_name],
                                ["type", "=", "customer"]
                            ]
                        }
                    },
                    "nodes": {
                        "id": {}, "name": {},
                        "locations": {
                            "nodes": {"id": {}, "name": {}, "address": {}}
                        }
                    }
                }
            }
        })
        accounts = search.get("organization", {}).get("accounts", {}).get("nodes", [])
        account_id = None
        location_id = None

        if accounts:
            account_id = accounts[0]["id"]
            locs = accounts[0].get("locations", {}).get("nodes", [])
            if locs:
                location_id = locs[0]["id"]
            print(f"[jobtread] Found existing account {account_id}")
        else:
            # Step 2: Create new customer account
            create_acct = await jobtread_query({
                "createAccount": {
                    "$": {"organizationId": org_id, "name": customer_name, "type": "customer"},
                    "createdAccount": {"id": {}, "name": {}}
                }
            })
            acct = create_acct.get("createAccount", {}).get("createdAccount", {})
            if not acct.get("id"):
                return {"error": f"Failed to create customer account: {create_acct}"}
            account_id = acct["id"]
            print(f"[jobtread] Created account {account_id}")

        # Step 3: Create location if none found
        if not location_id:
            loc_name = params.get("address") or f"{customer_name} Location"
            loc_args: dict = {"accountId": account_id, "name": loc_name}
            if params.get("address"):
                loc_args["address"] = params["address"]
                loc_args["parseAddress"] = True
            create_loc = await jobtread_query({
                "createLocation": {
                    "$": loc_args,
                    "createdLocation": {"id": {}, "name": {}, "address": {}}
                }
            })
            loc = create_loc.get("createLocation", {}).get("createdLocation", {})
            if not loc.get("id"):
                return {"error": f"Failed to create location: {create_loc}"}
            location_id = loc["id"]
            print(f"[jobtread] Created location {location_id}")

        # Step 4: Create the job
        job_args: dict = {"locationId": location_id, "name": params["name"]}
        if params.get("description"):
            job_args["description"] = params["description"]
        result = await jobtread_query({
            "createJob": {
                "$": job_args,
                "createdJob": {"id": {}, "name": {}, "number": {}}
            }
        })
        job = result.get("createJob", {}).get("createdJob", {})
        if job.get("id"):
            return {
                "success": True,
                "job_id": job["id"],
                "job_name": job.get("name"),
                "job_number": job.get("number"),
                "customer": customer_name,
                "location_id": location_id
            }
        return {"error": f"createJob response: {result}"}

    elif tool == "jobtread_add_note":
        return await jobtread_query({
            "createComment": {
                "$": {
                    "targetId": params["job_id"],
                    "targetType": "job",
                    "message": params["note"]
                },
                "createdComment": {"id": {}, "message": {}, "createdAt": {}}
            }
        })

    elif tool == "jobtread_get_contacts":
        org_id = await get_jobtread_org_id()
        search = params.get("search", "")
        args: dict = {"size": 20, "where": ["type", "=", "customer"]}
        return await jobtread_query({
            "organization": {
                "$": {"id": org_id},
                "accounts": {
                    "$": args,
                    "nodes": {
                        "id": {}, "name": {}, "type": {},
                        "locations": {
                            "nodes": {"id": {}, "address": {}}
                        }
                    }
                }
            }
        })

    elif tool == "jobtread_get_expenses":
        if params.get("job_id"):
            return await jobtread_query({
                "job": {
                    "$": {"id": params["job_id"]},
                    "documents": {
                        "$": {"where": ["type", "=", "vendorBill"], "size": 50},
                        "nodes": {
                            "id": {}, "name": {}, "number": {}, "status": {},
                            "cost": {}, "createdAt": {}
                        }
                    }
                }
            })
        else:
            org_id = await get_jobtread_org_id()
            return await jobtread_query({
                "organization": {
                    "$": {"id": org_id},
                    "documents": {
                        "$": {"where": ["type", "=", "vendorBill"], "size": 50},
                        "nodes": {
                            "id": {}, "name": {}, "number": {}, "status": {},
                            "cost": {}, "createdAt": {},
                            "job": {"id": {}, "name": {}}
                        }
                    }
                }
            })

    elif tool == "jobtread_budget_vs_actual":
        result = await jobtread_query({
            "job": {
                "$": {"id": params["job_id"]},
                "id": {}, "name": {}, "number": {},
                "documents": {
                    "$": {
                        "where": {
                            "and": [
                                ["type", "=", "customerOrder"],
                                ["status", "=", "approved"]
                            ]
                        },
                        "size": 50
                    },
                    "nodes": {
                        "id": {}, "name": {}, "status": {},
                        "price": {}, "cost": {}, "priceWithTax": {}
                    }
                }
            }
        })
        return result

    elif tool == "jobtread_close_job":
        from datetime import date
        today = date.today().isoformat()
        return await jobtread_query({
            "updateJob": {
                "$": {"id": params["job_id"], "closedOn": today},
                "job": {
                    "$": {"id": params["job_id"]},
                    "id": {}, "name": {}, "closedOn": {}
                }
            }
        })

    return {"error": f"Unhandled JobTread tool: {tool}"}


# ─────────────────────────────────────────────
# QBO TOOLS
# ─────────────────────────────────────────────

async def qbo_request(method: str, endpoint: str, params: dict = None, json_body: dict = None) -> dict:
    """Make a QBO API request. Auto-refreshes token on 401."""
    token = os.getenv("QBO_ACCESS_TOKEN")
    realm = os.getenv("QBO_REALM_ID")
    base = f"https://quickbooks.api.intuit.com/v3/company/{realm}"

    async with httpx.AsyncClient() as client:
        resp = await client.request(
            method,
            f"{base}/{endpoint}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params=params,
            json=json_body,
            timeout=30
        )
        if resp.status_code == 401:
            new_token = await refresh_qbo_token()
            if new_token:
                resp = await client.request(
                    method,
                    f"{base}/{endpoint}",
                    headers={"Authorization": f"Bearer {new_token}", "Accept": "application/json"},
                    params=params,
                    json=json_body,
                    timeout=30
                )
        resp.raise_for_status()
        return resp.json()


async def qbo_query(sql: str) -> dict:
    return await qbo_request("GET", "query", params={"query": sql})


async def _persist_qbo_tokens_to_railway(access_token: str, refresh_token: str):
    """Push new QBO tokens back to Railway so they survive redeploys."""
    railway_token = os.getenv("RAILWAY_TOKEN", "")
    project_id = os.getenv("RAILWAY_PROJECT_ID", "be63e025-0e77-4466-8e36-2e08ad2cf753")
    env_id = os.getenv("RAILWAY_ENV_ID", "d02dce4a-0c67-4766-819d-10eb9be9dc9b")
    service_id = os.getenv("RAILWAY_MCP_SERVICE_ID", "eb2b0794-5cf4-4092-a6ce-756ea1319870")

    if not railway_token:
        print("[QBO persist] RAILWAY_TOKEN not set — tokens saved in memory only (will reset on redeploy)")
        return

    async def upsert(name: str, value: str):
        query = json.dumps({
            "query": f'mutation {{ variableUpsert(input: {{ projectId: "{project_id}", environmentId: "{env_id}", serviceId: "{service_id}", name: "{name}", value: {json.dumps(value)} }}) }}'
        })
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                resp = await c.post(
                    "https://backboard.railway.app/graphql/v2",
                    content=query,
                    headers={
                        "Authorization": f"Bearer {railway_token}",
                        "Content-Type": "application/json"
                    }
                )
                if resp.status_code == 200:
                    print(f"[QBO persist] {name} pushed to Railway ✅")
                else:
                    print(f"[QBO persist] {name} push failed: {resp.status_code} {resp.text[:100]}")
        except Exception as e:
            print(f"[QBO persist] {name} exception: {e}")

    await upsert("QBO_ACCESS_TOKEN", access_token)
    await upsert("QBO_REFRESH_TOKEN", refresh_token)


async def refresh_qbo_token() -> str:
    """Refresh QBO OAuth token using refresh token. Logs errors for diagnosis.
    On success, persists new tokens to Railway so they survive redeploys."""
    import base64
    client_id = os.getenv("QBO_CLIENT_ID", "")
    client_secret = os.getenv("QBO_CLIENT_SECRET", "")
    refresh_token = os.getenv("QBO_REFRESH_TOKEN", "")

    if not all([client_id, client_secret, refresh_token]):
        print(f"[QBO refresh] Missing credentials: client_id={bool(client_id)}, secret={bool(client_secret)}, refresh={bool(refresh_token)}")
        return None

    creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
                headers={
                    "Authorization": f"Basic {creds}",
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token
                }
            )
            print(f"[QBO refresh] Status: {resp.status_code}, body: {resp.text[:300]}")
            if resp.status_code == 200:
                data = resp.json()
                new_access = data["access_token"]
                new_refresh = data.get("refresh_token", refresh_token)
                # Update in-memory immediately
                os.environ["QBO_ACCESS_TOKEN"] = new_access
                os.environ["QBO_REFRESH_TOKEN"] = new_refresh
                print(f"[QBO refresh] Success — new access token obtained")
                # Persist to Railway so tokens survive redeploys
                await _persist_qbo_tokens_to_railway(new_access, new_refresh)
                return new_access
            print(f"[QBO refresh] Failed: {resp.status_code} — {resp.text[:200]}")
    except Exception as e:
        print(f"[QBO refresh] Exception: {e}")
    return None


@app.get("/qbo-refresh")
async def force_qbo_refresh(x_mcp_secret: str = Header(None)):
    """Force a QBO token refresh and return the result for diagnosis."""
    if MCP_SECRET and x_mcp_secret != MCP_SECRET:
        raise HTTPException(status_code=401, detail="Invalid MCP secret")
    new_token = await refresh_qbo_token()
    if new_token:
        # Test it immediately
        test = await qbo_request("GET", "companyinfo/{}".format(os.getenv("QBO_REALM_ID")))
        return {"status": "ok", "token_obtained": True, "test_call": "success" if "error" not in test else test.get("error")}
    return {"status": "failed", "token_obtained": False, "detail": "Check Railway logs for [QBO refresh] lines"}


async def execute_qbo(tool: str, params: dict) -> dict:
    if tool == "qbo_get_invoices":
        status = params.get("status", "all")
        conditions = []
        if status == "unpaid":
            conditions.append("Balance > '0'")
        elif status == "paid":
            conditions.append("Balance = '0'")
        elif status == "overdue":
            conditions.append("Balance > '0' AND DueDate < TODAY")
        if params.get("customer_name"):
            conditions.append(f"CustomerRef IN (SELECT Id FROM Customer WHERE DisplayName LIKE '%{params['customer_name']}%')")
        where = " AND ".join(conditions)
        sql = f"SELECT * FROM Invoice{' WHERE ' + where if where else ''} ORDERBY DueDate ASC MAXRESULTS 50"
        return await qbo_query(sql)

    elif tool == "qbo_create_invoice":
        customer_resp = await qbo_query(
            f"SELECT Id, DisplayName FROM Customer WHERE DisplayName LIKE '%{params['customer_name']}%' MAXRESULTS 1"
        )
        customers = customer_resp.get("QueryResponse", {}).get("Customer", [])
        if not customers:
            return {"error": f"Customer '{params['customer_name']}' not found in QBO"}
        cust_id = customers[0]["Id"]
        line_items = []
        for i, item in enumerate(params.get("line_items", []), 1):
            line_items.append({
                "LineNum": i,
                "Amount": item["amount"] * item.get("quantity", 1),
                "DetailType": "SalesItemLineDetail",
                "Description": item["description"],
                "SalesItemLineDetail": {"Qty": item.get("quantity", 1), "UnitPrice": item["amount"]}
            })
        body = {
            "CustomerRef": {"value": cust_id},
            "Line": line_items
        }
        if params.get("due_date"):
            body["DueDate"] = params["due_date"]
        if params.get("memo"):
            body["CustomerMemo"] = {"value": params["memo"]}
        return await qbo_request("POST", "invoice", json_body=body)

    elif tool == "qbo_get_profit_loss":
        period_map = {
            "this_month": ("This Month-to-date", None, None),
            "last_month": ("Last Month", None, None),
            "this_quarter": ("This Fiscal Quarter-to-date", None, None),
            "ytd": ("This Fiscal Year-to-date", None, None),
            "last_year": ("Last Fiscal Year", None, None)
        }
        p = period_map.get(params.get("period", "this_month"), ("This Month-to-date", None, None))
        return await qbo_request("GET", "reports/ProfitAndLoss",
                                 params={"date_macro": p[0], "accounting_method": "Accrual"})

    elif tool == "qbo_get_cash_flow":
        period_map = {
            "this_month": "This Month-to-date",
            "last_month": "Last Month",
            "this_quarter": "This Fiscal Quarter-to-date",
            "ytd": "This Fiscal Year-to-date"
        }
        return await qbo_request("GET", "reports/CashFlow",
                                 params={"date_macro": period_map.get(params.get("period", "this_month"))})

    elif tool == "qbo_get_balance_sheet":
        qp = {"accounting_method": "Accrual"}
        if params.get("as_of"):
            qp["end_date"] = params["as_of"]
        else:
            qp["date_macro"] = "Today"
        return await qbo_request("GET", "reports/BalanceSheet", params=qp)

    elif tool == "qbo_get_customers":
        search = params.get("search", "")
        active_filter = " AND Active = True" if params.get("active_only", True) else ""
        sql = f"SELECT * FROM Customer WHERE DisplayName LIKE '%{search}%'{active_filter} MAXRESULTS 30"
        return await qbo_query(sql)

    elif tool == "qbo_get_unpaid_bills":
        where = "Balance > '0'"
        if params.get("overdue_only"):
            where += " AND DueDate < TODAY"
        sql = f"SELECT * FROM Bill WHERE {where} ORDERBY DueDate ASC MAXRESULTS 50"
        return await qbo_query(sql)

    elif tool == "qbo_refresh_token":
        token = await refresh_qbo_token()
        return {"success": bool(token), "message": "Token refreshed" if token else "Refresh failed"}

    elif tool == "qbo_create_expense":
        from datetime import date as _date
        vendor_name = params["vendor_name"]
        amount = params["amount"]
        category = params.get("category", "Job Materials")
        txn_date = params.get("date") or _date.today().isoformat()
        memo = params.get("memo", "")
        payment_type = params.get("payment_type", "CreditCard")

        # Look up or create vendor
        vendor_resp = await qbo_query(
            f"SELECT Id, DisplayName FROM Vendor WHERE DisplayName LIKE '%{vendor_name}%' MAXRESULTS 1"
        )
        vendors = vendor_resp.get("QueryResponse", {}).get("Vendor", [])
        if vendors:
            vendor_id = vendors[0]["Id"]
        else:
            # Create vendor on the fly
            create_resp = await qbo_request("POST", "vendor", json_body={"DisplayName": vendor_name})
            vendor_id = create_resp.get("Vendor", {}).get("Id")
            if not vendor_id:
                return {"error": f"Could not find or create vendor '{vendor_name}': {create_resp}"}

        # Look up expense account
        acct_resp = await qbo_query(
            f"SELECT Id, Name FROM Account WHERE AccountType = 'Cost of Goods Sold' OR AccountType = 'Expense' MAXRESULTS 50"
        )
        accounts = acct_resp.get("QueryResponse", {}).get("Account", [])
        account_id = None
        for a in accounts:
            if category.lower() in a.get("Name", "").lower():
                account_id = a["Id"]
                break
        if not account_id and accounts:
            account_id = accounts[0]["Id"]  # fallback to first expense account

        if not account_id:
            return {"error": f"No expense account found for category '{category}'"}

        body = {
            "PaymentType": payment_type,
            "EntityRef": {"value": vendor_id, "type": "Vendor"},
            "TxnDate": txn_date,
            "Line": [
                {
                    "Amount": amount,
                    "DetailType": "AccountBasedExpenseLineDetail",
                    "AccountBasedExpenseLineDetail": {
                        "AccountRef": {"value": account_id}
                    },
                    "Description": memo or category
                }
            ]
        }
        if memo:
            body["PrivateNote"] = memo

        result = await qbo_request("POST", "purchase", json_body=body)
        purchase = result.get("Purchase", {})
        return {
            "success": True,
            "expense_id": purchase.get("Id"),
            "amount": purchase.get("TotalAmt"),
            "vendor": vendor_name,
            "date": txn_date,
            "memo": memo
        } if purchase.get("Id") else {"error": f"Expense creation response: {result}"}

    return {"error": f"Unhandled QBO tool: {tool}"}


# ─────────────────────────────────────────────
# META TOOLS
# ─────────────────────────────────────────────

async def meta_request(endpoint: str, params: dict = None, method: str = "GET", data: dict = None, use_page_token: bool = False) -> dict:
    base = "https://graph.facebook.com/v19.0"
    token = (META_PAGE_TOKEN or META_TOKEN) if use_page_token else META_TOKEN
    p = {"access_token": token}
    if params:
        p.update(params)
    async with httpx.AsyncClient() as client:
        if method == "GET":
            resp = await client.get(f"{base}/{endpoint}", params=p, timeout=30)
        else:
            resp = await client.post(f"{base}/{endpoint}", params=p, data=data, timeout=30)
        resp.raise_for_status()
        return resp.json()


async def execute_meta(tool: str, params: dict) -> dict:
    # Page tools require a Page Access Token (new Pages experience).
    # If META_PAGE_TOKEN is not set, return actionable instructions.
    PAGE_TOKEN_MISSING_MSG = (
        "Meta page tools require a Page Access Token. "
        "Go to developers.facebook.com/tools/explorer, select your app, click 'Generate Access Token', "
        "add permissions: pages_read_engagement, pages_manage_posts, pages_read_user_content, pages_show_list. "
        "Then set META_PAGE_TOKEN in Railway environment variables and redeploy."
    )

    if tool == "meta_get_page_posts":
        if not META_PAGE_TOKEN:
            return {"error": PAGE_TOKEN_MISSING_MSG}
        limit = params.get("limit", 10)
        return await meta_request(
            f"{META_PAGE_ID}/posts",
            {"fields": "id,message,created_time,likes.summary(true),comments.summary(true),shares", "limit": limit},
            use_page_token=True
        )

    elif tool == "meta_get_insights":
        if not META_PAGE_TOKEN:
            return {"error": PAGE_TOKEN_MISSING_MSG}
        period = params.get("period", "week")
        # Valid metrics for new Pages experience (v19.0+)
        default_metrics = [
            "page_impressions",
            "page_impressions_unique",
            "page_post_engagements",
            "page_fans",
            "page_views_total"
        ]
        raw_metrics = params.get("metrics", default_metrics)
        # Map legacy names to correct API names
        metric_map = {
            "reach": "page_impressions_unique",
            "impressions": "page_impressions",
            "engagement": "page_post_engagements",
            "followers": "page_fans",
            "views": "page_views_total"
        }
        metrics = [metric_map.get(m, m) for m in raw_metrics]
        return await meta_request(
            f"{META_PAGE_ID}/insights",
            {"metric": ",".join(metrics), "period": period},
            use_page_token=True
        )

    elif tool == "meta_create_post":
        if not META_PAGE_TOKEN:
            return {"error": PAGE_TOKEN_MISSING_MSG}
        data = {"message": params["message"]}
        if params.get("scheduled_time"):
            data["scheduled_publish_time"] = params["scheduled_time"]
            data["published"] = "false"
        return await meta_request(f"{META_PAGE_ID}/feed", method="POST", data=data, use_page_token=True)

    elif tool == "meta_get_campaigns":
        status_filter = params.get("status", "ALL")
        p: dict = {
            "fields": "id,name,status,objective,daily_budget,lifetime_budget,spend_cap,created_time,start_time,stop_time",
            "limit": 25
        }
        if status_filter != "ALL":
            p["effective_status"] = f'["{status_filter}"]'
        return await meta_request(f"act_{META_AD_ACCOUNT}/campaigns", params=p)

    elif tool == "meta_get_ad_insights":
        level = params.get("level", "campaign")
        date_preset = params.get("date_preset", "last_30d")
        return await meta_request(
            f"act_{META_AD_ACCOUNT}/insights",
            params={
                "level": level,
                "date_preset": date_preset,
                "fields": "campaign_name,adset_name,ad_name,spend,impressions,reach,clicks,cpm,ctr,actions,cost_per_action_type",
                "limit": 50
            }
        )

    elif tool == "meta_create_campaign":
        data = {
            "name": params["name"],
            "objective": params.get("objective", "LEAD_GENERATION"),
            "status": params.get("status", "PAUSED"),
            "daily_budget": str(int(params["daily_budget"])),
            "special_ad_categories": "[]"
        }
        return await meta_request(f"act_{META_AD_ACCOUNT}/campaigns", method="POST", data=data)

    elif tool == "meta_get_ad_account_info":
        return await meta_request(
            f"act_{META_AD_ACCOUNT}",
            params={"fields": "id,name,account_status,currency,balance,spend_cap,amount_spent,daily_spend_limit,timezone_name"}
        )

    return {"error": f"Unhandled Meta tool: {tool}"}


# ─────────────────────────────────────────────
# GOOGLE TOOLS
# ─────────────────────────────────────────────

async def _get_google_creds():
    """
    Build Google OAuth2 Credentials from env vars.
    Accepts GOOGLE_REFRESH_TOKEN, GMAIL_TOKEN, or GOOGLE_CALENDAR_TOKEN — whichever is set.
    The google-auth library auto-refreshes the access_token when it expires.
    """
    from google.oauth2.credentials import Credentials
    # Accept any of these var names — whichever Jacob sets on Railway
    refresh_token = (
        os.getenv("GOOGLE_REFRESH_TOKEN", "") or
        os.getenv("GMAIL_TOKEN", "") or
        os.getenv("GOOGLE_CALENDAR_TOKEN", "")
    )
    access_token = os.getenv("GOOGLE_ACCESS_TOKEN", "")
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")

    if not refresh_token or refresh_token in ("PENDING", ""):
        return None, "Google not authorized — set GOOGLE_REFRESH_TOKEN (or GMAIL_TOKEN / GOOGLE_CALENDAR_TOKEN) on Railway"
    if not (client_id and client_secret):
        return None, "GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET not set"

    creds = Credentials(
        token=access_token or None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=[
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.compose",
        ]
    )
    return creds, None


async def execute_google(tool: str, params: dict) -> dict:
    creds, err = await _get_google_creds()
    if err:
        return {"error": err}

    try:
        from googleapiclient.discovery import build
        import pytz
        from datetime import datetime as dt, timedelta
        edmonton = pytz.timezone("America/Edmonton")

        if tool in ("google_calendar_today", "google_calendar_week"):
            service_obj = build("calendar", "v3", credentials=creds)

            if tool == "google_calendar_today":
                date_str = params.get("date") or dt.now(edmonton).strftime("%Y-%m-%d")
                day_start = edmonton.localize(dt.strptime(date_str, "%Y-%m-%d"))
                day_end = day_start + timedelta(hours=23, minutes=59, seconds=59)
                label = date_str
            else:  # google_calendar_week
                offset = int(params.get("week_offset", 0))
                today = dt.now(edmonton).date()
                mon = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
                sun = mon + timedelta(days=6)
                day_start = edmonton.localize(dt.combine(mon, dt.min.time()))
                day_end = edmonton.localize(dt.combine(sun, dt.max.time().replace(microsecond=0)))
                label = f"{mon.isoformat()} to {sun.isoformat()}"

            events_result = service_obj.events().list(
                calendarId="primary",
                timeMin=day_start.isoformat(),
                timeMax=day_end.isoformat(),
                singleEvents=True,
                orderBy="startTime"
            ).execute()
            events = events_result.get("items", [])
            simplified = []
            for e in events:
                start = e["start"].get("dateTime", e["start"].get("date", ""))
                end = e["end"].get("dateTime", e["end"].get("date", ""))
                simplified.append({
                    "title": e.get("summary", "No title"),
                    "start": start,
                    "end": end,
                    "location": e.get("location", ""),
                    "description": (e.get("description", "") or "")[:150],
                    "attendees": len(e.get("attendees", [])),
                    "event_id": e.get("id", ""),
                })
            return {"events": simplified, "count": len(simplified), "period": label}

        elif tool == "google_calendar_create_event":
            import base64
            service_obj = build("calendar", "v3", credentials=creds)
            title = params["title"]
            start_str = params["start_datetime"]  # YYYY-MM-DDTHH:MM
            end_str = params.get("end_datetime")

            # Parse and localize start time
            start_dt = edmonton.localize(dt.strptime(start_str, "%Y-%m-%dT%H:%M"))
            if end_str:
                end_dt = edmonton.localize(dt.strptime(end_str, "%Y-%m-%dT%H:%M"))
            else:
                end_dt = start_dt + timedelta(hours=1)

            event_body = {
                "summary": title,
                "start": {"dateTime": start_dt.isoformat(), "timeZone": "America/Edmonton"},
                "end": {"dateTime": end_dt.isoformat(), "timeZone": "America/Edmonton"},
            }
            if params.get("location"):
                event_body["location"] = params["location"]
            if params.get("description"):
                event_body["description"] = params["description"]
            if params.get("attendee_emails"):
                event_body["attendees"] = [{"email": e} for e in params["attendee_emails"]]

            created = service_obj.events().insert(
                calendarId="primary",
                body=event_body,
                sendUpdates="all" if params.get("attendee_emails") else "none"
            ).execute()
            return {
                "success": True,
                "event_id": created.get("id"),
                "title": created.get("summary"),
                "start": created["start"].get("dateTime"),
                "html_link": created.get("htmlLink"),
            }

        elif tool == "gmail_urgent":
            max_results = int(params.get("max_results", 5))
            service_obj = build("gmail", "v1", credentials=creds)
            results = service_obj.users().messages().list(
                userId="me",
                q="is:unread newer_than:2d -category:promotions -category:social",
                maxResults=max_results
            ).execute()
            messages = results.get("messages", [])
            emails = []
            for m in messages:
                msg = service_obj.users().messages().get(
                    userId="me", id=m["id"], format="metadata",
                    metadataHeaders=["From", "Subject", "Date"]
                ).execute()
                headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
                emails.append({
                    "from": headers.get("From", "Unknown"),
                    "subject": headers.get("Subject", "No subject"),
                    "date": headers.get("Date", ""),
                    "snippet": msg.get("snippet", "")[:150]
                })
            return {"emails": emails, "unread_count": len(emails)}

        elif tool == "gmail_send":
            import base64
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            service_obj = build("gmail", "v1", credentials=creds)
            to = params["to"]
            subject = params["subject"]
            body = params["body"]
            cc = params.get("cc", "")

            msg = MIMEMultipart("alternative")
            msg["To"] = to
            msg["Subject"] = subject
            if cc:
                msg["Cc"] = cc
            msg.attach(MIMEText(body, "plain"))

            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            sent = service_obj.users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()
            return {
                "success": True,
                "message_id": sent.get("id"),
                "to": to,
                "subject": subject,
            }

    except Exception as ex:
        return {"error": str(ex)}

    return {"error": f"Unhandled Google tool: {tool}"}


# ─────────────────────────────────────────────
# WEATHER (open-meteo, no key required)
# ─────────────────────────────────────────────

# Red Deer, Alberta approximate centroid
RED_DEER_LAT = 52.2681
RED_DEER_LON = -113.8112


async def execute_weather(params: dict) -> dict:
    days = max(1, min(int(params.get("days", 3)), 7))
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": RED_DEER_LAT,
                    "longitude": RED_DEER_LON,
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max,weather_code",
                    "timezone": "America/Edmonton",
                    "forecast_days": days
                }
            )
            resp.raise_for_status()
            d = resp.json().get("daily", {})

        dates = d.get("time", [])
        forecast = []
        risk_flags = []
        # WMO weather codes — keep it simple
        code_map = {
            0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
            45: "fog", 48: "freezing fog",
            51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
            61: "light rain", 63: "rain", 65: "heavy rain",
            71: "light snow", 73: "snow", 75: "heavy snow",
            77: "snow grains",
            80: "rain showers", 81: "heavy showers", 82: "violent showers",
            85: "snow showers", 86: "heavy snow showers",
            95: "thunderstorm", 96: "thunderstorm with hail", 99: "severe thunderstorm"
        }

        for i, date in enumerate(dates):
            high = d.get("temperature_2m_max", [None] * len(dates))[i]
            low = d.get("temperature_2m_min", [None] * len(dates))[i]
            precip = d.get("precipitation_sum", [0] * len(dates))[i] or 0
            precip_prob = d.get("precipitation_probability_max", [0] * len(dates))[i] or 0
            wind = d.get("wind_speed_10m_max", [0] * len(dates))[i] or 0
            code = d.get("weather_code", [0] * len(dates))[i]
            condition = code_map.get(code, f"code {code}")

            day_summary = {
                "date": date,
                "condition": condition,
                "high_c": high,
                "low_c": low,
                "precip_mm": round(precip, 1),
                "precip_chance_pct": precip_prob,
                "wind_kmh_max": round(wind, 1)
            }
            forecast.append(day_summary)

            # Outdoor-work risk flags
            if precip >= 5 or precip_prob >= 60:
                risk_flags.append(f"{date}: {condition}, {precip_prob}% precip — risk for deck/framing/concrete")
            if wind >= 40:
                risk_flags.append(f"{date}: wind {wind:.0f}km/h — risk for roof/lift work")
            if low is not None and low < -10:
                risk_flags.append(f"{date}: low {low}C — concrete cure issue, framing slow")
            if code in (95, 96, 99):
                risk_flags.append(f"{date}: thunderstorm — stop outdoor work")

        return {
            "location": "Red Deer, AB",
            "forecast": forecast,
            "outdoor_risk_flags": risk_flags,
            "any_risk": len(risk_flags) > 0
        }
    except Exception as e:
        return {"error": f"Weather fetch failed: {e}"}


# ─────────────────────────────────────────────
# BRIEFING ENDPOINT
# ─────────────────────────────────────────────

@app.post("/briefing")
async def trigger_briefing(request: Request):
    """Trigger a full morning briefing push to Jacob's Telegram."""
    secret = request.headers.get("x-mcp-secret")
    if MCP_SECRET and secret != MCP_SECRET:
        raise HTTPException(status_code=403, detail="Unauthorized")
    try:
        from briefing import generate_briefing, send_telegram as briefing_send
        import httpx as _httpx
        msg = await generate_briefing()
        async with _httpx.AsyncClient() as client:
            await briefing_send(client, msg)
        return {"status": "sent", "preview": msg[:300]}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

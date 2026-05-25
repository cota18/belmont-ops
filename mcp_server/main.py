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
    return {"status": "Belmont MCP Server online", "tools": 27}


@app.get("/mcp/tools")
async def list_tools():
    """Returns the full tool manifest for Claude Managed Agents."""
    return {
        "tools": [
            # ── JOBTREAD ──────────────────────────────────────────
            {
                "name": "jobtread_list_jobs",
                "description": "List all jobs in JobTread. Filter by status: active, completed, pending, all.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["active", "completed", "pending", "all"], "default": "active"}
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
                "description": "Get Jacob's Google Calendar events for today. Returns meetings, appointments, family events, and time blocks.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "description": "Date in YYYY-MM-DD format. Defaults to today."}
                    }
                }
            },
            {
                "name": "gmail_urgent",
                "description": "Check Gmail for unread messages in the last 24 hours that look important or time-sensitive. Returns subject, sender, and snippet.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "max_results": {"type": "integer", "description": "Max emails to return. Default 5."}
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
        elif tool_name in ("google_calendar_today", "gmail_urgent"):
            result = await execute_google(tool_name, params)
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
        return await jobtread_query({
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
                        }
                    },
                    "nextPage": {}
                }
            }
        })

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


async def refresh_qbo_token() -> str:
    """Refresh QBO OAuth token using refresh token."""
    import base64
    creds = base64.b64encode(
        f"{os.getenv('QBO_CLIENT_ID')}:{os.getenv('QBO_CLIENT_SECRET')}".encode()
    ).decode()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
            headers={
                "Authorization": f"Basic {creds}",
                "Content-Type": "application/x-www-form-urlencoded"
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": os.getenv("QBO_REFRESH_TOKEN")
            }
        )
        if resp.status_code == 200:
            data = resp.json()
            os.environ["QBO_ACCESS_TOKEN"] = data["access_token"]
            if "refresh_token" in data:
                os.environ["QBO_REFRESH_TOKEN"] = data["refresh_token"]
            return data["access_token"]
    return None


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

async def execute_google(tool: str, params: dict) -> dict:
    token = os.getenv("GOOGLE_CALENDAR_TOKEN") if tool == "google_calendar_today" else os.getenv("GMAIL_TOKEN")
    refresh_token = os.getenv("GOOGLE_CALENDAR_REFRESH_TOKEN") if tool == "google_calendar_today" else os.getenv("GMAIL_REFRESH_TOKEN")
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

    if not all([token, refresh_token, client_id, client_secret]) or token in ("PENDING", None):
        service = "Google Calendar" if tool == "google_calendar_today" else "Gmail"
        return {"error": f"{service} not yet configured. Complete OAuth setup first."}

    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        creds = Credentials(
            token=token, refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id, client_secret=client_secret
        )

        if tool == "google_calendar_today":
            from datetime import datetime as dt
            date = params.get("date") or dt.now().strftime("%Y-%m-%d")
            service_obj = build("calendar", "v3", credentials=creds)
            events_result = service_obj.events().list(
                calendarId="primary",
                timeMin=f"{date}T00:00:00Z",
                timeMax=f"{date}T23:59:59Z",
                singleEvents=True, orderBy="startTime"
            ).execute()
            events = events_result.get("items", [])
            simplified = []
            for e in events:
                start = e["start"].get("dateTime", e["start"].get("date"))
                simplified.append({
                    "title": e.get("summary", "No title"),
                    "start": start,
                    "location": e.get("location", ""),
                    "description": (e.get("description", "") or "")[:100]
                })
            return {"events": simplified, "count": len(simplified), "date": date}

        elif tool == "gmail_urgent":
            max_results = params.get("max_results", 5)
            service_obj = build("gmail", "v1", credentials=creds)
            results = service_obj.users().messages().list(
                userId="me", q="is:unread newer_than:1d", maxResults=max_results
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
                    "snippet": msg.get("snippet", "")[:120]
                })
            return {"emails": emails, "unread_count": len(messages)}

    except Exception as ex:
        return {"error": str(ex)}

    return {"error": f"Unhandled Google tool: {tool}"}


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

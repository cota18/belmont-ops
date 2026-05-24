"""
BELMONT OPS - MCP TOOL SERVER
Exposes JobTread, QBO, and Meta as MCP-compatible tools
that Claude Managed Agents connects to.
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
META_PAGE_ID = os.getenv("META_PAGE_ID")
META_AD_ACCOUNT = os.getenv("META_AD_ACCOUNT_ID")
MCP_SECRET = os.getenv("MCP_SERVER_SECRET", "")

# ─────────────────────────────────────────────
# MCP PROTOCOL ENDPOINTS
# ─────────────────────────────────────────────

@app.get("/")
async def health():
    return {"status": "Belmont MCP Server online", "tools": 20}


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
        else:
            result = {"error": f"Unknown tool: {tool_name}"}
    except Exception as e:
        result = {"error": str(e), "tool": tool_name}

    return JSONResponse(content=result)


# ─────────────────────────────────────────────
# JOBTREAD TOOLS
# ─────────────────────────────────────────────

async def jobtread_query(query: dict) -> dict:
    """Execute a JobTread Pave API query."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.jobtread.com/pave",
            json={"query": query},
            headers={"Authorization": f"Bearer {JOBTREAD_KEY}"},
            timeout=30
        )
        resp.raise_for_status()
        return resp.json()


async def execute_jobtread(tool: str, params: dict) -> dict:
    if tool == "jobtread_list_jobs":
        status = params.get("status", "active")
        status_filter = {"$ne": "completed"} if status == "active" else (
            "completed" if status == "completed" else None
        )
        query = {
            "account": {
                "jobs": {
                    "$fields": ["id", "name", "status", "createdDate", "completedDate",
                                "totalBudget", "totalCost", "customer"],
                    "$filter": {"status": status_filter} if status_filter and status != "all" else {}
                }
            }
        }
        return await jobtread_query(query)

    elif tool == "jobtread_get_job_details":
        query = {
            "account": {
                "job": {
                    "$args": {"id": params["job_id"]},
                    "$fields": ["id", "name", "status", "description", "address",
                                "totalBudget", "totalCost", "createdDate", "completedDate",
                                "customer", "contacts", "notes", "lineItems", "expenses"]
                }
            }
        }
        return await jobtread_query(query)

    elif tool == "jobtread_get_estimates":
        query = {
            "account": {
                "estimates": {
                    "$fields": ["id", "name", "status", "total", "createdDate", "sentDate",
                                "approvedDate", "job", "lineItems"],
                    "$filter": {"jobId": params["job_id"]} if params.get("job_id") else {}
                }
            }
        }
        return await jobtread_query(query)

    elif tool == "jobtread_create_job":
        query = {
            "createJob": {
                "$args": {
                    "name": params["name"],
                    "customerName": params.get("customer_name"),
                    "customerEmail": params.get("customer_email"),
                    "customerPhone": params.get("customer_phone"),
                    "address": params.get("address"),
                    "description": params.get("description"),
                    "totalBudget": params.get("estimated_value")
                },
                "$fields": ["id", "name", "status"]
            }
        }
        return await jobtread_query(query)

    elif tool == "jobtread_add_note":
        query = {
            "createNote": {
                "$args": {
                    "jobId": params["job_id"],
                    "content": params["note"]
                },
                "$fields": ["id", "content", "createdDate"]
            }
        }
        return await jobtread_query(query)

    elif tool == "jobtread_get_contacts":
        query = {
            "account": {
                "contacts": {
                    "$fields": ["id", "name", "email", "phone", "company", "jobs"],
                    "$filter": {"search": params.get("search", "")}
                }
            }
        }
        return await jobtread_query(query)

    elif tool == "jobtread_get_expenses":
        query = {
            "account": {
                "expenses": {
                    "$fields": ["id", "description", "amount", "date", "category", "job"],
                    "$filter": {"jobId": params["job_id"]} if params.get("job_id") else {}
                }
            }
        }
        return await jobtread_query(query)

    elif tool == "jobtread_budget_vs_actual":
        details = await jobtread_query({
            "account": {
                "job": {
                    "$args": {"id": params["job_id"]},
                    "$fields": ["id", "name", "totalBudget", "totalCost", "lineItems", "expenses"]
                }
            }
        })
        job = details.get("account", {}).get("job", {})
        budget = float(job.get("totalBudget") or 0)
        actual = float(job.get("totalCost") or 0)
        variance = budget - actual
        return {
            "job_id": params["job_id"],
            "job_name": job.get("name"),
            "budget": budget,
            "actual_cost": actual,
            "variance": variance,
            "status": "OVER BUDGET" if variance < 0 else "ON BUDGET",
            "percent_used": round((actual / budget * 100) if budget > 0 else 0, 1)
        }

    elif tool == "jobtread_close_job":
        query = {
            "updateJob": {
                "$args": {
                    "id": params["job_id"],
                    "status": "completed",
                    "completionNotes": params.get("completion_notes", "")
                },
                "$fields": ["id", "name", "status"]
            }
        }
        return await jobtread_query(query)

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

    return {"error": f"Unhandled QBO tool: {tool}"}


# ─────────────────────────────────────────────
# META TOOLS
# ─────────────────────────────────────────────

async def meta_request(endpoint: str, params: dict = None, method: str = "GET", data: dict = None) -> dict:
    base = "https://graph.facebook.com/v19.0"
    p = {"access_token": META_TOKEN}
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
    if tool == "meta_get_page_posts":
        limit = params.get("limit", 10)
        return await meta_request(f"{META_PAGE_ID}/posts",
                                  {"fields": "id,message,created_time,likes.summary(true),comments.summary(true),shares", "limit": limit})

    elif tool == "meta_get_insights":
        period = params.get("period", "week")
        metrics = params.get("metrics", ["reach", "impressions", "page_engaged_users"])
        return await meta_request(f"{META_PAGE_ID}/insights",
                                  {"metric": ",".join(metrics), "period": period})

    elif tool == "meta_create_post":
        data = {"message": params["message"]}
        if params.get("scheduled_time"):
            import time
            data["scheduled_publish_time"] = params["scheduled_time"]
            data["published"] = "false"
        return await meta_request(f"{META_PAGE_ID}/feed", method="POST", data=data)

    return {"error": f"Unhandled Meta tool: {tool}"}

"""
BELMONT OPS - CLAUDE AGENT WITH TOOL-USE LOOP
Uses Anthropic Messages API directly with tool_use blocks.
Fetches tool manifest from MCP server, executes tools via POST /mcp/execute,
loops until Claude returns a final text response.
Supports vision content for photo/receipt processing.
"""

import os
import asyncio
import httpx
import json
import sys
from datetime import datetime
from typing import Optional

# ── Config ────────────────────────────────────────────────────────────────────

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "").rstrip("/")
MCP_SECRET = os.getenv("MCP_SERVER_SECRET", "")

MODEL_HEAVY = "claude-opus-4-5"
MODEL_FAST = "claude-sonnet-4-5"

HEAVY_AGENTS = {"orchestrator", "estimating", "finance"}

# ── Prompt import ─────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
try:
    from agents.prompts import AGENT_PROMPTS
except ImportError:
    print("[agent] WARNING: could not import agents.prompts — using fallback")
    AGENT_PROMPTS = {
        "orchestrator": "You are the Belmont & Co operations assistant. Help Jacob manage his construction business. Be concise and direct."
    }

# ── MCP Tool Fetcher ──────────────────────────────────────────────────────────

async def get_mcp_tools() -> list:
    """Fetch Anthropic-format tool definitions from the MCP server."""
    if not MCP_SERVER_URL:
        print("[agent] MCP_SERVER_URL is not set — no tools available")
        return []
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{MCP_SERVER_URL}/mcp/tools",
                headers={"x-mcp-secret": MCP_SECRET} if MCP_SECRET else {}
            )
            if resp.status_code == 200:
                data = resp.json()
                tools = [
                    {
                        "name": t["name"],
                        "description": t["description"],
                        "input_schema": t.get("input_schema", {"type": "object", "properties": {}})
                    }
                    for t in data.get("tools", [])
                ]
                print(f"[agent] Loaded {len(tools)} tools from MCP server")
                return tools
            else:
                print(f"[agent] MCP tools endpoint returned {resp.status_code}")
    except Exception as e:
        print(f"[agent] Failed to fetch MCP tools: {e}")
    return []


# ── MCP Tool Executor ─────────────────────────────────────────────────────────

async def call_mcp_tool(tool_name: str, params: dict) -> dict:
    """Execute a tool via the MCP server."""
    if not MCP_SERVER_URL:
        return {"error": "MCP_SERVER_URL not configured"}
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                f"{MCP_SERVER_URL}/mcp/execute",
                headers={"x-mcp-secret": MCP_SECRET, "content-type": "application/json"},
                json={"tool": tool_name, "params": params}
            )
            if resp.status_code == 200:
                result = resp.json()
                print(f"[agent] Tool {tool_name} returned OK")
                return result
            else:
                err = f"MCP returned {resp.status_code}: {resp.text[:200]}"
                print(f"[agent] Tool {tool_name} error: {err}")
                return {"error": err}
    except Exception as e:
        print(f"[agent] Tool {tool_name} exception: {e}")
        return {"error": str(e)}


# ── BJJ Tracker ───────────────────────────────────────────────────────────────

async def log_bjj_session(zep_client, user_id: str) -> str:
    """Log a BJJ session and return weekly count."""
    from datetime import datetime, timedelta
    today = datetime.now().strftime("%Y-%m-%d")
    week_start = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%Y-%m-%d")

    try:
        from zep_cloud.types import Message
        await zep_client.memory.add(
            session_id=f"{user_id}_bjj",
            messages=[
                Message(
                    role_type="user",
                    content=f"BJJ session logged: {today}",
                    role="Jacob"
                )
            ]
        )
        # Search this week's sessions
        results = await zep_client.memory.search_sessions(
            user_id=user_id,
            text=f"BJJ session logged {week_start[:7]}",
            limit=10
        )
        if results and results.results:
            this_week = [
                r for r in results.results
                if r.message and week_start in (r.message.content or "")
            ]
            count = max(1, len(this_week))
        else:
            count = 1
        remaining = max(0, 4 - count)
        status = "Target hit!" if count >= 4 else f"{remaining} more to hit your weekly target"
        return f"BJJ session logged. This week: {count}/4. {status}"
    except Exception as e:
        return f"BJJ session logged for {today}."


# ── Main Agentic Loop ─────────────────────────────────────────────────────────

async def run_agent(
    agent_type: str,
    message: str,
    memory_context: str = "",
    chat_id: str = "default",
    vision_content: list = None,
    conversation_history: list = None
) -> str:
    """
    Run Claude with tool-use loop against the MCP server.
    Supports optional vision_content for image/photo messages.
    conversation_history: list of {role, content} dicts for within-session recall.
    """
    if not ANTHROPIC_KEY:
        return "Error: ANTHROPIC_API_KEY is not set."

    base_prompt = AGENT_PROMPTS.get(agent_type, AGENT_PROMPTS.get("orchestrator", "You are a helpful assistant."))
    system_prompt = base_prompt
    if memory_context:
        system_prompt = f"{base_prompt}\n\n--- MEMORY CONTEXT ---\n{memory_context}\n--- END MEMORY ---"

    tools = await get_mcp_tools()
    if not tools:
        print(f"[agent] No tools available — Claude will answer from knowledge only")
        tools = []

    # Add Anthropic's built-in web search tool — Red Deer localized
    # Server-side: Claude executes searches automatically, no MCP routing needed
    web_search_tool = {
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": 5,
        "user_location": {
            "type": "approximate",
            "city": "Red Deer",
            "region": "Alberta",
            "country": "CA",
            "timezone": "America/Edmonton"
        }
    }
    tools.append(web_search_tool)
    print(f"[agent] Total tools: {len(tools)} (incl. built-in web_search)")

    model = MODEL_HEAVY if agent_type in HEAVY_AGENTS else MODEL_FAST

    # Build message list — prepend conversation history for within-session recall
    if vision_content:
        user_message_content = vision_content
    else:
        user_message_content = message

    # Start with recent conversation history (last N turns), then current message
    messages = list(conversation_history) if conversation_history else []
    messages.append({"role": "user", "content": user_message_content})

    headers = {
        "x-api-key": ANTHROPIC_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }

    async with httpx.AsyncClient(timeout=120) as client:
        for iteration in range(10):
            payload = {
                "model": model,
                "max_tokens": 8192,
                "system": system_prompt,
                "messages": messages
            }
            if tools:
                payload["tools"] = tools

            print(f"[agent] Calling Claude ({model}), iteration {iteration + 1}, {len(messages)} messages")

            try:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=headers,
                    json=payload,
                    timeout=90
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                print(f"[agent] Anthropic API error {e.response.status_code}: {e.response.text[:300]}")
                return f"API error {e.response.status_code} — check Railway logs."
            except Exception as e:
                print(f"[agent] Anthropic request failed: {e}")
                return f"Request failed: {e}"

            data = resp.json()
            stop_reason = data.get("stop_reason")
            content = data.get("content", [])

            print(f"[agent] Claude stop_reason={stop_reason}, content blocks={len(content)}")

            if stop_reason == "end_turn":
                # Concatenate all text blocks (web_search responses may have multiple)
                texts = [b["text"] for b in content if b.get("type") == "text"]
                if texts:
                    return "\n\n".join(t for t in texts).strip()
                return "[Task complete — no text output]"

            # pause_turn: Claude paused mid-thought (long server-side tool runs);
            # continue the loop with same messages to resume
            if stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": content})
                print(f"[agent] pause_turn — continuing loop")
                continue

            if stop_reason == "tool_use":
                # Only handle client-side tool_use blocks (MCP tools).
                # Server-side tools (web_search) have type=server_tool_use and are
                # auto-executed by the Anthropic API — no action from us needed.
                tool_results = []
                for block in content:
                    if block.get("type") == "tool_use":
                        tool_name = block["name"]
                        tool_input = block.get("input", {})
                        print(f"[agent] Executing tool: {tool_name} with {list(tool_input.keys())}")
                        result = await call_mcp_tool(tool_name, tool_input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block["id"],
                            "content": json.dumps(result)
                        })

                # If only server-side tools ran (no client tools), Claude may
                # already have all info needed. Continue without adding tool_results.
                if tool_results:
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": tool_results})
                else:
                    messages.append({"role": "assistant", "content": content})
                    print(f"[agent] No client-side tools to execute — Claude continuing")
                continue

            print(f"[agent] Unexpected stop_reason: {stop_reason}")
            # Try to recover any text in content before bailing
            texts = [b["text"] for b in content if b.get("type") == "text"]
            if texts:
                return "\n\n".join(texts).strip()
            break

    return "[Agent loop ended without a final response]"

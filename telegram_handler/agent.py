"""
BELMONT OPS - CLAUDE AGENT WITH TOOL-USE LOOP
Uses Anthropic Messages API directly with tool_use blocks.
Fetches tool manifest from MCP server, executes tools via POST /mcp/execute,
loops until Claude returns a final text response.
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

MODEL_HEAVY = "claude-opus-4-6"
MODEL_FAST = "claude-sonnet-4-6"

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
    """Execute a tool via the MCP server. Returns result dict."""
    if not MCP_SERVER_URL:
        return {"error": "MCP_SERVER_URL not configured"}
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                f"{MCP_SERVER_URL}/mcp/execute",
                headers={
                    "x-mcp-secret": MCP_SECRET,
                    "content-type": "application/json"
                },
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


# ── Main Agentic Loop ─────────────────────────────────────────────────────────

async def run_agent(
    agent_type: str,
    message: str,
    memory_context: str = "",
    chat_id: str = "default"
) -> str:
    """
    Run Claude with tool-use loop against the MCP server.
    1. Fetch tool manifest from MCP server
    2. Send user message to Claude with tools
    3. If Claude calls tools: execute via MCP, feed results back
    4. Loop until Claude returns final text
    """
    if not ANTHROPIC_KEY:
        return "Error: ANTHROPIC_API_KEY is not set."

    # Build system prompt
    base_prompt = AGENT_PROMPTS.get(agent_type, AGENT_PROMPTS.get("orchestrator", "You are a helpful assistant."))
    system_prompt = base_prompt
    if memory_context:
        system_prompt = f"{base_prompt}\n\n--- MEMORY CONTEXT ---\n{memory_context}\n--- END MEMORY ---"

    # Fetch tools
    tools = await get_mcp_tools()
    if not tools:
        print(f"[agent] No tools available — Claude will answer from knowledge only")

    model = MODEL_HEAVY if agent_type in HEAVY_AGENTS else MODEL_FAST
    messages = [{"role": "user", "content": message}]

    headers = {
        "x-api-key": ANTHROPIC_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }

    async with httpx.AsyncClient(timeout=120) as client:
        for iteration in range(10):  # max 10 agentic iterations
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

            # Done — extract text
            if stop_reason == "end_turn":
                for block in content:
                    if block.get("type") == "text":
                        return block["text"].strip()
                return "[Task complete — no text output]"

            # Tool use — execute and feed results back
            if stop_reason == "tool_use":
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

                # Append assistant turn + tool results
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": tool_results})
                continue

            # Any other stop reason — bail
            print(f"[agent] Unexpected stop_reason: {stop_reason}")
            break

    return "[Agent loop ended without a final response]"

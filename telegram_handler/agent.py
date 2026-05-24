"""
BELMONT OPS - CLAUDE MANAGED AGENTS INTEGRATION
Handles session creation, async execution, and multi-agent orchestration.
"""

import os
import asyncio
import httpx
import json
from datetime import datetime
from typing import Optional

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "https://belmont-mcp.railway.app")
MCP_SECRET = os.getenv("MCP_SERVER_SECRET", "")
BETA_HEADER = "managed-agents-2026-04-01"

# Claude model selection: Opus for complex tasks, Sonnet for routine
MODEL_HEAVY = "claude-opus-4-6"
MODEL_FAST = "claude-sonnet-4-6"

BASE_URL = "https://api.anthropic.com/v1/managed-agents"

# Stored agent IDs (created once, reused)
_agent_ids: dict[str, str] = {}


def get_headers() -> dict:
    return {
        "x-api-key": ANTHROPIC_KEY,
        "anthropic-version": "2023-06-01",
        "anthropic-beta": BETA_HEADER,
        "content-type": "application/json"
    }


async def get_or_create_agent(agent_type: str, system_prompt: str) -> str:
    """Get cached agent ID or create new agent definition."""
    if agent_type in _agent_ids:
        return _agent_ids[agent_type]

    # Determine model based on agent type
    model = MODEL_HEAVY if agent_type in ["orchestrator", "estimating", "finance"] else MODEL_FAST

    payload = {
        "name": f"belmont_{agent_type}",
        "model": model,
        "system_prompt": system_prompt,
        "tools": {
            "mcp": [
                {
                    "server_url": f"{MCP_SERVER_URL}/mcp",
                    "headers": {"x-mcp-secret": MCP_SECRET} if MCP_SECRET else {}
                }
            ]
        },
        "settings": {
            "max_tokens": 8192,
            "temperature": 0.3
        }
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{BASE_URL}/agents",
            headers=get_headers(),
            json=payload
        )
        if resp.status_code in (200, 201):
            agent_id = resp.json().get("id")
            _agent_ids[agent_type] = agent_id
            return agent_id
        else:
            # Fall back to direct Messages API if Managed Agents unavailable
            _agent_ids[agent_type] = f"fallback_{agent_type}"
            return _agent_ids[agent_type]


async def create_session(agent_id: str) -> Optional[str]:
    """Create a new Managed Agents session."""
    if agent_id.startswith("fallback_"):
        return f"fallback_session_{datetime.utcnow().timestamp()}"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{BASE_URL}/sessions",
            headers=get_headers(),
            json={"agent_id": agent_id}
        )
        if resp.status_code in (200, 201):
            return resp.json().get("id")
    return None


async def send_message_to_session(session_id: str, message: str) -> str:
    """
    Send a message to a Managed Agents session and stream the response.
    Handles both Managed Agents sessions and fallback direct API calls.
    """
    if session_id.startswith("fallback_"):
        return await _fallback_direct_api(session_id.split("_")[2], message)

    full_response = ""
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST",
            f"{BASE_URL}/sessions/{session_id}/events",
            headers=get_headers(),
            json={"type": "user", "content": message},
        ) as resp:
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[6:])
                    etype = event.get("type", "")
                    if etype == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            full_response += delta.get("text", "")
                    elif etype == "message_stop":
                        break
                except (json.JSONDecodeError, KeyError):
                    continue

    return full_response.strip() or "[Agent completed task with no text output]"


async def _fallback_direct_api(agent_type: str, message: str) -> str:
    """
    Fallback: use direct Anthropic Messages API with manual tool loop.
    Used when Managed Agents is not available or returns errors.
    """
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from agents.prompts import AGENT_PROMPTS

    system = AGENT_PROMPTS.get(agent_type, AGENT_PROMPTS["orchestrator"])

    # Get available tools from MCP server
    tools = await get_mcp_tools()

    messages = [{"role": "user", "content": message}]

    async with httpx.AsyncClient(timeout=60) as client:
        for _ in range(10):  # max 10 agentic iterations
            payload = {
                "model": MODEL_HEAVY if agent_type in ["orchestrator", "estimating", "finance"] else MODEL_FAST,
                "max_tokens": 8192,
                "system": system,
                "tools": tools,
                "messages": messages
            }
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json=payload,
                timeout=60
            )
            resp.raise_for_status()
            data = resp.json()

            stop_reason = data.get("stop_reason")
            content = data.get("content", [])

            if stop_reason == "end_turn":
                # Extract text
                for block in content:
                    if block.get("type") == "text":
                        return block["text"]
                return "[No response text]"

            if stop_reason == "tool_use":
                # Execute tool calls
                tool_results = []
                for block in content:
                    if block.get("type") == "tool_use":
                        tool_result = await call_mcp_tool(block["name"], block.get("input", {}))
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block["id"],
                            "content": json.dumps(tool_result)
                        })

                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": tool_results})
                continue

            break

    return "[Agent loop ended without response]"


async def get_mcp_tools() -> list:
    """Fetch tool definitions from the MCP server."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{MCP_SERVER_URL}/mcp/tools")
            if resp.status_code == 200:
                data = resp.json()
                # Convert to Anthropic tool format
                return [
                    {
                        "name": t["name"],
                        "description": t["description"],
                        "input_schema": t.get("input_schema", {"type": "object", "properties": {}})
                    }
                    for t in data.get("tools", [])
                ]
    except Exception as e:
        print(f"Failed to fetch MCP tools: {e}")
    return []


async def call_mcp_tool(tool_name: str, params: dict) -> dict:
    """Execute a tool via the MCP server."""
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                f"{MCP_SERVER_URL}/mcp/execute",
                headers={"x-mcp-secret": MCP_SECRET},
                json={"tool": tool_name, "params": params}
            )
            if resp.status_code == 200:
                return resp.json()
            return {"error": f"MCP returned {resp.status_code}"}
    except Exception as e:
        return {"error": str(e)}


async def run_agent(
    agent_type: str,
    message: str,
    memory_context: str = "",
    chat_id: str = "default"
) -> str:
    """
    Main entry point for running an agent on a task.
    Handles agent creation, session management, memory injection.
    """
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from agents.prompts import AGENT_PROMPTS

    base_prompt = AGENT_PROMPTS.get(agent_type, AGENT_PROMPTS["orchestrator"])

    # Inject memory context into system prompt
    full_system = base_prompt
    if memory_context:
        full_system = f"{base_prompt}\n\n--- MEMORY CONTEXT ---\n{memory_context}\n--- END MEMORY ---"

    # Try Managed Agents first, fallback to direct API
    try:
        agent_id = await get_or_create_agent(agent_type, full_system)
        if not agent_id.startswith("fallback_"):
            session_id = await create_session(agent_id)
            if session_id:
                return await send_message_to_session(session_id, message)
    except Exception as e:
        print(f"Managed Agents error: {e}, falling back to direct API")

    # Fallback: direct API call with manual tool loop
    return await _fallback_direct_api(agent_type, message)

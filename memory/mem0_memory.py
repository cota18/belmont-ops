"""
BELMONT OPS - MEM0 MEMORY LAYER
Replaces Zep. Persistent long-term memory via mem0 Cloud.
Free tier: unlimited users, 10k memories. Survives restarts.
No session concept — all memory is tied to user_id "jacob_belmont".

API docs: https://docs.mem0.ai
Sign up:  https://app.mem0.ai  -> Settings -> API Keys
"""

import os
import asyncio
from typing import Optional

MEM0_API_KEY = os.getenv("MEM0_API_KEY", "")
USER_ID = "jacob_belmont"

_client = None


def _get_client():
    """Return singleton mem0 AsyncMemoryClient. Returns None if no API key."""
    global _client
    if _client is None and MEM0_API_KEY:
        try:
            from mem0 import AsyncMemoryClient
            _client = AsyncMemoryClient(api_key=MEM0_API_KEY)
            print("[mem0] Client initialized")
        except Exception as e:
            print(f"[mem0] Client init failed: {e}")
    return _client


# ── Interface matches zep_memory.py so main.py needs minimal changes ──────────

async def ensure_user():
    """No-op for mem0 — users are auto-created on first add()."""
    pass


async def get_session_id(agent_type: str, chat_id: str) -> str:
    """Kept for interface compatibility — mem0 doesn't use sessions."""
    return f"belmont_{agent_type}_{chat_id}"


async def ensure_session(session_id: str, agent_type: str):
    """No-op for mem0 — no session management needed."""
    pass


async def load_memory(session_id: str, query: str = None) -> str:
    """
    Search mem0 for memories relevant to the current query.
    Returns formatted string ready to inject into system prompt.
    Always silent on failure — agent works fine without memory context.
    """
    client = _get_client()
    if not client or not query:
        return ""

    try:
        results = await asyncio.to_thread(
            client.search, query, user_id=USER_ID, limit=10
        )
        if not results:
            return ""

        # mem0 returns list of dicts: {"memory": "...", "score": 0.9, ...}
        relevant = [
            r["memory"] for r in results
            if r.get("score", 0) > 0.3 and r.get("memory")
        ]
        if not relevant:
            return ""

        lines = "\n".join(f"- {m}" for m in relevant[:8])
        return f"MEMORY (what I know about Jacob & Belmont):\n{lines}"
    except Exception as e:
        print(f"[mem0] load_memory failed (silenced): {e}")
        return ""


async def save_exchange(session_id: str, user_msg: str, agent_response: str):
    """
    Save a conversation exchange to mem0.
    mem0 automatically extracts facts and relationships from the conversation.
    """
    client = _get_client()
    if not client:
        return

    # Skip saving trivial/short exchanges that don't contain useful facts
    if len(user_msg) < 10 and len(agent_response) < 30:
        return

    try:
        await asyncio.to_thread(
            client.add,
            [
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": agent_response}
            ],
            user_id=USER_ID
        )
    except Exception as e:
        print(f"[mem0] save_exchange failed (silenced): {e}")


async def save_fact(fact: str, category: str = "business"):
    """Explicitly save a key fact. Useful for /remember commands."""
    client = _get_client()
    if not client:
        return

    try:
        await asyncio.to_thread(
            client.add,
            [{"role": "user", "content": f"Remember this: {fact}"}],
            user_id=USER_ID
        )
        print(f"[mem0] Saved fact: {fact[:60]}")
    except Exception as e:
        print(f"[mem0] save_fact failed (silenced): {e}")


async def search_memory(query: str, limit: int = 5) -> list[dict]:
    """Search all of Jacob's memory. Returns list of {content, score} dicts."""
    client = _get_client()
    if not client:
        return []

    try:
        results = await asyncio.to_thread(
            client.search, query, user_id=USER_ID, limit=limit
        )
        return [
            {"content": r.get("memory", ""), "score": r.get("score", 0)}
            for r in (results or [])
            if r.get("memory")
        ]
    except Exception as e:
        print(f"[mem0] search_memory failed (silenced): {e}")
        return []


async def get_all_memories() -> list[str]:
    """Return all stored memories for Jacob (for /memory command)."""
    client = _get_client()
    if not client:
        return []

    try:
        results = await asyncio.to_thread(client.get_all, user_id=USER_ID)
        return [r.get("memory", "") for r in (results or []) if r.get("memory")]
    except Exception as e:
        print(f"[mem0] get_all_memories failed (silenced): {e}")
        return []


async def delete_memory(memory_id: str) -> bool:
    """Delete a specific memory by ID."""
    client = _get_client()
    if not client:
        return False

    try:
        await asyncio.to_thread(client.delete, memory_id)
        return True
    except Exception as e:
        print(f"[mem0] delete failed: {e}")
        return False

"""
BELMONT OPS - ZEP MEMORY LAYER
Persistent temporal knowledge graph for Jacob's business context.
Remembers clients, jobs, decisions, preferences across all sessions.
"""

import os
from datetime import datetime
from typing import Optional
from zep_cloud.client import AsyncZep
from zep_cloud.types import Message

ZEP_API_KEY = os.getenv("ZEP_API_KEY")
USER_ID = os.getenv("ZEP_USER_ID", "jacob_cota")

# Zep session IDs by agent type
SESSION_PREFIX = "belmont"


def get_client() -> AsyncZep:
    return AsyncZep(api_key=ZEP_API_KEY)


async def ensure_user():
    """Create Jacob's user profile in Zep if it doesn't exist. Non-fatal — bot works without memory."""
    zep = get_client()
    try:
        await zep.user.get(USER_ID)
    except Exception:
        try:
            await zep.user.add(
                user_id=USER_ID,
                first_name="Jacob",
                last_name="Cota",
                email="jacob.cota1@gmail.com",
                metadata={
                    "company": "Belmont & Co Fine Homes & Renovations",
                    "role": "Co-founder",
                    "location": "Red Deer, Alberta",
                    "focus": "premium renovations, custom homes, development"
                }
            )
        except Exception as e:
            print(f"[Zep] ensure_user failed (non-fatal): {e}")


async def get_session_id(agent_type: str, chat_id: str) -> str:
    """Get or create a Zep session for a given agent + Telegram chat."""
    return f"{SESSION_PREFIX}_{agent_type}_{chat_id}"


async def ensure_session(session_id: str, agent_type: str):
    """Create Zep session if it doesn't exist. Non-fatal — bot works without memory."""
    zep = get_client()
    try:
        await zep.memory.get_session(session_id)
    except Exception:
        try:
            await zep.memory.add_session(
                session_id=session_id,
                user_id=USER_ID,
                metadata={"agent_type": agent_type, "created": datetime.utcnow().isoformat()}
            )
        except Exception as e:
            print(f"[Zep] ensure_session failed (non-fatal): {e}")


async def load_memory(session_id: str, query: str = None) -> str:
    """
    Load relevant memory context for a session.
    Returns formatted string ready to inject into system prompt.
    """
    zep = get_client()
    context_parts = []

    try:
        # Get conversation summary for this session
        memory = await zep.memory.get(session_id, lastn=10)
        if memory.summary:
            context_parts.append(f"RECENT SESSION SUMMARY:\n{memory.summary.content}")

        # Semantic search across all memory if query given
        if query:
            results = await zep.memory.search_sessions(
                user_id=USER_ID,
                text=query,
                limit=5
            )
            if results and results.results:
                relevant = []
                for r in results.results:
                    if r.message and r.score > 0.7:
                        relevant.append(f"- {r.message.content}")
                if relevant:
                    context_parts.append("RELEVANT MEMORY:\n" + "\n".join(relevant))

        # Get facts about Jacob stored by previous sessions
        facts = await zep.user.get_facts(USER_ID)
        if facts and facts.facts:
            fact_lines = [f"- {f.fact}" for f in facts.facts[:15]]
            context_parts.append("KNOWN FACTS ABOUT JACOB & BELMONT:\n" + "\n".join(fact_lines))

    except Exception as e:
        context_parts.append(f"[Memory load error: {e}]")

    return "\n\n".join(context_parts) if context_parts else ""


async def save_exchange(session_id: str, user_msg: str, agent_response: str):
    """Save a conversation exchange to Zep memory."""
    zep = get_client()
    try:
        await zep.memory.add(
            session_id=session_id,
            messages=[
                Message(role_type="user", content=user_msg, role="Jacob"),
                Message(role_type="assistant", content=agent_response, role="Belmont Agent")
            ]
        )
    except Exception as e:
        print(f"Memory save error: {e}")


async def save_fact(fact: str, category: str = "business"):
    """Explicitly save a key fact about Jacob or Belmont to long-term memory."""
    zep = get_client()
    try:
        # Add as a structured fact on the user
        await zep.user.add_facts(
            user_id=USER_ID,
            facts=[{"fact": fact, "category": category, "created_at": datetime.utcnow().isoformat()}]
        )
    except Exception as e:
        print(f"Fact save error: {e}")


async def search_memory(query: str, limit: int = 5) -> list[dict]:
    """Search all of Jacob's memory for relevant context."""
    zep = get_client()
    try:
        results = await zep.memory.search_sessions(
            user_id=USER_ID,
            text=query,
            limit=limit
        )
        if results and results.results:
            return [
                {"content": r.message.content, "score": r.score, "session": r.session_id}
                for r in results.results
                if r.message and r.score > 0.6
            ]
    except Exception as e:
        print(f"Memory search error: {e}")
    return []

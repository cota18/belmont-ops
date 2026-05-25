"""
BELMONT OPS - SHARED MUTABLE STATE
Used by main.py (webhook handler) and scheduler.py (cron jobs)
to coordinate snooze windows and similar transient state.
Resets on redeploy — acceptable for short-lived DND windows.
"""

from datetime import datetime, timedelta
from typing import Optional

_snooze_until: dict = {}


def set_snooze(chat_id: str, hours: float) -> datetime:
    """Set a snooze deadline for a chat. Returns the deadline."""
    until = datetime.now() + timedelta(hours=hours)
    _snooze_until[str(chat_id)] = until
    return until


def clear_snooze(chat_id: str):
    """Clear snooze for a chat."""
    _snooze_until.pop(str(chat_id), None)


def is_snoozed(chat_id: str) -> bool:
    """Check if a chat is currently within a snooze window. Auto-expires."""
    until = _snooze_until.get(str(chat_id))
    if not until:
        return False
    if datetime.now() >= until:
        _snooze_until.pop(str(chat_id), None)
        return False
    return True


def get_snooze_deadline(chat_id: str) -> Optional[datetime]:
    """Get the snooze deadline for a chat, or None if not snoozed."""
    return _snooze_until.get(str(chat_id))

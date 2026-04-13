"""Conversation history persistence — saves/loads to a local JSON file.

Allows chat history to survive Streamlit page refreshes and server restarts.
History is stored in `.chat_history.json` at the project root. For a local
single-user tool this is the simplest, dependency-free approach.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

_HISTORY_FILE = Path(__file__).parent.parent / ".chat_history.json"
_MAX_PERSISTED_MESSAGES = 200  # cap to keep the file manageable


def load_history() -> List[dict]:
    """Load conversation history from disk. Returns [] if file absent or corrupt."""
    try:
        if _HISTORY_FILE.exists():
            data = json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception as e:
        logger.warning("Could not load chat history from %s: %s", _HISTORY_FILE, e)
    return []


def save_history(history: List[dict]) -> None:
    """Persist conversation history to disk. Silently ignores write errors."""
    try:
        trimmed = history[-_MAX_PERSISTED_MESSAGES:]
        _HISTORY_FILE.write_text(
            json.dumps(trimmed, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("Could not save chat history to %s: %s", _HISTORY_FILE, e)


def clear_history() -> None:
    """Delete the persisted history file."""
    try:
        if _HISTORY_FILE.exists():
            _HISTORY_FILE.unlink()
    except Exception as e:
        logger.warning("Could not clear chat history: %s", e)

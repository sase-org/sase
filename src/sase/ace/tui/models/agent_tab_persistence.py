"""Versioned persistence for the active agent tab (phase sase-1bc.6.1.3).

The TUI owns lifecycle scheduling; this module is synchronous and
side-effect free except for its explicit load/save functions so callers
can run all file and JSON work through ``asyncio.to_thread``.

Schema version 1 stores ``{"active": <token>}`` where the token is one of
``default``, ``machine:<id>``, or ``named:<name>`` (see
:func:`sase.core.agent_tab.agent_tab_key_token`). Unresolved-machine keys
have no token and are never persisted. Loading fails open to ``None``
(no persisted selection), letting the startup-selection order decide.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from sase.core.agent_tab import (
    AgentTabKey,
    agent_tab_key_token,
    parse_agent_tab_key_token,
)
from sase.core.paths import sase_home

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
FILENAME = "ace_agents_tab_state.json"
MAX_FILE_BYTES = 4 * 1024


def agent_tab_state_path() -> Path:
    """Return the global ACE active-agent-tab state path."""
    return sase_home() / FILENAME


def load_active_agent_tab(path: Path | None = None) -> AgentTabKey | None:
    """Load the persisted active tab key, or None when absent/invalid.

    Missing files, oversized files, malformed JSON, wrong schema versions,
    and unparseable tokens all fail open to None. Unresolved-machine keys
    can never round-trip (they have no token), so they never load either.
    """
    state_path = path or agent_tab_state_path()
    try:
        with state_path.open("rb") as stream:
            raw_bytes = stream.read(MAX_FILE_BYTES + 1)
    except FileNotFoundError:
        log.debug("Active agent tab state is missing: %s", state_path)
        return None
    except OSError:
        log.warning(
            "Unable to read active agent tab state: %s", state_path, exc_info=True
        )
        return None
    if len(raw_bytes) > MAX_FILE_BYTES:
        log.warning("Ignoring oversized active agent tab state: %s", state_path)
        return None
    try:
        decoded = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        log.warning(
            "Ignoring malformed active agent tab state: %s", state_path, exc_info=True
        )
        return None
    if not isinstance(decoded, dict):
        log.warning("Ignoring malformed active agent tab state: %s", state_path)
        return None
    if decoded.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        log.warning(
            "Ignoring active agent tab state with unsupported schema: %s", state_path
        )
        return None
    key = parse_agent_tab_key_token(decoded.get("active"))
    if key is None:
        log.debug("No valid persisted active agent tab in %s", state_path)
        return None
    if key.kind == "unresolved_machine":
        return None
    return key


def save_active_agent_tab(key: AgentTabKey, path: Path | None = None) -> None:
    """Atomically persist *key* using a same-directory temporary file.

    Unresolved-machine keys have no token and are silently skipped.
    """
    token = agent_tab_key_token(key)
    if token is None:
        return
    state_path = path or agent_tab_state_path()
    payload = json.dumps(
        {"schema_version": SCHEMA_VERSION, "active": token},
        separators=(",", ":"),
        sort_keys=True,
    )
    state_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=state_path.parent,
        prefix=f".{state_path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            try:
                os.fsync(stream.fileno())
            except OSError:
                pass
        os.replace(temporary, state_path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def serialize_active_agent_tab(key: AgentTabKey) -> dict[str, Any]:
    """Return the JSON-serializable payload for *key* (tests only)."""
    token = agent_tab_key_token(key)
    return {"schema_version": SCHEMA_VERSION, "active": token}


__all__ = [
    "FILENAME",
    "MAX_FILE_BYTES",
    "SCHEMA_VERSION",
    "agent_tab_state_path",
    "load_active_agent_tab",
    "save_active_agent_tab",
    "serialize_active_agent_tab",
]

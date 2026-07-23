"""Shared types, regexes, and helpers for agent name resolution.

The dismissed-name helpers (``DISMISSED_NAME_PREFIX_RE``, ``is_dismissed_prefixed``,
``add_dismissed_prefix``, ``strip_dismissed_prefix``) live here because
lookup, migration, and old dismissed-bundle compatibility still need to parse
names produced by the previous dismissal-prefix model.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.core.agent_identity_facade import AgentIdentitySnapshot


class AgentRefError(Exception):
    """Raised when an @name agent reference cannot be resolved."""


class NameCollisionError(ValueError):
    """Raised when an explicit repeat-name base conflicts with existing agents."""


class ImportedNameCollisionError(NameCollisionError):
    """Typed collision between an imported claim and durable registry state."""

    def __init__(
        self,
        name: str,
        *,
        reason: str,
        existing: dict[str, object] | None = None,
    ) -> None:
        self.name = name
        self.reason = reason
        self.existing = existing
        super().__init__(f"imported agent name '{name}' collides: {reason}")


# Auto-name prefix: the lowercase letter/digit segment before the first ``.``
# in an agent name or workflow name. The base is intentionally restricted to
# names reachable by the auto-name sequence
# (``0``, ``1``, ..., ``z``, ``00``, ``01``, ...) so they are extracted by
# ``_get_active_agent_names``. Multi-segment user bases like ``sase-z``
# are already reserved via the ``workflow_name`` path.
_AUTO_NAME_PREFIX_RE = re.compile(r"^([a-z0-9]+)\.")

DISMISSED_NAME_PREFIX_RE = re.compile(r"^(\d{6})\.")


def extract_auto_name_prefix(
    *values: object,
    identity: AgentIdentitySnapshot | None = None,
) -> str | None:
    """Return the longest auto-name prefix before the first ``.`` in any value."""
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        present_agent_name,
    )

    if identity is None:
        identity = AgentIdentitySnapshot.current()
    best: str | None = None
    for v in values:
        if not isinstance(v, str):
            continue
        m = _AUTO_NAME_PREFIX_RE.match(present_agent_name(v, identity))
        if m is None:
            continue
        candidate = m.group(1)
        if best is None or len(candidate) > len(best):
            best = candidate
    return best


@dataclass
class NamedAgent:
    """A named agent found in the artifacts directory."""

    name: str
    artifacts_dir: str
    is_done: bool
    outcome: str | None


def is_process_alive(meta: dict[str, object], artifact_dir: Path) -> bool:
    """Check if an agent's process is still running.

    Checks the PID from ``agent_meta.json`` (preferred) or
    ``running.json`` (fallback for older home-mode agents).
    Returns ``False`` if no PID can be found or the process is dead.
    """
    pid = meta.get("pid")

    # Fallback: home-mode agents store PID in running.json
    if pid is None:
        running_path = artifact_dir / "running.json"
        if running_path.exists():
            try:
                with open(running_path, encoding="utf-8") as f:
                    running_data = json.load(f)
                pid = running_data.get("pid")
            except (json.JSONDecodeError, OSError):
                pass

    if not isinstance(pid, int):
        return False
    if pid <= 1:
        return False

    # If the agent was explicitly stopped, it's dead regardless of PID state
    if meta.get("stopped_at"):
        return False

    # Delegate zombie detection to the shared helper
    from sase.ace.hooks.processes import is_process_running

    if not is_process_running(pid):
        return False

    # Guard against PID recycling: verify the process is actually a sase agent
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
        if b"sase" not in cmdline and b"python" not in cmdline:
            return False
    except (FileNotFoundError, PermissionError, OSError):
        pass

    return True


def is_dismissed_prefixed(name: str) -> bool:
    """Return ``True`` iff *name* starts with a ``YYmmdd.`` dismissal prefix."""
    return DISMISSED_NAME_PREFIX_RE.match(name) is not None


def add_dismissed_prefix(name: str, completion_date: date | datetime) -> str:
    """Return *name* prefixed with ``YYmmdd.`` for *completion_date*.

    Idempotent: if *name* is already dismissal-prefixed, return it unchanged
    (the caller's date is ignored in that case).
    """
    if is_dismissed_prefixed(name):
        return name
    if isinstance(completion_date, datetime):
        completion_date = completion_date.date()
    return f"{completion_date.strftime('%y%m%d')}.{name}"


def strip_dismissed_prefix(name: str) -> str:
    """Return *name* with its leading ``YYmmdd.`` dismissal prefix removed.

    Strips at most one prefix and only the canonical six-digit form; names
    without a matching prefix are returned unchanged. Any collision suffix
    on the returned base is preserved.
    """
    m = DISMISSED_NAME_PREFIX_RE.match(name)
    if m is None:
        return name
    return name[m.end() :]

"""Best-effort, coalescing maintenance hooks for the agent artifact index.

Phase 4 of ``sase-3r`` (Fast Agents Tab Disk Loading). The persistent
``~/.sase/agent_artifact_index.sqlite`` only stays useful for the
visibility-aware Tier 1 inbox query if it tracks the artifact tree as
markers and dismissal state change. This adapter wraps the Rust facade
in :mod:`sase.core.agent_scan_facade` so:

- Lifecycle marker writes (launch / running / waiting / done) can upsert
  the affected artifact directory in one call.
- Dismiss / kill cleanup paths can update dismissal visibility and
  delete index rows when artifacts are removed.
- Revive paths can clear dismissal visibility and upsert restored rows.
- Startup can synchronize the dismissal projection from the legacy
  ``~/.sase/dismissed_agents.json`` before the first inbox query.

Every entry point is best-effort: missing/stale Rust bindings, OS errors,
malformed sqlite, etc. are caught and logged at ``debug`` so callers in
the Textual event loop never see an exception.

In-process coalescing
---------------------

Active agents (Claude/Gemini/Codex hooks) can write the same
``agent_meta.json`` many times per second. Each upsert reparses the
artifact directory and rewrites one sqlite row. To keep this from
turning into a write storm we suppress repeat upserts for the same
``artifact_dir`` inside :data:`_COALESCE_WINDOW_SECONDS`. The suppression
is per-process and per-directory; the first call after the window goes
through. Lifecycle transitions that need to land immediately pass
``coalesce=False``.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING
from collections.abc import Iterable

from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    delete_agent_artifact_index_row,
    replace_dismissed_agent_visibility,
    upsert_agent_artifact_index_row,
)
from sase.core.agent_scan_wire import DismissedAgentIdentityWire

if TYPE_CHECKING:
    from sase.ace.tui.models.agent import AgentType

logger = logging.getLogger(__name__)

_COALESCE_WINDOW_SECONDS = 1.0

_state_lock = threading.Lock()
_last_upsert_time: dict[str, float] = {}
_DISMISSED_SIGNATURE_UNSET = object()
_last_dismissed_signature: object = _DISMISSED_SIGNATURE_UNSET


def _default_projects_root() -> Path:
    return Path.home() / ".sase" / "projects"


def _default_dismissed_file() -> Path:
    return Path.home() / ".sase" / "dismissed_agents.json"


def _resolve_index_path(index_path: Path | str | None) -> Path:
    if index_path is None:
        return default_agent_artifact_index_path()
    return Path(index_path)


def _identity_to_wire(
    identity: tuple[AgentType | str, str, str | None],
) -> DismissedAgentIdentityWire:
    agent_type = identity[0]
    agent_type_value = getattr(agent_type, "value", None) or str(agent_type)
    return DismissedAgentIdentityWire(
        agent_type=agent_type_value,
        cl_name=identity[1],
        raw_suffix=identity[2],
    )


def upsert_artifact_dir(
    artifact_dir: str | os.PathLike[str],
    *,
    projects_root: Path | str | None = None,
    index_path: Path | str | None = None,
    coalesce: bool = True,
) -> bool:
    """Upsert one artifact directory into the persistent index.

    Returns ``True`` when the call was made (or intentionally coalesced)
    and ``False`` when an exception was suppressed. Callers should not
    branch on the return value beyond logging; the index is eventually
    consistent through the rebuild path.
    """

    artifact_dir_str = os.fspath(artifact_dir)
    index = _resolve_index_path(index_path)
    if not index.is_file():
        # Nothing to update — the rebuild worker will populate the index
        # when it next runs.
        return True

    now = time.monotonic()
    if coalesce:
        with _state_lock:
            last = _last_upsert_time.get(artifact_dir_str)
            if last is not None and (now - last) < _COALESCE_WINDOW_SECONDS:
                return True
            _last_upsert_time[artifact_dir_str] = now
    else:
        with _state_lock:
            _last_upsert_time[artifact_dir_str] = now

    root = (
        Path(projects_root) if projects_root is not None else _default_projects_root()
    )
    try:
        upsert_agent_artifact_index_row(index, root, artifact_dir_str)
        return True
    except Exception as exc:  # noqa: BLE001  best-effort
        logger.debug(
            "agent_artifact_index upsert failed: artifact_dir=%s err=%s",
            artifact_dir_str,
            exc,
        )
        return False


def delete_artifact_dir(
    artifact_dir: str | os.PathLike[str],
    *,
    index_path: Path | str | None = None,
) -> bool:
    """Remove one artifact directory row from the persistent index."""

    artifact_dir_str = os.fspath(artifact_dir)
    index = _resolve_index_path(index_path)
    if not index.is_file():
        return True

    with _state_lock:
        _last_upsert_time.pop(artifact_dir_str, None)

    try:
        delete_agent_artifact_index_row(index, artifact_dir_str)
        return True
    except Exception as exc:  # noqa: BLE001  best-effort
        logger.debug(
            "agent_artifact_index delete failed: artifact_dir=%s err=%s",
            artifact_dir_str,
            exc,
        )
        return False


def sync_dismissed_visibility(
    dismissed: Iterable[tuple[AgentType | str, str, str | None]],
    *,
    index_path: Path | str | None = None,
) -> bool:
    """Atomically replace the sidecar contents with *dismissed*."""

    index = _resolve_index_path(index_path)
    if not index.is_file():
        return True

    identities = [_identity_to_wire(identity) for identity in dismissed]
    try:
        replace_dismissed_agent_visibility(index, identities)
        return True
    except Exception as exc:  # noqa: BLE001  best-effort
        logger.debug(
            "agent_artifact_index sync_dismissed_visibility failed: err=%s", exc
        )
        return False


def maybe_sync_dismissed_from_file(
    *,
    dismissed_file: Path | str | None = None,
    index_path: Path | str | None = None,
    force: bool = False,
) -> bool:
    """Sync the index sidecar from ``~/.sase/dismissed_agents.json``.

    Cheap: returns immediately when the JSON file's ``(st_mtime_ns,
    st_size)`` matches the last sync signature. Called from the TUI loader
    before the first inbox query so the visibility-aware query sees any
    dismissals that were written by a previous session or sibling process.
    """

    global _last_dismissed_signature

    dismissed_path = (
        Path(dismissed_file)
        if dismissed_file is not None
        else _default_dismissed_file()
    )
    index = _resolve_index_path(index_path)
    if not index.is_file():
        return True

    try:
        if dismissed_path.exists():
            stat = dismissed_path.stat()
            signature: tuple[int, int] | None = (stat.st_mtime_ns, stat.st_size)
        else:
            signature = None
    except OSError as exc:
        logger.debug("dismissed_agents.json stat failed: err=%s", exc)
        return False

    with _state_lock:
        if not force and signature == _last_dismissed_signature:
            return True

    from sase.ace.dismissed_agents_state import load_dismissed_agents

    try:
        dismissed = load_dismissed_agents(dismissed_path)
    except Exception as exc:  # noqa: BLE001  do not wipe sidecar on bad legacy file
        logger.debug("dismissed_agents.json load failed: err=%s", exc)
        return False
    ok = sync_dismissed_visibility(dismissed, index_path=index)
    if ok:
        with _state_lock:
            _last_dismissed_signature = signature
    return ok


__all__ = [
    "delete_artifact_dir",
    "maybe_sync_dismissed_from_file",
    "sync_dismissed_visibility",
    "upsert_artifact_dir",
]

"""Registry of live SASE TUI sessions.

One running TUI process is one *session*. The canonical session id is the
existing toast-session id (``<YYYYMMDDTHHMMSSZ>-<pid>``) so session-scoped
records — background tasks, toast history — join on a single value.

This registry is deliberately Python rather than Rust core: it is OS
process-liveness plumbing (pid plus process start time, ``/proc`` reads) with
no cross-surface domain rules, matching the precedent in
:mod:`sase.ace.hooks.processes` and :mod:`sase.axe.maintenance`.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.ace.hooks.processes import is_process_running
from sase.core.paths import sase_subdir
from sase.core.state_write_guard import best_effort_test_state_write_allowed
from sase.logs.toast_log import current_toast_session

log = logging.getLogger(__name__)

SESSIONS_SUBDIR = "sessions"
SESSION_KIND_ACE = "ace"

_STATE_WRITE_CATEGORY = "sessions"
_PROC_BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")

CURRENT_SESSION_REF = "current"
LATEST_SESSION_REF = "latest"
NO_SESSION_REF = "none"


class SessionRefError(ValueError):
    """A ``--session`` reference matched no live session, or too many."""


@dataclass(frozen=True)
class SessionIdentity:
    """Identity of one live SASE session."""

    session_id: str
    kind: str
    pid: int
    started_at: str
    project: str | None = None
    workspace_num: int | None = None
    cwd: str | None = None
    title: str | None = None


def sessions_dir() -> Path:
    """Return the directory holding live-session records."""
    return sase_subdir(SESSIONS_SUBDIR)


def session_record_path(session_id: str) -> Path:
    """Return the record path for one session id."""
    return sessions_dir() / f"{session_id}.json"


def current_session_id() -> str:
    """Return this process's canonical session id.

    Reuses the toast-session id rather than forking the format, so a task row
    and a toast row from the same TUI run share one id.
    """
    return current_toast_session().session_id


def register_session(
    kind: str = SESSION_KIND_ACE,
    *,
    project: str | None = None,
    workspace_num: int | None = None,
    cwd: str | None = None,
    title: str | None = None,
) -> SessionIdentity | None:
    """Record this process as a live session.

    Registration is best effort: a failed write logs at debug level and
    returns ``None``, exactly like toast recording. It must never break TUI
    startup.
    """
    try:
        session = current_toast_session()
        identity = SessionIdentity(
            session_id=session.session_id,
            kind=kind,
            pid=session.pid,
            started_at=session.session_started_at,
            project=project,
            workspace_num=workspace_num,
            cwd=cwd if cwd is not None else os.getcwd(),
            title=title,
        )
        record = _to_record(identity)
        process_identity = _process_identity(identity.pid)
        if process_identity is not None:
            record["process_identity"] = process_identity
        _write_record(session_record_path(identity.session_id), record)
        return identity
    except Exception:
        log.debug("session registration failed", exc_info=True)
        return None


def unregister_session(session_id: str | None = None) -> bool:
    """Remove a session record, defaulting to this process's own.

    Returns:
        True if a record was removed, False otherwise.
    """
    try:
        resolved = session_id or current_session_id()
        session_record_path(resolved).unlink()
        return True
    except FileNotFoundError:
        return False
    except Exception:
        log.debug("session unregistration failed", exc_info=True)
        return False


def live_sessions() -> list[SessionIdentity]:
    """Return every live session, newest first.

    Records whose process is gone — or whose pid has been recycled by a
    different process — are dropped and their files opportunistically deleted.
    """
    directory = sessions_dir()
    try:
        entries = sorted(directory.glob("*.json"))
    except OSError:
        return []

    sessions: list[SessionIdentity] = []
    for path in entries:
        record = _read_record(path)
        identity = _identity_from_record(record) if record is not None else None
        if identity is None or not _record_is_live(record or {}, identity):
            _remove_stale_record(path)
            continue
        sessions.append(identity)

    sessions.sort(key=lambda item: (item.started_at, item.pid), reverse=True)
    return sessions


def latest_session() -> SessionIdentity | None:
    """Return the most recently started live session, if any."""
    sessions = live_sessions()
    return sessions[0] if sessions else None


def resolve_session_ref(ref: str | None) -> SessionIdentity | None:
    """Resolve a ``--session`` reference to a live session.

    ``ref`` accepts ``current``, ``latest``, ``none``, a full session id, a
    short handle, or a unique session-id prefix. ``current`` (also the default
    for ``ref=None``) resolves to this process's own session when it has one,
    then falls back to the latest live session, then to no session at all —
    the chain that lets an epic approved from Telegram land in the TUI the
    user is actually looking at.

    Raises:
        SessionRefError: The reference matched no live session, or was
            ambiguous. The message lists the candidates.
    """
    normalized = (ref or CURRENT_SESSION_REF).strip()
    if not normalized or normalized.lower() == CURRENT_SESSION_REF:
        return _resolve_current()
    lowered = normalized.lower()
    if lowered == NO_SESSION_REF:
        return None
    if lowered == LATEST_SESSION_REF:
        return latest_session()

    sessions = live_sessions()
    for identity in sessions:
        if identity.session_id == normalized:
            return identity

    matches = [
        identity
        for identity in sessions
        if identity.session_id.startswith(normalized)
        or _handle_of(identity.session_id) == lowered
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise SessionRefError(
            f"no live session matches {normalized!r}{_candidate_suffix(sessions)}"
        )
    raise SessionRefError(f"{normalized!r} is ambiguous{_candidate_suffix(matches)}")


def _resolve_current() -> SessionIdentity | None:
    own_id = current_session_id()
    for identity in live_sessions():
        if identity.session_id == own_id:
            return identity
    return latest_session()


def _candidate_suffix(sessions: list[SessionIdentity]) -> str:
    if not sessions:
        return "; no SASE sessions are running"
    names = ", ".join(
        f"{_handle_of(identity.session_id)} ({identity.session_id})"
        for identity in sessions
    )
    return f"; candidates: {names}"


def _handle_of(session_id: str) -> str:
    from .display import short_session_handle

    return short_session_handle(session_id)


def _to_record(identity: SessionIdentity) -> dict[str, Any]:
    return {
        "session_id": identity.session_id,
        "kind": identity.kind,
        "pid": identity.pid,
        "started_at": identity.started_at,
        "project": identity.project,
        "workspace_num": identity.workspace_num,
        "cwd": identity.cwd,
        "title": identity.title,
    }


def _identity_from_record(record: dict[str, Any]) -> SessionIdentity | None:
    """Build an identity from a record, tolerating junk like toast history."""
    session_id = record.get("session_id")
    pid = record.get("pid")
    started_at = record.get("started_at")
    if not isinstance(session_id, str) or not session_id:
        return None
    if not isinstance(pid, int) or pid <= 0:
        return None
    if not isinstance(started_at, str) or not started_at:
        return None
    kind = record.get("kind")
    workspace_num = record.get("workspace_num")
    return SessionIdentity(
        session_id=session_id,
        kind=kind if isinstance(kind, str) and kind else SESSION_KIND_ACE,
        pid=pid,
        started_at=started_at,
        project=_optional_str(record.get("project")),
        workspace_num=workspace_num if isinstance(workspace_num, int) else None,
        cwd=_optional_str(record.get("cwd")),
        title=_optional_str(record.get("title")),
    )


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _record_is_live(record: dict[str, Any], identity: SessionIdentity) -> bool:
    """Return whether the recorded process is still the one that registered."""
    if not is_process_running(identity.pid):
        return False
    recorded = record.get("process_identity")
    if not isinstance(recorded, dict):
        return True
    current = _process_identity(identity.pid)
    if current is None:
        return True
    return recorded == current


def _process_identity(pid: int) -> dict[str, Any] | None:
    """Return a Linux process identity that changes when a PID is recycled."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        close_paren = stat.rfind(")")
        if close_paren < 0:
            return None
        # The tail starts at field 3 (state); process start time is field 22.
        fields = stat[close_paren + 1 :].split()
        start_ticks = int(fields[19])
    except (IndexError, OSError, ValueError):
        return None

    identity: dict[str, Any] = {"start_ticks": start_ticks}
    try:
        boot_id = _PROC_BOOT_ID_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        boot_id = ""
    if boot_id:
        identity["boot_id"] = boot_id
    return identity


def _write_record(path: Path, record: dict[str, Any]) -> None:
    if not best_effort_test_state_write_allowed(path, category=_STATE_WRITE_CATEGORY):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".json.tmp")
    try:
        temp_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        temp_path.rename(path)
    except OSError:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise


def _read_record(path: Path) -> dict[str, Any] | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _remove_stale_record(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass

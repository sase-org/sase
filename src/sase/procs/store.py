"""Python facade over the Rust durable proc store."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.config.core import get_proc_history_limit
from sase.core.rust import require_rust_binding

from ._migration import ensure_procs_migrated
from .logs import delete_proc_logs
from .models import (
    Proc,
    ProcAppendOutcome,
    ProcPruneOutcome,
    ProcStoreSnapshot,
    ProcUpdate,
    ProcUpdateOutcome,
)
from .paths import proc_store_path


class ProcStoreLockTimeoutError(TimeoutError):
    """The proc-store lock stayed busy past its bounded wait."""


class _AnySession:
    pass


_ANY_SESSION = _AnySession()


def read_procs(
    *,
    path: Path | str | None = None,
    status: str | Collection[str] | None = None,
    kind: str | Collection[str] | None = None,
    session_id: str | None | _AnySession = _ANY_SESSION,
    project: str | None = None,
    tag: str | None = None,
    query: str | None = None,
) -> list[Proc]:
    """Read newest-first procs, applying the shared CLI/TUI filters."""
    payload: Mapping[str, Any] = _call_binding(
        "read_procs_snapshot", str(path or proc_store_path())
    )
    snapshot = ProcStoreSnapshot.from_dict(payload)
    return filter_procs(
        snapshot.procs,
        status=status,
        kind=kind,
        session_id=session_id,
        project=project,
        tag=tag,
        query=query,
    )


def get_proc(proc_id: str, *, path: Path | str | None = None) -> Proc | None:
    """Return the exact proc id, or ``None`` when it is absent."""
    return next(
        (proc for proc in read_procs(path=path) if proc.proc_id == proc_id),
        None,
    )


def append_proc(
    proc: Proc | Mapping[str, Any],
    *,
    path: Path | str | None = None,
    history_limit: int | None = None,
) -> ProcAppendOutcome:
    """Append a proc, enforce retention, and remove logs pruned with rows."""
    record = proc if isinstance(proc, Proc) else Proc.from_dict(proc)
    payload: Mapping[str, Any] = _call_binding(
        "append_proc",
        str(path or proc_store_path()),
        record.to_dict(),
        history_limit if history_limit is not None else get_proc_history_limit(),
    )
    outcome = ProcAppendOutcome.from_dict(payload)
    delete_proc_logs(outcome.pruned_proc_ids)
    return outcome


def update_proc(
    update: ProcUpdate | Mapping[str, Any] | str,
    *,
    path: Path | str | None = None,
    **changes: Any,
) -> ProcUpdateOutcome:
    """Apply a partial update; a string proc id accepts keyword changes."""
    if isinstance(update, str):
        record = ProcUpdate(proc_id=update, **changes)
    elif changes:
        raise TypeError("keyword changes require a string proc id")
    elif isinstance(update, ProcUpdate):
        record = update
    else:
        record = ProcUpdate.from_dict(update)
    payload: Mapping[str, Any] = _call_binding(
        "update_proc", str(path or proc_store_path()), record.to_dict()
    )
    return ProcUpdateOutcome.from_dict(payload)


def prune_procs(
    *,
    path: Path | str | None = None,
    history_limit: int | None = None,
) -> ProcPruneOutcome:
    """Enforce current retention and remove logs for every pruned row."""
    payload: Mapping[str, Any] = _call_binding(
        "prune_procs",
        str(path or proc_store_path()),
        history_limit if history_limit is not None else get_proc_history_limit(),
    )
    outcome = ProcPruneOutcome.from_dict(payload)
    delete_proc_logs(outcome.pruned_proc_ids)
    return outcome


def filter_procs(
    procs: Sequence[Proc],
    *,
    status: str | Collection[str] | None = None,
    kind: str | Collection[str] | None = None,
    session_id: str | None | _AnySession = _ANY_SESSION,
    project: str | None = None,
    tag: str | None = None,
    query: str | None = None,
) -> list[Proc]:
    """Apply the canonical exact-match fields and free-text proc query."""
    statuses = _value_set(status)
    kinds = _value_set(kind)
    needle = query.casefold() if query else None
    result: list[Proc] = []
    for proc in procs:
        if statuses is not None and proc.status not in statuses:
            continue
        if kinds is not None and proc.kind not in kinds:
            continue
        if session_id is not _ANY_SESSION and proc.session_id != session_id:
            continue
        if project is not None and proc.project != project:
            continue
        if tag is not None and tag not in proc.tags:
            continue
        if needle is not None and needle not in _search_text(proc).casefold():
            continue
        result.append(proc)
    return result


def _value_set(
    value: str | Collection[str] | None,
) -> frozenset[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return frozenset({value})
    return frozenset(value)


def _search_text(proc: Proc) -> str:
    return "\n".join(
        (
            proc.label,
            " ".join(proc.command),
            proc.cl_name or "",
        )
    )


def _call_binding(name: str, *args: Any) -> Any:
    ensure_procs_migrated()
    binding = require_rust_binding(name)
    try:
        return binding(*args)
    except Exception as exc:
        if isinstance(exc, TimeoutError) or type(exc).__name__ == (
            "ProcStoreLockTimeoutError"
        ):
            raise ProcStoreLockTimeoutError(str(exc)) from exc
        raise


__all__ = [
    "ProcStoreLockTimeoutError",
    "append_proc",
    "filter_procs",
    "get_proc",
    "prune_procs",
    "read_procs",
    "update_proc",
]

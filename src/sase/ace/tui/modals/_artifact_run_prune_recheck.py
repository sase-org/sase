"""Durable re-check submission for a blocked or missing ACE-run prune preview."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from sase.ace.tui.actions._durable_ops import (
    durable_fingerprint,
    durable_request_payload,
    sase_argv,
)
from sase.core.agent_artifact_run_prune_review import human_size
from sase.ops.names import ARTIFACT_PRUNE_RUNS_PREVIEW

PRUNE_CONCURRENCY_KEY = "artifact-run-prune"


def prune_is_running(app: object) -> bool:
    """Return True when a prune or re-check already holds the concurrency key."""

    projection_getter = getattr(app, "_effective_proc_projection", None)
    try:
        projection = projection_getter() if callable(projection_getter) else None
        if projection is None:
            projection = getattr(app, "_proc_projection", None)
        scope_conflict = getattr(projection, "scope_conflict", None)
        return (
            callable(scope_conflict)
            and scope_conflict((PRUNE_CONCURRENCY_KEY,)) is not None
        )
    except Exception:
        return False


def submit_run_prune_recheck(modal: Any) -> bool:
    """Submit the durable re-check proc. Returns True when a proc was queued."""

    app = modal.app
    if prune_is_running(app):
        modal._is_running = True
        modal._refresh_render()
        app.notify("ACE run pruning is already running.", severity="warning")
        return False
    submit = getattr(app, "_submit_durable_proc", None)
    if not callable(submit):
        app.notify("Durable prune queue is unavailable", severity="error")
        return False

    nonce = uuid4().hex
    proc = submit(
        sase_argv("artifact", "prune-runs", "--publish-preview", "--json"),
        operation=ARTIFACT_PRUNE_RUNS_PREVIEW,
        request=durable_request_payload(nonce=nonce),
        request_fingerprint=durable_fingerprint(ARTIFACT_PRUNE_RUNS_PREVIEW, nonce),
        concurrency_keys=(PRUNE_CONCURRENCY_KEY,),
        label="Re-check ACE run prune",
        display_name="Re-check ACE run prune",
        duplicate_message="ACE run pruning is already running",
        on_complete=lambda completion: _on_recheck_complete(app, completion),
        reload_on_complete=False,
        notify_on_complete=False,
    )
    if proc is None:
        return False
    app.notify(
        "↻ Re-checking ACE run prune protections…",
        severity="information",
    )
    modal.dismiss(None)
    return True


def _on_recheck_complete(app: object, completion: object) -> None:
    """Toast the re-check outcome and refresh the inbox badge."""

    payload = getattr(completion, "payload", None)
    success = bool(getattr(completion, "success", False))
    fields = payload if isinstance(payload, Mapping) else {}
    notify = getattr(app, "notify", None)
    if not callable(notify):
        return
    if not success:
        reason = (
            getattr(completion, "error", None)
            or getattr(completion, "message", None)
            or "the re-check did not complete"
        )
        notify(
            f"🧹 Re-check failed: {reason}. See the proc log.",
            severity="error",
        )
    else:
        notify(
            _recheck_success_toast(fields), severity=_recheck_success_severity(fields)
        )
    refresh = getattr(app, "_refresh_notification_count", None)
    if callable(refresh):
        refresh()


def _recheck_success_severity(fields: Mapping[str, object]) -> str:
    if _as_count(fields.get("unavailable_count"), 0) > 0:
        return "error"
    return "information"


def _recheck_success_toast(fields: Mapping[str, object]) -> str:
    unavailable = _as_count(fields.get("unavailable_count"), 0)
    if unavailable > 0:
        sources = fields.get("unavailable_sources") or ()
        first = ""
        if isinstance(sources, list | tuple) and sources:
            first = str(sources[0])
        suffix = f" ({first})" if first else ""
        return (
            f"🧹 Still paused: {unavailable} protection sources are unreadable"
            f"{suffix}. See the proc log."
        )
    selected = _as_count(fields.get("selected"), 0)
    if selected > 0:
        size = human_size(_as_count(fields.get("bytes"), 0))
        return (
            "🧹 Protections re-checked — a fresh preview is ready: "
            f"{selected:,} runs · {size}. Open it from the inbox."
        )
    return "🧹 Protections re-checked — nothing to prune."


def _as_count(value: object, default: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            pass
    return default


__all__ = [
    "PRUNE_CONCURRENCY_KEY",
    "prune_is_running",
    "submit_run_prune_recheck",
]

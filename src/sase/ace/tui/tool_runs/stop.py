"""Confirmed tool-run stop: copy, ancestor resolution, submit args (§3.11).

Pure helpers for the Admin Runs ``s`` key and the palette
"Stop live tool run" command. Nothing here touches SQLite, the store,
or the TUI: callers load runs (glance rows, briefs, or ``tool_run_show``)
and hand plain mappings in.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

LIVE_RUN_STATES = frozenset({"created", "running"})

_STOP_CONCURRENCY_PREFIX = "tool-stop:"


def short_run_id(run_id: str) -> str:
    """Return the 8-char run prefix used across stop copy and labels."""

    return (run_id or "")[:8]


def run_label(run: Mapping[str, Any]) -> str:
    """Return the human label for stop copy (brief/glance ``label`` first)."""

    label = str(run.get("label") or "").strip()
    if label:
        return label
    tool = str(run.get("tool_name") or "").strip()
    return tool or "ad-hoc"


def is_live_run(run: Mapping[str, Any]) -> bool:
    """Return whether *run* is still stoppable (created or running)."""

    return str(run.get("state") or "") in LIVE_RUN_STATES


def resolve_stoppable_ancestor(
    run: Mapping[str, Any],
    load_run: Callable[[str], Mapping[str, Any] | None],
    *,
    max_depth: int = 8,
) -> Mapping[str, Any]:
    """Follow ``parent_run_id`` to the outermost stoppable ancestor.

    Returns *run* itself when it has no parent. Stops at the deepest
    loadable ancestor: an unloadable parent keeps the last loaded run,
    so the confirm always names a real run. Cycles terminate on revisit.
    """

    current = run
    seen = {str(current.get("run_id") or "")}
    for _ in range(max_depth):
        parent_id = str(current.get("parent_run_id") or "").strip()
        if not parent_id or parent_id in seen:
            return current
        try:
            parent = load_run(parent_id)
        except Exception:
            return current
        if not isinstance(parent, dict) or not parent.get("run_id"):
            return current
        seen.add(parent_id)
        current = parent
    return current


def stop_confirm_copy(
    run: Mapping[str, Any],
    ancestor: Mapping[str, Any] | None = None,
) -> tuple[str, str]:
    """Return ``(title, message)`` for the stop confirm of *run*.

    Copy depends on the owner: inline agent runs warn about exit 143,
    monitor-owned runs warn the follow-up will not launch, proc-owned
    hand-offs warn the proc is killed, and nested runs resolve to the
    outermost stoppable ancestor first.
    """

    target = ancestor or run
    label = run_label(target)
    short = short_run_id(str(target.get("run_id") or ""))
    if ancestor is not None and str(ancestor.get("run_id") or "") != str(
        run.get("run_id") or ""
    ):
        parent_short = short_run_id(str(ancestor.get("run_id") or ""))
        return (
            "Stop Tool Run",
            f"This run belongs to run `{parent_short}`; stopping it stops both.",
        )
    owner_kind = str(target.get("owner_kind") or "")
    owner_id = str(target.get("owner_id") or "")
    if owner_kind == "monitor" and owner_id:
        return (
            "Stop Tool Run",
            f"Stop \u2692 {label} owned by monitor `{owner_id}`? "
            "The monitor stops and its follow-up agent will not launch.",
        )
    if owner_kind == "proc" and owner_id:
        return (
            "Stop Tool Run",
            f"Stop \u2692 {label}? Its hand-off proc is killed, "
            "and the run settles as stopped.",
        )
    return (
        "Stop Tool Run",
        f"Stop \u2692 {label} (run {short})? The agent's `sase tool run` "
        "exits 143 and it will see a failed check. The agent keeps running.",
    )


def stop_submit_label(run: Mapping[str, Any]) -> str:
    """Return the durable-proc display label for stopping *run*."""

    return (
        f"stop tool run {run_label(run)} ({short_run_id(str(run.get('run_id') or ''))})"
    )


def stop_concurrency_key(run_id: str) -> str:
    """Return the per-run concurrency key for stop submissions."""

    return f"{_STOP_CONCURRENCY_PREFIX}{run_id}"


__all__ = [
    "LIVE_RUN_STATES",
    "is_live_run",
    "resolve_stoppable_ancestor",
    "run_label",
    "short_run_id",
    "stop_concurrency_key",
    "stop_confirm_copy",
    "stop_submit_label",
]

"""Exact artifact-dir resolution for completion and pending-gate arrivals."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._notification_agent_targeting import (
    agent_artifact_dir,
    loaded_real_agent_roster,
)
from ._notification_matching import (
    is_active_agent_settlement_notification,
    is_active_pending_gate_refresh_notification,
    normalized_suffix,
    notification_family_root_suffix,
    notification_raw_suffix,
    pending_gate_notification_suffixes,
    active_completion_agent_keys,
)

if TYPE_CHECKING:
    from sase.notifications import Notification

    from ...models import Agent


def completion_notification_delta_dirs(
    app: Any,
    notifications: Iterable[Notification] | None = None,
) -> list[Path]:
    if notifications is None:
        snapshot = getattr(app, "_notification_snapshot_cache", None)
        cached = getattr(snapshot, "notifications", None)
        notifications = cached if isinstance(cached, list) else []
    notification_list = list(notifications)
    completion_keys = active_completion_agent_keys(notification_list)
    settlement_notifications = [
        notification
        for notification in notification_list
        if is_active_agent_settlement_notification(notification)
    ]
    if not completion_keys and not settlement_notifications:
        return []

    artifact_dirs: list[Path] = []
    seen: set[str] = set()
    resolved_keys: set[tuple[str, str | None]] = set()
    resolved_suffixes: set[str] = set()
    roster = loaded_real_agent_roster(app)
    agents_by_suffix: dict[str, Agent] = {}
    for agent in roster:
        suffix = normalized_suffix(agent.raw_suffix)
        if suffix and suffix not in agents_by_suffix:
            agents_by_suffix[suffix] = agent

    def add_artifact_dir(path: Path | None) -> bool:
        if path is None:
            return False
        key = str(path)
        if key in seen:
            return False
        seen.add(key)
        artifact_dirs.append(path)
        return True

    def add_agent_artifact_dir(agent: Agent) -> bool:
        return add_artifact_dir(agent_artifact_dir(agent))

    for agent in roster:
        agent_key = (agent.cl_name, agent.raw_suffix)
        cl_only = (agent.cl_name, None)
        matched = {key for key in (agent_key, cl_only) if key in completion_keys}
        if not matched:
            continue
        if add_agent_artifact_dir(agent):
            suffix = normalized_suffix(agent.raw_suffix)
            if suffix:
                resolved_suffixes.add(suffix)
        resolved_keys.update(matched)

    settlement_suffixes: set[str] = set()
    for notification in settlement_notifications:
        raw_suffix = notification_raw_suffix(notification)
        if raw_suffix is None:
            continue
        root_suffix = notification_family_root_suffix(notification)
        settlement_suffixes.add(raw_suffix)
        if root_suffix is not None:
            settlement_suffixes.add(root_suffix)
        resolved_suffixes.update(
            add_loaded_family_chain_artifact_dirs(
                agents_by_suffix,
                raw_suffix=raw_suffix,
                root_suffix=root_suffix,
                add_agent_artifact_dir=add_agent_artifact_dir,
            )
        )

    unresolved_suffixes = {
        raw_suffix
        for cl_name, raw_suffix in completion_keys
        if raw_suffix
        and (cl_name, raw_suffix) not in resolved_keys
        and (cl_name, None) not in resolved_keys
    }
    unresolved_suffixes.update(settlement_suffixes - resolved_suffixes)
    if unresolved_suffixes:
        from ...models.agent_loader import (
            artifact_dirs_for_normalized_timestamps,
            normalize_timestamps,
        )

        for extra in artifact_dirs_for_normalized_timestamps(
            normalize_timestamps(unresolved_suffixes)
        ):
            add_artifact_dir(extra)
    return artifact_dirs


def add_loaded_family_chain_artifact_dirs(
    agents_by_suffix: dict[str, Agent],
    *,
    raw_suffix: str,
    root_suffix: str | None,
    add_agent_artifact_dir: Callable[[Agent], bool],
) -> set[str]:
    """Add the loaded settled shell and ancestor family dirs, returning suffixes."""
    resolved: set[str] = set()
    current_suffix: str | None = raw_suffix
    visited: set[str] = set()
    while current_suffix and current_suffix not in visited:
        visited.add(current_suffix)
        agent = agents_by_suffix.get(current_suffix)
        if agent is None:
            break
        add_agent_artifact_dir(agent)
        resolved.add(current_suffix)
        if root_suffix is not None and current_suffix == root_suffix:
            break
        current_suffix = normalized_suffix(getattr(agent, "parent_timestamp", None))

    if root_suffix is not None and root_suffix not in resolved:
        root_agent = agents_by_suffix.get(root_suffix)
        if root_agent is not None:
            add_agent_artifact_dir(root_agent)
            resolved.add(root_suffix)
    return resolved


def pending_gate_notification_delta_dirs(
    app: Any,
    pending: Sequence[Notification],
) -> list[Path]:
    """Resolve exact family-chain dirs for active pending-review gate arrivals.

    Touches disk (``is_dir`` and the unloaded-timestamp scan), so it runs only
    from ``prepare_pending_gate_notification_refresh`` on the notification-poll
    worker; ``request_notification_agents_refresh`` consumes that result rather
    than re-resolving on the event loop. Does not call
    ``find_gate_shell_by_gate_id``; the indexed legacy fallback lives in the
    caller.
    """
    if not pending:
        return []

    artifact_dirs: list[Path] = []
    seen: set[str] = set()
    resolved_suffixes: set[str] = set()
    unresolved_suffixes: set[str] = set()
    roster = loaded_real_agent_roster(app)
    agents_by_suffix: dict[str, Agent] = {}
    for agent in roster:
        suffix = normalized_suffix(agent.raw_suffix)
        if suffix and suffix not in agents_by_suffix:
            agents_by_suffix[suffix] = agent

    def add_artifact_dir(path: Path | None) -> bool:
        if path is None:
            return False
        key = str(path)
        if key in seen:
            return False
        seen.add(key)
        artifact_dirs.append(path)
        return True

    def add_agent_artifact_dir(agent: Agent) -> bool:
        return add_artifact_dir(agent_artifact_dir(agent))

    for notification in pending:
        artifacts_dir = notification.action_data.get("artifacts_dir")
        if isinstance(artifacts_dir, str) and artifacts_dir:
            path = Path(artifacts_dir)
            if path.is_dir():
                add_artifact_dir(path)
        suffixes = pending_gate_notification_suffixes(notification)
        unresolved_suffixes.update(suffixes)
        raw_suffix = notification_raw_suffix(notification)
        if raw_suffix is None:
            continue
        resolved_suffixes.update(
            add_loaded_family_chain_artifact_dirs(
                agents_by_suffix,
                raw_suffix=raw_suffix,
                root_suffix=notification_family_root_suffix(notification),
                add_agent_artifact_dir=add_agent_artifact_dir,
            )
        )

    unresolved_suffixes.difference_update(resolved_suffixes)
    if unresolved_suffixes:
        from ...models.agent_loader import (
            artifact_dirs_for_normalized_timestamps,
            normalize_timestamps,
        )

        for extra in artifact_dirs_for_normalized_timestamps(
            normalize_timestamps(unresolved_suffixes)
        ):
            add_artifact_dir(extra)
    return artifact_dirs


def prepare_pending_gate_notification_refresh(
    app: Any,
    notifications: Iterable[Notification],
) -> tuple[Path, ...]:
    """Resolve pending-review gate dirs on the notification-poll worker thread.

    Stamped ``raw_suffix`` rows resolve from action_data and the roster. Legacy
    in-flight notifications without the new keys fall back to the indexed
    ``find_gate_shell_by_gate_id`` lookup.
    """
    pending = [
        notification
        for notification in notifications
        if is_active_pending_gate_refresh_notification(notification)
    ]
    if not pending:
        return ()
    artifact_dirs = pending_gate_notification_delta_dirs(app, pending)
    seen = {str(path) for path in artifact_dirs}
    extras: list[Path] = []
    for notification in pending:
        if notification_raw_suffix(notification) is not None:
            continue
        gate_id = str(notification.action_data.get("request_id") or "").strip()
        if not gate_id:
            continue
        from sase.gate_shell.store import find_gate_shell_by_gate_id

        record = find_gate_shell_by_gate_id(None, gate_id)
        artifacts_dir = getattr(record, "artifacts_dir", None) if record else None
        if not artifacts_dir:
            continue
        path = Path(str(artifacts_dir))
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        extras.append(path)
    if not extras:
        return tuple(artifact_dirs)
    return tuple(artifact_dirs + extras)

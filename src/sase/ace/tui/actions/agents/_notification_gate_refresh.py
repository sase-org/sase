"""Refresh orchestration: delta scheduling, gate receipts, disappearances."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._notification_agent_targeting import (
    agent_artifact_dir,
    call_schedule_agents_refresh,
    resolve_notification_agent,
    refresh_notification_agent_from_cache,
)
from ._notification_delta_dirs import completion_notification_delta_dirs

if TYPE_CHECKING:
    from sase.notifications import Notification

    from ...models import Agent


def request_notification_agents_refresh(
    app: Any,
    *,
    agent: Agent | None = None,
    notification: Notification | None = None,
    notifications: Iterable[Notification] | None = None,
    allow_broad_fallback: bool = True,
) -> None:
    """Request notification/completion-triggered agent reconciliation."""
    if agent is None:
        agent = resolve_notification_agent(app, notification)

    artifact_dirs: list[Path] = []
    if agent is not None:
        artifact_dir = agent_artifact_dir(agent)
        if artifact_dir is not None:
            artifact_dirs.append(artifact_dir)
    else:
        targets = notifications
        if targets is None:
            targets = getattr(app, "_last_new_completion_notifications", None)
        artifact_dirs.extend(completion_notification_delta_dirs(app, targets))
        # Pending-gate dirs need disk and the indexed gate lookup, so the poll
        # already resolved them on its worker thread; consume that result.
        prepared = getattr(app, "_last_pending_gate_artifact_dirs", None)
        if prepared:
            seen_dirs = {str(path) for path in artifact_dirs}
            for path in prepared:
                key = str(path)
                if key in seen_dirs:
                    continue
                seen_dirs.add(key)
                artifact_dirs.append(path)

    if artifact_dirs:
        schedule_delta = getattr(app, "_schedule_agent_artifact_delta_refresh", None)
        if callable(schedule_delta):
            schedule_delta(artifact_dirs, source="notification")
            return

    if not allow_broad_fallback:
        return
    call_schedule_agents_refresh(app)


def request_gate_decision_refresh(
    app: Any,
    *,
    notification: Notification,
    agent: Agent | None = None,
    allow_broad_fallback: bool = True,
    artifact_dirs: Sequence[Path] = (),
) -> None:
    """Refresh ACE surfaces after a gate decision becomes durable.

    ``artifact_dirs`` are exact planner/shell rows resolved off the event loop
    by the receipt watcher; they route through the artifact-delta queue.
    """
    schedule_snapshot = getattr(app, "_schedule_notification_snapshot_refresh", None)
    if callable(schedule_snapshot):
        schedule_snapshot()
    else:
        refresh_count = getattr(app, "_refresh_notification_count", None)
        if callable(refresh_count):
            refresh_count()
    if artifact_dirs:
        schedule_delta = getattr(app, "_schedule_agent_artifact_delta_refresh", None)
        if callable(schedule_delta):
            schedule_delta(list(artifact_dirs), source="notification")
            return
    request_notification_agents_refresh(
        app,
        agent=agent,
        notification=notification,
        allow_broad_fallback=allow_broad_fallback,
    )


def schedule_gate_decision_receipt_refresh(
    app: Any,
    *,
    notification: Notification,
    bundle_path: Path,
    agent: Agent | None = None,
    timeout_seconds: float = 5.0,
) -> None:
    """Watch one submitted gate for its fast decision receipt, then refresh."""
    from ...util.pump_tasks import spawn_pump_free_task

    key = (notification.id, str(bundle_path))
    active = getattr(app, "_gate_decision_refresh_keys", None)
    if active is None:
        active = set()
        app._gate_decision_refresh_keys = active
    if key in active:
        return

    async def _watch() -> None:
        import asyncio
        import time

        receipt_seen = False
        deadline = time.monotonic() + timeout_seconds
        try:
            while time.monotonic() <= deadline:
                receipt_seen = await asyncio.to_thread(
                    gate_decision_is_visible,
                    bundle_path,
                )
                if receipt_seen:
                    break
                await asyncio.sleep(0.05)
            if receipt_seen:
                exact_dirs = await asyncio.to_thread(
                    gate_decision_exact_artifact_dirs,
                    app,
                    notification,
                    agent,
                )
                request_gate_decision_refresh(
                    app,
                    notification=notification,
                    agent=agent,
                    allow_broad_fallback=False,
                    artifact_dirs=exact_dirs,
                )
        finally:
            active.discard(key)

    task = spawn_pump_free_task(
        app,
        _watch(),
        name=f"gate-decision-refresh:{notification.id}",
        registry_attr="_gate_decision_refresh_tasks",
    )
    if task is not None:
        active.add(key)


def gate_decision_exact_artifact_dirs(
    app: Any,
    notification: Notification,
    agent: Agent | None,
) -> tuple[Path, ...]:
    """Resolve the planner and gate-shell artifact dirs a decision touches.

    Reads the filesystem, so the receipt watcher calls it on a worker thread.
    """
    dirs: dict[str, Path] = {}
    try:
        planner = (
            agent
            if agent is not None
            else resolve_notification_agent(app, notification)
        )
        planner_dir = agent_artifact_dir(planner) if planner is not None else None
        if planner_dir is not None:
            dirs[str(planner_dir)] = planner_dir
        shell_dir, _needs_fallback = accepted_gate_shell_artifact_dir(notification)
        if shell_dir is not None:
            dirs[str(shell_dir)] = shell_dir
    except Exception:
        return tuple(dirs.values())
    return tuple(dirs.values())


def gate_decision_is_visible(bundle_path: Path) -> bool:
    from sase.notification_gates.decision import DECISION_RECEIPT_FILENAME
    from sase.notification_gates.paths import CANCELLATION_FILENAME, RESPONSE_FILENAME

    return any(
        (bundle_path / filename).exists()
        for filename in (
            DECISION_RECEIPT_FILENAME,
            RESPONSE_FILENAME,
            CANCELLATION_FILENAME,
        )
    )


def prepare_disappeared_plan_notification_refresh(
    app: Any,
    previous_notifications: list[Notification],
    current_notifications: list[Notification],
) -> tuple[tuple[Path, ...], bool]:
    """Resolve disappeared gate-review rows to a bounded refresh request.

    This helper may call ``Agent.get_artifacts_dir()``, which can inspect the
    filesystem. Polling therefore invokes it on the same worker thread that
    reads the notification snapshot and only applies the returned paths on the
    Textual thread.

    Returns ``(artifact_dirs, needs_broad_fallback)``. Duplicate notifications
    for one artifact are coalesced. Plan approvals preserve their historical
    row-targeting behavior; other shell-backed gates refresh only after a
    durable decision/terminal marker is visible.
    """
    current_ids = {notification.id for notification in current_notifications}
    artifact_dirs: set[Path] = set()
    needs_broad_fallback = False
    for notification in previous_notifications:
        if notification.dismissed or notification.id in current_ids:
            continue
        if notification.action in {"PlanApproval", "EpicApproval"}:
            agent = resolve_notification_agent(app, notification)
            artifact_dir = agent_artifact_dir(agent) if agent is not None else None
            if artifact_dir is None:
                needs_broad_fallback = True
                continue
            artifact_dirs.add(artifact_dir)
            continue

        artifact_dir, needs_fallback = accepted_gate_shell_artifact_dir(notification)
        if artifact_dir is not None:
            artifact_dirs.add(artifact_dir)
        elif needs_fallback:
            needs_broad_fallback = True
    return tuple(sorted(artifact_dirs, key=str)), needs_broad_fallback


def accepted_gate_shell_artifact_dir(
    notification: Notification,
) -> tuple[Path | None, bool]:
    """Return an exact shell artifact dir for an accepted generic gate."""
    try:
        from sase.notification_gates.decision import DECISION_RECEIPT_FILENAME
        from sase.notification_gates.durability import read_json_object
        from sase.notification_gates.paths import resolve_notification_bundle
        from sase.notification_gates.registry import adapter_for_action

        if adapter_for_action(notification.action) is None:
            return None, False
        bundle = resolve_notification_bundle(notification)
        if bundle is None or bundle.legacy:
            return None, False
        if not any(
            path.exists()
            for path in (
                bundle.root / DECISION_RECEIPT_FILENAME,
                bundle.response,
                bundle.cancellation,
            )
        ):
            return None, False
        envelope = read_json_object(bundle.request)
        if not isinstance(envelope.get("shell"), dict):
            return None, False
        gate_id = str(
            envelope.get("request_id")
            or notification.action_data.get("request_id")
            or ""
        )
        if not gate_id:
            return None, True
        from sase.gate_shell.store import find_gate_shell_by_gate_id

        record = find_gate_shell_by_gate_id(None, gate_id)
        if record is None or not getattr(record, "artifacts_dir", None):
            return None, True
        return Path(str(record.artifacts_dir)), False
    except Exception:
        return None, True


def apply_disappeared_plan_notification_refresh(
    app: Any,
    artifact_dirs: tuple[Path, ...],
    *,
    needs_broad_fallback: bool,
) -> None:
    """Apply a worker-prepared plan-review disappearance refresh request."""
    if artifact_dirs:
        schedule_delta = getattr(app, "_schedule_agent_artifact_delta_refresh", None)
        if callable(schedule_delta):
            schedule_delta(artifact_dirs, source="notification")
        else:
            needs_broad_fallback = True
    if needs_broad_fallback:
        call_schedule_agents_refresh(app)


def refresh_notification_agent_or_request(
    app: Any,
    *,
    agent: Agent | None = None,
    notification: Notification | None = None,
) -> None:
    """Patch/refilter a notification-targeted row, falling back to reconcile."""
    if refresh_notification_agent_from_cache(
        app,
        agent=agent,
        notification=notification,
    ):
        return
    request_notification_agents_refresh(
        app,
        agent=agent,
        notification=notification,
    )

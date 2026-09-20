"""Shared notification helpers for the ACE agents TUI."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from inspect import Parameter, getattr_static, signature
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from sase.notifications import Notification

    from ...models import Agent


TabName = Literal["artifacts", "agents", "axe"]
_SETTLEMENT_NOTIFICATION_SENDERS = frozenset({"epic-launch", "monitor-settlement"})
_PENDING_GATE_REFRESH_ACTIONS = frozenset(
    {"PlanApproval", "EpicApproval", "UserQuestion"}
)
_FAMILY_ROOT_SUFFIX_KEYS = (
    "family_root_suffix",
    "family_root_raw_suffix",
    "agent_root_timestamp",
    "root_raw_suffix",
)


def loaded_real_agent_roster(owner: Any) -> tuple[Agent, ...]:
    """Return the complete loaded display-eligible roster without clan rows.

    Notification targeting must resolve against every loaded agent, not
    just the currently visible/folded/filtered ``_agents`` projection, so
    a completion for a folded or search-hidden row still resolves to an
    exact artifact-delta refresh instead of falling back to a broad load.
    """
    roster: Iterable[Agent] = (
        getattr(owner, "_agents_with_children", None)
        or getattr(owner, "_agents", ())
        or ()
    )
    return tuple(agent for agent in roster if not agent.is_clan_container)


def _callable_accepts_kwarg(callback: Callable[..., object], name: str) -> bool:
    try:
        params = signature(callback).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.kind == Parameter.VAR_KEYWORD or p.name == name for p in params)


def _call_schedule_agents_refresh(app: Any) -> None:
    if getattr_static(app, "request_agents_refresh", None) is not None:
        request_refresh = getattr(app, "request_agents_refresh", None)
        if callable(request_refresh):
            request_refresh("notification", latest_only=True)
            return

    schedule_refresh = getattr(app, "_schedule_agents_async_refresh", None)
    if not callable(schedule_refresh):
        return
    if _callable_accepts_kwarg(schedule_refresh, "source"):
        schedule_refresh(source="notification")
    else:
        schedule_refresh()


def _agent_artifact_dir(agent: Any) -> Path | None:
    get_artifacts_dir = getattr(agent, "get_artifacts_dir", None)
    if not callable(get_artifacts_dir):
        return None
    artifacts_dir = get_artifacts_dir()
    if not isinstance(artifacts_dir, str) or not artifacts_dir:
        return None
    return Path(artifacts_dir)


def _resolve_notification_agent(
    app: Any,
    notification: Notification | None,
) -> Agent | None:
    if notification is None:
        return None
    try:
        from ._notification_navigation import find_agent_for_notification

        return find_agent_for_notification(app, notification)
    except Exception:
        return None


def refresh_notification_agent_from_cache(
    app: Any,
    *,
    agent: Agent | None = None,
    notification: Notification | None = None,
) -> bool:
    """Refresh notification-driven row state without forcing disk I/O."""
    if agent is None:
        agent = _resolve_notification_agent(app, notification)
    if agent is None:
        return False

    agents_with_children = getattr(app, "_agents_with_children", None)
    refilter = getattr(app, "_refilter_agents", None)
    if (
        callable(refilter)
        and isinstance(agents_with_children, list)
        and agents_with_children
    ):
        refilter()
        return True

    try_patch = None
    if getattr_static(app, "_try_patch_agent_row", None) is not None:
        try_patch = getattr(app, "_try_patch_agent_row", None)
    if callable(try_patch):
        try:
            return bool(try_patch(agent))
        except Exception:
            return False
    return False


def _completion_notification_delta_dirs(
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
        if _is_active_agent_settlement_notification(notification)
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
        suffix = _normalized_suffix(agent.raw_suffix)
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
        return add_artifact_dir(_agent_artifact_dir(agent))

    for agent in roster:
        agent_key = (agent.cl_name, agent.raw_suffix)
        cl_only = (agent.cl_name, None)
        matched = {key for key in (agent_key, cl_only) if key in completion_keys}
        if not matched:
            continue
        if add_agent_artifact_dir(agent):
            suffix = _normalized_suffix(agent.raw_suffix)
            if suffix:
                resolved_suffixes.add(suffix)
        resolved_keys.update(matched)

    settlement_suffixes: set[str] = set()
    for notification in settlement_notifications:
        raw_suffix = _notification_raw_suffix(notification)
        if raw_suffix is None:
            continue
        root_suffix = _notification_family_root_suffix(notification)
        settlement_suffixes.add(raw_suffix)
        if root_suffix is not None:
            settlement_suffixes.add(root_suffix)
        resolved_suffixes.update(
            _add_loaded_family_chain_artifact_dirs(
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


def _add_loaded_family_chain_artifact_dirs(
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
        current_suffix = _normalized_suffix(getattr(agent, "parent_timestamp", None))

    if root_suffix is not None and root_suffix not in resolved:
        root_agent = agents_by_suffix.get(root_suffix)
        if root_agent is not None:
            add_agent_artifact_dir(root_agent)
            resolved.add(root_suffix)
    return resolved


def _notification_raw_suffix(notification: Notification) -> str | None:
    return _normalized_suffix(notification.action_data.get("raw_suffix"))


def _notification_family_root_suffix(notification: Notification) -> str | None:
    for key in _FAMILY_ROOT_SUFFIX_KEYS:
        suffix = _normalized_suffix(notification.action_data.get(key))
        if suffix:
            return suffix
    return None


def _pending_gate_notification_suffixes(notification: Notification) -> list[str]:
    """Return gate-member, planner, and family-root suffixes in that order."""
    ordered: list[str] = []
    seen: set[str] = set()
    for value in (
        _notification_raw_suffix(notification),
        _normalized_suffix(notification.action_data.get("agent_timestamp")),
        _notification_family_root_suffix(notification),
    ):
        if value is None or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _pending_gate_notification_delta_dirs(
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
        suffix = _normalized_suffix(agent.raw_suffix)
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
        return add_artifact_dir(_agent_artifact_dir(agent))

    for notification in pending:
        artifacts_dir = notification.action_data.get("artifacts_dir")
        if isinstance(artifacts_dir, str) and artifacts_dir:
            path = Path(artifacts_dir)
            if path.is_dir():
                add_artifact_dir(path)
        suffixes = _pending_gate_notification_suffixes(notification)
        unresolved_suffixes.update(suffixes)
        raw_suffix = _notification_raw_suffix(notification)
        if raw_suffix is None:
            continue
        resolved_suffixes.update(
            _add_loaded_family_chain_artifact_dirs(
                agents_by_suffix,
                raw_suffix=raw_suffix,
                root_suffix=_notification_family_root_suffix(notification),
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
        if _is_active_pending_gate_refresh_notification(notification)
    ]
    if not pending:
        return ()
    artifact_dirs = _pending_gate_notification_delta_dirs(app, pending)
    seen = {str(path) for path in artifact_dirs}
    extras: list[Path] = []
    for notification in pending:
        if _notification_raw_suffix(notification) is not None:
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


def _normalized_suffix(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    from ...models._timestamps import normalize_to_14_digit

    return normalize_to_14_digit(value.strip())


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
        agent = _resolve_notification_agent(app, notification)

    artifact_dirs: list[Path] = []
    if agent is not None:
        artifact_dir = _agent_artifact_dir(agent)
        if artifact_dir is not None:
            artifact_dirs.append(artifact_dir)
    else:
        targets = notifications
        if targets is None:
            targets = getattr(app, "_last_new_completion_notifications", None)
        artifact_dirs.extend(_completion_notification_delta_dirs(app, targets))
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
    _call_schedule_agents_refresh(app)


def _request_gate_decision_refresh(
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
                    _gate_decision_is_visible,
                    bundle_path,
                )
                if receipt_seen:
                    break
                await asyncio.sleep(0.05)
            if receipt_seen:
                exact_dirs = await asyncio.to_thread(
                    _gate_decision_exact_artifact_dirs,
                    app,
                    notification,
                    agent,
                )
                _request_gate_decision_refresh(
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


def _gate_decision_exact_artifact_dirs(
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
            else _resolve_notification_agent(app, notification)
        )
        planner_dir = _agent_artifact_dir(planner) if planner is not None else None
        if planner_dir is not None:
            dirs[str(planner_dir)] = planner_dir
        shell_dir, _needs_fallback = _accepted_gate_shell_artifact_dir(notification)
        if shell_dir is not None:
            dirs[str(shell_dir)] = shell_dir
    except Exception:
        return tuple(dirs.values())
    return tuple(dirs.values())


def _gate_decision_is_visible(bundle_path: Path) -> bool:
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
            agent = _resolve_notification_agent(app, notification)
            artifact_dir = _agent_artifact_dir(agent) if agent is not None else None
            if artifact_dir is None:
                needs_broad_fallback = True
                continue
            artifact_dirs.add(artifact_dir)
            continue

        artifact_dir, needs_fallback = _accepted_gate_shell_artifact_dir(notification)
        if artifact_dir is not None:
            artifact_dirs.add(artifact_dir)
        elif needs_fallback:
            needs_broad_fallback = True
    return tuple(sorted(artifact_dirs, key=str)), needs_broad_fallback


def _accepted_gate_shell_artifact_dir(
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
        _call_schedule_agents_refresh(app)


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


def active_completion_agent_keys(
    notifications: list[Notification],
) -> set[tuple[str, str | None]]:
    """Return ``(cl_name, raw_suffix)`` keys for active completion notifications.

    A completion notification is identified by ``sender == "user-agent"`` and
    ``action`` in ``{"JumpToAgent", "ViewErrorReport"}`` with ``cl_name``
    present in ``action_data``. ``raw_suffix`` may be absent when the writer
    did not record one, so those rows match agents by ``cl_name`` only.

    "Active" means not yet dismissed. Default snapshots already omit
    dismissed rows, but the predicate is enforced here as well so callers
    that pass ``include_dismissed=True`` get the right projection. Silent
    rows still count: per the one-to-one contract, dismissed status is
    what gates the row, not indicator visibility.
    """
    keys: set[tuple[str, str | None]] = set()
    for n in notifications:
        if not _is_active_agent_completion_notification(n):
            continue
        cl_name = n.action_data.get("cl_name")
        if not cl_name:
            continue
        raw_suffix = n.action_data.get("raw_suffix") or None
        keys.add((cl_name, raw_suffix))
    return keys


def active_row_owned_notification_keys(
    notifications: list[Notification],
) -> set[tuple[str, str | None]]:
    """Return ``(cl_name, raw_suffix)`` keys for active row-owned notifications.

    Union of :func:`active_completion_agent_keys` and the exact keys of active
    host-owned settlement rows (``epic-launch`` / ``monitor-settlement``). The
    settlement half mirrors :func:`agent_settlement_notification_matches_agent`:
    exact match only, no ``cl_name``-only fallback.
    """
    keys = active_completion_agent_keys(notifications)
    for n in notifications:
        if n.dismissed:
            continue
        if n.sender not in _SETTLEMENT_NOTIFICATION_SENDERS:
            continue
        cl_name = n.action_data.get("cl_name")
        raw_suffix = n.action_data.get("raw_suffix")
        if not cl_name or not raw_suffix:
            continue
        keys.add((cl_name, raw_suffix))
    return keys


def _is_active_agent_completion_notification(notification: Notification) -> bool:
    """Return True for active agent completion notifications."""
    if notification.sender != "user-agent":
        return False
    if notification.action not in ("JumpToAgent", "ViewErrorReport"):
        return False
    return not notification.dismissed


def _is_active_agent_settlement_notification(notification: Notification) -> bool:
    """Return True for active settlement notifications with row identity."""
    if notification.dismissed:
        return False
    data = notification.action_data
    raw_suffix = _notification_raw_suffix(notification)
    if not data.get("cl_name") or raw_suffix is None:
        return False
    if notification.sender in _SETTLEMENT_NOTIFICATION_SENDERS:
        return True
    if not _is_active_agent_completion_notification(notification):
        return False
    root_suffix = _notification_family_root_suffix(notification)
    return root_suffix is not None and root_suffix != raw_suffix


def _is_active_pending_gate_refresh_notification(notification: Notification) -> bool:
    """Return True for an active pending-review gate notification.

    Sibling of the completion and settlement predicates. Plan/epic/question
    arrivals need an exact family-chain refresh on the toast tick; they are
    not settlement senders.
    """
    if notification.dismissed:
        return False
    return notification.action in _PENDING_GATE_REFRESH_ACTIONS


def is_active_agent_refresh_notification(notification: Notification) -> bool:
    """Return True when a new notification can drive an exact Agents refresh."""
    return (
        _is_active_agent_completion_notification(notification)
        or _is_active_agent_settlement_notification(notification)
        or _is_active_pending_gate_refresh_notification(notification)
    )


def _agent_completion_notification_matches_agent(
    notification: Notification,
    *,
    cl_name: str,
    raw_suffix: str | None,
) -> bool:
    """Return True when *notification* targets the supplied agent key."""
    if not _is_active_agent_completion_notification(notification):
        return False
    notification_cl_name = notification.action_data.get("cl_name")
    if not notification_cl_name or notification_cl_name != cl_name:
        return False
    notification_raw_suffix = notification.action_data.get("raw_suffix") or None
    return notification_raw_suffix is None or notification_raw_suffix == raw_suffix


def agent_settlement_notification_matches_agent(
    notification: Notification,
    *,
    cl_name: str,
    raw_suffix: str | None,
) -> bool:
    """Return True when *notification* is a settlement row owned by the key.

    Mirrors ``matches_agent_settlement_notification_for_agents`` in the Rust
    core: the sender must be host-owned settlement (``epic-launch`` or
    ``monitor-settlement``) and ``action_data`` must name a non-empty
    ``cl_name`` and a non-empty ``raw_suffix`` that both equal the supplied
    key. There is deliberately no ``cl_name``-only fallback: ``cl_name`` on
    these rows is the project-wide patch name, so a fallback would let
    acknowledging one agent dismiss every project-wide settlement row.
    """
    if notification.dismissed:
        return False
    if notification.sender not in _SETTLEMENT_NOTIFICATION_SENDERS:
        return False
    if not cl_name or not raw_suffix:
        return False
    notification_cl_name = notification.action_data.get("cl_name")
    notification_raw_suffix = notification.action_data.get("raw_suffix")
    if not notification_cl_name or not notification_raw_suffix:
        return False
    return notification_cl_name == cl_name and notification_raw_suffix == raw_suffix


def agent_row_notification_matches_agent(
    notification: Notification,
    *,
    cl_name: str,
    raw_suffix: str | None,
) -> bool:
    """Return True when *notification* is acknowledged with the supplied row.

    Single completion-or-settlement predicate for read-ack and dismissal
    paths so the two rules stay in one place.
    """
    return _agent_completion_notification_matches_agent(
        notification, cl_name=cl_name, raw_suffix=raw_suffix
    ) or agent_settlement_notification_matches_agent(
        notification, cl_name=cl_name, raw_suffix=raw_suffix
    )


def unread_notification_buckets(
    notifications: list[Notification],
) -> tuple[
    list[Notification], list[Notification], list[Notification], list[Notification]
]:
    from sase.notifications import is_error, is_priority

    unread_priority: list[Notification] = []
    unread_errors: list[Notification] = []
    unread_rest: list[Notification] = []
    unread_muted: list[Notification] = []
    for n in notifications:
        if n.read or n.silent:
            continue
        if n.muted:
            unread_muted.append(n)
        elif is_error(n):
            unread_errors.append(n)
        elif is_priority(n):
            unread_priority.append(n)
        else:
            unread_rest.append(n)
    return unread_priority, unread_errors, unread_rest, unread_muted

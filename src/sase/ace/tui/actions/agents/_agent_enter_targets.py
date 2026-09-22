"""In-memory AgentEnterTarget resolver for context-aware Enter.

Pure projection over already-loaded TUI ``Agent`` rows and the in-memory
notification snapshot. Performs no disk reads: gate subtitles come from row
fields or the in-memory notification, and Patch badges come from the
in-memory Patch lookup. The ``wire`` phase connects this resolver to the
``act_on_agent`` action and the chooser modal.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone, UTC
from typing import TYPE_CHECKING, Any, Literal

from sase.gate_shell.state import gate_state_is_terminal
from sase.gate_shell.status import gate_status_pair, gate_status_style
from sase.notification_gates.registry import adapter_for_action
from sase.notifications.agent_matching import agent_matches_notification_identity
from sase.project_display_names import humanize_cl_name

from ...models.agent_family_members import (
    concrete_family_shell_rows,
    family_roster_container,
    row_is_family_shell,
)

if TYPE_CHECKING:
    from ...models import Agent
    from sase.notifications import Notification

EnterTargetKind = Literal["gate", "patch"]
EnterTargetSource = Literal[
    "gate_row",
    "notification",
    "question_marker",
    "workflow_hitl",
    "remote_attention",
    "patch",
]

#: Message when Enter lands on a clan container row.
CLAN_EMPTY_MESSAGE = "Select an agent inside this clan"

#: Message when Enter finds neither a pending gate nor a Patch.
NO_TARGET_EMPTY_MESSAGE = "No pending gate or Patch for this agent"


@dataclass(frozen=True, slots=True)
class PatchSummary:
    """In-memory Patch badge data for one Patch name."""

    status: str | None = None
    pr_label: str | None = None


@dataclass(frozen=True, slots=True)
class AgentEnterTarget:
    """One actionable Enter target for the selected agent row."""

    kind: EnterTargetKind
    source: EnterTargetSource
    key: str
    label: str
    detail: str | None = None
    badge: str | None = None
    badge_style: str | None = None
    age_seconds: float | None = None
    notification_id: str | None = None
    bundle_path: str | None = None
    gate_id: str | None = None
    row_identity: tuple[object, ...] | None = None
    patch_name: str | None = None
    project_file: str | None = None


@dataclass(frozen=True, slots=True)
class AgentEnterResolution:
    """Ordered Enter targets for one selected row."""

    targets: tuple[AgentEnterTarget, ...] = ()
    scope_title: str = ""
    empty_message: str | None = None

    @property
    def primary(self) -> AgentEnterTarget | None:
        """Return the first target (gates first, newest first, Patch last)."""
        return self.targets[0] if self.targets else None


@dataclass
class GateNotificationIndex:
    """Prefiltered gate-notification lookup for one snapshot object."""

    by_id: dict[str, Notification] = field(default_factory=dict)
    by_bundle_path: dict[str, Notification] = field(default_factory=dict)
    by_raw_suffix: dict[str, list[Notification]] = field(default_factory=dict)
    gate_notifications: tuple[Notification, ...] = ()


_INDEX_CACHE_REF: Any = None
_INDEX_CACHE: GateNotificationIndex | None = None


def build_gate_notification_index(snapshot: Any) -> GateNotificationIndex:
    """Prefilter *snapshot*'s notifications into a gate lookup index.

    The result is cached per snapshot object: repeated calls with the same
    object return the same index without rebuilding. Any other object
    rebuilds. Accepts the ``AceNotificationSnapshot`` shape (``.notifications``)
    or a plain sequence of notifications.
    """
    global _INDEX_CACHE_REF, _INDEX_CACHE
    if snapshot is _INDEX_CACHE_REF and _INDEX_CACHE is not None:
        return _INDEX_CACHE
    notifications: Sequence[Notification]
    if isinstance(snapshot, (list, tuple)):
        notifications = snapshot
    else:
        notifications = getattr(snapshot, "notifications", None) or ()
    by_id: dict[str, Notification] = {}
    by_bundle_path: dict[str, Notification] = {}
    by_raw_suffix: dict[str, list[Notification]] = {}
    gate_notifications: list[Notification] = []
    for notification in notifications:
        by_id.setdefault(notification.id, notification)
        bundle_path = notification.action_data.get("bundle_path")
        if bundle_path:
            by_bundle_path.setdefault(str(bundle_path), notification)
        raw_suffix = notification.action_data.get("raw_suffix")
        if raw_suffix:
            by_raw_suffix.setdefault(str(raw_suffix), []).append(notification)
        if adapter_for_action(notification.action) is not None:
            gate_notifications.append(notification)
    index = GateNotificationIndex(
        by_id=by_id,
        by_bundle_path=by_bundle_path,
        by_raw_suffix=by_raw_suffix,
        gate_notifications=tuple(gate_notifications),
    )
    _INDEX_CACHE_REF = snapshot
    _INDEX_CACHE = index
    return index


def empty_gate_notification_index() -> GateNotificationIndex:
    """Return an index with no notifications (snapshot cache still empty)."""
    return GateNotificationIndex()


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

#: Gate-kind labels for Enter targets and the chooser. The footer lowercases
#: the label, so entries are stored in display case here.
_GATE_KIND_LABELS: dict[str, str] = {
    "plan": "Review plan",
    "epic_plan": "Review epic plan",
    "question": "Answer question",
    "sudo": "Review sudo request",
    "launch": "Approve agent launch",
    "hitl": "Respond to checkpoint",
    "task_triage": "Triage task",
    "bead_snooze": "Review snoozed bead",
    "flag_triage": "Triage flag",
    "bead_stale_cleanup": "Clean up stale beads",
    "plugins_required": "Install required plugins",
}

#: Notification action to gate kind, for notification-only targets.
_NOTIFICATION_ACTION_KINDS: dict[str, str] = {
    "PlanApproval": "plan",
    "EpicApproval": "epic_plan",
    "UserQuestion": "question",
    "SudoRequest": "sudo",
    "LaunchApproval": "launch",
    "HITL": "hitl",
    "TaskTriage": "task_triage",
    "BeadSnooze": "bead_snooze",
    "FlagTriage": "flag_triage",
    "BeadStaleCleanup": "bead_stale_cleanup",
    "PluginsRequired": "plugins_required",
    "CustomGate": "custom",
}


def _gate_target_label(
    *,
    kind: str | None,
    pending_status: str | None = None,
    fallback_label: str | None = None,
) -> str:
    """Return the display label for one gate target.

    Table-driven over the gate kind. A ``plan`` gate whose pending status is
    ``TALE`` reads as a tale-plan review. Custom and unknown kinds fall back
    to the row's ``gate_label``, else ``Open gate``.
    """
    normalized_kind = (kind or "").strip()
    normalized_status = (pending_status or "").strip().upper()
    if normalized_kind == "plan" and normalized_status == "TALE":
        return "Review tale plan"
    label = _GATE_KIND_LABELS.get(normalized_kind)
    if label is not None:
        return label
    cleaned = (fallback_label or "").strip()
    return cleaned if cleaned else "Open gate"


def _notification_gate_kind(notification: Notification) -> str | None:
    """Return the gate kind for a gate-action notification, if known."""
    adapter = adapter_for_action(notification.action)
    if adapter is not None:
        return adapter.kind
    if notification.action is not None:
        return _NOTIFICATION_ACTION_KINDS.get(notification.action)
    return None


def _notification_pending_status(notification: Notification) -> str | None:
    """Return the pending status carried by a notification, if any."""
    for key in ("pending_status", "gate_start_status", "status"):
        value = notification.action_data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


# ---------------------------------------------------------------------------
# Badges, age, and subtitles
# ---------------------------------------------------------------------------


def _compact_age(age_seconds: float | None) -> str | None:
    if age_seconds is None or age_seconds < 0:
        return None
    try:
        from ...models.agent_time import format_compact_duration

        return format_compact_duration(age_seconds)
    except Exception:
        minutes = int(age_seconds // 60)
        if minutes < 60:
            return f"{minutes}m"
        hours = minutes // 60
        if hours < 48:
            return f"{hours}h"
        return f"{hours // 24}d"


def _gate_badge(status: str | None, age_seconds: float | None) -> str | None:
    normalized = (status or "").strip().upper() or "GATE"
    age = _compact_age(age_seconds)
    return f"{normalized} · {age}" if age else normalized


def _notification_age_seconds(notification: Notification) -> float | None:
    raw = (notification.timestamp or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    delta = datetime.now(UTC) - parsed
    return max(0.0, delta.total_seconds())


def _row_age_seconds(row: Agent) -> float | None:
    start = getattr(row, "start_time", None)
    if not isinstance(start, datetime):
        return None
    if start.tzinfo is None:
        now = datetime.now()
    else:
        now = datetime.now(UTC)
    try:
        return max(0.0, (now - start).total_seconds())
    except TypeError:
        return None


def _gate_badge_style(row: Agent) -> str | None:
    try:
        pair = gate_status_pair(
            getattr(row, "gate_start_status", None),
            getattr(row, "gate_stop_status", None),
        )
        return gate_status_style(
            pair,
            gate_state=getattr(row, "gate_state", None),
            accent=getattr(row, "gate_accent", None),
        )
    except Exception:
        return None


def _notification_gate_detail(notification: Notification) -> str | None:
    if notification.files:
        name = str(notification.files[0]).strip()
        if name:
            return name.rsplit("/", 1)[-1]
    for key in ("title", "message", "plan_file"):
        value = notification.action_data.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            return text.rsplit("/", 1)[-1] if "/" in text else text
    return None


def _linked_notification(
    row: Agent, index: GateNotificationIndex
) -> Notification | None:
    notification_id = getattr(row, "gate_notification_id", None)
    if notification_id and notification_id in index.by_id:
        return index.by_id[notification_id]
    bundle_path = getattr(row, "gate_bundle_path", None)
    if bundle_path and str(bundle_path) in index.by_bundle_path:
        return index.by_bundle_path[str(bundle_path)]
    return None


# ---------------------------------------------------------------------------
# Scope classification
# ---------------------------------------------------------------------------


def _is_pending_gate_row(row: Agent) -> bool:
    return (
        bool(getattr(row, "is_gate", False))
        and getattr(row, "gate_state", None) == "pending"
        and getattr(row, "stop_time", None) is None
        and not bool(getattr(row, "gate_execution_active", False))
    )


def _is_settled_gate_row(row: Agent) -> bool:
    if not bool(getattr(row, "is_gate", False)):
        return False
    if getattr(row, "stop_time", None) is not None:
        return True
    return bool(gate_state_is_terminal(getattr(row, "gate_state", None)))


def _classify_scope(agent: Agent) -> str:
    if bool(getattr(agent, "is_clan_container", False)):
        return "clan"
    if bool(getattr(agent, "is_monitor", False)) or bool(
        getattr(agent, "is_proc_shell", False)
    ):
        return "monitor_proc"
    if bool(getattr(agent, "is_gate", False)):
        return "gate"
    if getattr(agent, "fleet_origin_alias", None):
        return "remote"
    if getattr(agent, "parent_workflow", None) is not None or bool(
        getattr(agent, "is_workflow_step_child", False)
    ):
        return "workflow_step"
    if bool(getattr(agent, "is_family_container_row", False)):
        return "container"
    if family_roster_container(agent) is not None:
        return "member"
    return "standalone"


def _scope_title(agent: Agent) -> str:
    presented = getattr(agent, "presented_agent_name", None)
    if isinstance(presented, str) and presented.strip():
        return presented.strip()
    name = getattr(agent, "agent_name", None)
    if isinstance(name, str) and name.strip():
        return name.strip()
    cl_name = getattr(agent, "cl_name", None) or ""
    return humanize_cl_name(str(cl_name)) if cl_name else ""


# ---------------------------------------------------------------------------
# Target builders
# ---------------------------------------------------------------------------


def _gate_row_target(row: Agent, *, linked: Notification | None) -> AgentEnterTarget:
    age = _row_age_seconds(row)
    pending_status = getattr(row, "gate_start_status", None)
    return AgentEnterTarget(
        kind="gate",
        source="gate_row",
        key=f"gate:{getattr(row, 'gate_id', None)}",
        label=_gate_target_label(
            kind=getattr(row, "gate_kind", None),
            pending_status=pending_status if isinstance(pending_status, str) else None,
            fallback_label=getattr(row, "gate_label", None),
        ),
        detail=_notification_gate_detail(linked)
        if linked is not None
        else getattr(row, "gate_reason", None),
        badge=_gate_badge(
            pending_status if isinstance(pending_status, str) else None, age
        ),
        badge_style=_gate_badge_style(row),
        age_seconds=age,
        notification_id=getattr(row, "gate_notification_id", None),
        bundle_path=getattr(row, "gate_bundle_path", None),
        gate_id=getattr(row, "gate_id", None),
        row_identity=_identity_of(row),
    )


def _notification_gate_target(
    notification: Notification, *, scope_agent: Agent
) -> AgentEnterTarget:
    kind = _notification_gate_kind(notification)
    bundle_path = notification.action_data.get("bundle_path")
    return AgentEnterTarget(
        kind="gate",
        source="notification",
        key=f"gate:{notification.id}",
        label=_gate_target_label(
            kind=kind,
            pending_status=_notification_pending_status(notification),
            fallback_label=notification.action_data.get("gate_label"),
        ),
        detail=_notification_gate_detail(notification),
        badge=_gate_badge(
            _notification_pending_status(notification)
            or _notification_badge_for_action(notification.action),
            _notification_age_seconds(notification),
        ),
        badge_style=None,
        age_seconds=_notification_age_seconds(notification),
        notification_id=notification.id,
        bundle_path=str(bundle_path) if bundle_path else None,
        gate_id=None,
        row_identity=_identity_of(scope_agent),
    )


def _notification_badge_for_action(action: str | None) -> str | None:
    if not action:
        return None
    return {
        "PlanApproval": "PLAN",
        "EpicApproval": "EPIC",
        "UserQuestion": "QUESTION",
        "SudoRequest": "SUDO",
        "LaunchApproval": "LAUNCH",
        "HITL": "HITL",
    }.get(action, "GATE")


def _question_marker_target(agent: Agent) -> AgentEnterTarget:
    return AgentEnterTarget(
        kind="gate",
        source="question_marker",
        key=f"question-marker:{getattr(agent, 'cl_name', '')}:{getattr(agent, 'raw_suffix', '')}",
        label="Answer question",
        detail=None,
        badge="QUESTION",
        badge_style=None,
        age_seconds=None,
        row_identity=_identity_of(agent),
    )


def _workflow_hitl_target(agent: Agent) -> AgentEnterTarget:
    step_name = getattr(agent, "step_name", None)
    workflow = getattr(agent, "workflow", None) or getattr(
        agent, "parent_workflow", None
    )
    detail = (
        str(step_name).strip()
        if step_name
        else (str(workflow).strip() if workflow else None)
    )
    return AgentEnterTarget(
        kind="gate",
        source="workflow_hitl",
        key=f"hitl:workflow:{workflow}:{getattr(agent, 'raw_suffix', '')}",
        label="Respond to checkpoint",
        detail=detail,
        badge="HITL",
        badge_style=None,
        age_seconds=None,
        row_identity=_identity_of(agent),
    )


def _remote_attention_target(agent: Agent) -> AgentEnterTarget:
    attention = getattr(agent, "fleet_attention", None)
    detail: str | None = None
    if isinstance(attention, dict):
        title = attention.get("title")
        if isinstance(title, str) and title.strip():
            detail = title.strip()
    return AgentEnterTarget(
        kind="gate",
        source="remote_attention",
        key=f"remote:{getattr(agent, 'cl_name', '')}:{getattr(agent, 'raw_suffix', '')}",
        label="Answer remote request",
        detail=detail,
        badge=None,
        badge_style=None,
        age_seconds=None,
        row_identity=_identity_of(agent),
    )


def _patch_target(
    *,
    patch_name: str,
    project_file: str | None,
    summary: PatchSummary | None,
    scope_agent: Agent,
) -> AgentEnterTarget:
    from sase.ace.display_helpers import get_status_color

    status = summary.status if summary is not None else None
    pr_label = summary.pr_label if summary is not None else None
    humanized = humanize_cl_name(patch_name)
    detail = f"{humanized} · {pr_label}" if pr_label else humanized
    style: str | None = None
    if status:
        try:
            style = get_status_color(status)
        except Exception:
            style = None
    return AgentEnterTarget(
        kind="patch",
        source="patch",
        key=f"patch:{patch_name}",
        label="Go to Patch",
        detail=detail,
        badge=status,
        badge_style=style,
        age_seconds=None,
        patch_name=patch_name,
        project_file=project_file,
        row_identity=_identity_of(scope_agent),
    )


def _identity_of(agent: Agent) -> tuple[object, ...] | None:
    try:
        identity = agent.identity
    except Exception:
        return None
    if isinstance(identity, tuple):
        return tuple(identity)
    return None


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


def _identity_matched_gate_notifications(
    candidates: Sequence[Agent], index: GateNotificationIndex
) -> list[Notification]:
    matched: list[Notification] = []
    for notification in index.gate_notifications:
        for candidate in candidates:
            try:
                if agent_matches_notification_identity(candidate, notification):
                    matched.append(notification)
                    break
            except Exception:
                continue
    return matched


def _order_gate_targets(
    targets: list[AgentEnterTarget],
) -> list[AgentEnterTarget]:
    # Stable sort: gates newest first (unknown age last). Row-backed targets
    # were appended before notification-only ones, so ties keep row priority.
    targets.sort(
        key=lambda target: (
            target.age_seconds is None,
            target.age_seconds or 0.0,
        )
    )
    return targets


def _dedupe_notification_targets(
    candidates: list[Notification],
    *,
    scope_agent: Agent,
    seen_notification_ids: set[str],
    seen_bundle_paths: set[str],
    settled_bundle_paths: set[str],
) -> list[AgentEnterTarget]:
    targets: list[AgentEnterTarget] = []
    for notification in candidates:
        if notification.id in seen_notification_ids:
            continue
        bundle_path = notification.action_data.get("bundle_path")
        bundle_text = str(bundle_path) if bundle_path else None
        if bundle_text and (
            bundle_text in seen_bundle_paths or bundle_text in settled_bundle_paths
        ):
            continue
        seen_notification_ids.add(notification.id)
        if bundle_text:
            seen_bundle_paths.add(bundle_text)
        targets.append(_notification_gate_target(notification, scope_agent=scope_agent))
    return targets


def _newest_member_patch(
    rows: Sequence[Agent],
    patch_name_for: Callable[[Agent], str | None],
) -> tuple[str | None, str | None]:
    best_name: str | None = None
    best_project: str | None = None
    best_time = float("-inf")
    for row in rows:
        if row_is_family_shell(row) or bool(getattr(row, "is_proc_shell", False)):
            continue
        try:
            name = patch_name_for(row)
        except Exception:
            continue
        if not name:
            continue
        start = getattr(row, "start_time", None)
        stamp = float("-inf")
        if isinstance(start, datetime):
            try:
                stamp = start.timestamp()
            except (OverflowError, OSError, ValueError):
                stamp = float("-inf")
        if stamp >= best_time:
            best_time = stamp
            best_name = name
            best_project = getattr(row, "project_file", None)
    return best_name, best_project


def resolve_agent_enter_targets(
    agent: Agent,
    *,
    gate_notifications: GateNotificationIndex,
    patch_name_for: Callable[[Agent], str | None],
    patch_lookup: Callable[[str], PatchSummary | None],
) -> AgentEnterResolution:
    """Resolve the ordered Enter targets for one selected agent row.

    Implements the epic scope table: pending gate rows (never settled or
    ``settling`` gates, never a container mirroring ``gate_state``),
    identity-matched gate notifications, the legacy question-marker and
    workflow-HITL fallbacks, and the row's Patch. Gates come first, newest
    first; the Patch comes last.
    """
    from ._remote_attention import has_pending_remote_attention

    scope = _classify_scope(agent)
    title = _scope_title(agent)

    if scope == "clan":
        return AgentEnterResolution(
            targets=(), scope_title=title, empty_message=CLAN_EMPTY_MESSAGE
        )
    if scope == "monitor_proc":
        return AgentEnterResolution(targets=(), scope_title=title)

    if scope == "gate":
        if _is_pending_gate_row(agent):
            target = _gate_row_target(
                agent, linked=_linked_notification(agent, gate_notifications)
            )
            return AgentEnterResolution(targets=(target,), scope_title=title)
        stop_status = getattr(agent, "gate_stop_status", None)
        state = getattr(agent, "gate_state", None)
        settled = stop_status or state or "settled"
        return AgentEnterResolution(
            targets=(),
            scope_title=title,
            empty_message=f"This gate already settled ({settled})",
        )

    if scope == "remote":
        try:
            pending = has_pending_remote_attention(agent)
        except Exception:
            pending = False
        if pending:
            return AgentEnterResolution(
                targets=(_remote_attention_target(agent),), scope_title=title
            )
        return AgentEnterResolution(targets=(), scope_title=title)

    gate_targets: list[AgentEnterTarget] = []
    seen_notification_ids: set[str] = set()
    seen_bundle_paths: set[str] = set()
    settled_bundle_paths: set[str] = set()

    roster: tuple[Agent, ...] = ()
    if scope == "container":
        roster = concrete_family_shell_rows(agent)
        pending_rows = [row for row in roster if _is_pending_gate_row(row)]
        seen_gate_ids: set[str] = set()
        for row in pending_rows:
            gate_id = getattr(row, "gate_id", None)
            if gate_id in seen_gate_ids:
                continue
            if gate_id is not None:
                seen_gate_ids.add(gate_id)
            linked = _linked_notification(row, gate_notifications)
            if linked is not None:
                seen_notification_ids.add(linked.id)
            bundle_path = getattr(row, "gate_bundle_path", None)
            if bundle_path:
                seen_bundle_paths.add(str(bundle_path))
            gate_targets.append(_gate_row_target(row, linked=linked))
        settled_bundle_paths = {
            str(getattr(row, "gate_bundle_path", None))
            for row in roster
            if _is_settled_gate_row(row) and getattr(row, "gate_bundle_path", None)
        }
        member_shells: list[Agent] = [agent] + [
            row for row in roster if not row_is_family_shell(row)
        ]
        candidates = _identity_matched_gate_notifications(
            member_shells, gate_notifications
        )
        gate_targets.extend(
            _dedupe_notification_targets(
                candidates,
                scope_agent=agent,
                seen_notification_ids=seen_notification_ids,
                seen_bundle_paths=seen_bundle_paths,
                settled_bundle_paths=settled_bundle_paths,
            )
        )
        patch_name: str | None = None
        patch_project: str | None = None
        try:
            patch_name = patch_name_for(agent)
        except Exception:
            patch_name = None
        if patch_name:
            patch_project = getattr(agent, "project_file", None)
        else:
            patch_name, patch_project = _newest_member_patch(roster, patch_name_for)
    else:
        if scope == "member":
            container = family_roster_container(agent)
            roster = (
                concrete_family_shell_rows(container) if container is not None else ()
            )
            created: list[Agent] = []
            seen_gate_ids = set()
            member_gate_id = getattr(agent, "gate_id", None)
            member_name = getattr(agent, "agent_name", None)
            for row in roster:
                if not _is_pending_gate_row(row):
                    continue
                row_gate_id = getattr(row, "gate_id", None)
                creator = getattr(row, "gate_creator_agent", None)
                if member_gate_id is not None and row_gate_id == member_gate_id:
                    pass
                elif creator and member_name and creator == member_name:
                    pass
                else:
                    continue
                if row_gate_id in seen_gate_ids:
                    continue
                if row_gate_id is not None:
                    seen_gate_ids.add(row_gate_id)
                created.append(row)
            for row in created:
                linked = _linked_notification(row, gate_notifications)
                if linked is not None:
                    seen_notification_ids.add(linked.id)
                bundle_path = getattr(row, "gate_bundle_path", None)
                if bundle_path:
                    seen_bundle_paths.add(str(bundle_path))
                gate_targets.append(_gate_row_target(row, linked=linked))
            settled_bundle_paths = {
                str(getattr(row, "gate_bundle_path", None))
                for row in roster
                if _is_settled_gate_row(row) and getattr(row, "gate_bundle_path", None)
            }
            candidates = _identity_matched_gate_notifications(
                [agent], gate_notifications
            )
        else:
            candidates = _identity_matched_gate_notifications(
                [agent], gate_notifications
            )
        gate_targets.extend(
            _dedupe_notification_targets(
                candidates,
                scope_agent=agent,
                seen_notification_ids=seen_notification_ids,
                seen_bundle_paths=seen_bundle_paths,
                settled_bundle_paths=settled_bundle_paths,
            )
        )
        if not gate_targets:
            status = getattr(agent, "status", None)
            if scope != "workflow_step" and status == "QUESTION":
                gate_targets.append(_question_marker_target(agent))
            if status == "WAITING INPUT":
                gate_targets.append(_workflow_hitl_target(agent))
        try:
            patch_name = patch_name_for(agent)
        except Exception:
            patch_name = None
        patch_project = getattr(agent, "project_file", None) if patch_name else None

    targets = _order_gate_targets(gate_targets)
    if patch_name:
        try:
            summary = patch_lookup(patch_name)
        except Exception:
            summary = None
        targets.append(
            _patch_target(
                patch_name=patch_name,
                project_file=patch_project,
                summary=summary,
                scope_agent=agent,
            )
        )
    return AgentEnterResolution(
        targets=tuple(targets), scope_title=title, empty_message=None
    )


__all__ = [
    "AgentEnterResolution",
    "AgentEnterTarget",
    "CLAN_EMPTY_MESSAGE",
    "GateNotificationIndex",
    "NO_TARGET_EMPTY_MESSAGE",
    "PatchSummary",
    "build_gate_notification_index",
    "empty_gate_notification_index",
    "resolve_agent_enter_targets",
]

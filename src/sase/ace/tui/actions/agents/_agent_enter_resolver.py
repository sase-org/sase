"""Ordered Enter-target resolution over agent rows and notifications."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from ...models.agent_family_members import (
    concrete_family_shell_rows,
    family_roster_container,
    row_is_family_shell,
)
from ._agent_enter_builders import (
    gate_row_target,
    notification_gate_target,
    patch_target,
    question_marker_target,
    remote_attention_target,
    workflow_hitl_target,
)
from ._agent_enter_index import (
    GateNotificationIndex,
    identity_matched_gate_notifications,
    linked_notification,
)
from ._agent_enter_models import (
    CLAN_EMPTY_MESSAGE,
    AgentEnterResolution,
    AgentEnterTarget,
)
from ._agent_enter_scopes import (
    classify_scope,
    is_pending_gate_row,
    is_settled_gate_row,
    scope_title,
)

if TYPE_CHECKING:
    from ...models import Agent
    from sase.notifications import Notification

    from ._agent_enter_models import PatchSummary


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
        targets.append(notification_gate_target(notification, scope_agent=scope_agent))
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

    scope = classify_scope(agent)
    title = scope_title(agent)

    if scope == "clan":
        return AgentEnterResolution(
            targets=(), scope_title=title, empty_message=CLAN_EMPTY_MESSAGE
        )
    if scope == "monitor_proc":
        return AgentEnterResolution(targets=(), scope_title=title)

    if scope == "gate":
        if is_pending_gate_row(agent):
            target = gate_row_target(
                agent, linked=linked_notification(agent, gate_notifications)
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
                targets=(remote_attention_target(agent),), scope_title=title
            )
        return AgentEnterResolution(targets=(), scope_title=title)

    gate_targets: list[AgentEnterTarget] = []
    seen_notification_ids: set[str] = set()
    seen_bundle_paths: set[str] = set()
    settled_bundle_paths: set[str] = set()

    roster: tuple[Agent, ...] = ()
    if scope == "container":
        roster = concrete_family_shell_rows(agent)
        pending_rows = [row for row in roster if is_pending_gate_row(row)]
        seen_gate_ids: set[str] = set()
        for row in pending_rows:
            gate_id = getattr(row, "gate_id", None)
            if gate_id in seen_gate_ids:
                continue
            if gate_id is not None:
                seen_gate_ids.add(gate_id)
            linked = linked_notification(row, gate_notifications)
            if linked is not None:
                seen_notification_ids.add(linked.id)
            bundle_path = getattr(row, "gate_bundle_path", None)
            if bundle_path:
                seen_bundle_paths.add(str(bundle_path))
            gate_targets.append(gate_row_target(row, linked=linked))
        settled_bundle_paths = {
            str(getattr(row, "gate_bundle_path", None))
            for row in roster
            if is_settled_gate_row(row) and getattr(row, "gate_bundle_path", None)
        }
        member_shells: list[Agent] = [agent] + [
            row for row in roster if not row_is_family_shell(row)
        ]
        candidates = identity_matched_gate_notifications(
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
                if not is_pending_gate_row(row):
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
                linked = linked_notification(row, gate_notifications)
                if linked is not None:
                    seen_notification_ids.add(linked.id)
                bundle_path = getattr(row, "gate_bundle_path", None)
                if bundle_path:
                    seen_bundle_paths.add(str(bundle_path))
                gate_targets.append(gate_row_target(row, linked=linked))
            settled_bundle_paths = {
                str(getattr(row, "gate_bundle_path", None))
                for row in roster
                if is_settled_gate_row(row) and getattr(row, "gate_bundle_path", None)
            }
            candidates = identity_matched_gate_notifications(
                [agent], gate_notifications
            )
        else:
            candidates = identity_matched_gate_notifications(
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
                gate_targets.append(question_marker_target(agent))
            if status == "WAITING INPUT":
                gate_targets.append(workflow_hitl_target(agent))
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
            patch_target(
                patch_name=patch_name,
                project_file=patch_project,
                summary=summary,
                scope_agent=agent,
            )
        )
    return AgentEnterResolution(
        targets=tuple(targets), scope_title=title, empty_message=None
    )


def enter_action_label_for_targets(
    targets: tuple[AgentEnterTarget, ...] | list[AgentEnterTarget],
) -> str | None:
    """Return the footer hint for Enter given resolved targets.

    One target renders its lowercase label (a lone Patch keeps the
    historical ``go to PR`` hint); several render ``choose action``; none
    renders no hint.
    """
    if not targets:
        return None
    if len(targets) >= 2:
        return "choose action"
    if targets[0].kind == "patch":
        return "go to PR"
    return targets[0].label.lower()


__all__ = [
    "enter_action_label_for_targets",
    "resolve_agent_enter_targets",
]

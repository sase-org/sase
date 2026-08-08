"""Frontend-free gate summary projection for notification detail surfaces.

Every notification the panel can highlight is either not gate-backed
(:func:`gate_summary_from_notification` returns ``None``) or projects onto a
:class:`GateSummary`. Two tiers exist because the render path must never touch
disk: :func:`gate_summary_from_notification` is the zero-I/O instant tier
built from the notification row alone, while :func:`load_gate_summary` is the
bundle tier that resolves, verifies, and folds the durable envelope. Neither
function ever raises — malformed or missing input degrades to a summary with
``unavailable_reason`` set, never an exception escaping to a caller.
"""

from __future__ import annotations

import dataclasses
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from sase.notification_gates.branches import GateBranchData
from sase.notification_gates.debug_artifacts import error_artifacts, terminal_artifact
from sase.notification_gates.debug_models import GateDebugBundlePaths
from sase.notification_gates.debug_rendering import iso_from_unix
from sase.notification_gates.hashing import load_and_verify_bundle
from sase.notification_gates.model_results import effective_response_input
from sase.notification_gates.models import (
    GateError,
    GateFeedbackMode,
    GateGroup,
    GateInputField,
    GateOption,
)
from sase.notification_gates.paths import resolve_notification_bundle
from sase.notification_gates.presentation import GATE_TITLE_ACTION_DATA_KEY
from sase.notification_gates.registry import adapter_for_action
from sase.notifications.models import Notification

GateSummaryStatus = Literal[
    "pending", "answered", "cancelled", "timed_out", "overdue", "unavailable"
]


def derive_gate_status(
    *,
    request_readable: bool,
    terminal_kind: str | None,
    terminal_readable: bool,
    cancellation_reason: str | None,
    deadline: float | None,
    now: float,
) -> GateSummaryStatus:
    """Return the one correct status for a gate from its terminal artifacts."""
    if terminal_kind is not None and not terminal_readable:
        return "unavailable"
    if terminal_kind == "response":
        return "answered"
    if terminal_kind == "cancellation":
        return "timed_out" if cancellation_reason == "timeout" else "cancelled"
    if not request_readable:
        return "unavailable"
    if deadline is not None and now > deadline:
        return "overdue"
    return "pending"


@dataclass(frozen=True)
class GateSummaryOption:
    """One option belonging to a gate branch, with its recorded selection."""

    id: str
    label: str
    icon: str | None
    argv: tuple[str, ...]
    feedback: GateFeedbackMode
    default_selected: bool
    selected: bool
    input_fields: tuple[GateInputField, ...] = ()
    submitted_input: dict[str, Any] | None = None


@dataclass(frozen=True)
class GateSummaryBranch:
    """One canonical-order branch of a gate's decision."""

    option_ids: tuple[str, ...]
    label: str
    icon: str | None
    is_primary: bool
    options: tuple[GateSummaryOption, ...]


@dataclass(frozen=True)
class GateSummary:
    """Complete, disk-optional projection of a gate-backed notification."""

    kind: str
    display_title: str
    title: str
    request_id: str
    status: GateSummaryStatus
    deadline_at: str | None
    query: str
    branches: tuple[GateSummaryBranch, ...]
    selected_option_ids: tuple[str, ...]
    feedback: str | None
    attachments: tuple[str, ...]
    error_count: int
    bundle_path: Path | None
    unavailable_reason: str | None
    option_inputs: dict[str, dict[str, Any]] = field(default_factory=dict)


def gate_summary_from_notification(notification: Notification) -> GateSummary | None:
    """Return the zero-I/O instant tier, or ``None`` for a non-gate row."""
    adapter = adapter_for_action(notification.action)
    if adapter is None:
        return None
    action_data = notification.action_data
    declared_title = action_data.get(GATE_TITLE_ACTION_DATA_KEY)
    title = declared_title if declared_title else adapter.display_title
    request_id = action_data.get("request_id") or notification.id
    attachments = tuple(os.path.basename(path) for path in notification.files)
    return GateSummary(
        kind=adapter.kind,
        display_title=adapter.display_title,
        title=title,
        request_id=request_id,
        status="pending",
        deadline_at=None,
        query="",
        branches=(),
        selected_option_ids=(),
        feedback=None,
        attachments=attachments,
        error_count=0,
        bundle_path=None,
        unavailable_reason=None,
    )


def load_gate_summary(notification: Notification) -> GateSummary | None:
    """Return the bundle tier; safe to call only off the UI thread.

    ``None`` for non-gate rows. Otherwise starts from the instant tier and
    enriches it with the durable envelope, degrading to the best partial
    summary recovered so far whenever a step fails.
    """
    instant = gate_summary_from_notification(notification)
    if instant is None:
        return None
    try:
        bundle = resolve_notification_bundle(notification)
        if bundle is None:
            return dataclasses.replace(
                instant,
                status="unavailable",
                unavailable_reason="no gate bundle is attached",
            )
        if bundle.legacy:
            return dataclasses.replace(
                instant,
                status="unavailable",
                bundle_path=bundle.root,
                unavailable_reason="this gate uses a legacy bundle layout",
            )
        try:
            envelope, bundle_adapter = load_and_verify_bundle(bundle.root)
        except (GateError, OSError) as exc:
            return dataclasses.replace(
                instant,
                status="unavailable",
                bundle_path=bundle.root,
                unavailable_reason=str(exc),
            )

        kind = str(envelope.get("kind") or instant.kind)
        request_id = str(envelope.get("request_id") or instant.request_id)
        title = _envelope_title(envelope) or instant.title
        deadline = _envelope_deadline(envelope)
        error_count = error_artifacts(bundle.root / "errors")[1]

        try:
            branch_data = GateBranchData.from_envelope(
                envelope, default_feedback=bundle_adapter.default_feedback
            )
        except GateError as exc:
            return dataclasses.replace(
                instant,
                status="unavailable",
                kind=kind,
                title=title,
                request_id=request_id,
                bundle_path=bundle.root,
                error_count=error_count,
                unavailable_reason=str(exc),
            )

        debug_paths = GateDebugBundlePaths(
            bundle.root,
            bundle.request,
            bundle.response,
            bundle.cancellation,
            bundle.legacy,
        )
        terminal, terminal_payload, terminal_kind = terminal_artifact(debug_paths)
        terminal_readable = terminal.status == "ok"

        selected_option_ids: tuple[str, ...] = ()
        feedback: str | None = None
        cancellation_reason: str | None = None
        option_inputs: dict[str, dict[str, Any]] = {}
        if terminal_kind == "response" and terminal_readable:
            raw_selected = terminal_payload.get("selected_option_ids")
            if isinstance(raw_selected, list):
                selected_option_ids = tuple(str(item) for item in raw_selected)
            raw_feedback = terminal_payload.get("feedback")
            if isinstance(raw_feedback, str) and raw_feedback:
                feedback = raw_feedback
            option_inputs = {
                option_id: effective_response_input(terminal_payload, option_id)
                for option_id in selected_option_ids
            }
        elif terminal_kind == "cancellation" and terminal_readable:
            raw_reason = terminal_payload.get("reason")
            cancellation_reason = str(raw_reason) if raw_reason is not None else None

        status = derive_gate_status(
            request_readable=True,
            terminal_kind=terminal_kind,
            terminal_readable=terminal_readable,
            cancellation_reason=cancellation_reason,
            deadline=deadline,
            now=time.time(),
        )

        selected_ids = set(selected_option_ids)
        options_by_id = {option.id: option for option in branch_data.options}
        groups_by_members = {
            frozenset(group.options): group for group in branch_data.groups
        }
        branches = tuple(
            _summary_branch(
                branch,
                options_by_id=options_by_id,
                groups_by_members=groups_by_members,
                is_primary=branch == branch_data.primary_branch,
                selected_ids=selected_ids,
                option_inputs=option_inputs,
            )
            for branch in branch_data.branches
        )

        return GateSummary(
            kind=kind,
            display_title=instant.display_title,
            title=title,
            request_id=request_id,
            status=status,
            deadline_at=None if deadline is None else iso_from_unix(deadline),
            query=branch_data.query,
            branches=branches,
            selected_option_ids=selected_option_ids,
            feedback=feedback,
            attachments=instant.attachments,
            error_count=error_count,
            bundle_path=bundle.root,
            unavailable_reason=None,
            option_inputs=option_inputs,
        )
    except Exception as exc:  # noqa: BLE001 - the "never raises" contract is structural
        return dataclasses.replace(
            instant,
            status="unavailable",
            unavailable_reason=f"{type(exc).__name__}: {exc}",
        )


def _summary_branch(
    branch: tuple[str, ...],
    *,
    options_by_id: Mapping[str, GateOption],
    groups_by_members: Mapping[frozenset[str], GateGroup],
    is_primary: bool,
    selected_ids: set[str],
    option_inputs: Mapping[str, dict[str, Any]],
) -> GateSummaryBranch:
    first = options_by_id[branch[0]]
    if len(branch) == 1:
        label, icon = first.label, first.icon
    else:
        group = groups_by_members[frozenset(branch)]
        label = group.label or first.label
        icon = group.icon
    options = tuple(
        _summary_option(options_by_id[option_id], selected_ids, option_inputs)
        for option_id in branch
    )
    return GateSummaryBranch(
        option_ids=branch,
        label=label,
        icon=icon,
        is_primary=is_primary,
        options=options,
    )


def _summary_option(
    option: GateOption,
    selected_ids: set[str],
    option_inputs: Mapping[str, dict[str, Any]],
) -> GateSummaryOption:
    return GateSummaryOption(
        id=option.id,
        label=option.label,
        icon=option.icon,
        argv=option.command.argv,
        feedback=option.feedback,
        default_selected=option.default_selected,
        selected=option.id in selected_ids,
        input_fields=option.inputs,
        submitted_input=option_inputs.get(option.id),
    )


def _envelope_title(envelope: Mapping[str, Any]) -> str | None:
    presentation = envelope.get("presentation")
    if not isinstance(presentation, Mapping):
        return None
    title = presentation.get("title")
    return title.strip() if isinstance(title, str) and title.strip() else None


def _envelope_deadline(envelope: Mapping[str, Any]) -> float | None:
    timeout = envelope.get("gate_timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        return None
    created_unix = envelope.get("created_at_unix")
    if isinstance(created_unix, bool) or not isinstance(created_unix, (int, float)):
        created_at = envelope.get("created_at")
        if not isinstance(created_at, str):
            return None
        try:
            created_unix = datetime.fromisoformat(created_at).timestamp()
        except ValueError:
            return None
    return float(created_unix) + float(timeout)


__all__ = [
    "GateSummary",
    "GateSummaryBranch",
    "GateSummaryOption",
    "GateSummaryStatus",
    "derive_gate_status",
    "gate_summary_from_notification",
    "load_gate_summary",
]

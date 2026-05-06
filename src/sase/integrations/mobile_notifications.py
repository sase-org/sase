"""Read-only host bridge for mobile notification gateway surfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any

from sase.core.time import get_timezone
from sase.notifications.models import Notification
from sase.notifications.priority import is_priority
from sase.notifications.store import read_notification_snapshot


# pyvision: public_api_methods.txt
@dataclass(frozen=True)
class MobileNotificationBridgeCounts:
    priority: int = 0
    rest: int = 0
    muted: int = 0


# pyvision: public_api_methods.txt
@dataclass(frozen=True)
class MobileNotificationBridgeRow:
    id: str
    timestamp: str
    sender: str
    priority: bool
    notes: list[str] = field(default_factory=list)
    display_files: list[str] = field(default_factory=list)
    host_files: list[str] = field(default_factory=list)
    action: str | None = None
    action_state: str = "unsupported"
    display_action_data: dict[str, str] = field(default_factory=dict)
    host_action_data: dict[str, str] = field(default_factory=dict)
    read: bool = False
    dismissed: bool = False
    silent: bool = False
    muted: bool = False
    snooze_until: str | None = None


# pyvision: public_api_methods.txt
@dataclass(frozen=True)
class MobileNotificationBridgeSnapshot:
    rows: list[MobileNotificationBridgeRow] = field(default_factory=list)
    counts: MobileNotificationBridgeCounts = field(
        default_factory=MobileNotificationBridgeCounts
    )
    expired_ids: list[str] = field(default_factory=list)


# pyvision: public_api_methods.txt
@dataclass(frozen=True)
class MobilePlanActionResult:
    prefix: str
    notification_id: str
    response_file: str
    response_json: dict[str, Any]
    message: str


class MobilePlanActionError(RuntimeError):
    """Deterministic host-side plan action failure."""

    def __init__(self, code: str, target: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.target = target


def read_mobile_notification_snapshot(
    *,
    unread_only: bool = False,
    include_dismissed: bool = False,
    include_silent: bool = False,
    limit: int | None = None,
    newer_than: str | None = None,
) -> MobileNotificationBridgeSnapshot:
    """Return the gateway's read-only host notification projection."""
    snapshot = read_notification_snapshot(
        include_dismissed=include_dismissed,
        expire_due_snoozes=True,
    )
    rows = sorted(snapshot.notifications, key=_timestamp_sort_key, reverse=True)
    if unread_only:
        rows = [row for row in rows if not row.read]
    if not include_silent:
        rows = [row for row in rows if not row.silent]
    if newer_than is not None:
        rows = [
            row
            for row in rows
            if _timestamp_sort_key(row) > _parse_timestamp_sort_key(newer_than)
        ]
    if limit is not None:
        rows = rows[: max(0, limit)]

    return MobileNotificationBridgeSnapshot(
        rows=[_bridge_row(row) for row in rows],
        counts=MobileNotificationBridgeCounts(
            priority=int(snapshot.counts.priority),
            rest=int(snapshot.counts.rest),
            muted=int(snapshot.counts.muted),
        ),
        expired_ids=list(snapshot.expired_ids),
    )


def resolve_mobile_notification_detail(
    notification_id: str,
) -> MobileNotificationBridgeRow | None:
    """Return one notification by exact id, including dismissed/silent rows."""
    snapshot = read_mobile_notification_snapshot(
        include_dismissed=True,
        include_silent=True,
    )
    return next((row for row in snapshot.rows if row.id == notification_id), None)


def execute_mobile_plan_action(
    prefix: str,
    choice: str,
    *,
    feedback: str | None = None,
    commit_plan: bool | None = None,
    run_coder: bool | None = None,
    coder_prompt: str | None = None,
    coder_model: str | None = None,
) -> MobilePlanActionResult:
    """Write a plan approval response and run best-effort host side effects."""
    from sase.notifications.pending_actions import resolve_prefix

    identity = resolve_prefix(prefix)
    if identity.resolution == "missing":
        raise MobilePlanActionError("not_found", prefix, "action prefix not found")
    if identity.resolution in {"ambiguous_prefix", "duplicate_full_id"}:
        raise MobilePlanActionError(
            "ambiguous_prefix", prefix, "action prefix is ambiguous"
        )

    notification = resolve_mobile_notification_detail(identity.notification_id)
    if notification is None:
        raise MobilePlanActionError(
            "not_found", identity.notification_id, "notification not found"
        )
    if notification.action != "PlanApproval":
        raise MobilePlanActionError(
            "unsupported_action",
            notification.action or "non_action",
            "notification is not a plan approval",
        )
    if notification.action_state == "already_handled":
        raise MobilePlanActionError(
            "conflict_already_handled",
            notification.id,
            "action already handled",
        )
    if notification.action_state == "stale":
        raise MobilePlanActionError("gone_stale", notification.id, "action is stale")
    if notification.action_state in {"missing_request", "missing_target"}:
        raise MobilePlanActionError(
            "invalid_request", notification.id, f"action is {notification.action_state}"
        )

    response_dir = Path(
        notification.host_action_data.get("response_dir", "")
    ).expanduser()
    if not response_dir.is_dir():
        raise MobilePlanActionError(
            "invalid_request", "response_dir", "response_dir is missing"
        )
    if not (response_dir / "plan_request.json").is_file():
        raise MobilePlanActionError(
            "conflict_already_handled",
            notification.id,
            "plan request was already consumed",
        )
    if not notification.host_files:
        raise MobilePlanActionError(
            "invalid_request", "plan_file", "plan file is missing"
        )

    response_json, message = _plan_response_json(
        choice,
        feedback=feedback,
        commit_plan=commit_plan,
        run_coder=run_coder,
        coder_prompt=coder_prompt,
        coder_model=coder_model,
    )
    response_path = response_dir / "plan_response.json"
    try:
        with response_path.open("x", encoding="utf-8") as f:
            json.dump(response_json, f, indent=2)
            f.write("\n")
    except FileExistsError as exc:
        raise MobilePlanActionError(
            "conflict_already_handled", notification.id, "response already exists"
        ) from exc

    _run_plan_side_effects(notification, choice, response_path, response_json)
    return MobilePlanActionResult(
        prefix=prefix,
        notification_id=notification.id,
        response_file="plan_response.json",
        response_json=response_json,
        message=message,
    )


def _bridge_row(notification: Notification) -> MobileNotificationBridgeRow:
    from sase.notifications.pending_actions import action_state_for_notification

    return MobileNotificationBridgeRow(
        id=notification.id,
        timestamp=notification.timestamp,
        sender=notification.sender,
        priority=is_priority(notification),
        notes=list(notification.notes),
        display_files=[_normalize_home_path(path) for path in notification.files],
        host_files=[str(Path(path).expanduser()) for path in notification.files],
        action=notification.action,
        action_state=action_state_for_notification(notification),
        display_action_data={
            key: _normalize_home_path(value)
            for key, value in notification.action_data.items()
        },
        host_action_data={
            key: str(Path(value).expanduser())
            for key, value in notification.action_data.items()
        },
        read=notification.read,
        dismissed=notification.dismissed,
        silent=notification.silent,
        muted=notification.muted,
        snooze_until=notification.snooze_until,
    )


def _plan_response_json(
    choice: str,
    *,
    feedback: str | None,
    commit_plan: bool | None,
    run_coder: bool | None,
    coder_prompt: str | None,
    coder_model: str | None,
) -> tuple[dict[str, Any], str]:
    response: dict[str, Any] = {}
    if choice == "approve":
        response["action"] = "approve"
        if commit_plan is not None:
            response["commit_plan"] = commit_plan
        if run_coder is not None:
            response["run_coder"] = run_coder
        if coder_prompt is not None:
            response["coder_prompt"] = coder_prompt
        if coder_model is not None:
            response["coder_model"] = coder_model
        return response, "Plan approved"
    if choice == "run":
        response.update({"action": "approve", "commit_plan": False, "run_coder": True})
        if coder_prompt is not None:
            response["coder_prompt"] = coder_prompt
        if coder_model is not None:
            response["coder_model"] = coder_model
        return response, "Running coder"
    if choice == "reject":
        response["action"] = "reject"
        if feedback is not None:
            response["feedback"] = feedback
        return response, "Plan rejected"
    if choice == "feedback":
        if not feedback:
            raise MobilePlanActionError(
                "invalid_request", "feedback", "feedback text is required"
            )
        return {"action": "reject", "feedback": feedback}, "Feedback received"
    if choice in {"epic", "legend"}:
        return {"action": choice}, f"{choice.title()} created"
    raise MobilePlanActionError(
        "unsupported_action", choice, "unsupported plan action choice"
    )


def _run_plan_side_effects(
    notification: MobileNotificationBridgeRow,
    choice: str,
    response_path: Path,
    response_json: dict[str, Any],
) -> None:
    try:
        from sase.notifications import mark_dismissed

        mark_dismissed(notification.id)
    except Exception:
        pass

    _persist_plan_approved_metadata(notification, choice, response_json)
    if choice in {"approve", "epic", "legend"}:
        saved_path = _archive_plan_for_mobile_approval(notification, choice)
        if saved_path:
            try:
                response_json["saved_plan_path"] = saved_path
                response_path.write_text(
                    json.dumps(response_json, indent=2) + "\n",
                    encoding="utf-8",
                )
            except OSError:
                pass


def _persist_plan_approved_metadata(
    notification: MobileNotificationBridgeRow,
    choice: str,
    response_json: dict[str, Any],
) -> None:
    if choice not in {"approve", "epic", "legend"}:
        return
    response_dir = Path(
        notification.host_action_data.get("response_dir", "")
    ).expanduser()
    meta_path = response_dir.parent / "agent_meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(meta, dict):
            meta = {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        meta = {}
    action = choice
    if (
        choice == "approve"
        and response_json.get("commit_plan", True) is True
        and response_json.get("run_coder", True) is False
    ):
        action = "commit"
    meta["plan_approved"] = True
    meta["plan_action"] = action
    try:
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def _archive_plan_for_mobile_approval(
    notification: MobileNotificationBridgeRow,
    choice: str,
) -> str | None:
    if not notification.host_files:
        return None
    try:
        from sase.gemini_wrapper.file_references import format_with_prettier
        from sase.llm_provider._plan_utils import add_create_time_frontmatter
        from sase.running_field import get_workspace_directory
        from sase.sdd.beads import get_sdd_config
        from sase.sdd.files import get_sdd_dir, get_yyyymm

        project_dir = notification.host_action_data.get("project_dir")
        if not project_dir:
            return None
        project_basename = os.path.basename(str(project_dir))
        workspace_dir = get_workspace_directory(project_basename, 1)
        sdd_dir = get_sdd_dir(workspace_dir, 1, get_sdd_config())
        plan_kind = (
            "epics"
            if choice == "epic"
            else "legends"
            if choice == "legend"
            else "tales"
        )
        dest_dir = sdd_dir / plan_kind / get_yyyymm()
        dest_dir.mkdir(parents=True, exist_ok=True)
        src_plan = Path(notification.host_files[0])
        content = format_with_prettier(src_plan.read_text(encoding="utf-8"))
        dest = dest_dir / src_plan.name
        dest.write_text(add_create_time_frontmatter(content), encoding="utf-8")
        return str(dest)
    except Exception:
        return None


def _normalize_home_path(value: str) -> str:
    expanded = str(Path(value).expanduser())
    home = str(Path.home())
    if expanded == home:
        return "~"
    if expanded.startswith(f"{home}/"):
        return f"~/{expanded[len(home) + 1 :]}"
    return value


def _timestamp_sort_key(notification: Notification) -> datetime:
    return _parse_timestamp_sort_key(notification.timestamp)


def _parse_timestamp_sort_key(value: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return datetime.min.replace(tzinfo=get_timezone())
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=get_timezone())
    return timestamp


__all__ = [
    "MobilePlanActionError",
    "MobilePlanActionResult",
    "MobileNotificationBridgeCounts",
    "MobileNotificationBridgeRow",
    "MobileNotificationBridgeSnapshot",
    "execute_mobile_plan_action",
    "read_mobile_notification_snapshot",
    "resolve_mobile_notification_detail",
]

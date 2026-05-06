"""Best-effort side effects for mobile notification actions."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sase.integrations._mobile_notification_models import MobileNotificationBridgeRow


def dismiss_notification_best_effort(notification_id: str) -> None:
    try:
        from sase.notifications import mark_dismissed

        mark_dismissed(notification_id)
    except Exception:
        pass


def run_plan_side_effects(
    notification: MobileNotificationBridgeRow,
    choice: str,
    response_path: Path,
    response_json: dict[str, Any],
) -> None:
    dismiss_notification_best_effort(notification.id)

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

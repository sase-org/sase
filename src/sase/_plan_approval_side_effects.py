"""Post-terminal plan approval side effects and host plan archiving."""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from sase._plan_approval_artifacts import durable_plan_file_for_context
from sase._plan_approval_protocol import PlanApprovalActionContext
from sase._plan_approval_protocol import PlanApprovalActionError

_logger = logging.getLogger(__name__)


def dismiss_notification_best_effort(notification_id: str) -> None:
    try:
        from sase.notifications import mark_dismissed

        mark_dismissed(notification_id)
    except Exception:
        pass


def _mark_action_handled_best_effort(
    notification_id: str,
    *,
    source: str,
    action: str | None = None,
) -> None:
    """Record that a notification action was resolved in the shared store."""
    try:
        from sase.notifications.pending_actions import mark_already_handled

        mark_already_handled(notification_id, source=source, action=action)
    except Exception:
        pass


def apply_plan_post_terminal_side_effects(
    notification: PlanApprovalActionContext,
    choice: str,
    *,
    source: str = "plan_response",
) -> None:
    dismiss_notification_best_effort(notification.id)
    _mark_action_handled_best_effort(notification.id, source=source, action=choice)


def preflight_plan_archive_credential(selected_option_ids: Sequence[str]) -> None:
    """Refuse a host-archived plan approval whose git credential is rejected.

    A tale approval that selects ``commit`` makes the host archive the plan over
    an SSH remote. Discovering a rejected credential there fails the gate after
    the decision was accepted; asking the remote first refuses the answer while
    the gate is still pending. Only an explicit ``denied`` refuses: an offline
    or otherwise unknowable remote (``unknown``) must not block an approval.
    """
    if "commit" not in selected_option_ids:
        return
    from sase.service.ssh_agent import probe_git_remote_auth

    if probe_git_remote_auth(os.environ) != "denied":
        return
    raise PlanApprovalActionError(
        "git_credential_denied",
        "git_remote",
        "the git remote rejected this host's SSH credential "
        "(`Permission denied (publickey)`, or a deploy key scoped to one other "
        "repository was offered first), so the approved plan cannot be "
        "archived; the gate remains pending. Give the host an unattended "
        "credential (a passphrase-less `IdentityFile` with `IdentitiesOnly yes` "
        "for `Host github.com`, or a key loaded into the agent the service host "
        "inherits; see docs/init.md), then answer again.",
    )


def sync_reviewed_plan_to_durable_best_effort(
    notification: PlanApprovalActionContext,
) -> None:
    """Copy reviewed bundle edits back to the durable proposal when known."""
    if not notification.host_files:
        return
    durable = durable_plan_file_for_context(notification)
    if durable is None:
        return
    reviewed = Path(notification.host_files[0]).expanduser()
    if reviewed.resolve(strict=False) == durable.resolve(strict=False):
        return
    try:
        content = reviewed.read_text(encoding="utf-8")
        durable.parent.mkdir(parents=True, exist_ok=True)
        durable.write_text(content, encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        _logger.warning(
            "Failed to sync reviewed plan %s to durable proposal %s",
            reviewed,
            durable,
            exc_info=True,
        )


def archive_plan_for_approval(
    notification: PlanApprovalActionContext,
    persisted_action: str,
    *,
    required: bool = False,
) -> str | None:
    if not notification.host_files:
        if required:
            raise PlanApprovalActionError(
                "invalid_request",
                "plan_file",
                "plan file is missing",
            )
        return None
    tier: Literal["tale", "epic"] = "epic" if persisted_action == "epic" else "tale"
    src_plan = durable_plan_file_for_context(notification) or Path(
        notification.host_files[0]
    )
    try:
        from sase._plan_archive_approval import archive_approved_plan

        return archive_approved_plan(
            notification.host_action_data,
            src_plan,
            tier=tier,
        )
    except Exception as error:
        from sase._plan_archive_approval import report_plan_archive_failure

        report_plan_archive_failure(src_plan, notification.host_action_data, error)
        if required:
            raise PlanApprovalActionError(
                "plan_archive_failed",
                str(src_plan),
                f"failed to archive approved plan: {error}",
            ) from error
        return None

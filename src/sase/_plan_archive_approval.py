"""Shared approval-time plan archiving for every approval surface.

Two surfaces archive an approved plan into its project's SDD plan store: the
gate-response path in :mod:`sase.plan_approval_actions` and the TUI background
worker in
:mod:`sase.ace.tui.actions.agents._notification_plan_background`.  Both start
from notification action data and have to resolve which project the plan
belongs to before a workspace and SDD store can be materialized.

That resolution is the step that regressed silently.  ``project_dir`` in the
action data is the *agent workspace* directory, not a project directory, and
plan gates write it with a trailing slash, so ``os.path.basename`` returned the
empty string and the workspace-plugin lookup was handed
``~/.sase/projects/.sase``.  Every approval-time archive raised and was
swallowed into a log warning.  Resolution now goes through
:func:`sase._plan_approval_artifacts.resolve_plan_action_project_name`, which
prefers ``agent_project_file`` and understands workspace directories, and
failures are reported to the notification inbox instead of only the log.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

PLAN_ARCHIVE_SENDER = "plan-archive"


class _PlanArchiveProjectError(Exception):
    """Raised when action data does not identify an archivable project."""


def archive_approved_plan(
    action_data: Mapping[str, str],
    src_plan: Path,
    *,
    tier: Literal["tale", "epic"],
    push_after_commit: bool | Literal["async"] | None = None,
) -> str:
    """Archive ``src_plan`` into its project's plan store and return the path.

    Raises:
        _PlanArchiveProjectError: If ``action_data`` names no resolvable project.
    """
    from sase._plan_approval_artifacts import (
        resolve_plan_action_project_name,
        resolve_plan_agent_artifacts_dir,
    )
    from sase.running_field import get_workspace_directory
    from sase.sdd.files import (
        commit_sdd_store_files,
        ensure_bare_git_sdd_initialized,
    )
    from sase.sdd.plan_archive import archive_plan_file
    from sase.sdd.store import materialize_sdd_store

    project_name = resolve_plan_action_project_name(action_data)
    if not project_name:
        raise _PlanArchiveProjectError(
            "no project could be resolved for the approved plan from action data"
            f" keys {sorted(action_data)}"
        )

    workspace_dir = get_workspace_directory(project_name, 1)
    sdd_store = materialize_sdd_store(workspace_dir, 1)
    if sdd_store.is_in_tree:
        ensure_bare_git_sdd_initialized(workspace_dir, commit=True, push=False)
    archived = archive_plan_file(
        src_plan,
        sdd_store,
        tier=tier,
        preserve_existing=False,
        expect_prompt_snapshot=(tier == "epic"),
    )
    if not sdd_store.is_in_tree:
        commit_sdd_store_files(
            sdd_store,
            f"Archive approved plan {src_plan.stem}",
            paths=[archived.path],
            push_after_commit=push_after_commit,
            artifacts_dir=resolve_plan_agent_artifacts_dir(action_data),
        )
    return str(archived.path)


def report_plan_archive_failure(
    src_plan: Path | str,
    action_data: Mapping[str, str],
    error: BaseException,
) -> None:
    """Log and surface an approval-time archive failure.

    Archiving stays best-effort -- an approval must never fail because its plan
    could not be filed -- but the failure is no longer log-only.  A silent
    warning is what let every approval-time archive fail for a week without
    anyone noticing.
    """
    plan_path = str(src_plan)
    log.error("Failed to archive approved plan %s", plan_path, exc_info=error)
    try:
        from sase.notifications import notify_workflow_complete

        notify_workflow_complete(
            PLAN_ARCHIVE_SENDER,
            action_data.get("agent_cl_name"),
            False,
            [
                f"Failed to archive approved plan: {Path(plan_path).name}",
                f"{type(error).__name__}: {error}",
                "The plan of record exists only on this machine until it is"
                " archived by a later launch.",
            ],
            extra_files=[plan_path],
            tags=["plan"],
        )
    except Exception:
        log.debug("Failed to report plan archive failure", exc_info=True)

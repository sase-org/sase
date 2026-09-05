"""Filesystem-backed loaders for completed agents."""

from concurrent.futures import CancelledError
from pathlib import Path

from sase.ace.patch.project_spec_path import preferred_project_spec_path
from sase.agent.status_buckets import EPIC_APPROVED_STATUS
from sase.core.agent_artifact_paths import parse_agent_artifact_path
from sase.core.paths import sase_projects_dir
from sase.gate_shell.status import DEFAULT_GATE_SHELL_SETTLED_STATUS
from sase.monitor_status import (
    DEFAULT_MONITOR_STOP_STATUS,
    clamp_monitor_status_or_default,
)

from ._done_common import (
    done_extra_files,
    enrich_agent_revert_state,
    enrich_missing_commit_metadata,
)
from ._json_cache import load_json_cached
from ._meta_enrichment import (
    enrich_agent_from_meta,
    enrich_agent_from_prompt_markers,
)
from ._meta_enrichment_common import apply_gate_done, apply_monitor_done
from .._timestamps import parse_timestamp_14_digit
from ..agent import Agent, AgentType


_DONE_AGENT_WORKFLOW_DIRS = [
    "ace-run",
    "run",
    "fix-hook",
    "crs",
    "summarize-hook",
]

_DONE_AGENT_WORKFLOW_PREFIXES = [
    "mentor-",
]


def iter_artifact_workflow_dirs(artifacts_dir: Path) -> list[Path]:
    """Yield workflow directories under an artifacts dir that may contain done.json.

    Handles both fixed-name directories (ace-run, fix-hook, crs, summarize-hook)
    and prefix-matched directories (mentor-*).
    """
    dirs: list[Path] = []
    for name in _DONE_AGENT_WORKFLOW_DIRS:
        d = artifacts_dir / name
        if d.exists():
            dirs.append(d)
    if artifacts_dir.exists():
        for d in artifacts_dir.iterdir():
            if not d.is_dir():
                continue
            for prefix in _DONE_AGENT_WORKFLOW_PREFIXES:
                if d.name.startswith(prefix):
                    dirs.append(d)
                    break
    return dirs


def load_done_agent_for_dir(
    artifact_dir: Path,
    workflow_dir_name: str,
    bug_by_cl_name: dict[str, str | None],
    cl_by_cl_name: dict[str, str | None],
) -> Agent | None:
    """Load a single done.json and build an Agent, or None on error/skip."""
    done_file = artifact_dir / "done.json"
    if not done_file.exists():
        return None

    try:
        data = load_json_cached(done_file)
        parsed_path = parse_agent_artifact_path(artifact_dir)

        project_file = data.get("project_file")
        if not project_file and parsed_path is not None:
            project_file = preferred_project_spec_path(
                str(sase_projects_dir() / parsed_path.project_name),
                parsed_path.project_name,
            )

        # Parse timestamp from artifact dir name (YYYYmmddHHMMSS)
        timestamp_str = artifact_dir.name
        start_time = parse_timestamp_14_digit(timestamp_str)

        cl_name = data.get("cl_name", "unknown")
        outcome = data.get("outcome", "completed")
        if outcome == "noop":
            return None
        if outcome in {"failed", "epic_launch_failed"}:
            # Spawn-on-retry: a failed parent that handed off to a child
            # displays as "FAILED (RETRIED)" so the user can distinguish a
            # terminal failure with a downstream retry from a dead-end one.
            if outcome == "failed" and data.get("retried_as_timestamp"):
                status = "FAILED (RETRIED)"
            else:
                status = "FAILED"
            error_message = data.get("error") or (
                "Epic launch failed" if outcome == "epic_launch_failed" else None
            )
            error_traceback = data.get("traceback")
        elif outcome == "monitored":
            raw_status = data.get("status_label")
            status = clamp_monitor_status_or_default(
                raw_status if isinstance(raw_status, str) else None,
                default=DEFAULT_MONITOR_STOP_STATUS,
            )
            error_message = (
                data.get("error") if isinstance(data.get("error"), str) else None
            )
            error_traceback = None
        elif outcome == "gated":
            status = (
                data.get("status_label")
                if isinstance(data.get("status_label"), str)
                else DEFAULT_GATE_SHELL_SETTLED_STATUS
            )
            error_message = (
                data.get("error") if isinstance(data.get("error"), str) else None
            )
            error_traceback = None
        elif outcome == "stopped" or data.get("repeat_stopped"):
            # Repeat-chain STOP: the slot was skipped by a predecessor's STOP
            # output variable. It keeps ``outcome: "completed"`` (so %wait
            # cascading still resolves it) but is a non-error terminal state,
            # so it must be checked before the generic completed mapping.
            #
            # Queued family children cancelled by a failed parent use
            # ``outcome: "stopped"`` because they must render the same visible
            # status without satisfying downstream wait dependencies.
            status = "STOPPED"
            error_message = None
            error_traceback = None
        elif outcome == "plan_rejected":
            status = "PLAN REJECTED"
            error_message = None
            error_traceback = None
        elif outcome == "epic_approved":
            status = EPIC_APPROVED_STATUS
            error_message = None
            error_traceback = None
        else:
            status = "DONE"
            error_message = None
            error_traceback = None
        extra_files = done_extra_files(
            data.get("plan_path"),
            data.get("markdown_pdf_paths"),
            data.get("image_paths"),
            data.get("video_paths"),
        )

        agent = Agent(
            agent_type=AgentType.RUNNING,
            cl_name=cl_name,
            project_file=project_file or "",
            status=status,
            start_time=start_time,
            status_bucket=(
                data.get("status_bucket")
                if isinstance(data.get("status_bucket"), str)
                else None
            ),
            workflow=workflow_dir_name,
            raw_suffix=timestamp_str,
            response_path=data.get("response_path"),
            diff_path=data.get("diff_path"),
            extra_files=extra_files,
            plan_path=(
                data.get("plan_path")
                if isinstance(data.get("plan_path"), str)
                else None
            ),
            archived_plan_path=(
                data.get("plan_path")
                if isinstance(data.get("plan_path"), str)
                else None
            ),
            step_output=data.get("step_output"),
            workspace_num=data.get("workspace_num"),
            workspace_dir=data.get("workspace_dir"),
            bug=bug_by_cl_name.get(cl_name),
            cl_num=cl_by_cl_name.get(cl_name),
            error_message=error_message,
            error_traceback=error_traceback,
            output_path=data.get("output_path"),
            model=data.get("model"),
            llm_provider=data.get("llm_provider"),
            vcs_provider=data.get("vcs_provider"),
            agent_name=data.get("name"),
            hidden=bool(data.get("hidden")),
            approve=bool(data.get("approve")),
            monitor_stop_status=status if outcome == "monitored" else None,
            gate_stop_status=status if outcome == "gated" else None,
        )

        # Retry-chain lineage from done.json (parent-side: forward pointer
        # to the spawned retry child).  Mirrors agent_meta.json.
        if data.get("retried_as_timestamp"):
            agent.retried_as_timestamp = data["retried_as_timestamp"]
        if data.get("retry_chain_root_timestamp"):
            agent.retry_chain_root_timestamp = data["retry_chain_root_timestamp"]
        if data.get("retry_error_category"):
            agent.retry_error_category = data["retry_error_category"]

        # Always enrich from agent_meta.json. It may contain fields not in
        # done.json, such as a name set via TUI rename after agent start.
        enrich_agent_from_meta(agent, str(artifact_dir))
        if outcome == "monitored":
            apply_monitor_done(
                agent,
                monitor_state=data.get("monitor_state"),
                monitor_exit_code=data.get("monitor_exit_code"),
                status_label=data.get("status_label"),
                monitor_followup_outcome=data.get("monitor_followup_outcome"),
                monitor_followup_error=data.get("monitor_followup_error"),
            )
        elif outcome == "gated":
            apply_gate_done(
                agent,
                gate_id=data.get("gate_id"),
                gate_kind=data.get("gate_kind"),
                gate_state=data.get("gate_state"),
                gate_elapsed_seconds=data.get("gate_elapsed_seconds"),
                gate_output_path=data.get("gate_output_path"),
                gate_output_truncated=data.get("gate_output_truncated"),
                gate_bundle_path=data.get("gate_bundle_path"),
                gate_notification_id=data.get("gate_notification_id"),
                status_label=data.get("status_label"),
                gate_followup_outcome=data.get("gate_followup_outcome"),
                gate_followup_error=data.get("gate_followup_error"),
                gate_followup_degraded_reason=data.get("gate_followup_degraded_reason"),
                gate_followup_prompt_path=data.get("gate_followup_prompt_path"),
            )
        enrich_agent_from_prompt_markers(agent, str(artifact_dir))
        enrich_missing_commit_metadata(agent, artifact_dir)
        enrich_agent_revert_state(agent, artifact_dir)

        return agent
    except Exception:
        return None


def load_done_agents(
    bug_by_cl_name: dict[str, str | None],
    cl_by_cl_name: dict[str, str | None],
) -> list[Agent]:
    """Load completed agents from done.json marker files.

    Scans ~/.sase/projects/*/artifacts/<workflow>/*/done.json for completed agents
    across every project lifecycle state.
    Supported workflow directories: ace-run, fix-hook, crs, summarize-hook, mentor-*.

    Args:
        bug_by_cl_name: Mapping of Patch names to bug URLs.
        cl_by_cl_name: Mapping of Patch names to PR numbers.

    Returns:
        List of Agent objects with DONE or FAILED status.
    """
    from ._json_cache import get_loader_executor, is_loader_executor_shutdown_error

    projects_dir = sase_projects_dir()

    if not projects_dir.exists():
        return []

    # Collect (artifact_dir, workflow_dir_name) pairs first so we can fan
    # out the JSON reads across a thread pool.
    tasks: list[tuple[Path, str]] = []
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        artifacts_base = project_dir / "artifacts"
        if not artifacts_base.exists():
            continue

        for workflow_dir in iter_artifact_workflow_dirs(artifacts_base):
            for artifact_dir in workflow_dir.iterdir():
                if not artifact_dir.is_dir():
                    continue
                tasks.append((artifact_dir, workflow_dir.name))

    if not tasks:
        return []

    executor = get_loader_executor()
    agents: list[Agent] = []
    try:
        for agent in executor.map(
            lambda t: load_done_agent_for_dir(
                t[0], t[1], bug_by_cl_name, cl_by_cl_name
            ),
            tasks,
        ):
            if agent is not None:
                agents.append(agent)
    except CancelledError:
        return agents
    except RuntimeError as exc:
        if is_loader_executor_shutdown_error(exc):
            return agents
        raise
    return agents

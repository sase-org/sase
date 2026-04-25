"""Filesystem artifact loaders (project files, done/running markers)."""

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from zoneinfo import ZoneInfo

from sase.running_field import get_claimed_workspaces
from sase.core.time import get_timezone

from ....hooks.processes import is_process_running
from ._json_cache import load_json_cached
from .._timestamps import (
    normalize_to_14_digit,
    parse_timestamp_14_digit,
    parse_timestamp_from_workflow_name,
)
from ..agent import Agent, AgentType


@lru_cache(maxsize=1)
def _cached_timezone() -> ZoneInfo:
    return get_timezone()


def _parse_utc_to_eastern(iso_str: str) -> datetime:
    """Parse a UTC ISO 8601 timestamp and convert to Eastern time (naive)."""
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return dt.astimezone(_cached_timezone()).replace(tzinfo=None)


def enrich_agent_from_meta(agent: Agent, artifacts_dir: str | None) -> None:
    """Read agent_meta.json and populate model/vcs_provider fields.

    Args:
        agent: The Agent to enrich (modified in place).
        artifacts_dir: Path to the artifacts directory, or None.
    """
    if not artifacts_dir:
        return

    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        data = load_json_cached(meta_path)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return

    if not isinstance(data, dict):
        return

    if data.get("model"):
        agent.model = data["model"]
    if data.get("llm_provider"):
        agent.llm_provider = data["llm_provider"]
    if data.get("vcs_provider"):
        agent.vcs_provider = data["vcs_provider"]
    if data.get("name"):
        agent.agent_name = data["name"]
    if data.get("wait_for"):
        agent.waiting_for = data["wait_for"]
    if data.get("approve"):
        agent.approve = True
    if data.get("hidden"):
        agent.hidden = True
    if data.get("role_suffix"):
        agent.role_suffix = data["role_suffix"]
    if data.get("parent_timestamp") and agent.parent_timestamp is None:
        agent.parent_timestamp = data["parent_timestamp"]
    if data.get("workspace_num") is not None and agent.workspace_num is None:
        try:
            agent.workspace_num = int(data["workspace_num"])
        except (ValueError, TypeError):
            pass

    # Retry-chain lineage (spawn-on-retry)
    if data.get("retry_of_timestamp"):
        agent.retry_of_timestamp = data["retry_of_timestamp"]
    raw_retry_attempt = data.get("retry_attempt")
    if isinstance(raw_retry_attempt, int):
        agent.retry_attempt = raw_retry_attempt
    if data.get("retry_chain_root_timestamp"):
        agent.retry_chain_root_timestamp = data["retry_chain_root_timestamp"]
    if data.get("retried_as_timestamp"):
        agent.retried_as_timestamp = data["retried_as_timestamp"]
    if data.get("retry_terminal"):
        agent.retry_terminal = bool(data["retry_terminal"])
    if data.get("retry_error_category"):
        agent.retry_error_category = data["retry_error_category"]

    def _append_timestamp_field(
        raw_value: object,
        target: list[datetime],
    ) -> None:
        values: list[str] = []
        if isinstance(raw_value, str):
            values = [raw_value]
        elif isinstance(raw_value, list):
            values = [v for v in raw_value if isinstance(v, str)]
        for value in values:
            try:
                target.append(_parse_utc_to_eastern(value))
            except ValueError:
                continue

    # Parse plan_submitted_at (when plan was submitted for review)
    _append_timestamp_field(data.get("plan_submitted_at"), agent.plan_times)

    # Parse feedback_submitted_at (when feedback was given on the plan)
    _append_timestamp_field(data.get("feedback_submitted_at"), agent.feedback_times)

    # Parse questions_submitted_at (when agent submitted questions)
    _append_timestamp_field(data.get("questions_submitted_at"), agent.questions_times)

    # Parse retry_started_at (list of timestamps, one per retry/fallback)
    retry_started_at = data.get("retry_started_at")
    if isinstance(retry_started_at, list):
        for ts in retry_started_at:
            if isinstance(ts, str):
                try:
                    agent.retry_times.append(_parse_utc_to_eastern(ts))
                except ValueError:
                    pass

    # Parse run_started_at (actual start time after waiting period)
    run_started_at = data.get("run_started_at")
    if isinstance(run_started_at, str):
        try:
            agent.run_start_time = _parse_utc_to_eastern(run_started_at)
        except ValueError:
            pass

    # Parse stopped_at (completion time for DONE/FAILED agents)
    stopped_at = data.get("stopped_at")
    if isinstance(stopped_at, str):
        try:
            agent.stop_time = _parse_utc_to_eastern(stopped_at)
        except ValueError:
            pass

    # Check for waiting.json to set WAITING status (takes precedence over PLANNING
    # since the agent can't plan until its dependencies are resolved)
    waiting_path = Path(artifacts_dir) / "waiting.json"
    if waiting_path.exists() and agent.status == "RUNNING":
        agent.status = "WAITING"
        # waiting.json may contain an updated waiting_for list (e.g. from the TUI
        # "w" keymap), which takes precedence over agent_meta.json's wait_for.
        try:
            with open(waiting_path, encoding="utf-8") as f:
                waiting_data = json.load(f)
            if isinstance(waiting_data, dict):
                if waiting_data.get("waiting_for"):
                    agent.waiting_for = waiting_data["waiting_for"]
                # Read wait_duration from waiting.json (preferred source)
                raw_dur = waiting_data.get("wait_duration")
                if raw_dur is not None:
                    try:
                        agent.wait_duration = float(raw_dur)
                    except (ValueError, TypeError):
                        pass
                # Read wait_until from waiting.json
                raw_until = waiting_data.get("wait_until")
                if isinstance(raw_until, str) and raw_until:
                    agent.wait_until = raw_until
        except (json.JSONDecodeError, OSError):
            pass

    # Fallback: read wait_duration from agent_meta.json if not set from waiting.json
    if agent.wait_duration is None:
        raw_dur = data.get("wait_duration")
        if raw_dur is not None:
            try:
                agent.wait_duration = float(raw_dur)
            except (ValueError, TypeError):
                pass

    # Fallback: read wait_until from agent_meta.json if not set from waiting.json
    if agent.wait_until is None:
        raw_until = data.get("wait_until")
        if isinstance(raw_until, str) and raw_until:
            agent.wait_until = raw_until

    # Set PLANNING / PLAN APPROVED / PLAN COMMITTED / EPIC APPROVED status
    # for agents launched with %plan directive
    if data.get("plan") and agent.status == "RUNNING":
        if data.get("plan_approved"):
            plan_action = data.get("plan_action")
            if plan_action == "commit":
                agent.status = "PLAN COMMITTED"
            elif plan_action == "epic":
                agent.status = "EPIC APPROVED"
            else:
                agent.status = "PLAN APPROVED"
        else:
            agent.status = "PLANNING"


def get_all_project_files() -> list[str]:
    """Get all project file paths.

    Returns:
        List of paths to .gp files.
    """
    projects_dir = Path.home() / ".sase" / "projects"

    if not projects_dir.exists():
        return []

    project_files: list[str] = []

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        project_name = project_dir.name
        gp_file = project_dir / f"{project_name}.gp"

        if gp_file.exists():
            project_files.append(str(gp_file))

    return project_files


def load_agents_from_running_field(
    project_files: list[str],
    bug_by_cl_name: dict[str, str | None],
    cl_by_cl_name: dict[str, str | None],
) -> list[Agent]:
    """Load agents from RUNNING field in all project files.

    Args:
        project_files: List of project file paths.
        bug_by_cl_name: Mapping of CL names to bug URLs.
        cl_by_cl_name: Mapping of CL names to CL numbers.

    Returns:
        List of Agent objects from RUNNING field claims.
    """
    agents: list[Agent] = []

    for project_file in project_files:
        claims = get_claimed_workspaces(project_file)
        for claim in claims:
            # Skip hook processes - they're not agents
            # Hook processes have workflow like "axe(hooks)-1" or "axe(hooks)-1a"
            if claim.workflow and claim.workflow.startswith("axe(hooks)"):
                continue

            # Detect workflow claims: workflow field starts with "workflow("
            is_workflow_claim = (
                claim.workflow
                and claim.workflow.startswith("workflow(")
                and claim.workflow.endswith(")")
            )

            if is_workflow_claim:
                # Extract workflow name from "workflow(name)"
                workflow_name = claim.workflow[9:-1]
                agent_type = AgentType.WORKFLOW
            else:
                workflow_name = claim.workflow
                agent_type = AgentType.RUNNING

            # Normalize timestamp (handles both 13-char and 14-digit formats)
            normalized_ts = normalize_to_14_digit(claim.artifacts_timestamp)
            start_time = (
                parse_timestamp_14_digit(normalized_ts)
                if normalized_ts
                else parse_timestamp_from_workflow_name(claim.workflow)
            )

            cl_name = claim.cl_name or "unknown"
            agent = Agent(
                agent_type=agent_type,
                cl_name=cl_name,
                project_file=project_file,
                status="RUNNING",
                start_time=start_time,
                workspace_num=claim.workspace_num,
                workflow=workflow_name,
                pid=claim.pid,
                # Use normalized timestamp as raw_suffix for prompt lookup
                raw_suffix=normalized_ts,
                bug=bug_by_cl_name.get(cl_name),
                cl_num=cl_by_cl_name.get(cl_name),
            )
            enrich_agent_from_meta(agent, agent.get_artifacts_dir())
            # Axe-spawned agents are always hidden
            # Normalize hyphens to underscores (canonical form uses underscores,
            # e.g. xprompt workflow_label "fix_hook")
            if claim.workflow and any(
                claim.workflow.replace("-", "_").startswith(p)
                for p in ["axe(mentor)", "axe(fix_hook)", "axe(crs)", "mentor("]
            ):
                agent.hidden = True
            agents.append(agent)

    return agents


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


def _iter_artifact_workflow_dirs(artifacts_dir: Path) -> list[Path]:
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


def _load_done_agent_for_dir(
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

        # Parse timestamp from artifact dir name (YYYYmmddHHMMSS)
        timestamp_str = artifact_dir.name
        start_time = parse_timestamp_14_digit(timestamp_str)

        cl_name = data.get("cl_name", "unknown")
        outcome = data.get("outcome", "completed")
        if outcome == "noop":
            return None
        if outcome == "failed":
            # Spawn-on-retry: a failed parent that handed off to a child
            # displays as "FAILED (RETRIED)" so the user can distinguish a
            # terminal failure with a downstream retry from a dead-end one.
            if data.get("retried_as_timestamp"):
                status = "FAILED (RETRIED)"
            else:
                status = "FAILED"
            error_message = data.get("error")
            error_traceback = data.get("traceback")
        else:
            status = "DONE"
            error_message = None
            error_traceback = None
        plan_path = data.get("plan_path")
        extra_files = [plan_path] if plan_path else []

        agent = Agent(
            agent_type=AgentType.RUNNING,
            cl_name=cl_name,
            project_file=data.get("project_file", ""),
            status=status,
            start_time=start_time,
            workflow=workflow_dir_name,
            raw_suffix=timestamp_str,
            response_path=data.get("response_path"),
            diff_path=data.get("diff_path"),
            extra_files=extra_files,
            step_output=data.get("step_output"),
            workspace_num=data.get("workspace_num"),
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
        )

        # Retry-chain lineage from done.json (parent-side: forward pointer
        # to the spawned retry child).  Mirrors agent_meta.json.
        if data.get("retried_as_timestamp"):
            agent.retried_as_timestamp = data["retried_as_timestamp"]
        if data.get("retry_chain_root_timestamp"):
            agent.retry_chain_root_timestamp = data["retry_chain_root_timestamp"]
        if data.get("retry_error_category"):
            agent.retry_error_category = data["retry_error_category"]

        # Always enrich from agent_meta.json — it may contain
        # fields not in done.json (e.g. name set via TUI rename
        # after the agent started, which the runner doesn't know
        # about when writing done.json).
        enrich_agent_from_meta(agent, str(artifact_dir))
        _enrich_agent_from_prompt_markers(agent, str(artifact_dir))

        return agent
    except Exception:
        return None


def load_done_agents(
    bug_by_cl_name: dict[str, str | None],
    cl_by_cl_name: dict[str, str | None],
) -> list[Agent]:
    """Load completed agents from done.json marker files.

    Scans ~/.sase/projects/*/artifacts/<workflow>/*/done.json for completed agents.
    Supported workflow directories: ace-run, fix-hook, crs, summarize-hook, mentor-*.

    Args:
        bug_by_cl_name: Mapping of CL names to bug URLs.
        cl_by_cl_name: Mapping of CL names to CL numbers.

    Returns:
        List of Agent objects with DONE or FAILED status.
    """
    from ._json_cache import get_loader_executor

    projects_dir = Path.home() / ".sase" / "projects"

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

        for workflow_dir in _iter_artifact_workflow_dirs(artifacts_base):
            for artifact_dir in workflow_dir.iterdir():
                if not artifact_dir.is_dir():
                    continue
                tasks.append((artifact_dir, workflow_dir.name))

    if not tasks:
        return []

    executor = get_loader_executor()
    results = executor.map(
        lambda t: _load_done_agent_for_dir(t[0], t[1], bug_by_cl_name, cl_by_cl_name),
        tasks,
    )
    return [agent for agent in results if agent is not None]


def _enrich_agent_from_prompt_markers(agent: Agent, artifacts_dir: str) -> None:
    """Read prompt_step_*.json markers and populate meta_* fields on step_output.

    Args:
        agent: The Agent to enrich (modified in place).
        artifacts_dir: Path to the artifacts directory.
    """
    artifacts_path = Path(artifacts_dir)
    meta_fields: dict[str, str] = {}
    for marker_file in sorted(artifacts_path.glob("prompt_step_*.json")):
        try:
            data = load_json_cached(marker_file)
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        output = data.get("output")
        if isinstance(output, dict):
            for k, v in output.items():
                if k.startswith("meta_") and v:
                    meta_fields[k] = str(v)
    if meta_fields:
        if agent.step_output is None:
            agent.step_output = {}
        agent.step_output.update(meta_fields)


def load_running_home_agents() -> list[Agent]:
    """Load running home mode agents from running.json marker files.

    Scans ~/.sase/projects/home/artifacts/ace-run/*/running.json for running agents.
    Only includes agents with PIDs that are still running.

    Returns:
        List of Agent objects with status="RUNNING".
    """
    agents: list[Agent] = []
    home_ace_run_dir = (
        Path.home() / ".sase" / "projects" / "home" / "artifacts" / "ace-run"
    )

    if not home_ace_run_dir.exists():
        return agents

    for artifact_dir in home_ace_run_dir.iterdir():
        if not artifact_dir.is_dir():
            continue

        running_file = artifact_dir / "running.json"
        if not running_file.exists():
            continue

        try:
            data = load_json_cached(running_file)

            # Verify PID is still running
            pid = data.get("pid")
            if pid is None or not is_process_running(pid):
                # Process died - clean up the stale marker
                try:
                    running_file.unlink()
                except OSError:
                    pass
                continue

            # Parse timestamp from artifact dir name (YYYYmmddHHMMSS)
            timestamp_str = artifact_dir.name
            start_time = parse_timestamp_14_digit(timestamp_str)

            cl_name = data.get("cl_name", "~")
            agent = Agent(
                agent_type=AgentType.RUNNING,
                cl_name=cl_name,
                project_file=str(
                    Path.home() / ".sase" / "projects" / "home" / "home.gp"
                ),
                status="RUNNING",
                start_time=start_time,
                workflow="ace(run)",
                pid=pid,
                raw_suffix=timestamp_str,
                model=data.get("model"),
                llm_provider=data.get("llm_provider"),
                vcs_provider=data.get("vcs_provider"),
            )
            enrich_agent_from_meta(agent, str(artifact_dir))
            _enrich_agent_from_prompt_markers(agent, str(artifact_dir))
            agents.append(agent)
        except Exception:
            continue

    return agents

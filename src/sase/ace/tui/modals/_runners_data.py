"""Data collection and parsing for the runners modal.

Collects information about running processes and agents from changespecs
and project files.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ...changespec import (
    ChangeSpec,
    HookEntry,
    HookStatusLine,
    MentorStatusLine,
    find_all_changespecs,
)
from ..models._loaders import get_all_project_files

# Workflow prefixes/names that indicate axe-spawned agents (not user-initiated)
_AXE_WORKFLOW_PREFIXES = (
    "axe(mentor)",
    "axe(fix-hook)",
    "axe(crs)",
    "axe(hooks)",
    "mentor-",
    "mentor(",
)
_AXE_WORKFLOW_NAMES = {"fix-hook", "crs", "mentor", "summarize-hook"}

_PROMPT_PREVIEW_MAX = 500


@dataclass
class RunnerInfo:
    """Information about a single runner."""

    runner_type: Literal["process", "agent"]
    cl_name: str
    project_name: str
    project_file: str
    hook_command: str | None  # For processes/hook agents
    agent_type: str | None  # fix-hook, summarize-hook, mentor, crs
    pid: int | None
    start_time: datetime | None
    reviewer: str | None  # For CRS agents
    raw_suffix: str | None
    workspace_num: int | None = None
    prompt_preview: str | None = None


def _parse_timestamp(ts: str) -> datetime | None:
    """Parse a YYmmdd_HHMMSS timestamp string to datetime.

    Args:
        ts: Timestamp string in YYmmdd_HHMMSS format.

    Returns:
        datetime object or None if parsing fails.
    """
    try:
        return datetime.strptime(ts, "%y%m%d_%H%M%S")
    except ValueError:
        return None


def _extract_pid_and_timestamp_from_suffix(
    suffix: str,
) -> tuple[int | None, str | None]:
    """Extract PID and timestamp from agent suffix format.

    Args:
        suffix: Suffix like "fix_hook-12345-251230_151429".

    Returns:
        Tuple of (pid, timestamp_str) or (None, None) if format doesn't match.
    """
    if "-" not in suffix:
        return None, None
    parts = suffix.split("-")
    if len(parts) < 3:
        return None, None
    ts = parts[-1]
    pid_str = parts[-2]
    if pid_str.isdigit() and len(ts) == 13 and ts[6] == "_":
        return int(pid_str), ts
    return None, None


def _collect_hook_runners(
    changespec: ChangeSpec,
    hook: HookEntry,
    status_line: HookStatusLine,
) -> RunnerInfo | None:
    """Collect runner info from a hook status line.

    Args:
        changespec: The ChangeSpec containing the hook.
        hook: The HookEntry containing the status line.
        status_line: The HookStatusLine to examine.

    Returns:
        RunnerInfo if this is a running process/agent, None otherwise.
    """
    suffix_type = status_line.suffix_type
    suffix = status_line.suffix

    if suffix_type == "running_process":
        # Running hook process - suffix is the PID
        pid = int(suffix) if suffix and suffix.isdigit() else None
        return RunnerInfo(
            runner_type="process",
            cl_name=changespec.name,
            project_name=changespec.project_basename,
            project_file=changespec.file_path,
            hook_command=hook.display_command,
            agent_type=None,
            pid=pid,
            start_time=_parse_timestamp(status_line.timestamp),
            reviewer=None,
            raw_suffix=suffix,
        )
    elif suffix_type == "running_agent":
        # Running agent (fix-hook or summarize-hook)
        pid, ts = _extract_pid_and_timestamp_from_suffix(suffix or "")
        # Determine agent type from suffix prefix
        agent_type = "fix-hook"
        if suffix and suffix.startswith("summarize"):
            agent_type = "summarize-hook"
        return RunnerInfo(
            runner_type="agent",
            cl_name=changespec.name,
            project_name=changespec.project_basename,
            project_file=changespec.file_path,
            hook_command=hook.display_command,
            agent_type=agent_type,
            pid=pid,
            start_time=_parse_timestamp(ts) if ts else None,
            reviewer=None,
            raw_suffix=suffix,
        )
    return None


def _collect_mentor_runners(
    changespec: ChangeSpec,
    status_line: MentorStatusLine,
) -> RunnerInfo | None:
    """Collect runner info from a mentor status line.

    Args:
        changespec: The ChangeSpec containing the mentor.
        status_line: The MentorStatusLine to examine.

    Returns:
        RunnerInfo if this is a running mentor agent, None otherwise.
    """
    if status_line.suffix_type != "running_agent":
        return None

    pid, ts = _extract_pid_and_timestamp_from_suffix(status_line.suffix or "")
    return RunnerInfo(
        runner_type="agent",
        cl_name=changespec.name,
        project_name=changespec.project_basename,
        project_file=changespec.file_path,
        hook_command=None,
        agent_type=f"mentor:{status_line.profile_name}:{status_line.mentor_name}",
        pid=pid,
        start_time=_parse_timestamp(ts) if ts else None,
        reviewer=None,
        raw_suffix=status_line.suffix,
    )


def _collect_comment_runners(changespec: ChangeSpec) -> list[RunnerInfo]:
    """Collect runner info from comment entries (CRS agents).

    Args:
        changespec: The ChangeSpec to examine.

    Returns:
        List of RunnerInfo for running CRS agents.
    """
    runners: list[RunnerInfo] = []
    if not changespec.comments:
        return runners

    for comment in changespec.comments:
        if comment.suffix_type != "running_agent":
            continue

        pid, ts = _extract_pid_and_timestamp_from_suffix(comment.suffix or "")
        runners.append(
            RunnerInfo(
                runner_type="agent",
                cl_name=changespec.name,
                project_name=changespec.project_basename,
                project_file=changespec.file_path,
                hook_command=None,
                agent_type="crs",
                pid=pid,
                start_time=_parse_timestamp(ts) if ts else None,
                reviewer=comment.reviewer,
                raw_suffix=comment.suffix,
            )
        )
    return runners


def _read_prompt_preview(
    project_name: str, artifacts_timestamp: str | None
) -> str | None:
    """Read a truncated prompt preview from the agent's raw_xprompt.md artifact.

    Args:
        project_name: The project name (e.g., "yserve").
        artifacts_timestamp: The artifacts timestamp (YYYYmmddHHMMSS or YYmmdd_HHMMSS).

    Returns:
        A single-line prompt preview string, or None if unavailable.
    """
    if not artifacts_timestamp:
        return None

    import os

    # Convert YYmmdd_HHMMSS to YYYYmmddHHMMSS if needed
    ts = artifacts_timestamp
    if len(ts) == 13 and ts[6] == "_":
        from sase.shared_utils import convert_timestamp_to_artifacts_format

        ts = convert_timestamp_to_artifacts_format(ts)

    raw_path = os.path.expanduser(
        f"~/.sase/projects/{project_name}/artifacts/ace-run/{ts}/raw_xprompt.md"
    )
    try:
        with open(raw_path, encoding="utf-8") as f:
            # Read first line only for preview
            first_line = f.readline().strip()
        if not first_line:
            return None
        if len(first_line) > _PROMPT_PREVIEW_MAX:
            return first_line[:_PROMPT_PREVIEW_MAX] + "..."
        return first_line
    except OSError:
        return None


def _collect_manual_agents() -> list[RunnerInfo]:
    """Collect manually started agents from RUNNING fields in all project files.

    These are agents started by the user (e.g., via @ or space in the TUI),
    as opposed to agents spawned by sase axe.

    Returns:
        List of RunnerInfo for manually started agents (workspace_num already set).
    """
    from sase.running_field import get_claimed_workspaces

    from pathlib import Path

    agents: list[RunnerInfo] = []

    for project_file in get_all_project_files():
        project_name = Path(project_file).stem
        claims = get_claimed_workspaces(project_file)
        for claim in claims:
            # Skip axe-spawned agents
            if claim.workflow and (
                any(claim.workflow.startswith(p) for p in _AXE_WORKFLOW_PREFIXES)
                or claim.workflow in _AXE_WORKFLOW_NAMES
            ):
                continue

            # Parse timestamp from workflow name if available
            start_time = None
            workflow = claim.workflow or ""
            # Workflows like "ace(run)-260306_143210" have embedded timestamps
            if "-" in workflow:
                ts_part = workflow.rsplit("-", 1)[-1]
                start_time = _parse_timestamp(ts_part)

            # Read prompt preview from artifacts raw_xprompt.md
            prompt_preview = _read_prompt_preview(
                project_name, claim.artifacts_timestamp
            )

            agents.append(
                RunnerInfo(
                    runner_type="agent",
                    cl_name=claim.cl_name or "unknown",
                    project_name=project_name,
                    project_file=project_file,
                    hook_command=None,
                    agent_type=workflow or "manual",
                    pid=claim.pid,
                    start_time=start_time,
                    reviewer=None,
                    raw_suffix=None,
                    workspace_num=claim.workspace_num,
                    prompt_preview=prompt_preview,
                )
            )

    return agents


def _build_workspace_maps(
    project_file: str,
) -> tuple[dict[int, int], dict[str, int]]:
    """Build PID-to-workspace and cl_name-to-workspace maps from RUNNING field.

    Args:
        project_file: Path to the ProjectSpec file.

    Returns:
        Tuple of (pid_to_ws, cl_to_ws) dicts mapping to workspace numbers.
    """
    from sase.running_field import get_claimed_workspaces

    pid_to_ws: dict[int, int] = {}
    cl_to_ws: dict[str, int] = {}

    for claim in get_claimed_workspaces(project_file):
        pid_to_ws[claim.pid] = claim.workspace_num
        if claim.cl_name:
            cl_to_ws[claim.cl_name] = claim.workspace_num

    return pid_to_ws, cl_to_ws


def _resolve_workspace_num(
    runner: RunnerInfo,
    pid_to_ws: dict[int, int],
    cl_to_ws: dict[str, int],
) -> int | None:
    """Resolve the workspace number for a runner.

    Tries PID match first (for agents that claim workspaces directly),
    then falls back to cl_name match (for hook processes running in a
    workspace claimed by the scheduler).

    Args:
        runner: The runner info to resolve.
        pid_to_ws: PID-to-workspace mapping.
        cl_to_ws: CL-name-to-workspace mapping.

    Returns:
        The workspace number, or None if it cannot be resolved.
    """
    # Try PID match first (agents claim workspaces with their own PID)
    if runner.pid is not None and runner.pid in pid_to_ws:
        return pid_to_ws[runner.pid]

    # Fall back to cl_name match (hook processes run in scheduler's workspace)
    if runner.cl_name in cl_to_ws:
        return cl_to_ws[runner.cl_name]

    return None


def _collect_runners_raw() -> tuple[
    list[RunnerInfo], list[RunnerInfo], list[RunnerInfo]
]:
    """Collect all running processes and agents without workspace resolution.

    Returns:
        Tuple of (processes, axe_agents, manual_agents) lists.
        processes and axe_agents have workspace_num unset;
        manual_agents have workspace_num already set from RUNNING field.
    """
    processes: list[RunnerInfo] = []
    axe_agents: list[RunnerInfo] = []

    for changespec in find_all_changespecs():
        # Collect from HOOKS
        if changespec.hooks:
            for hook in changespec.hooks:
                if hook.status_lines:
                    for sl in hook.status_lines:
                        runner = _collect_hook_runners(changespec, hook, sl)
                        if runner:
                            if runner.runner_type == "process":
                                processes.append(runner)
                            else:
                                axe_agents.append(runner)

        # Collect from COMMENTS (CRS agents)
        axe_agents.extend(_collect_comment_runners(changespec))

        # Collect from MENTORS
        if changespec.mentors:
            for mentor in changespec.mentors:
                if mentor.status_lines:
                    for msl in mentor.status_lines:
                        runner = _collect_mentor_runners(changespec, msl)
                        if runner:
                            axe_agents.append(runner)

    # Collect manually started agents from RUNNING field
    manual_agents = _collect_manual_agents()

    return processes, axe_agents, manual_agents


def collect_runners() -> tuple[list[RunnerInfo], list[RunnerInfo], list[RunnerInfo]]:
    """Collect all running processes and agents with workspace numbers resolved.

    Returns:
        Tuple of (processes, axe_agents, manual_agents) lists with workspace_num set
        (or None if resolution failed).
    """
    processes, axe_agents, manual_agents = _collect_runners_raw()

    # Build workspace maps per project file (cached)
    ws_maps_cache: dict[str, tuple[dict[int, int], dict[str, int]]] = {}

    # Only resolve workspace for processes and axe_agents
    # (manual_agents already have workspace_num from RUNNING field)
    for runner in [*processes, *axe_agents]:
        project_file = runner.project_file
        if project_file not in ws_maps_cache:
            ws_maps_cache[project_file] = _build_workspace_maps(project_file)
        pid_to_ws, cl_to_ws = ws_maps_cache[project_file]
        runner.workspace_num = _resolve_workspace_num(runner, pid_to_ws, cl_to_ws)

    return processes, axe_agents, manual_agents


def get_runner_count() -> int:
    """Get the total count of running processes and agents.

    Returns:
        Total number of running processes and agents (both axe and manual).
    """
    processes, axe_agents, manual_agents = _collect_runners_raw()
    return len(processes) + len(axe_agents) + len(manual_agents)

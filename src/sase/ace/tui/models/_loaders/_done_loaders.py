"""Loaders for completed agents (DONE / FAILED / PLAN REJECTED).

Reads ``done.json`` markers from filesystem artifact directories or from a
pre-walked :class:`AgentArtifactScanWire` snapshot. Both paths produce the
same :class:`Agent` shape.
"""

from pathlib import Path

from sase.core.agent_scan_wire import (
    DONE_WORKFLOW_DIR_NAMES,
    DONE_WORKFLOW_DIR_PREFIXES,
    AgentArtifactRecordWire,
    AgentArtifactScanWire,
)

from ._json_cache import load_json_cached
from ._meta_enrichment import (
    enrich_agent_from_prompt_markers,
    enrich_agent_from_prompt_markers_wire,
    enrich_agent_from_meta,
    enrich_agent_from_meta_wire,
)
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


def _done_extra_files(
    plan_path: str | None,
    markdown_pdf_paths: object,
    image_paths: object,
) -> list[str]:
    """Return plan/PDF/image attachments for the Agents tab file panel."""
    files: list[str] = []
    seen: set[str] = set()
    markdown_pdfs = markdown_pdf_paths if isinstance(markdown_pdf_paths, list) else []
    images = image_paths if isinstance(image_paths, list) else []
    for path in [plan_path, *markdown_pdfs, *images]:
        if not isinstance(path, str):
            continue
        if not path:
            continue
        key = str(Path(path).expanduser().resolve(strict=False))
        if key in seen:
            continue
        seen.add(key)
        files.append(path)
    return files


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
        elif outcome == "plan_rejected":
            status = "PLAN REJECTED"
            error_message = None
            error_traceback = None
        else:
            status = "DONE"
            error_message = None
            error_traceback = None
        extra_files = _done_extra_files(
            data.get("plan_path"),
            data.get("markdown_pdf_paths"),
            data.get("image_paths"),
        )

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
        enrich_agent_from_prompt_markers(agent, str(artifact_dir))

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


def _is_done_record(record: AgentArtifactRecordWire) -> bool:
    """Return True iff *record* lives under a workflow dir that holds done agents."""
    name = record.workflow_dir_name
    if name in DONE_WORKFLOW_DIR_NAMES:
        return True
    return any(name.startswith(p) for p in DONE_WORKFLOW_DIR_PREFIXES)


def _build_done_agent_from_record(
    record: AgentArtifactRecordWire,
    bug_by_cl_name: dict[str, str | None],
    cl_by_cl_name: dict[str, str | None],
) -> Agent | None:
    """Snapshot-aware mirror of :func:`_load_done_agent_for_dir`."""
    if not record.has_done_marker:
        return None
    done = record.done
    if done is None:
        return None
    timestamp_str = record.timestamp
    start_time = parse_timestamp_14_digit(timestamp_str)

    cl_name = done.cl_name or "unknown"
    outcome = done.outcome or "completed"
    if outcome == "noop":
        return None
    if outcome == "failed":
        if done.retried_as_timestamp:
            status = "FAILED (RETRIED)"
        else:
            status = "FAILED"
        error_message = done.error
        error_traceback = done.traceback
    elif outcome == "plan_rejected":
        status = "PLAN REJECTED"
        error_message = None
        error_traceback = None
    else:
        status = "DONE"
        error_message = None
        error_traceback = None
    extra_files = _done_extra_files(
        done.plan_path,
        done.markdown_pdf_paths,
        done.image_paths,
    )

    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file=done.project_file or "",
        status=status,
        start_time=start_time,
        workflow=record.workflow_dir_name,
        raw_suffix=timestamp_str,
        response_path=done.response_path,
        diff_path=done.diff_path,
        extra_files=extra_files,
        step_output=done.step_output,
        workspace_num=done.workspace_num,
        bug=bug_by_cl_name.get(cl_name),
        cl_num=cl_by_cl_name.get(cl_name),
        error_message=error_message,
        error_traceback=error_traceback,
        output_path=done.output_path,
        model=done.model,
        llm_provider=done.llm_provider,
        vcs_provider=done.vcs_provider,
        agent_name=done.name,
        hidden=bool(done.hidden),
        approve=bool(done.approve),
    )

    if done.retried_as_timestamp:
        agent.retried_as_timestamp = done.retried_as_timestamp
    if done.retry_chain_root_timestamp:
        agent.retry_chain_root_timestamp = done.retry_chain_root_timestamp
    if done.retry_error_category:
        agent.retry_error_category = done.retry_error_category

    enrich_agent_from_meta_wire(agent, record.agent_meta, record.waiting)
    enrich_agent_from_prompt_markers_wire(agent, record.prompt_steps)
    return agent


def load_done_agents_from_snapshot(
    snapshot: AgentArtifactScanWire,
    bug_by_cl_name: dict[str, str | None],
    cl_by_cl_name: dict[str, str | None],
) -> list[Agent]:
    """Snapshot-aware mirror of :func:`load_done_agents`.

    Iterates pre-walked artifact records from a single
    :class:`AgentArtifactScanWire` instead of re-walking the filesystem.
    """
    agents: list[Agent] = []
    for record in snapshot.records:
        if not _is_done_record(record):
            continue
        agent = _build_done_agent_from_record(record, bug_by_cl_name, cl_by_cl_name)
        if agent is not None:
            agents.append(agent)
    return agents

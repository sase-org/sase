"""Loaders for completed agents (DONE / FAILED / PLAN REJECTED).

Reads ``done.json`` markers from filesystem artifact directories or from a
pre-walked :class:`AgentArtifactScanWire` snapshot. Both paths produce the
same :class:`Agent` shape.

Completed-agent history intentionally spans all project lifecycle states so
archiving or closing a project does not hide prior agent rows from history
views.
"""

from concurrent.futures import CancelledError
from pathlib import Path
from typing import Any

from sase.agent.status_buckets import EPIC_APPROVED_STATUS
from sase.core.agent_scan_wire import (
    DONE_WORKFLOW_DIR_NAMES,
    DONE_WORKFLOW_DIR_PREFIXES,
    AgentArtifactRecordWire,
    AgentArtifactScanWire,
)
from sase.core.paths import sase_projects_dir
from sase.ace.revert_agent import agent_is_reverted

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


def _enrich_agent_revert_state(agent: Agent, artifact_dir: str | Path | None) -> None:
    agent.reverted = agent_is_reverted(str(artifact_dir) if artifact_dir else None)


def _single_commit_record_from_metadata(
    metadata: dict[str, str],
) -> dict[str, str] | None:
    record: dict[str, str] = {}
    if message := metadata.get("meta_commit_message"):
        record["message"] = message
    if sha := metadata.get("meta_new_commit"):
        record["sha"] = sha
    if cwd := metadata.get("meta_commit_cwd"):
        record["cwd"] = cwd
    return record or None


def _commit_results_marker_exists(artifact_dir: str | Path | None) -> bool:
    if artifact_dir is None:
        return False
    return (Path(artifact_dir).expanduser() / "commit_results.json").is_file()


def _commit_record_key(record: dict[str, Any]) -> tuple[str, str] | None:
    cwd = record.get("cwd")
    sha = record.get("sha") or record.get("result") or record.get("commit_result")
    cwd_text = cwd if isinstance(cwd, str) else ""
    sha_text = sha if isinstance(sha, str) else ""
    if not cwd_text and not sha_text:
        return None
    return (cwd_text, sha_text)


def _merge_commit_records(
    existing_records: list[object],
    loaded_records: list[dict[str, str]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    index_by_key: dict[tuple[str, str], int] = {}

    for raw_record in [*existing_records, *loaded_records]:
        if not isinstance(raw_record, dict):
            continue
        record = dict(raw_record)
        key = _commit_record_key(record)
        if key is not None and key in index_by_key:
            merged[index_by_key[key]].update(record)
            continue
        if key is not None:
            index_by_key[key] = len(merged)
        merged.append(record)
    return merged


def _enrich_missing_commit_metadata(
    agent: Agent, artifact_dir: str | Path | None
) -> None:
    """Backfill and merge commit cwd/list metadata for done markers."""
    from sase.axe.run_agent_helpers_state import (
        read_commit_result_metadata,
        read_commit_results_metadata,
    )

    step_output = agent.step_output
    marker_exists = _commit_results_marker_exists(artifact_dir)
    artifact_dir_str = str(artifact_dir) if artifact_dir else None
    commits = read_commit_results_metadata(artifact_dir_str) if marker_exists else []
    if not isinstance(step_output, dict):
        if not commits:
            return
        step_output = {}
        agent.step_output = step_output

    has_primary_commit = bool(
        step_output.get("meta_commit_message") or step_output.get("meta_new_commit")
    )
    existing_raw = step_output.get("meta_commits")
    existing_commits = existing_raw if isinstance(existing_raw, list) else []

    if not (has_primary_commit or existing_commits or marker_exists):
        return

    single_metadata: dict[str, str] | None = None

    if not commits and has_primary_commit and not existing_commits:
        single_metadata = read_commit_result_metadata(artifact_dir_str)
        single_commit = _single_commit_record_from_metadata(single_metadata)
        commits = [single_commit] if single_commit else []
    if existing_commits or commits:
        merged_commits = _merge_commit_records(existing_commits, commits)
        if merged_commits:
            step_output["meta_commits"] = merged_commits

    if has_primary_commit and not step_output.get("meta_commit_cwd"):
        if single_metadata is None:
            single_metadata = read_commit_result_metadata(artifact_dir_str)
        commit_cwd = single_metadata.get("meta_commit_cwd")
        if commit_cwd:
            step_output["meta_commit_cwd"] = commit_cwd


def _done_extra_files(
    plan_path: str | None,
    markdown_pdf_paths: object,
    image_paths: object,
    video_paths: object,
) -> list[str]:
    """Return plan/PDF/image/video attachments for the Agents tab file panel."""
    files: list[str] = []
    seen: set[str] = set()
    markdown_pdfs = markdown_pdf_paths if isinstance(markdown_pdf_paths, list) else []
    images = image_paths if isinstance(image_paths, list) else []
    videos = video_paths if isinstance(video_paths, list) else []
    for path in [plan_path, *markdown_pdfs, *images, *videos]:
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
        extra_files = _done_extra_files(
            data.get("plan_path"),
            data.get("markdown_pdf_paths"),
            data.get("image_paths"),
            data.get("video_paths"),
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
        _enrich_missing_commit_metadata(agent, artifact_dir)
        _enrich_agent_revert_state(agent, artifact_dir)

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
        bug_by_cl_name: Mapping of ChangeSpec names to bug URLs.
        cl_by_cl_name: Mapping of ChangeSpec names to PR numbers.

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

        for workflow_dir in _iter_artifact_workflow_dirs(artifacts_base):
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
            lambda t: _load_done_agent_for_dir(
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
    if outcome in {"failed", "epic_launch_failed"}:
        if outcome == "failed" and done.retried_as_timestamp:
            status = "FAILED (RETRIED)"
        else:
            status = "FAILED"
        error_message = done.error or (
            "Epic launch failed" if outcome == "epic_launch_failed" else None
        )
        error_traceback = done.traceback
    elif outcome == "stopped" or done.repeat_stopped:
        # Repeat-chain STOP: skipped by a predecessor's STOP output variable.
        # Keeps ``outcome: "completed"`` for %wait cascading but renders as a
        # non-error terminal STOPPED row (checked before generic completed).
        # Queue cancellation uses ``outcome: "stopped"`` for the same display
        # status without the repeat-chain cascade semantics.
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
    extra_files = _done_extra_files(
        done.plan_path,
        done.markdown_pdf_paths,
        done.image_paths,
        done.video_paths,
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
        plan_path=done.plan_path,
        archived_plan_path=done.plan_path,
        step_output=done.step_output,
        workspace_num=done.workspace_num,
        workspace_dir=done.workspace_dir,
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

    enrich_agent_from_meta_wire(
        agent,
        record.agent_meta,
        record.waiting,
        record.pending_question,
        plan_path_marker=(
            record.plan_path.plan_path if record.plan_path is not None else None
        ),
    )
    enrich_agent_from_prompt_markers_wire(agent, record.prompt_steps)
    _enrich_missing_commit_metadata(agent, record.artifact_dir)
    _enrich_agent_revert_state(agent, record.artifact_dir)
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

"""sase.core facade for the agent/artifact filesystem snapshot scan.

Phase 3A wires a pure-Python scanner behind :func:`sase.core.backend.dispatch`
so a future ``sase_core_rs`` implementation can replace it one operation at
a time. The wire shape is defined in :mod:`sase.core.agent_scan_wire`.

The Python implementation here is intentionally simple: it walks the
filesystem with ``pathlib`` and reads each marker file with the existing
``load_json_cached`` helper used by the TUI loader. It is **not** a
performance target — the baseline benchmark in
``tests/perf/bench_agent_scan.py`` measures both this snapshot scanner and
the existing direct loaders so a Rust port has a clear before-picture to
beat.

What this scanner does NOT do:

- It does not check process liveness. Phase 3 keeps liveness in Python
  (`sase.ace.hooks.processes.is_process_running` and `/proc` guards).
- It does not parse RUNNING-field claims from project ``.gp`` files.
  Workspace-claim semantics live in :mod:`sase.running_field` and stay
  Python-only in Phase 3.
- It does not mutate any filesystem state.

Soft errors (unreadable directories, malformed marker JSON) are absorbed
silently and counted in :class:`AgentArtifactScanStatsWire`. Callers that
care about diagnostics can inspect ``snapshot.stats``.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    DONE_WORKFLOW_DIR_NAMES,
    DONE_WORKFLOW_DIR_PREFIXES,
    WORKFLOW_STATE_DIR_NAMES,
    WORKFLOW_STATE_DIR_PREFIXES,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    DoneMarkerWire,
    PlanPathMarkerWire,
    PromptStepMarkerWire,
    RunningMarkerWire,
    WaitingMarkerWire,
    WorkflowStateWire,
    WorkflowStepStateWire,
    agent_scan_wire_from_dict,
)
from sase.core.backend import dispatch, load_rust_extension

_RAW_PROMPT_FILE = "raw_xprompt.md"


def _supported_workflow_dir(name: str) -> bool:
    """Return True iff *name* is a workflow folder the scanner walks."""
    if name in DONE_WORKFLOW_DIR_NAMES:
        return True
    if name in WORKFLOW_STATE_DIR_NAMES:
        return True
    for prefix in DONE_WORKFLOW_DIR_PREFIXES:
        if name.startswith(prefix):
            return True
    for prefix in WORKFLOW_STATE_DIR_PREFIXES:
        if name.startswith(prefix):
            return True
    return False


def _load_marker_json(
    path: Path,
    stats: dict[str, int],
) -> Any | None:
    """Load *path* with the shared mtime cache, counting soft errors."""
    # Lazy import: ``sase.ace.tui.models._loaders._json_cache`` lives under
    # the TUI models package, whose ``__init__`` imports
    # ``agent_loader``, which imports from this facade. Importing the
    # cache helper at module top would form a load-time cycle and break
    # ``import sase.core.agent_scan_facade`` for any caller (including
    # the bench script and standalone scripts) that hasn't already
    # warmed the TUI submodule.
    from sase.ace.tui.models._loaders._json_cache import load_json_cached

    try:
        data = load_json_cached(path)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, ValueError):
        stats["json_decode_errors"] += 1
        return None
    except OSError:
        stats["os_errors"] += 1
        return None
    if data is None:
        return None
    return data


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):  # bool is an int subclass; reject it.
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _coerce_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _coerce_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []


def _coerce_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _coerce_str_str_dict(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    out: dict[str, str] = {}
    for k, v in value.items():
        if isinstance(k, str) and isinstance(v, str):
            out[k] = v
    return out or None


def _agent_meta_from_dict(data: dict[str, Any]) -> AgentMetaWire:
    return AgentMetaWire(
        name=_coerce_str(data.get("name")),
        workflow_name=_coerce_str(data.get("workflow_name")),
        pid=_coerce_int(data.get("pid")),
        model=_coerce_str(data.get("model")),
        llm_provider=_coerce_str(data.get("llm_provider")),
        vcs_provider=_coerce_str(data.get("vcs_provider")),
        role_suffix=_coerce_str(data.get("role_suffix")),
        parent_timestamp=_coerce_str(data.get("parent_timestamp")),
        workspace_num=_coerce_int(data.get("workspace_num")),
        approve=bool(data.get("approve")),
        hidden=bool(data.get("hidden")),
        plan=bool(data.get("plan")),
        plan_approved=bool(data.get("plan_approved")),
        plan_action=_coerce_str(data.get("plan_action")),
        wait_for=_coerce_str_list(data.get("wait_for")),
        wait_duration=_coerce_float(data.get("wait_duration")),
        wait_until=_coerce_str(data.get("wait_until")),
        plan_submitted_at=_coerce_str_list(data.get("plan_submitted_at")),
        feedback_submitted_at=_coerce_str_list(data.get("feedback_submitted_at")),
        questions_submitted_at=_coerce_str_list(data.get("questions_submitted_at")),
        retry_started_at=_coerce_str_list(data.get("retry_started_at")),
        run_started_at=_coerce_str(data.get("run_started_at")),
        stopped_at=_coerce_str(data.get("stopped_at")),
        retry_of_timestamp=_coerce_str(data.get("retry_of_timestamp")),
        retry_attempt=(
            data["retry_attempt"]
            if isinstance(data.get("retry_attempt"), int)
            and not isinstance(data.get("retry_attempt"), bool)
            else None
        ),
        retry_chain_root_timestamp=_coerce_str(data.get("retry_chain_root_timestamp")),
        retried_as_timestamp=_coerce_str(data.get("retried_as_timestamp")),
        retry_terminal=bool(data.get("retry_terminal")),
        retry_error_category=_coerce_str(data.get("retry_error_category")),
    )


def _done_marker_from_dict(data: dict[str, Any]) -> DoneMarkerWire:
    return DoneMarkerWire(
        outcome=_coerce_str(data.get("outcome")),
        finished_at=_coerce_float(data.get("finished_at")),
        cl_name=_coerce_str(data.get("cl_name")),
        project_file=_coerce_str(data.get("project_file")),
        workspace_num=_coerce_int(data.get("workspace_num")),
        pid=_coerce_int(data.get("pid")),
        model=_coerce_str(data.get("model")),
        llm_provider=_coerce_str(data.get("llm_provider")),
        vcs_provider=_coerce_str(data.get("vcs_provider")),
        name=_coerce_str(data.get("name")),
        plan_path=_coerce_str(data.get("plan_path")),
        diff_path=_coerce_str(data.get("diff_path")),
        response_path=_coerce_str(data.get("response_path")),
        output_path=_coerce_str(data.get("output_path")),
        step_output=_coerce_dict(data.get("step_output")),
        error=_coerce_str(data.get("error")),
        traceback=_coerce_str(data.get("traceback")),
        retried_as_timestamp=_coerce_str(data.get("retried_as_timestamp")),
        retry_chain_root_timestamp=_coerce_str(data.get("retry_chain_root_timestamp")),
        retry_error_category=_coerce_str(data.get("retry_error_category")),
        approve=bool(data.get("approve")),
        hidden=bool(data.get("hidden")),
    )


def _running_marker_from_dict(data: dict[str, Any]) -> RunningMarkerWire:
    return RunningMarkerWire(
        pid=_coerce_int(data.get("pid")),
        cl_name=_coerce_str(data.get("cl_name")),
        model=_coerce_str(data.get("model")),
        llm_provider=_coerce_str(data.get("llm_provider")),
        vcs_provider=_coerce_str(data.get("vcs_provider")),
    )


def _waiting_marker_from_dict(data: dict[str, Any]) -> WaitingMarkerWire:
    return WaitingMarkerWire(
        waiting_for=_coerce_str_list(data.get("waiting_for")),
        wait_duration=_coerce_float(data.get("wait_duration")),
        wait_until=_coerce_str(data.get("wait_until")),
    )


def _workflow_step_from_dict(data: dict[str, Any]) -> WorkflowStepStateWire:
    return WorkflowStepStateWire(
        name=_coerce_str(data.get("name")) or "",
        status=_coerce_str(data.get("status")) or "pending",
        output=_coerce_dict(data.get("output")),
        output_types=_coerce_str_str_dict(data.get("output_types")),
        error=_coerce_str(data.get("error")),
        traceback=_coerce_str(data.get("traceback")),
    )


def _workflow_state_from_dict(data: dict[str, Any]) -> WorkflowStateWire:
    raw_steps = data.get("steps")
    steps: list[WorkflowStepStateWire] = []
    if isinstance(raw_steps, list):
        for step in raw_steps:
            if isinstance(step, dict):
                steps.append(_workflow_step_from_dict(step))

    context = data.get("context")
    cl_name = None
    if isinstance(context, dict):
        cl_name = _coerce_str(context.get("cl_name"))

    return WorkflowStateWire(
        workflow_name=_coerce_str(data.get("workflow_name")) or "unknown",
        cl_name=cl_name,
        status=_coerce_str(data.get("status")) or "running",
        pid=_coerce_int(data.get("pid")),
        appears_as_agent=bool(data.get("appears_as_agent")),
        is_anonymous=bool(data.get("is_anonymous")),
        current_step_index=_coerce_int(data.get("current_step_index")) or 0,
        start_time=_coerce_str(data.get("start_time")),
        error=_coerce_str(data.get("error")),
        traceback=_coerce_str(data.get("traceback")),
        steps=steps,
    )


def _prompt_step_from_dict(
    file_name: str, data: dict[str, Any]
) -> PromptStepMarkerWire:
    return PromptStepMarkerWire(
        file_name=file_name,
        workflow_name=_coerce_str(data.get("workflow_name")) or "unknown",
        step_name=_coerce_str(data.get("step_name")) or "unknown",
        step_type=_coerce_str(data.get("step_type")) or "agent",
        step_source=_coerce_str(data.get("step_source")),
        step_index=_coerce_int(data.get("step_index")),
        total_steps=_coerce_int(data.get("total_steps")),
        parent_step_index=_coerce_int(data.get("parent_step_index")),
        parent_total_steps=_coerce_int(data.get("parent_total_steps")),
        status=_coerce_str(data.get("status")) or "completed",
        hidden=bool(data.get("hidden")),
        is_pre_prompt_step=bool(data.get("is_pre_prompt_step")),
        embedded_workflow_name=_coerce_str(data.get("embedded_workflow_name")),
        artifacts_dir=_coerce_str(data.get("artifacts_dir")),
        diff_path=_coerce_str(data.get("diff_path")),
        response_path=_coerce_str(data.get("response_path")),
        error=_coerce_str(data.get("error")),
        traceback=_coerce_str(data.get("traceback")),
        model=_coerce_str(data.get("model")),
        llm_provider=_coerce_str(data.get("llm_provider")),
        output=_coerce_dict(data.get("output")),
        output_types=_coerce_str_str_dict(data.get("output_types")),
    )


def _plan_path_from_dict(data: dict[str, Any]) -> PlanPathMarkerWire:
    return PlanPathMarkerWire(plan_path=_coerce_str(data.get("plan_path")))


def _read_raw_prompt_snippet(
    artifact_dir: Path,
    max_bytes: int,
    stats: dict[str, int],
) -> str | None:
    raw_path = artifact_dir / _RAW_PROMPT_FILE
    try:
        text = raw_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        stats["os_errors"] += 1
        return None
    return text[:max_bytes].strip()


def _scan_artifact_dir(
    *,
    project_name: str,
    project_dir: Path,
    workflow_dir_name: str,
    artifact_dir: Path,
    options: AgentArtifactScanOptionsWire,
    stats: dict[str, int],
) -> AgentArtifactRecordWire:
    project_file = project_dir / f"{project_name}.gp"

    def _load_object(path: Path) -> dict[str, Any] | None:
        data = _load_marker_json(path, stats)
        if data is None:
            return None
        if not isinstance(data, dict):
            stats["json_decode_errors"] += 1
            return None
        stats["marker_files_parsed"] += 1
        return data

    agent_meta_data = _load_object(artifact_dir / "agent_meta.json")
    agent_meta = (
        _agent_meta_from_dict(agent_meta_data) if agent_meta_data is not None else None
    )

    done_path = artifact_dir / "done.json"
    has_done_marker = done_path.exists()
    done_data = _load_object(done_path) if has_done_marker else None
    done = _done_marker_from_dict(done_data) if done_data is not None else None
    if has_done_marker and done is None:
        # Mirror current behavior: "done.json exists but unreadable" still
        # counts as completed for callers that only look at file presence.
        # Returning a default DoneMarkerWire keeps the boolean truthiness
        # of ``record.done is not None`` aligned with that.
        done = DoneMarkerWire()

    running_data = _load_object(artifact_dir / "running.json")
    running = (
        _running_marker_from_dict(running_data) if running_data is not None else None
    )

    waiting_data = _load_object(artifact_dir / "waiting.json")
    waiting = (
        _waiting_marker_from_dict(waiting_data) if waiting_data is not None else None
    )

    workflow_state_data = _load_object(artifact_dir / "workflow_state.json")
    workflow_state = (
        _workflow_state_from_dict(workflow_state_data)
        if workflow_state_data is not None
        else None
    )

    plan_path_data = _load_object(artifact_dir / "plan_path.json")
    plan_path = (
        _plan_path_from_dict(plan_path_data) if plan_path_data is not None else None
    )

    prompt_steps: list[PromptStepMarkerWire] = []
    if options.include_prompt_step_markers:
        try:
            step_files = sorted(artifact_dir.glob("prompt_step_*.json"))
        except OSError:
            stats["os_errors"] += 1
            step_files = []
        for step_file in step_files:
            data = _load_object(step_file)
            if data is None:
                continue
            stats["prompt_step_markers_parsed"] += 1
            prompt_steps.append(_prompt_step_from_dict(step_file.name, data))

    raw_prompt_snippet = None
    if options.include_raw_prompt_snippets:
        raw_prompt_snippet = _read_raw_prompt_snippet(
            artifact_dir, options.max_prompt_snippet_bytes, stats
        )

    return AgentArtifactRecordWire(
        project_name=project_name,
        project_dir=str(project_dir),
        project_file=str(project_file),
        workflow_dir_name=workflow_dir_name,
        artifact_dir=str(artifact_dir),
        timestamp=artifact_dir.name,
        agent_meta=agent_meta,
        done=done,
        running=running,
        waiting=waiting,
        workflow_state=workflow_state,
        plan_path=plan_path,
        prompt_steps=prompt_steps,
        raw_prompt_snippet=raw_prompt_snippet,
        has_done_marker=has_done_marker,
    )


def _safe_iterdir(path: Path, stats: dict[str, int]) -> list[Path]:
    try:
        return list(path.iterdir())
    except (FileNotFoundError, NotADirectoryError):
        return []
    except OSError:
        stats["os_errors"] += 1
        return []


# pyvision: tests/test_core_agent_scan.py
def scan_agent_artifacts_python(
    projects_root: Path | str,
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactScanWire:
    """Pure-Python implementation of :func:`scan_agent_artifacts`.

    Walks ``projects_root`` and produces a deterministic snapshot of every
    artifact directory's marker files. Soft errors are absorbed and
    reflected in :class:`AgentArtifactScanStatsWire`. The Python backend
    of :func:`scan_agent_artifacts` calls into this helper directly; tests
    that need to bypass dispatch can call this function by name.
    """
    opts = options or AgentArtifactScanOptionsWire()
    only = set(opts.only_workflow_dirs) if opts.only_workflow_dirs else None

    stats_dict: dict[str, int] = {
        "projects_visited": 0,
        "artifact_dirs_visited": 0,
        "marker_files_parsed": 0,
        "json_decode_errors": 0,
        "os_errors": 0,
        "prompt_step_markers_parsed": 0,
    }
    records: list[AgentArtifactRecordWire] = []

    root = Path(projects_root)

    if root.exists():
        for project_dir in sorted(
            _safe_iterdir(root, stats_dict), key=lambda p: p.name
        ):
            if not project_dir.is_dir():
                continue
            stats_dict["projects_visited"] += 1
            artifacts_base = project_dir / "artifacts"
            if not artifacts_base.exists():
                continue

            workflow_dirs = sorted(
                _safe_iterdir(artifacts_base, stats_dict),
                key=lambda p: p.name,
            )
            for workflow_dir in workflow_dirs:
                if not workflow_dir.is_dir():
                    continue
                workflow_dir_name = workflow_dir.name
                if only is not None and workflow_dir_name not in only:
                    continue
                if only is None and not _supported_workflow_dir(workflow_dir_name):
                    continue

                for artifact_dir in sorted(
                    _safe_iterdir(workflow_dir, stats_dict), key=lambda p: p.name
                ):
                    if not artifact_dir.is_dir():
                        continue
                    stats_dict["artifact_dirs_visited"] += 1
                    record = _scan_artifact_dir(
                        project_name=project_dir.name,
                        project_dir=project_dir,
                        workflow_dir_name=workflow_dir_name,
                        artifact_dir=artifact_dir,
                        options=opts,
                        stats=stats_dict,
                    )
                    records.append(record)

    # Final sort for determinism. The walk order above already produces
    # this ordering, but a re-sort is cheap insurance against future
    # walker changes (parallel parsing, etc.).
    records.sort(key=lambda r: (r.project_name, r.workflow_dir_name, r.timestamp))

    stats = AgentArtifactScanStatsWire(**stats_dict)
    return AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root=str(root),
        options=opts,
        stats=stats,
        records=records,
    )


def _options_to_dict(options: AgentArtifactScanOptionsWire) -> dict[str, Any]:
    return {
        "include_prompt_step_markers": options.include_prompt_step_markers,
        "include_raw_prompt_snippets": options.include_raw_prompt_snippets,
        "max_prompt_snippet_bytes": options.max_prompt_snippet_bytes,
        "only_workflow_dirs": list(options.only_workflow_dirs),
    }


def _rust_scan_agent_artifacts_impl(
    projects_root: Path | str,
    options: AgentArtifactScanOptionsWire,
) -> AgentArtifactScanWire:
    """Adapter from ``sase_core_rs.scan_agent_artifacts`` to typed wire records.

    The PyO3 binding returns a plain dict in the
    :func:`agent_scan_wire_to_json_dict` shape; this rebuilds the Python
    dataclasses via :func:`agent_scan_wire_from_dict` so callers see the
    same return type regardless of backend.
    """
    rust_module = load_rust_extension()
    if rust_module is None:
        raise RuntimeError(
            "sase_core_rs is not importable; the Rust backend was registered "
            "but the extension module disappeared at call time."
        )
    payload: dict[str, Any] = rust_module.scan_agent_artifacts(  # type: ignore[attr-defined]
        str(projects_root),
        _options_to_dict(options),
    )
    return agent_scan_wire_from_dict(payload)


def scan_agent_artifacts(
    projects_root: Path | str,
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactScanWire:
    """Return a snapshot of all agent artifact directories under *projects_root*.

    Routes through :func:`sase.core.backend.dispatch` so a future Rust
    implementation can replace the pure-Python walker without callers
    changing. ``projects_root`` is required and is normally
    ``Path.home() / ".sase" / "projects"`` — passing it explicitly keeps
    the contract testable and lets future shells (server, mobile) supply
    a different root without Rust reading global config.

    Phase 3C registers a Rust implementation when the optional
    ``sase_core_rs`` extension is importable. The Rust binding releases
    the GIL during the filesystem walk and returns the same wire shape
    the Python implementation produces; callers see
    :class:`AgentArtifactScanWire` either way.
    """
    opts = options or AgentArtifactScanOptionsWire()
    rust_module = load_rust_extension()
    rust_impl = (
        _rust_scan_agent_artifacts_impl
        if rust_module is not None and hasattr(rust_module, "scan_agent_artifacts")
        else None
    )
    return dispatch(
        operation="scan_agent_artifacts",
        python_impl=scan_agent_artifacts_python,
        rust_impl=rust_impl,
        args=(projects_root, opts),
    )


# pyvision: tests/test_core_agent_scan.py
def with_options(
    base: AgentArtifactScanOptionsWire,
    **overrides: Any,
) -> AgentArtifactScanOptionsWire:
    """Return a copy of *base* with *overrides* applied.

    Convenience for callers that want to derive a tweaked options record
    without juggling :func:`dataclasses.replace` imports.
    """
    return replace(base, **overrides)


__all__ = [
    "scan_agent_artifacts",
    "scan_agent_artifacts_python",
    "with_options",
]

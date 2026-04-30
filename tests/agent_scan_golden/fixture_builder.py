"""Build a synthetic artifact tree used by the Phase 3A scanner tests.

The tree mirrors what ``~/.sase/projects/`` looks like in practice: one
``home`` project with a running home-mode agent, and one ``myproj``
project with a mix of ace-run, workflow-*, and mentor-* artifact
directories. Marker JSON files use the same field names production
writers use so the wire converter is exercised on realistic inputs.

Each timestamp directory's name is a 14-digit ``YYYYmmddHHMMSS`` string
because the production scanner sorts records by timestamp and several
loaders parse the directory name as a datetime.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Timestamps used for the synthetic artifact directories. Must be 14
# digits so production timestamp parsers accept them.
TS_HOME_RUNNING = "20260427100000"
TS_ACE_RUN_RUNNING = "20260427110000"
TS_ACE_RUN_DONE = "20260427120000"
TS_ACE_RUN_FAILED = "20260427130000"
TS_ACE_RUN_RETRIED_PARENT = "20260427140000"
TS_ACE_RUN_RETRIED_CHILD = "20260427140500"
TS_WORKFLOW_ROOT = "20260427150000"
TS_MENTOR_DONE = "20260427160000"
TS_WAITING = "20260427170000"
TS_MALFORMED = "20260427180000"

# Convenience tuple consumed by tests that only need to know which
# timestamps the fixture creates (e.g. when verifying ordering).
EXPECTED_TIMESTAMPS: tuple[str, ...] = (
    TS_HOME_RUNNING,
    TS_ACE_RUN_RUNNING,
    TS_ACE_RUN_DONE,
    TS_ACE_RUN_FAILED,
    TS_ACE_RUN_RETRIED_PARENT,
    TS_ACE_RUN_RETRIED_CHILD,
    TS_WORKFLOW_ROOT,
    TS_MENTOR_DONE,
    TS_WAITING,
    TS_MALFORMED,
)

# The fixture intentionally writes one corrupt agent_meta.json (in the
# malformed dir) and one corrupt waiting.json (in the waiting dir). The
# scanner should count these and keep going.
EXPECTED_DECODE_ERRORS = 2

# The fixture does not currently provoke OS errors. Tests pin the
# expected count so a future regression that flips a permission bit is
# caught.
EXPECTED_OS_ERRORS = 0


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_home_running(root: Path) -> None:
    artifact_dir = root / "home" / "artifacts" / "ace-run" / TS_HOME_RUNNING
    _write_json(
        artifact_dir / "running.json",
        {
            "pid": 11111,
            "cl_name": "~",
            "model": "claude-opus-4-7",
            "llm_provider": "claude",
            "vcs_provider": "github",
            "workspace_dir": "/tmp/home-target",
        },
    )
    _write_json(
        artifact_dir / "agent_meta.json",
        {
            "name": "home_runner",
            "pid": 11111,
            "model": "claude-opus-4-7",
            "llm_provider": "claude",
            "vcs_provider": "github",
            "workspace_dir": "/tmp/home-target",
            "approve": True,
            "run_started_at": "2026-04-27T10:00:00Z",
        },
    )
    _write_text(artifact_dir / "raw_xprompt.md", "Investigate the failing job\n")


def _build_ace_run_running(root: Path) -> None:
    artifact_dir = root / "myproj" / "artifacts" / "ace-run" / TS_ACE_RUN_RUNNING
    _write_json(
        artifact_dir / "agent_meta.json",
        {
            "name": "running_alpha",
            "workflow_name": "wf_alpha",
            "pid": 22222,
            "model": "claude-sonnet-4-6",
            "llm_provider": "claude",
            "vcs_provider": "github",
            "workspace_dir": "/tmp/workspaces/alpha",
            "approve": False,
            "plan": True,
            "plan_approved": False,
            "wait_for": ["bob", "carol"],
            "wait_duration": 3600.0,
        },
    )


def _build_ace_run_done(root: Path) -> None:
    artifact_dir = root / "myproj" / "artifacts" / "ace-run" / TS_ACE_RUN_DONE
    _write_json(
        artifact_dir / "agent_meta.json",
        {
            "name": "done_alpha",
            "model": "claude-haiku-4-5-20251001",
            "llm_provider": "claude",
            "vcs_provider": "github",
            "workspace_dir": "/tmp/workspaces/alpha_3",
            "stopped_at": "2026-04-27T12:05:00Z",
        },
    )
    _write_json(
        artifact_dir / "done.json",
        {
            "outcome": "completed",
            "finished_at": 1745758800.0,
            "cl_name": "feature_alpha",
            "project_file": "/home/u/.sase/projects/myproj/myproj.gp",
            "workspace_num": 3,
            "workspace_dir": "/tmp/workspaces/alpha_3",
            "model": "claude-haiku-4-5-20251001",
            "llm_provider": "claude",
            "vcs_provider": "github",
            "name": "done_alpha",
            "diff_path": "/tmp/diff_alpha.diff",
            "markdown_pdf_paths": ["/tmp/markdown_pdfs/notes.pdf"],
            "response_path": "/tmp/resp_alpha.md",
            "output_path": "/tmp/out_alpha.log",
        },
    )


def _build_ace_run_failed(root: Path) -> None:
    artifact_dir = root / "myproj" / "artifacts" / "ace-run" / TS_ACE_RUN_FAILED
    _write_json(
        artifact_dir / "agent_meta.json",
        {
            "name": "failed_beta",
            "model": "claude-sonnet-4-6",
            "llm_provider": "claude",
            "stopped_at": "2026-04-27T13:10:00Z",
        },
    )
    _write_json(
        artifact_dir / "done.json",
        {
            "outcome": "failed",
            "finished_at": 1745762400.0,
            "cl_name": "feature_beta",
            "name": "failed_beta",
            "error": "RuntimeError: kaboom",
            "traceback": "Traceback (most recent call last):\n  ...",
        },
    )


def _build_ace_run_retried(root: Path) -> None:
    parent_dir = root / "myproj" / "artifacts" / "ace-run" / TS_ACE_RUN_RETRIED_PARENT
    _write_json(
        parent_dir / "agent_meta.json",
        {
            "name": "retry_root",
            "model": "claude-opus-4-7",
            "llm_provider": "claude",
            "retry_chain_root_timestamp": TS_ACE_RUN_RETRIED_PARENT,
            "retried_as_timestamp": TS_ACE_RUN_RETRIED_CHILD,
            "retry_terminal": True,
            "retry_error_category": "transient",
        },
    )
    _write_json(
        parent_dir / "done.json",
        {
            "outcome": "failed",
            "name": "retry_root",
            "error": "Temporary upstream failure",
            "retried_as_timestamp": TS_ACE_RUN_RETRIED_CHILD,
            "retry_chain_root_timestamp": TS_ACE_RUN_RETRIED_PARENT,
            "retry_error_category": "transient",
        },
    )

    child_dir = root / "myproj" / "artifacts" / "ace-run" / TS_ACE_RUN_RETRIED_CHILD
    _write_json(
        child_dir / "agent_meta.json",
        {
            "name": "retry_root",
            "model": "claude-opus-4-7",
            "llm_provider": "claude",
            "retry_of_timestamp": TS_ACE_RUN_RETRIED_PARENT,
            "retry_attempt": 1,
            "retry_chain_root_timestamp": TS_ACE_RUN_RETRIED_PARENT,
            "pid": 33333,
        },
    )


def _build_workflow(root: Path) -> None:
    artifact_dir = (
        root / "myproj" / "artifacts" / "workflow-three_phase" / TS_WORKFLOW_ROOT
    )
    _write_json(
        artifact_dir / "workflow_state.json",
        {
            "workflow_name": "three_phase",
            "context": {"cl_name": "feature_workflow"},
            "status": "completed",
            "pid": 44444,
            "appears_as_agent": True,
            "is_anonymous": False,
            "current_step_index": 2,
            "start_time": "2026-04-27T15:00:00",
            "steps": [
                {
                    "name": "plan",
                    "status": "completed",
                    "output": {"plan_path": "/tmp/plan.md"},
                    "output_types": {"plan_path": "path"},
                },
                {
                    "name": "code",
                    "status": "completed",
                    "output": {"diff_path": "/tmp/diff.diff"},
                    "output_types": {"diff_path": "path"},
                },
                {
                    "name": "review",
                    "status": "completed",
                    "output": {"response_path": "/tmp/review.md"},
                },
            ],
        },
    )
    _write_json(
        artifact_dir / "plan_path.json",
        {"plan_path": "/tmp/plan.md"},
    )
    _write_json(
        artifact_dir / "prompt_step_001_plan.json",
        {
            "workflow_name": "three_phase",
            "step_name": "plan",
            "step_type": "agent",
            "step_index": 0,
            "total_steps": 3,
            "status": "completed",
            "model": "claude-opus-4-7",
            "llm_provider": "claude",
            "output": {"meta_workspace": "5", "plan_path": "/tmp/plan.md"},
            "output_types": {"plan_path": "path"},
            "artifacts_dir": str(artifact_dir),
        },
    )
    _write_json(
        artifact_dir / "prompt_step_002_code.json",
        {
            "workflow_name": "three_phase",
            "step_name": "code",
            "step_type": "agent",
            "step_index": 1,
            "total_steps": 3,
            "status": "completed",
            "hidden": True,
            "diff_path": "/tmp/diff.diff",
            "output": {"diff_path": "/tmp/diff.diff"},
            "output_types": {"diff_path": "path"},
        },
    )
    _write_json(
        artifact_dir / "prompt_step_000_pre.json",
        {
            "workflow_name": "three_phase",
            "step_name": "pre",
            "step_type": "python",
            "step_index": -1,
            "total_steps": 3,
            "status": "completed",
            "is_pre_prompt_step": True,
            "embedded_workflow_name": "three_phase",
        },
    )


def _build_mentor_done(root: Path) -> None:
    artifact_dir = root / "myproj" / "artifacts" / "mentor-bryan" / TS_MENTOR_DONE
    _write_json(
        artifact_dir / "done.json",
        {
            "outcome": "completed",
            "cl_name": "feature_alpha",
            "name": "mentor_review",
            "response_path": "/tmp/mentor.md",
        },
    )


def _build_waiting(root: Path) -> None:
    artifact_dir = root / "myproj" / "artifacts" / "ace-run" / TS_WAITING
    _write_json(
        artifact_dir / "agent_meta.json",
        {
            "name": "waiter",
            "wait_for": ["upstream"],
            "wait_duration": 600.0,
        },
    )
    # Intentionally malformed waiting.json; the scanner should count it
    # as a json_decode_error and continue without crashing.
    _write_text(artifact_dir / "waiting.json", "{ not json")


def _build_malformed(root: Path) -> None:
    artifact_dir = root / "myproj" / "artifacts" / "ace-run" / TS_MALFORMED
    _write_text(artifact_dir / "agent_meta.json", "{not json}")
    # done.json is missing entirely so the scanner picks up only the
    # corrupt agent_meta.json (and counts it).


def build_fixture_tree(root: Path) -> Path:
    """Materialize the synthetic artifact tree at *root*.

    Returns *root* for convenience so callers can write::

        snapshot = scan_agent_artifacts(build_fixture_tree(tmp_path))
    """
    root.mkdir(parents=True, exist_ok=True)
    _build_home_running(root)
    _build_ace_run_running(root)
    _build_ace_run_done(root)
    _build_ace_run_failed(root)
    _build_ace_run_retried(root)
    _build_workflow(root)
    _build_mentor_done(root)
    _build_waiting(root)
    _build_malformed(root)
    return root


def fixture_summary() -> dict[str, Any]:
    """Return a stable dict describing what the fixture writes.

    Tests assert on this so that adding a new fixture branch forces a
    matching update to the expected counts.
    """
    return {
        "timestamps": list(EXPECTED_TIMESTAMPS),
        "expected_decode_errors": EXPECTED_DECODE_ERRORS,
        "expected_os_errors": EXPECTED_OS_ERRORS,
    }


__all__ = [
    "EXPECTED_DECODE_ERRORS",
    "EXPECTED_OS_ERRORS",
    "EXPECTED_TIMESTAMPS",
    "TS_ACE_RUN_DONE",
    "TS_ACE_RUN_FAILED",
    "TS_ACE_RUN_RETRIED_CHILD",
    "TS_ACE_RUN_RETRIED_PARENT",
    "TS_ACE_RUN_RUNNING",
    "TS_HOME_RUNNING",
    "TS_MALFORMED",
    "TS_MENTOR_DONE",
    "TS_WAITING",
    "TS_WORKFLOW_ROOT",
    "build_fixture_tree",
    "fixture_summary",
]

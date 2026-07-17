"""Real artifact fixture for a live plan family in provider retry backoff."""

from __future__ import annotations

import json
from pathlib import Path

from sase.llm_provider.retry_config import RetryState


ROOT_TIMESTAMP = "20260706115800"
CODE_TIMESTAMP = "20260706115900"
RUNNER_PID = 4242


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def build_retrying_plan_family(
    sase_home: Path,
    *,
    next_retry_at_epoch: float,
    include_retry_state: bool = True,
) -> Path:
    """Write a completed planner root plus its newest failed coder child."""
    project_file = sase_home / "projects" / "home" / "home.sase"
    project_file.parent.mkdir(parents=True, exist_ok=True)
    project_file.write_text("", encoding="utf-8")

    root_dir = project_file.parent / "artifacts" / "ace-run" / ROOT_TIMESTAMP
    _write_json(
        root_dir / "running.json",
        {
            "pid": RUNNER_PID,
            "cl_name": "retry-family",
            "model": "gpt-5",
            "llm_provider": "codex",
        },
    )
    _write_json(
        root_dir / "workflow_state.json",
        {
            "workflow_name": "ace-run",
            "context": {"cl_name": "retry-family"},
            "status": "completed",
            "pid": RUNNER_PID,
            "appears_as_agent": True,
            "is_anonymous": False,
            "start_time": "2026-07-06T11:58:00",
            "steps": [],
        },
    )
    _write_json(
        root_dir / "agent_meta.json",
        {
            "name": "retry-family",
            "agent_family": "retry-family",
            "agent_family_role": "root",
            "plan_chain_root": True,
            "role_suffix": "--plan",
            "plan": True,
            "plan_approved": True,
            "plan_action": "tale",
            "plan_submitted_at": ["2026-07-06T11:58:30Z"],
            "run_started_at": "2026-07-06T11:58:00Z",
            "pid": RUNNER_PID,
            "model": "gpt-5",
            "llm_provider": "codex",
        },
    )
    if include_retry_state:
        RetryState(
            status="retrying",
            retry_count=2,
            max_retries=3,
            next_retry_at_epoch=next_retry_at_epoch,
            wait_seconds=300,
        ).write_to(str(root_dir))

    code_dir = project_file.parent / "artifacts" / "ace-run" / CODE_TIMESTAMP
    _write_json(
        code_dir / "done.json",
        {
            "outcome": "failed",
            "finished_at": 1783353574.0,
            "cl_name": "retry-family--code",
            "project_file": str(project_file),
            "name": "retry-family--code",
            "error": "provider temporarily unavailable",
        },
    )
    _write_json(
        code_dir / "agent_meta.json",
        {
            "name": "retry-family--code",
            "agent_family": "retry-family",
            "agent_family_role": "code",
            "role_suffix": "--code",
            "parent_timestamp": ROOT_TIMESTAMP,
            "plan_action": "tale",
            "run_started_at": "2026-07-06T11:59:00Z",
            "stopped_at": "2026-07-06T11:59:34Z",
            "model": "gpt-5",
            "llm_provider": "codex",
        },
    )
    return root_dir

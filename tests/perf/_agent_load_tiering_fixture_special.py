"""Special-case rows for the synthetic load-tiering archive."""

from __future__ import annotations

import os
from pathlib import Path

from tests.perf._agent_load_tiering_fixture_core import (
    _artifact_dir,
    _done_payload,
    _meta_payload,
    _write_json,
)


def _write_running(projects_root: Path, index: int, *, active_pid: int) -> None:
    artifact_dir = _artifact_dir(projects_root, "home", "ace-run", index)
    running = {
        "pid": active_pid,
        "fixture_active_pid": True,
        "cl_name": "feature-hot",
        "model": "gpt-5.6-sol",
        "llm_provider": "codex",
        "vcs_provider": "github",
        "workspace_dir": "/tmp/sase-load-tiering/home",
    }
    _write_json(artifact_dir / "running.json", running)
    _write_json(
        artifact_dir / "agent_meta.json",
        _meta_payload(
            index=index,
            name="feature-hot-running",
            cl_name="feature-hot",
            provider="codex",
            model="gpt-5.6-sol",
            pid=active_pid,
            active=True,
        ),
    )


def _write_waiting(projects_root: Path, index: int, *, active_pid: int) -> None:
    artifact_dir = _artifact_dir(projects_root, "gh_sase-org__sase", "ace-run", index)
    _write_json(
        artifact_dir / "agent_meta.json",
        _meta_payload(
            index=index,
            name="feature-waiting",
            cl_name="feature-wait",
            provider="claude",
            model="claude-sonnet-5",
            pid=active_pid,
            active=True,
        )
        | {"wait_for": ["upstream"], "wait_duration": 300.0},
    )
    _write_json(
        artifact_dir / "waiting.json",
        {
            "cl_name": "feature-wait",
            "waiting_for": ["upstream"],
            "wait_duration": 300.0,
        },
    )


def _write_pending_question(
    projects_root: Path,
    index: int,
    *,
    active_pid: int,
) -> None:
    artifact_dir = _artifact_dir(
        projects_root, "gh_bobs-org__bob-cli", "ace-run", index
    )
    _write_json(
        artifact_dir / "agent_meta.json",
        _meta_payload(
            index=index,
            name="feature-question",
            cl_name="feature-question",
            provider="codex",
            model="gpt-5.6-sol",
            pid=active_pid,
            active=True,
        )
        | {"question_request_path": "/tmp/question.md"},
    )
    _write_json(
        artifact_dir / "pending_question.json",
        {
            "session_id": "question-session",
            "request_path": "/tmp/question.md",
            "submitted_at": "2026-09-12T13:01:00Z",
        },
    )


def _write_completed(
    projects_root: Path,
    index: int,
    *,
    provider: str,
    model: str,
) -> None:
    project = "gh_sase-org__sase"
    artifact_dir = _artifact_dir(projects_root, project, "ace-run", index)
    project_file = projects_root / project / f"{project}.sase"
    name = "feature-done-codex"
    cl_name = "feature-done"
    _write_json(
        artifact_dir / "agent_meta.json",
        _meta_payload(
            index=index,
            name=name,
            cl_name=cl_name,
            provider=provider,
            model=model,
        ),
    )
    _write_json(
        artifact_dir / "done.json",
        _done_payload(
            name=name,
            cl_name=cl_name,
            provider=provider,
            model=model,
            project_file=project_file,
        ),
    )
    (artifact_dir / "raw_xprompt.md").write_text(
        "feature-free-text-needle in prompt\n",
        encoding="utf-8",
    )


def _write_failed(projects_root: Path, index: int) -> None:
    project = "gh_bobs-org__bob-cli"
    artifact_dir = _artifact_dir(projects_root, project, "ace-run", index)
    project_file = projects_root / project / f"{project}.sase"
    name = "feature-failed-claude"
    cl_name = "feature-failed"
    _write_json(
        artifact_dir / "agent_meta.json",
        _meta_payload(
            index=index,
            name=name,
            cl_name=cl_name,
            provider="claude",
            model="claude-sonnet-5",
        ),
    )
    _write_json(
        artifact_dir / "done.json",
        _done_payload(
            name=name,
            cl_name=cl_name,
            provider="claude",
            model="claude-sonnet-5",
            project_file=project_file,
            outcome="failed",
        ),
    )


def _write_hidden_completed(projects_root: Path, index: int) -> None:
    project = "gh_sase-org__sase"
    artifact_dir = _artifact_dir(projects_root, project, "ace-run", index)
    project_file = projects_root / project / f"{project}.sase"
    name = "hidden-feature-agent"
    cl_name = "hidden-feature"
    _write_json(
        artifact_dir / "agent_meta.json",
        _meta_payload(
            index=index,
            name=name,
            cl_name=cl_name,
            provider="codex",
            model="gpt-5.6-sol",
            hidden=True,
        ),
    )
    _write_json(
        artifact_dir / "done.json",
        _done_payload(
            name=name,
            cl_name=cl_name,
            provider="codex",
            model="gpt-5.6-sol",
            project_file=project_file,
            hidden=True,
        ),
    )


def _write_workflow(projects_root: Path, index: int) -> None:
    project = "gh_sase-org__sase"
    artifact_dir = _artifact_dir(projects_root, project, "workflow-feature", index)
    _write_json(
        artifact_dir / "agent_meta.json",
        _meta_payload(
            index=index,
            name="workflow-feature-root",
            cl_name="feature-workflow",
            provider="claude",
            model="claude-sonnet-5",
        )
        | {
            "plan_approved": True,
            "plan_action": "epic",
            "role_suffix": "--plan",
        },
    )
    _write_json(
        artifact_dir / "workflow_state.json",
        {
            "workflow_name": "feature_workflow",
            "context": {"cl_name": "feature-workflow"},
            "status": "completed",
            "pid": os.getpid(),
            "appears_as_agent": True,
            "is_anonymous": False,
            "current_step_index": 2,
            "start_time": "2026-09-12T13:15:00",
            "steps": [
                {
                    "name": "plan",
                    "status": "completed",
                    "output": {"plan_path": "/tmp/feature-plan.md"},
                    "output_types": {"plan_path": "path"},
                },
                {
                    "name": "code",
                    "status": "completed",
                    "output": {"diff_path": "/tmp/feature.diff"},
                    "output_types": {"diff_path": "path"},
                },
            ],
        },
    )
    _write_json(
        artifact_dir / "plan_path.json",
        {"plan_path": "/tmp/feature-plan.md"},
    )
    _write_json(
        artifact_dir / "prompt_step_001_plan.json",
        {
            "workflow_name": "feature_workflow",
            "step_name": "plan",
            "step_type": "agent",
            "step_index": 0,
            "total_steps": 2,
            "status": "completed",
            "model": "claude-sonnet-5",
            "llm_provider": "claude",
            "output": {"meta_workspace": "10", "plan_path": "/tmp/feature-plan.md"},
            "output_types": {"plan_path": "path"},
            "artifacts_dir": str(artifact_dir),
        },
    )
    _write_json(
        artifact_dir / "prompt_step_002_code.json",
        {
            "workflow_name": "feature_workflow",
            "step_name": "code",
            "step_type": "agent",
            "step_index": 1,
            "total_steps": 2,
            "status": "completed",
            "hidden": True,
            "model": "gpt-5.6-sol",
            "llm_provider": "codex",
            "output": {"diff_path": "/tmp/feature.diff"},
            "output_types": {"diff_path": "path"},
            "artifacts_dir": str(artifact_dir),
        },
    )


def _write_monitor_done(projects_root: Path, index: int) -> None:
    project = "home"
    artifact_dir = _artifact_dir(projects_root, project, "ace-run", index)
    project_file = projects_root / project / f"{project}.sase"
    name = "feature-monitor"
    cl_name = "feature-monitor"
    family_shell = {
        "kind": "monitor",
        "id": "mon-fixture",
        "state": "completed",
        "start_status": "MONITORING",
        "stop_status": "MONITORED",
        "monitor": {
            "command": "sleep 0",
            "cwd": str(projects_root / project),
            "settled": True,
        },
    }
    _write_json(
        artifact_dir / "agent_meta.json",
        _meta_payload(
            index=index,
            name=name,
            cl_name=cl_name,
            provider="codex",
            model="gpt-5.6-sol",
        )
        | {
            "agent_family": "feature-monitor-family",
            "agent_family_role": "monitor",
            "family_shell": family_shell,
        },
    )
    _write_json(
        artifact_dir / "done.json",
        _done_payload(
            name=name,
            cl_name=cl_name,
            provider="codex",
            model="gpt-5.6-sol",
            project_file=project_file,
            outcome="monitored",
        )
        | {
            "status_label": "MONITORED",
            "family_shell": family_shell,
        },
    )


def _write_provenance_completed(projects_root: Path, index: int) -> None:
    project = "gh_sase-org__sase"
    artifact_dir = _artifact_dir(projects_root, project, "ace-run", index)
    project_file = projects_root / project / f"{project}.sase"
    name = "feature-remote-provenance"
    cl_name = "feature-remote"
    _write_json(
        artifact_dir / "agent_meta.json",
        _meta_payload(
            index=index,
            name=name,
            cl_name=cl_name,
            provider="codex",
            model="gpt-5.6-sol",
            provenance=True,
        ),
    )
    _write_json(
        artifact_dir / "done.json",
        _done_payload(
            name=name,
            cl_name=cl_name,
            provider="codex",
            model="gpt-5.6-sol",
            project_file=project_file,
            provenance=True,
        ),
    )

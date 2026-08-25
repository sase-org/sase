"""Shared helpers for wait_checks chop script tests."""

import json
import sys
from pathlib import Path

from sase.axe.chop_script_context import ChopScriptContext, write_chop_context
from sase.scripts.sase_chop_wait_checks import main as wait_checks_main

from tests._agent_names_fixtures import make_agent


def write_context(tmp_path: Path) -> Path:
    path = tmp_path / "context.json"
    write_chop_context(
        ChopScriptContext(
            max_hook_runners=3,
            max_agent_runners=3,
            zombie_timeout_seconds=600,
            query="status:Ready",
            lumberjack_name="wait_checks",
            state_dir=str(tmp_path / "state"),
            all_patches_file=str(tmp_path / "all.json"),
            filtered_patches_file=str(tmp_path / "filtered.json"),
        ),
        str(path),
    )
    return path


def make_waiting_agent(
    base: Path,
    *waiting_for: str,
    suffix: str = "waiter",
    wait_for_artifacts: list[dict[str, str]] | None = None,
    wait_for_fork_sources: list[dict[str, str]] | None = None,
    wait_for_beads: list[str] | None = None,
) -> Path:
    artifact_dir = base / ".sase/projects/proj/artifacts/ace-run" / suffix
    artifact_dir.mkdir(parents=True)
    marker = {
        "waiting_for": list(waiting_for),
        "cl_name": "waiter-cl",
        "timestamp": "waiter",
    }
    if wait_for_artifacts is not None:
        marker["wait_for_artifacts"] = wait_for_artifacts
    if wait_for_fork_sources is not None:
        marker["wait_for_fork_sources"] = wait_for_fork_sources
    if wait_for_beads is not None:
        marker["wait_for_beads"] = wait_for_beads
    (artifact_dir / "waiting.json").write_text(
        json.dumps(marker),
        encoding="utf-8",
    )
    return artifact_dir


def make_submitted_planner(
    base: Path,
    timestamp: str,
    name: str,
    *,
    plan_path: str | None = "sdd/plans/202606/example.md",
    role_suffix: str = "--plan",
    write_plan_path_json: bool = True,
    promoted: bool = True,
    agent_name: str | None = None,
) -> Path:
    """Create a submitted-and-waiting planner artifact (no done.json)."""
    artifact_dir = make_agent(
        base,
        "proj",
        timestamp,
        agent_name or name,
        workflow_name=name if promoted else None,
        agent_family=name if promoted else None,
        role_suffix=role_suffix,
    )
    meta_path = artifact_dir / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["plan"] = True
    meta["plan_submitted_at"] = ["2026-06-25T18:47:16+00:00"]
    if plan_path is not None:
        meta["plan_path"] = plan_path
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    if write_plan_path_json and plan_path is not None:
        (artifact_dir / "plan_path.json").write_text(
            json.dumps({"plan_path": plan_path}), encoding="utf-8"
        )
    return artifact_dir


def write_workflow_state(
    artifact_dir: Path,
    *,
    status: str = "completed",
    step_status: str = "completed",
    marker_status: str = "completed",
) -> None:
    (artifact_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "workflow_name": "run",
                "status": status,
                "current_step_index": 0,
                "steps": [
                    {
                        "name": "main",
                        "status": step_status,
                        "error": None,
                        "traceback": None,
                    }
                ],
                "appears_as_agent": True,
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "prompt_step_main.json").write_text(
        json.dumps(
            {
                "step_name": "main",
                "status": marker_status,
                "error": None,
                "traceback": None,
            }
        ),
        encoding="utf-8",
    )


def run_wait_checks(tmp_path: Path, monkeypatch) -> None:
    context_path = write_context(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["sase_chop_wait_checks", "--context", str(context_path)],
    )
    wait_checks_main()

"""Shared helpers for the GitHub Actions workflow/action contract tests.

Not itself a test module (leading underscore keeps pytest from collecting
it); the GitHub Actions contract modules import from here so they agree on how
workflow YAML and composite actions are parsed and inspected.
"""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent

# Jobs that run source lanes against the Rust artifacts `build-core` built from
# sase-core master rather than against published or stale local artifacts.
CORE_ARTIFACT_CONSUMER_JOBS = (
    "lint",
    "test",
    "coverage-contexts",
    "visual-test",
    "ace-page-group-isolation",
    "contention-test",
    "perf-floors",
)


def _load_ci_workflow() -> dict[str, Any]:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    return yaml.safe_load(workflow_path.read_text())


def _load_publish_workflow() -> dict[str, Any]:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "publish.yml"
    return yaml.safe_load(workflow_path.read_text())


def _load_master_gate_workflow() -> dict[str, Any]:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "master-gate.yml"
    return yaml.safe_load(workflow_path.read_text())


def _load_full_workflow() -> dict[str, Any]:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "full.yml"
    return yaml.safe_load(workflow_path.read_text())


def _load_core_pin_ratchet_workflow() -> dict[str, Any]:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "core-pin-ratchet.yml"
    return yaml.safe_load(workflow_path.read_text())


def _load_setup_sase_action() -> dict[str, Any]:
    action_path = REPO_ROOT / ".github" / "actions" / "setup-sase" / "action.yml"
    return yaml.safe_load(action_path.read_text())


def _workflow_triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    return workflow["on" if "on" in workflow else True]


def _job_run_text(job: dict[str, Any]) -> str:
    return "\n".join(
        step.get("run", "") for step in job["steps"] if isinstance(step.get("run"), str)
    )


def _setup_sase_install_script() -> str:
    steps = _load_setup_sase_action()["runs"]["steps"]
    return next(
        step["run"] for step in steps if step.get("name") == "Install dependencies"
    )


def _write_executable(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)

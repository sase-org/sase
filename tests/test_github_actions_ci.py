from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _load_ci_workflow() -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parent.parent
    workflow_path = repo_root / ".github" / "workflows" / "ci.yml"
    return yaml.safe_load(workflow_path.read_text())


def test_lint_job_initializes_sase_home_before_lint() -> None:
    workflow = _load_ci_workflow()
    steps = workflow["jobs"]["lint"]["steps"]

    install_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Install dependencies"
    )
    init_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Initialize SASE home"
    )
    lint_index = next(
        index for index, step in enumerate(steps) if step.get("name") == "Lint"
    )

    assert install_index < init_index < lint_index
    assert steps[init_index]["run"] == (
        "./.venv/bin/sase init memory --no-commit\n"
        "./.venv/bin/sase skill init --force\n"
    )


def test_lint_job_uses_single_lint_command() -> None:
    workflow = _load_ci_workflow()
    steps = workflow["jobs"]["lint"]["steps"]

    assert any(
        step.get("name") == "Lint" and step.get("run") == "just lint" for step in steps
    )
    assert not any(step.get("run") == "just symvision" for step in steps)
    assert not any(step.get("run") == "just toobig" for step in steps)

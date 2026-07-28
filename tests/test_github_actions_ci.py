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


def test_rust_core_is_built_once_and_shared_with_source_based_jobs() -> None:
    workflow = _load_ci_workflow()
    jobs = workflow["jobs"]
    build_core = jobs["build-core"]
    build_steps = build_core["steps"]

    assert any(
        step.get("with", {}).get("repository") == "sase-org/sase-core"
        for step in build_steps
    )
    assert any("maturin build --release" in step.get("run", "") for step in build_steps)
    assert any(
        step.get("uses") == "actions/upload-artifact@v4"
        and step.get("with", {}).get("name") == "sase-core-wheel"
        for step in build_steps
    )

    consumers = {
        "lint",
        "test",
        "visual-test",
        "build",
        "bead-backend",
        "phase7-perf-floor",
        "launch-perf-floor",
        "view-hints-perf-floor",
        "install-smoke",
    }
    for job_name in consumers:
        job = jobs[job_name]
        assert job["needs"] == "build-core"
        assert any(
            step.get("uses") == "./.github/actions/setup-sase" for step in job["steps"]
        )
        assert not any(
            step.get("with", {}).get("repository") == "sase-org/sase-core"
            for step in job["steps"]
        )
        assert not any(
            step.get("uses") == "dtolnay/rust-toolchain@stable" for step in job["steps"]
        )
        assert not any("rust-check" in step.get("run", "") for step in job["steps"])


def test_setup_sase_action_installs_downloaded_wheel() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    action_path = repo_root / ".github" / "actions" / "setup-sase" / "action.yml"
    action = yaml.safe_load(action_path.read_text())
    steps = action["runs"]["steps"]

    assert any(
        step.get("uses") == "actions/download-artifact@v4"
        and step.get("with", {}).get("name") == "sase-core-wheel"
        for step in steps
    )
    install_script = next(
        step["run"] for step in steps if step.get("name") == "Install dependencies"
    )
    assert 'SASE_CORE_WHEEL="${wheels[0]}" just "$INSTALL_RECIPE"' in install_script
    assert "sase-core-sha.txt" in install_script

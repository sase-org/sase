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
        "perf-floors",
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


def test_redundant_lanes_are_consolidated_without_dropping_commands() -> None:
    workflow = _load_ci_workflow()
    jobs = workflow["jobs"]

    assert {
        "fmt-md-check",
        "build",
        "bead-backend",
        "phase7-perf-floor",
        "launch-perf-floor",
        "view-hints-perf-floor",
        "install-smoke",
    }.isdisjoint(jobs)

    lint_steps = jobs["lint"]["steps"]
    assert any(step.get("run") == "just fmt-md-check" for step in lint_steps)
    assert any(step.get("run") == "just build-check" for step in lint_steps)
    assert any(
        step.get("uses") == "actions/cache@v4"
        and step.get("with", {}).get("path") == "node_modules"
        and "hashFiles('package-lock.json')" in step.get("with", {}).get("key", "")
        for step in lint_steps
    )

    perf_steps = jobs["perf-floors"]["steps"]
    commands = {
        step.get("run") for step in perf_steps if isinstance(step.get("run"), str)
    }
    assert {
        ".venv/bin/sase core health --json",
        "just phase7-perf-check",
        "just launch-perf-check",
        "just view-hints-perf-check",
        "just bead-perf-smoke",
    } <= commands
    floor_steps = [
        step for step in perf_steps if step.get("run", "").startswith("just ")
    ]
    assert all(step.get("if") == "always()" for step in floor_steps)
    artifact_names = {
        step.get("with", {}).get("name")
        for step in perf_steps
        if step.get("uses") == "actions/upload-artifact@v4"
    }
    assert {
        "phase7-perf-floor-report",
        "launch-perf-floor-report",
        "view-hints-perf-floor-report",
        "bead-perf-smoke",
    } <= artifact_names


def test_test_job_timeout_allows_slow_3_12_leg() -> None:
    workflow = _load_ci_workflow()
    assert workflow["jobs"]["test"]["timeout-minutes"] == 90


def test_test_job_only_collects_coverage_on_3_12_leg() -> None:
    workflow = _load_ci_workflow()
    steps = workflow["jobs"]["test"]["steps"]

    coverage_step = next(
        step for step in steps if step.get("name") == "Run tests (coverage leg)"
    )
    assert coverage_step["if"] == "matrix.python-version == '3.12'"
    assert coverage_step["run"] == "just test-cov"

    plain_step = next(
        step
        for step in steps
        if step.get("name") == "Run tests" and step.get("run") == "just test"
    )
    assert plain_step["if"] == "matrix.python-version != '3.12'"


def test_visual_suite_runs_only_in_dedicated_job() -> None:
    workflow = _load_ci_workflow()
    jobs = workflow["jobs"]

    run_tests = next(
        step for step in jobs["test"]["steps"] if step.get("name") == "Run tests"
    )
    assert run_tests["env"]["SASE_PYTEST_EXCLUDE_VISUAL"] == "true"
    assert not any(
        "sase-visual" in step.get("with", {}).get("path", "")
        for step in jobs["test"]["steps"]
    )
    assert any(
        step.get("run") == "just test-visual" for step in jobs["visual-test"]["steps"]
    )


def test_docs_build_once_per_event_and_deploys_are_serialized() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    ci = _load_ci_workflow()
    docs_build = ci["jobs"]["docs-build"]
    assert docs_build["if"] == (
        "github.event_name == 'pull_request' && "
        "github.event.pull_request.head.ref != "
        "'release-please--branches--master'"
    )
    assert any(
        step.get("uses") == "actions/cache@v4"
        and step.get("with", {}).get("path") == "~/.cache/ms-playwright"
        for step in docs_build["steps"]
    )

    deploy_path = repo_root / ".github" / "workflows" / "docs-deploy.yml"
    deploy = yaml.safe_load(deploy_path.read_text())
    assert deploy["concurrency"] == {
        "group": "docs-deploy",
        "cancel-in-progress": False,
    }
    assert any(
        step.get("uses") == "actions/cache@v4"
        and step.get("with", {}).get("path") == "~/.cache/ms-playwright"
        for step in deploy["jobs"]["deploy"]["steps"]
    )


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

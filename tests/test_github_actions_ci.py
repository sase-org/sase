from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests._test_selection_contexts import ARTIFACT_PREFIX


pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parent.parent

# Jobs that run source lanes against the wheel `build-core` built from
# sase-core master rather than against a published sase-core-rs release.
WHEEL_CONSUMER_JOBS = (
    "lint",
    "test",
    "visual-test",
    "ace-page-group-isolation",
    "perf-floors",
    "coverage-contexts",
)


def _load_ci_workflow() -> dict[str, Any]:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    return yaml.safe_load(workflow_path.read_text())


def _load_publish_workflow() -> dict[str, Any]:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "publish.yml"
    return yaml.safe_load(workflow_path.read_text())


def _load_setup_sase_action() -> dict[str, Any]:
    action_path = REPO_ROOT / ".github" / "actions" / "setup-sase" / "action.yml"
    return yaml.safe_load(action_path.read_text())


def _job_run_text(job: dict[str, Any]) -> str:
    return "\n".join(
        step.get("run", "") for step in job["steps"] if isinstance(step.get("run"), str)
    )


def _setup_sase_install_script() -> str:
    steps = _load_setup_sase_action()["runs"]["steps"]
    return next(
        step["run"] for step in steps if step.get("name") == "Install dependencies"
    )


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
        "ace-page-group-isolation",
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


def test_contexts_job_publishes_the_per_test_database_on_master_only() -> None:
    """The scoped lane's ground-truth source only exists if CI publishes it.

    Master-only because baselines are resolved as ancestors of an agent's
    ``HEAD``: a per-PR database is one nobody would ever look up. The artifact
    name carries the commit SHA because the local cache is keyed by it, and
    asserting the prefix against the consumer's own constant keeps the producer
    and consumer from drifting apart silently.
    """
    job = _load_ci_workflow()["jobs"]["coverage-contexts"]

    assert job["if"] == "github.ref == 'refs/heads/master'"
    assert any(step.get("run") == "just test-contexts" for step in job["steps"])

    step = next(
        step
        for step in job["steps"]
        if step.get("name") == "Upload coverage contexts database"
    )
    assert step["uses"] == "actions/upload-artifact@v4"
    assert step["with"]["name"] == f"{ARTIFACT_PREFIX}-${{{{ github.sha }}}}"
    assert step["with"]["path"] == ".coverage"
    # `always()` so a red suite still publishes: contexts are unioned into the
    # selection, so partial ground truth is strictly better than none.
    assert step["if"] == "always()"


def test_contexts_job_does_not_slow_the_per_pr_coverage_leg() -> None:
    """Contexts cost 68s and 889 MB when folded into the branch-coverage leg."""
    steps = _load_ci_workflow()["jobs"]["test"]["steps"]

    assert not any(
        "contexts" in str(step.get("with", {}).get("name", "")) for step in steps
    )
    assert not any("test-contexts" in str(step.get("run", "")) for step in steps)


def test_contexts_databases_are_portable_between_machines() -> None:
    """The artifact is read on a different checkout than the one that wrote it."""
    config = (REPO_ROOT / "coverage_contexts.toml").read_text()

    assert "relative_files = true" in config
    # Branch coverage times per-test contexts is the 906 MB artifact.
    assert "branch = false" in config


def test_release_branch_core_floor_lane_uses_published_floor() -> None:
    workflow = _load_ci_workflow()
    job = workflow["jobs"]["release-core-floor-smoke"]

    assert job["if"] == (
        "github.event_name == 'pull_request' && "
        "github.event.pull_request.head.ref == "
        "'release-please--branches--master'"
    )
    assert "needs" not in job
    assert job["timeout-minutes"] == 30
    assert not any(
        step.get("uses") == "./.github/actions/setup-sase" for step in job["steps"]
    )
    assert not any(
        step.get("with", {}).get("name") == "sase-core-wheel"
        for step in job["steps"]
        if step.get("uses") == "actions/download-artifact@v4"
    )

    run_text = _job_run_text(job)
    assert (
        "tools/smoke_sase_core_rs_telemetry --print-minimum pyproject.toml" in run_text
    )
    assert '"sase-core-rs==${core_minimum}"' in run_text
    assert 'importlib.metadata.version("sase-core-rs")' in run_text
    assert "actual != expected" in run_text
    assert "tools/check_sase_core_rs_bindings" in run_text
    assert "tools/validate_sase_core_rs" in run_text
    assert "tools/smoke_sase_core_rs_telemetry" in run_text
    assert "tools/smoke_sase_core_rs_at_reference_file_gate" in run_text
    assert "tools/smoke_sase_core_rs_bead_resolution" in run_text
    assert "tools/smoke_sase_core_rs_plan_header" in run_text
    assert "mapfile -t contract_files < tests/contract_manifest.txt" in run_text
    assert "python -m pytest -m contract" in run_text


def test_ci_never_runs_the_diff_scoped_test_lane() -> None:
    """CI always exercises the exhaustive lane; the scoped lane is a local, agent-only fast path.

    A diff-scoped selection is a heuristic backstopped by CI running everything
    on every push; CI itself must never be the thing that skips tests.
    """
    workflow_path = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    workflow_text = workflow_path.read_text()

    assert "test-scoped" not in workflow_text
    assert "run_pytest scoped" not in workflow_text
    assert "just check\n" not in workflow_text


def test_visual_suite_runs_only_in_dedicated_job() -> None:
    workflow = _load_ci_workflow()
    jobs = workflow["jobs"]

    assert not any(
        "VISUAL" in name
        for step in jobs["test"]["steps"]
        for name in step.get("env", {})
    )
    assert not any(
        "sase-visual" in step.get("with", {}).get("path", "")
        for step in jobs["test"]["steps"]
    )
    assert any(
        step.get("run") == "just test-visual" for step in jobs["visual-test"]["steps"]
    )


def test_ace_page_group_isolation_job_runs_dedicated_lane() -> None:
    steps = _load_ci_workflow()["jobs"]["ace-page-group-isolation"]["steps"]

    assert any(step.get("run") == "just test-ace-page-group-isolated" for step in steps)


def test_perf_floors_job_runs_slow_lane() -> None:
    workflow = _load_ci_workflow()
    steps = workflow["jobs"]["perf-floors"]["steps"]

    slow_step = next(step for step in steps if step.get("run") == "just test-slow")
    assert slow_step["if"] == "always()"


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
    steps = _load_setup_sase_action()["runs"]["steps"]

    assert any(
        step.get("uses") == "actions/download-artifact@v4"
        and step.get("with", {}).get("name") == "sase-core-wheel"
        for step in steps
    )
    install_script = _setup_sase_install_script()
    assert 'SASE_CORE_WHEEL="${wheels[0]}" just "$INSTALL_RECIPE"' in install_script
    assert "sase-core-sha.txt" in install_script


def test_setup_sase_action_exports_wheel_for_the_whole_job() -> None:
    """Later `just` recipes must still see the wheel build-core produced.

    Every recipe re-enters `_setup`, and `_core-overrides-arg` only lifts the
    published sase-core-rs window when SASE_CORE_WHEEL is set. Scoping the
    variable to the install step alone lets the editable install silently
    re-resolve sase-core-rs back inside the pyproject window.
    """
    install_script = _setup_sase_install_script()

    assert 'echo "SASE_CORE_WHEEL=${wheels[0]}" >> "$GITHUB_ENV"' in install_script


def test_publish_depends_on_floor_exact_install_smoke() -> None:
    workflow = _load_publish_workflow()
    jobs = workflow["jobs"]

    assert "install-smoke-core-floor" in jobs
    assert jobs["install-smoke-core-floor"]["needs"] == "build"
    assert jobs["publish"]["needs"] == [
        "release",
        "build",
        "install-smoke",
        "install-smoke-core-floor",
    ]

    free_resolution = _job_run_text(jobs["install-smoke"])
    floor_exact = _job_run_text(jobs["install-smoke-core-floor"])
    assert '"sase-core-rs==${core_minimum}"' not in free_resolution
    assert (
        "tools/smoke_sase_core_rs_telemetry --print-minimum pyproject.toml"
        in floor_exact
    )
    assert '"sase-core-rs==${core_minimum}"' in floor_exact
    assert 'importlib.metadata.version("sase-core-rs")' in floor_exact
    assert "actual != expected" in floor_exact
    assert "/tmp/smoke-floor-venv/bin/sase core health --json" in floor_exact
    assert "/tmp/smoke-floor-venv/bin/sase version" in floor_exact
    assert "/tmp/smoke-floor-venv/bin/sase doctor -C llm.default -j" in floor_exact
    assert "/tmp/smoke-floor-venv/bin/sase run --help" in floor_exact
    assert 'grep -Fq "[PROMPT]"' in floor_exact
    assert 'grep -Fq "sase chat list"' in floor_exact


def test_publish_sync_release_metadata_reports_ratchet_before_lock_refresh() -> None:
    workflow = _load_publish_workflow()
    jobs = workflow["jobs"]

    assert "sync-lockfile" not in jobs
    job = jobs["sync-release-metadata"]
    assert job["needs"] == "release"
    assert job["if"] == "${{ always() && github.event_name == 'push' }}"
    assert workflow["concurrency"] == {
        "group": "${{ github.workflow }}-${{ github.ref }}",
        "cancel-in-progress": False,
    }

    check_branch = next(
        step
        for step in job["steps"]
        if step.get("name") == "Check for a pending release-please branch"
    )
    assert "release-please--branches--master" in check_branch["run"]
    assert check_branch["env"]["GH_TOKEN"] == "${{ secrets.SASE_RELEASE_TOKEN }}"

    run_text = _job_run_text(job)
    assert "python tools/ratchet_core_window --report-only" in run_text
    assert 'if [ "$ratchet_status" -eq 2 ]; then' in run_text
    assert "uv lock" in run_text
    assert (
        "python tools/ratchet_core_window --report-only" in run_text.split("uv lock")[0]
    )
    assert "git diff --quiet -- pyproject.toml uv.lock" in run_text
    assert "git add pyproject.toml uv.lock" in run_text
    assert 'git commit -m "chore: sync release metadata"' in run_text
    assert "git push origin HEAD:release-please--branches--master" in run_text


def test_wheel_consumer_jobs_run_just_recipes_after_setup() -> None:
    """The export matters only because later steps re-enter `_setup`."""
    jobs = _load_ci_workflow()["jobs"]

    for job_name in WHEEL_CONSUMER_JOBS:
        steps = jobs[job_name]["steps"]
        setup_index = next(
            index
            for index, step in enumerate(steps)
            if step.get("uses") == "./.github/actions/setup-sase"
        )
        assert any(
            step.get("run", "").startswith("just ") for step in steps[setup_index + 1 :]
        ), f"{job_name} runs no just recipe after setup-sase"


def test_setup_sase_install_script_records_the_wheel_in_github_env(
    tmp_path: Path,
) -> None:
    """Run the action's install script the way a runner would."""
    artifact_dir = tmp_path / "sase-core-wheel"
    artifact_dir.mkdir()
    wheel = artifact_dir / "sase_core_rs-0.18.1-cp312-abi3-manylinux_2_39_x86_64.whl"
    wheel.touch()
    (artifact_dir / "sase-core-sha.txt").write_text("deadbeef\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    just_stub = bin_dir / "just"
    just_stub.write_text(
        '#!/bin/sh\nprintf "just %s SASE_CORE_WHEEL=%s\\n" "$1" "$SASE_CORE_WHEEL"\n',
        encoding="utf-8",
    )
    just_stub.chmod(just_stub.stat().st_mode | stat.S_IXUSR)

    github_env = tmp_path / "github_env"
    github_env.touch()
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "CORE_ARTIFACT_DIR": str(artifact_dir),
        "INSTALL_RECIPE": "install",
        "GITHUB_ENV": str(github_env),
    }

    result = subprocess.run(
        ["bash", "-e", "-c", _setup_sase_install_script()],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert f"just install SASE_CORE_WHEEL={wheel}" in result.stdout
    assert (
        f"SASE_CORE_WHEEL={wheel}"
        in github_env.read_text(encoding="utf-8").splitlines()
    )

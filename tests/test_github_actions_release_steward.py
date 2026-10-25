"""Contract tests for the live release-steward workflow (sase-1n6.9)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._github_actions_ci_helpers import REPO_ROOT
from tests._github_actions_ci_helpers import _job_run_text
from tests._github_actions_ci_helpers import _load_release_steward_workflow
from tests._github_actions_ci_helpers import _workflow_triggers


pytestmark = pytest.mark.contract

WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "release-steward.yml"
CACHE_KEY = (
    "release-steward-core-wheel-v1-${{ runner.os }}-${{ runner.arch }}"
    "-cp312-abi3-${{ steps.core-sha.outputs.sha }}"
)


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_schedule_is_live_and_manual_live_defaults_false() -> None:
    workflow = _load_release_steward_workflow()
    triggers = _workflow_triggers(workflow)
    assert triggers["schedule"] == [{"cron": "*/15 * * * *"}]
    live = triggers["workflow_dispatch"]["inputs"]["live"]
    assert live["type"] == "boolean"
    assert live["required"] is False
    assert live["default"] is False

    tick = next(
        step
        for step in workflow["jobs"]["steward"]["steps"]
        if step.get("name") == "Run the steward tick"
    )
    run_text = tick["run"]
    assert "--tick --json" in run_text
    assert "github.event_name" in run_text
    assert '"schedule"' in run_text
    schedule_index = run_text.index('"schedule"')
    first_live_index = run_text.index("extra+=(--live)")
    assert schedule_index < first_live_index
    assert "inputs.live" in run_text
    assert 'inputs.live }}" = "true"' in run_text
    second_live_index = run_text.index("extra+=(--live)", first_live_index + 1)
    inputs_index = run_text.index("inputs.live")
    assert inputs_index < second_live_index


def test_once_daily_metrics_block_is_informational_only() -> None:
    workflow = _load_release_steward_workflow()
    steps = workflow["jobs"]["steward"]["steps"]
    names = [step.get("name") for step in steps]
    assert "Append the once-daily release metrics block" in names
    tick_index = names.index("Run the steward tick")
    metrics_index = names.index("Append the once-daily release metrics block")
    assert tick_index < metrics_index

    metrics = steps[metrics_index]
    assert metrics["env"]["GH_TOKEN"] == "${{ secrets.SASE_RELEASE_TOKEN }}"
    run_text = metrics["run"]
    assert "tools/release_metrics" in run_text
    assert "## Release metrics" in run_text
    assert "GITHUB_STEP_SUMMARY" in run_text
    # Once-daily gate: only the 09:00 UTC ticks collect metrics.
    assert "date -u +%H" in run_text
    assert '"09"' in run_text
    # Informational only: a metrics failure still leaves the step green.
    assert "never gates the train" in run_text
    assert "exit 0" in run_text


def test_concurrency_never_cancels() -> None:
    workflow = _load_release_steward_workflow()
    assert workflow["concurrency"] == {
        "group": "release-steward",
        "cancel-in-progress": False,
    }


def test_checks_out_master() -> None:
    workflow = _load_release_steward_workflow()
    checkout = workflow["jobs"]["steward"]["steps"][0]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"]["ref"] == "master"


def test_builds_exact_core_pin_with_established_maturin() -> None:
    workflow = _load_release_steward_workflow()
    job = workflow["jobs"]["steward"]
    run_text = _job_run_text(job)
    assert "sase-core-revision.txt" in run_text
    assert r"^[0-9a-f]{40}$" in run_text
    core_checkout = next(
        step for step in job["steps"] if step.get("name") == "Check out Rust core"
    )
    assert core_checkout["with"]["repository"] == "sase-org/sase-core"
    assert core_checkout["with"]["ref"] == "${{ steps.core-sha.outputs.sha }}"
    build = next(
        step
        for step in job["steps"]
        if step.get("name") == "Build abi3 Rust core wheel"
    )
    assert build["working-directory"] == "sase-core/crates/sase_core_py"
    assert "uvx maturin build --release" in build["run"]
    assert build.get("if") == "steps.restore-core-wheel.outputs.cache-hit != 'true'"


def test_wheel_cache_key_is_sha_platform_abi_and_contract() -> None:
    workflow = _load_release_steward_workflow()
    restore = next(
        step
        for step in workflow["jobs"]["steward"]["steps"]
        if step.get("name") == "Restore cached core wheel"
    )
    save = next(
        step
        for step in workflow["jobs"]["steward"]["steps"]
        if step.get("name") == "Save core wheel cache"
    )
    assert restore["with"]["key"] == CACHE_KEY
    assert save["with"]["key"] == CACHE_KEY
    assert restore["with"]["path"] == "dist/"
    assert "cp312-abi3" in CACHE_KEY
    assert "release-steward-core-wheel-v1" in CACHE_KEY


def test_credential_routing_uses_release_token() -> None:
    workflow = _load_release_steward_workflow()
    tick = next(
        step
        for step in workflow["jobs"]["steward"]["steps"]
        if step.get("name") == "Run the steward tick"
    )
    assert tick["env"]["GH_TOKEN"] == "${{ secrets.SASE_RELEASE_TOKEN }}"
    assert tick["env"]["GH_REPO"] == "sase-org/sase"
    text = _workflow_text()
    assert "secrets.GITHUB_TOKEN" not in text
    assert "secrets.SASE_RELEASE_TOKEN" in text


def test_step_summary_is_required_for_the_tick() -> None:
    workflow = _load_release_steward_workflow()
    run_text = _job_run_text(workflow["jobs"]["steward"])
    assert "GITHUB_STEP_SUMMARY" in run_text
    assert "tools/release_watch" in run_text


def test_merge_authority_defaults_to_the_unset_repository_variable() -> None:
    workflow = _load_release_steward_workflow()
    tick = next(
        step
        for step in workflow["jobs"]["steward"]["steps"]
        if step.get("name") == "Run the steward tick"
    )
    assert tick["env"]["RELEASE_STEWARD_MERGE_ENABLED"] == (
        "${{ vars.RELEASE_STEWARD_MERGE_ENABLED }}"
    )
    text = _workflow_text()
    assert "RELEASE_STEWARD_MERGE_ENABLED: true" not in text
    assert "RELEASE_STEWARD_MERGE_ENABLED: 'true'" not in text


def test_isolated_env_installs_core_wheel_and_packaging_only() -> None:
    workflow = _load_release_steward_workflow()
    run_text = _job_run_text(workflow["jobs"]["steward"])
    assert "uv venv --python 3.12" in run_text
    assert "packaging" in run_text
    assert "sase_core_rs-*.whl" in run_text
    assert "just install" not in run_text
    assert "uv tool install sase" not in run_text
    assert "pip install sase\n" not in run_text
    assert "pip install . " not in run_text

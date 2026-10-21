from __future__ import annotations

import pytest

from tests._github_actions_ci_helpers import REPO_ROOT
from tests._github_actions_ci_helpers import job_run_text
from tests._github_actions_ci_helpers import load_ci_workflow
from tests._github_actions_ci_helpers import load_master_gate_workflow
from tests._github_actions_ci_helpers import workflow_triggers
from tests._test_shards import DEFAULT_SHARD_COUNT

pytestmark = pytest.mark.contract


def test_master_gate_triggers_on_master_pushes_and_manual_dispatch_only() -> None:
    workflow = load_master_gate_workflow()
    triggers = workflow_triggers(workflow)

    assert set(triggers) == {"push", "workflow_dispatch"}
    assert triggers["push"] == {"branches": ["master"]}


def test_master_gate_never_cancels_a_running_sha() -> None:
    workflow = load_master_gate_workflow()

    assert workflow["concurrency"] == {
        "group": "master-gate-${{ github.sha }}",
        "cancel-in-progress": False,
    }


def test_master_gate_has_read_only_contents_permission() -> None:
    workflow = load_master_gate_workflow()

    assert workflow["permissions"] == {"contents": "read"}


def test_master_gate_builds_docs_without_core_wheel_dependency() -> None:
    job = load_master_gate_workflow()["jobs"]["docs"]

    assert "needs" not in job
    assert int(job["timeout-minutes"]) <= 20
    assert any(step.get("run") == "just docs-check" for step in job["steps"])
    assert not any("setup-sase" in str(step.get("uses", "")) for step in job["steps"])


def test_master_gate_jobs_stay_within_the_twenty_minute_ceiling() -> None:
    workflow = load_master_gate_workflow()

    for job_name, job in workflow["jobs"].items():
        assert job["timeout-minutes"] <= 20, job_name


def test_master_gate_shard_matrix_matches_the_declared_shard_count() -> None:
    workflow = load_master_gate_workflow()

    assert workflow["env"]["SHARD_COUNT"] == DEFAULT_SHARD_COUNT
    test_job = workflow["jobs"]["test"]
    assert test_job["needs"] == "core-wheel"
    assert test_job["strategy"]["fail-fast"] is False
    assert test_job["strategy"]["matrix"]["shard"] == list(
        range(1, DEFAULT_SHARD_COUNT + 1)
    )


def test_master_gate_test_job_runs_only_the_sharded_fast_lane() -> None:
    job = load_master_gate_workflow()["jobs"]["test"]

    setup_step = next(
        step
        for step in job["steps"]
        if step.get("uses") == "./.github/actions/setup-sase"
    )
    assert setup_step["name"] == "Install dependencies"
    assert setup_step["with"] == {"python-version": "3.12"}

    run_step = next(step for step in job["steps"] if step.get("run") == "just test")
    assert run_step["env"] == {
        "SASE_TEST_SHARD": "${{ matrix.shard }}/${{ env.SHARD_COUNT }}"
    }

    run_text = job_run_text(job)
    for forbidden in (
        "test-scoped",
        "test-cov",
        "test-cost",
        "test-slow",
        "test-contexts",
        "test-visual",
        "fix-tui-screenshots",
        "update-visual-snapshots",
    ):
        assert forbidden not in run_text


def test_master_gate_never_runs_screenshot_maintenance() -> None:
    workflow_text = (
        REPO_ROOT / ".github" / "workflows" / "master-gate.yml"
    ).read_text()

    assert "fix-tui-screenshots" not in workflow_text
    assert "update-visual-snapshots" not in workflow_text
    assert "test-visual" not in workflow_text


def test_master_gate_core_wheel_job_resolves_and_caches_by_sha() -> None:
    job = load_master_gate_workflow()["jobs"]["core-wheel"]
    run_text = job_run_text(job)

    assert "sase-core-revision.txt" in run_text
    assert "^[0-9a-f]{40}$" in run_text
    assert "git ls-remote" not in run_text

    checkout_sase_step = job["steps"][0]
    assert checkout_sase_step["uses"] == "actions/checkout@v4"
    assert "with" not in checkout_sase_step

    restore_step = next(
        step for step in job["steps"] if step.get("uses") == "actions/cache/restore@v4"
    )
    assert restore_step["id"] == "restore-core-wheel"
    assert restore_step["with"]["path"] == "dist/"
    key = restore_step["with"]["key"]
    assert "${{ runner.os }}" in key
    assert "${{ steps.core-sha.outputs.sha }}" in key

    guarded_condition = "steps.restore-core-wheel.outputs.cache-hit != 'true'"
    save_step = next(
        step for step in job["steps"] if step.get("uses") == "actions/cache/save@v4"
    )
    assert save_step["with"]["key"] == key
    assert save_step["if"] == guarded_condition

    checkout_step = next(
        step
        for step in job["steps"]
        if step.get("with", {}).get("repository") == "sase-org/sase-core"
    )
    assert checkout_step["with"]["ref"] == "${{ steps.core-sha.outputs.sha }}"
    assert checkout_step["if"] == guarded_condition

    # Every build step is guarded the same way a cache hit means none of them
    # need to run.
    build_step_names = {
        "Set up Rust",
        "Cache Rust build",
        "Build abi3 Rust core wheel",
        "Build macro LSP",
        "Record wheel provenance",
    }
    for step in job["steps"]:
        if step.get("name") in build_step_names:
            assert step["if"] == guarded_condition

    assert "uvx maturin build --release" in run_text
    assert 'cargo build --release -p "$lsp_pkg"' in run_text
    assert "sase_macro_lsp" in run_text
    assert '"target/release/$lsp_bin"' in run_text

    upload_step = next(
        step
        for step in job["steps"]
        if step.get("uses") == "actions/upload-artifact@v4"
        and step.get("with", {}).get("name") == "sase-core-wheel"
    )
    assert upload_step["with"]["path"] == "dist/"
    assert upload_step["with"]["if-no-files-found"] == "error"
    assert "if" not in upload_step


def test_master_gate_lint_job_matches_ci_lint_steps_byte_for_byte() -> None:
    """Only qualification reporting and the core-producer identity may differ.

    Everything a maintainer would actually read as "the lint job" -- setup,
    sidecars, SASE init, format checks, validation, build verification -- has
    to be the exact same steps as `ci.yml`'s, or this gate's lint signal could
    silently drift from what PR CI already promises. ci.yml may wrap checkout
    with an explicit ref, assert a published core version, preflight bindings,
    and upload qualification evidence.
    """
    ci_job = load_ci_workflow()["jobs"]["lint"]
    gate_job = load_master_gate_workflow()["jobs"]["lint"]
    qualification_step_names = {
        "Set up preflight Python",
        "Download Rust core artifacts for bindings preflight",
        "Preflight core bindings",
        "Record installed core version",
        "Write qualification evidence",
        "Upload qualification evidence",
    }

    ci_by_name = {step["name"]: step for step in ci_job["steps"] if "name" in step}
    gate_by_name = {step["name"]: step for step in gate_job["steps"] if "name" in step}
    for name, gate_step in gate_by_name.items():
        ci_step = ci_by_name[name]
        if name == "Install dependencies":
            ci_with = dict(ci_step.get("with") or {})
            gate_with = dict(gate_step.get("with") or {})
            ci_with.pop("expected-core-version", None)
            assert ci_with == gate_with
            assert ci_step["uses"] == gate_step["uses"]
            continue
        if name == "Check pinned core bindings":
            ci_compare = {key: value for key, value in ci_step.items() if key != "id"}
            gate_compare = {
                key: value for key, value in gate_step.items() if key != "id"
            }
            assert ci_compare == gate_compare
            continue
        assert ci_step == gate_step
    assert qualification_step_names <= set(ci_by_name)
    assert qualification_step_names.isdisjoint(gate_by_name)
    assert gate_job["runs-on"] == ci_job["runs-on"]
    assert gate_job["needs"] == "core-wheel"
    assert ci_job["needs"] == ["prepare", "build-core"]

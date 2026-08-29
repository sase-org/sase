"""Contract tests for the scheduled/per-SHA workflows layered on top of ci.yml.

Companion to ``test_github_actions_ci_workflow.py``; master-gate.yml,
full.yml, core-pin-ratchet.yml, and shard-timings-ratchet.yml live here
because they have their own trigger and reuse contracts. Shared workflow
loaders live in ``tests/_github_actions_ci_helpers.py``.
"""

from __future__ import annotations

import pytest

from tests._github_actions_ci_helpers import REPO_ROOT
from tests._github_actions_ci_helpers import _job_run_text
from tests._github_actions_ci_helpers import _load_ci_workflow
from tests._github_actions_ci_helpers import _load_core_pin_ratchet_workflow
from tests._github_actions_ci_helpers import _load_full_workflow
from tests._github_actions_ci_helpers import _load_master_gate_workflow
from tests._github_actions_ci_helpers import _load_shard_timings_ratchet_workflow
from tests._github_actions_ci_helpers import _workflow_triggers
from tests._test_shards import DEFAULT_SHARD_COUNT
from tests._test_shards import SHARD_TIMINGS_ARTIFACT_NAME


pytestmark = pytest.mark.contract


# --------------------------------------------------------------------------
# master-gate.yml
# --------------------------------------------------------------------------


def test_master_gate_triggers_on_master_pushes_and_manual_dispatch_only() -> None:
    workflow = _load_master_gate_workflow()
    triggers = _workflow_triggers(workflow)

    assert set(triggers) == {"push", "workflow_dispatch"}
    assert triggers["push"] == {"branches": ["master"]}


def test_master_gate_never_cancels_a_running_sha() -> None:
    workflow = _load_master_gate_workflow()

    assert workflow["concurrency"] == {
        "group": "master-gate-${{ github.sha }}",
        "cancel-in-progress": False,
    }


def test_master_gate_has_read_only_contents_permission() -> None:
    workflow = _load_master_gate_workflow()

    assert workflow["permissions"] == {"contents": "read"}


def test_master_gate_jobs_stay_within_the_twenty_minute_ceiling() -> None:
    workflow = _load_master_gate_workflow()

    for job_name, job in workflow["jobs"].items():
        assert job["timeout-minutes"] <= 20, job_name


def test_master_gate_shard_matrix_matches_the_declared_shard_count() -> None:
    workflow = _load_master_gate_workflow()

    assert workflow["env"]["SHARD_COUNT"] == DEFAULT_SHARD_COUNT
    test_job = workflow["jobs"]["test"]
    assert test_job["needs"] == "core-wheel"
    assert test_job["strategy"]["fail-fast"] is False
    assert test_job["strategy"]["matrix"]["shard"] == list(
        range(1, DEFAULT_SHARD_COUNT + 1)
    )


def test_master_gate_test_job_runs_only_the_sharded_fast_lane() -> None:
    job = _load_master_gate_workflow()["jobs"]["test"]

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

    run_text = _job_run_text(job)
    for forbidden in (
        "test-scoped",
        "test-cov",
        "test-cost",
        "test-slow",
        "test-contexts",
        "test-visual",
    ):
        assert forbidden not in run_text


def test_master_gate_core_wheel_job_resolves_and_caches_by_sha() -> None:
    job = _load_master_gate_workflow()["jobs"]["core-wheel"]
    run_text = _job_run_text(job)

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
        "Build xprompt LSP",
        "Record wheel provenance",
    }
    for step in job["steps"]:
        if step.get("name") in build_step_names:
            assert step["if"] == guarded_condition

    assert "uvx maturin build --release" in run_text
    assert "cargo build --release -p sase_xprompt_lsp" in run_text
    assert "install -m 0755 target/release/sase-xprompt-lsp" in run_text

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
    """Only what identifies the core artifact producer may differ.

    Everything a maintainer would actually read as "the lint job" -- setup,
    sidecars, SASE init, format checks, validation, build verification -- has
    to be the exact same steps as `ci.yml`'s, or this gate's lint signal could
    silently drift from what PR CI already promises.
    """
    ci_job = _load_ci_workflow()["jobs"]["lint"]
    gate_job = _load_master_gate_workflow()["jobs"]["lint"]

    assert gate_job["steps"] == ci_job["steps"]
    assert gate_job["runs-on"] == ci_job["runs-on"]
    assert gate_job["needs"] == "core-wheel"
    assert ci_job["needs"] == "build-core"


# --------------------------------------------------------------------------
# full.yml
# --------------------------------------------------------------------------


def test_full_ci_triggers_and_calls_the_reusable_ci_workflow() -> None:
    workflow = _load_full_workflow()
    triggers = _workflow_triggers(workflow)

    assert set(triggers) == {"schedule", "workflow_dispatch"}
    assert triggers["schedule"] == [{"cron": "17 */2 * * *"}]
    assert workflow["concurrency"] == {
        "group": "full-ci",
        "cancel-in-progress": False,
    }
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"] == {
        "full": {
            "uses": "./.github/workflows/ci.yml",
            "secrets": "inherit",
        }
    }


def test_heavy_lane_jobs_are_defined_once_in_the_reusable_workflow() -> None:
    ci_jobs = set(_load_ci_workflow()["jobs"])
    full_jobs = set(_load_full_workflow()["jobs"])
    heavy_jobs = {
        "build-core",
        "test",
        "coverage-contexts",
        "visual-test",
        "ace-page-group-isolation",
        "contention-test",
        "perf-floors",
    }

    assert heavy_jobs <= ci_jobs
    for job_name in heavy_jobs:
        assert int(job_name in ci_jobs) + int(job_name in full_jobs) == 1


def test_readme_explains_the_three_ci_badges() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "actions/workflows/ci.yml/badge.svg" in readme
    assert "actions/workflows/master-gate.yml/badge.svg" in readme
    assert "actions/workflows/full.yml/badge.svg?branch=master" in readme
    assert (
        "CI checks pull requests, Master Gate is the per-SHA master release gate, "
        "and Full CI runs the scheduled exhaustive lane."
    ) in readme


# --------------------------------------------------------------------------
# core-pin-ratchet.yml
# --------------------------------------------------------------------------


def test_core_pin_ratchet_runs_on_schedule_not_push() -> None:
    """The ratchet must never itself be a push-path gate.

    It only ever opens a PR, which then runs the normal per-ref CI, so a
    pinned revision that would break sase cannot merge silently.
    """
    workflow = _load_core_pin_ratchet_workflow()
    triggers = _workflow_triggers(workflow)

    assert set(triggers) == {"schedule", "workflow_dispatch"}
    assert "push" not in triggers
    assert workflow["concurrency"] == {
        "group": "core-pin-ratchet",
        "cancel-in-progress": False,
    }
    assert workflow["permissions"] == {"contents": "read"}


def test_core_pin_ratchet_uses_the_shared_tool_and_names_the_pin_file() -> None:
    job = _load_core_pin_ratchet_workflow()["jobs"]["ratchet"]
    run_text = _job_run_text(job)

    assert "tools/ratchet_core_revision --check" in run_text
    assert "tools/ratchet_core_revision" in run_text
    assert "sase-core-revision.txt" in run_text
    assert "gh pr create" in run_text


# --------------------------------------------------------------------------
# shard-timings-ratchet.yml
# --------------------------------------------------------------------------


def test_shard_timings_ratchet_runs_on_schedule_not_push() -> None:
    """The ratchet must never itself be a push-path gate.

    It only ever opens a PR, which then runs the normal per-ref CI, so a
    stale timings table cannot redden master on its own.
    """
    workflow = _load_shard_timings_ratchet_workflow()
    triggers = _workflow_triggers(workflow)

    assert set(triggers) == {"schedule", "workflow_dispatch"}
    assert "push" not in triggers
    assert workflow["concurrency"] == {
        "group": "shard-timings-ratchet",
        "cancel-in-progress": False,
    }
    assert workflow["permissions"] == {"contents": "read"}


def test_shard_timings_ratchet_consumes_the_full_ci_artifact() -> None:
    job = _load_shard_timings_ratchet_workflow()["jobs"]["ratchet"]
    run_text = _job_run_text(job)

    assert "--workflow=full.yml" in run_text
    assert f"--name {SHARD_TIMINGS_ARTIFACT_NAME}" in run_text
    assert "tools/refresh_shard_timings" in run_text
    assert "--from-payload" in run_text
    assert "--check" in run_text
    assert "--assignment" in run_text
    assert "--max-age 14" in run_text
    assert "tests/shard_timings.json" in run_text
    assert "gh pr create" in run_text

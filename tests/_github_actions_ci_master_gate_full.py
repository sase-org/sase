from __future__ import annotations

import pytest

from tests._github_actions_ci_helpers import REPO_ROOT
from tests._github_actions_ci_helpers import TELEMETRY_CORE_ARTIFACT_CONSUMER_JOBS
from tests._github_actions_ci_helpers import callee_declared_scopes
from tests._github_actions_ci_helpers import caller_effective_permissions
from tests._github_actions_ci_helpers import job_run_text
from tests._github_actions_ci_helpers import load_build_core_workflow
from tests._github_actions_ci_helpers import load_ci_workflow
from tests._github_actions_ci_helpers import load_full_workflow
from tests._github_actions_ci_helpers import load_release_workflow
from tests._github_actions_ci_helpers import load_telemetry_workflow
from tests._github_actions_ci_helpers import permission_gaps
from tests._github_actions_ci_helpers import reusable_caller_permission_gaps
from tests._github_actions_ci_helpers import workflow_triggers

pytestmark = pytest.mark.contract


def test_full_ci_triggers_and_calls_the_reusable_ci_workflow() -> None:
    workflow = load_full_workflow()
    triggers = workflow_triggers(workflow)

    assert set(triggers) == {"schedule", "workflow_dispatch"}
    assert triggers["schedule"] == [{"cron": "17 */2 * * *"}]
    assert workflow["concurrency"] == {
        "group": "full-ci",
        "cancel-in-progress": False,
    }
    assert workflow["permissions"] == {"contents": "read", "actions": "read"}
    assert workflow["jobs"] == {
        "full": {
            "uses": "./.github/workflows/ci.yml",
            "secrets": "inherit",
        }
    }


def test_reusable_workflow_callers_grant_callee_permissions() -> None:
    problems = reusable_caller_permission_gaps(REPO_ROOT / ".github" / "workflows")
    assert problems == []


def test_old_full_yml_fails_the_reusable_permission_contract() -> None:
    caller = dict(load_full_workflow())
    caller["permissions"] = {"contents": "read"}
    callee = load_ci_workflow()
    gaps = permission_gaps(
        caller_effective_permissions(caller, caller["jobs"]["full"]),
        callee_declared_scopes(callee),
    )
    assert any(gap.startswith("actions:read") for gap in gaps)


def test_named_reusable_calls_cover_callee_scopes() -> None:
    cases = (
        (
            "release.yml",
            "qualify-ci",
            load_release_workflow(),
            load_ci_workflow(),
        ),
        (
            "ci.yml",
            "build-core",
            load_ci_workflow(),
            load_build_core_workflow(),
        ),
        (
            "telemetry.yml",
            "build-core",
            load_telemetry_workflow(),
            load_build_core_workflow(),
        ),
    )
    for caller_name, job_name, caller, callee in cases:
        gaps = permission_gaps(
            caller_effective_permissions(caller, caller["jobs"][job_name]),
            callee_declared_scopes(callee),
        )
        assert gaps == [], f"{caller_name} {job_name}: {gaps}"


def test_write_permission_covers_read_and_missing_explicit_map_fails() -> None:
    assert permission_gaps({"contents": "write"}, {"contents": "read"}) == []
    assert permission_gaps({"contents": "read"}, {"contents": "write"}) == [
        "contents:write (caller has read)"
    ]
    assert permission_gaps(None, {"contents": "read"}) == [
        "contents:read (caller has no explicit permissions)"
    ]


def test_heavy_lane_jobs_are_defined_once_in_the_reusable_workflow() -> None:
    ci_jobs = set(load_ci_workflow()["jobs"])
    full_jobs = set(load_full_workflow()["jobs"])
    heavy_jobs = {
        "build-core",
        "test",
        "visual-test",
        "ace-page-group-isolation",
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


def test_build_core_workflow_is_reusable_only() -> None:
    workflow = load_build_core_workflow()
    triggers = workflow_triggers(workflow)

    assert set(triggers) == {"workflow_call"}
    call = triggers["workflow_call"]
    # sase-1n6.5.1.2 added explicit-ref plumbing and the published-core mode:
    # inputless callers (ci.yml, telemetry.yml) stay on source defaults, and
    # the probe path stays rehearse-only. Input detail lives in
    # test_github_actions_build_core.py; this guard pins the trigger shape.
    assert set(call["inputs"]) == {
        "ref",
        "core-source",
        "core-version",
        "manifest-artifact",
        "probe-core-version",
    }
    assert set(call.get("outputs", {})) == {"core-version", "probe"}
    assert workflow["permissions"] == {"contents": "read"}


def test_build_core_workflow_is_the_only_consumer_of_its_own_artifact_name() -> None:
    """ci.yml and telemetry.yml both call this one workflow, not inline copies."""
    ci_workflow_text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    telemetry_workflow_text = (
        REPO_ROOT / ".github" / "workflows" / "telemetry.yml"
    ).read_text()

    for workflow_text in (ci_workflow_text, telemetry_workflow_text):
        assert "uses: ./.github/workflows/build-core.yml" in workflow_text
        assert "sase-org/sase-core" not in workflow_text


def test_telemetry_workflow_triggers_on_a_schedule_offset_from_full_ci() -> None:
    ci_workflow = load_ci_workflow()
    workflow = load_telemetry_workflow()
    triggers = workflow_triggers(workflow)

    assert set(triggers) == {"schedule", "workflow_dispatch"}
    full_ci_triggers = workflow_triggers(load_full_workflow())
    assert triggers["schedule"] != full_ci_triggers["schedule"]
    assert workflow["concurrency"] == {
        "group": "ci-telemetry",
        "cancel-in-progress": False,
    }
    assert workflow["permissions"] == {"contents": "read"}
    # ci.yml itself carries no schedule of its own: only full.yml and
    # telemetry.yml (both callers) schedule it.
    assert "schedule" not in workflow_triggers(ci_workflow)


def test_telemetry_workflow_builds_core_through_the_shared_reusable_workflow() -> None:
    job = load_telemetry_workflow()["jobs"]["build-core"]

    assert job == {"uses": "./.github/workflows/build-core.yml"}


def test_telemetry_workflow_runs_cost_attribution_with_realistic_timeout() -> None:
    job = load_telemetry_workflow()["jobs"]["test-cost"]

    assert job["needs"] == "build-core"
    assert job["timeout-minutes"] == 180
    setup_step = next(
        step
        for step in job["steps"]
        if step.get("uses") == "./.github/actions/setup-sase"
    )
    assert setup_step["with"] == {"python-version": "3.13"}
    assert any(step.get("run") == "just test-cost" for step in job["steps"])


def test_telemetry_workflow_publishes_contexts_on_master_only_with_headroom() -> None:
    job = load_telemetry_workflow()["jobs"]["coverage-contexts"]

    assert job["needs"] == "build-core"
    assert job["if"] == "github.ref == 'refs/heads/master'"
    assert job["timeout-minutes"] == 120
    assert any(step.get("run") == "just test-contexts" for step in job["steps"])
    upload_step = next(
        step
        for step in job["steps"]
        if step.get("name") == "Upload coverage contexts database"
    )
    assert upload_step["with"]["name"] == "sase-coverage-contexts-${{ github.sha }}"


def test_telemetry_workflow_runs_one_contention_repeat_within_the_same_ceiling() -> (
    None
):
    """REPEAT dropped 3 -> 1 because three repeats missed Full CI's 90-minute ceiling."""
    job = load_telemetry_workflow()["jobs"]["contention-test"]
    run_text = job_run_text(job)

    assert job["needs"] == "build-core"
    assert job["timeout-minutes"] == 90
    assert "SASE_CONTENTION_REPEAT=1 just test-contention" in run_text
    assert "SASE_CONTENTION_REPEAT=3" not in run_text


def test_telemetry_lane_jobs_run_just_recipes_against_the_shared_core_artifact() -> (
    None
):
    jobs = load_telemetry_workflow()["jobs"]

    for job_name in TELEMETRY_CORE_ARTIFACT_CONSUMER_JOBS:
        steps = jobs[job_name]["steps"]
        setup_index = next(
            index
            for index, step in enumerate(steps)
            if step.get("uses") == "./.github/actions/setup-sase"
        )
        assert any(
            "just " in step.get("run", "") for step in steps[setup_index + 1 :]
        ), f"{job_name} runs no just recipe after setup-sase"

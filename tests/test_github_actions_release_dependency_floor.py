"""Contract tests for the shared release-dependency-floor reusable workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from tests._github_actions_ci_helpers import REPO_ROOT
from tests._github_actions_ci_helpers import _job_run_text
from tests._github_actions_ci_helpers import _workflow_triggers


WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "release-dependency-floor.yml"


def _load_workflow() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_workflow_is_reusable_only() -> None:
    workflow = _load_workflow()
    triggers = _workflow_triggers(workflow)

    assert set(triggers) == {"workflow_call"}
    inputs = triggers["workflow_call"]["inputs"]
    assert inputs["probe_requirement"]["type"] == "string"
    assert inputs["probe_requirement"]["required"] is False
    assert inputs["probe_requirement"]["default"] == ""


def test_header_cites_ci_watch_skip_semantics() -> None:
    raw = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "plan_release_merge" in raw
    assert "release_pr_checks_not_green" in raw
    assert "SKIPPED" in raw
    assert "ci_watch" in raw
    assert "job.workflow_sha" in raw
    assert "gh run rerun --failed" in raw
    assert "50 re-runs" in raw
    assert "release-core-floor-smoke" in raw


def test_jobs_are_never_skipped() -> None:
    workflow = _load_workflow()
    jobs = workflow["jobs"]

    assert set(jobs) == {"check", "rerun"}
    for name, job in jobs.items():
        assert "if" not in job, name
        assert "timeout-minutes" in job


def test_check_job_targets_pr_head_and_workflow_sha() -> None:
    workflow = _load_workflow()
    job = workflow["jobs"]["check"]
    steps = job["steps"]

    assert job["permissions"] == {"contents": "read"}
    assert job["name"] == "Release dependency floor"

    caller = next(
        step
        for step in steps
        if step.get("name") == "Check out the caller at the PR head"
    )
    assert caller["uses"] == "actions/checkout@v4"
    assert caller["with"]["ref"] == (
        "${{ github.event.pull_request.head.sha || github.sha }}"
    )
    assert "path" not in caller.get("with", {})

    script = next(
        step
        for step in steps
        if step.get("name")
        == "Check out the floor-check script at this workflow's commit"
    )
    assert script["with"]["repository"] == "${{ job.workflow_repository }}"
    assert script["with"]["ref"] == "${{ job.workflow_sha }}"
    assert script["with"]["path"] == ".sase-floor-check"

    run_text = _job_run_text(job)
    assert "uv run --python 3.12 --no-project --with packaging" in run_text
    assert "tools/check_release_dependency_floor" in run_text
    assert "--head-ref" in run_text
    assert "--extra-requirement" in run_text


def test_rerun_job_owns_actions_write() -> None:
    workflow = _load_workflow()
    job = workflow["jobs"]["rerun"]

    assert job["permissions"] == {
        "actions": "write",
        "contents": "read",
        "pull-requests": "read",
    }
    assert job["permissions"]["actions"] == "write"
    assert workflow["jobs"]["check"]["permissions"].get("actions") is None

    run_text = _job_run_text(job)
    assert "check_release_dependency_floor rerun" in run_text
    assert "--workflow release-dependency-floor.yml" in run_text
    assert "GH_TOKEN" in str(job)


def test_sase_ci_does_not_call_the_plugin_floor_check() -> None:
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "release-dependency-floor.yml" not in ci
    assert "release-core-floor-smoke" in ci

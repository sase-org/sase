"""Contract tests for the handover-trimmed publish workflow (sase-1n6.9).

publish.yml keeps only release-please generation (`release`) and the
release-PR metadata sync (`sync-release-metadata`). Building, exercising,
publishing, and confirming moved to release.yml; recovering an old version is
`release.yml -f mode=resume` at its tag. The steward dispatches this workflow
bare (`gh workflow run publish.yml`) in metadata mode.
"""

from __future__ import annotations

import pytest

from tests._github_actions_ci_helpers import _job_run_text
from tests._github_actions_ci_helpers import _load_publish_workflow
from tests._github_actions_ci_helpers import _workflow_triggers


pytestmark = pytest.mark.contract


def test_publish_keeps_only_release_and_metadata_jobs() -> None:
    workflow = _load_publish_workflow()
    jobs = workflow["jobs"]

    assert set(jobs) == {"release", "sync-release-metadata"}
    assert "build" not in jobs
    assert "install-smoke" not in jobs
    assert "install-smoke-core-floor" not in jobs
    assert "publish" not in jobs


def test_publish_triggers_are_schedule_or_bare_dispatch() -> None:
    workflow = _load_publish_workflow()
    triggers = _workflow_triggers(workflow)

    assert "push" not in triggers
    assert triggers["schedule"] == [{"cron": "17 */3 * * *"}]
    # The steward dispatches publish.yml bare in metadata mode, so
    # workflow_dispatch carries no inputs (publish_existing is gone).
    assert triggers["workflow_dispatch"] is None


def test_publish_release_please_retries_have_no_publish_inputs() -> None:
    workflow = _load_publish_workflow()
    jobs = workflow["jobs"]

    release_steps = jobs["release"]["steps"]
    release_please_steps = [
        step
        for step in release_steps
        if step.get("uses") == "googleapis/release-please-action@v5"
    ]
    assert [step["id"] for step in release_please_steps] == [
        "release1",
        "release2",
        "release3",
    ]
    assert "if" not in release_please_steps[0]
    assert release_please_steps[1]["if"] == "${{ steps.release1.outcome == 'failure' }}"
    assert release_please_steps[2]["if"] == "${{ steps.release2.outcome == 'failure' }}"
    assert any(
        step.get("name") == "Back off before release-please retry 2"
        and step.get("if") == "${{ steps.release1.outcome == 'failure' }}"
        for step in release_steps
    )
    assert any(
        step.get("name") == "Back off before release-please retry 3"
        and step.get("if") == "${{ steps.release2.outcome == 'failure' }}"
        for step in release_steps
    )
    assert jobs["release"].get("outputs") in (None, {})


def test_publish_sync_release_metadata_applies_ratchet_before_lock_refresh() -> None:
    workflow = _load_publish_workflow()
    jobs = workflow["jobs"]

    assert "sync-lockfile" not in jobs
    job = jobs["sync-release-metadata"]
    assert job["needs"] == "release"
    assert job["if"] == "${{ always() }}"
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

    reconcile = next(
        step
        for step in job["steps"]
        if step.get("name") == "Reconcile release metadata"
    )
    assert reconcile["env"]["UV_DEFAULT_INDEX"] == "https://pypi.org/simple/"
    # tools/_release_core.py reads tag workflows through `gh api` (or urllib
    # with GH_TOKEN), so the ratchet step must not run unauthenticated.
    assert reconcile["env"]["GH_TOKEN"] == "${{ secrets.SASE_RELEASE_TOKEN }}"

    run_text = _job_run_text(job)
    assert (
        "python tools/ratchet_core_pin --allow-transitive-lock-refresh "
        "|| ratchet_status=$?"
    ) in run_text
    assert "python tools/ratchet_core_window --report-only" not in run_text
    assert "python tools/ratchet_core_pin --report-only" not in run_text
    assert 'if [ "$ratchet_status" -eq 2 ]; then' in run_text
    assert "ratchet applied dependency metadata changes" in run_text
    assert "uv lock" in run_text
    assert (
        "python tools/ratchet_core_pin --allow-transitive-lock-refresh"
        in run_text.split("uv lock")[0]
    )
    assert "git diff --quiet -- pyproject.toml uv.lock" in run_text
    assert "git add pyproject.toml uv.lock" in run_text
    assert 'git commit -m "chore: sync release metadata"' in run_text

from __future__ import annotations

import pytest

from tests._github_actions_ci_helpers import _job_run_text
from tests._github_actions_ci_helpers import _load_publish_workflow
from tests._github_actions_ci_helpers import _workflow_triggers


pytestmark = pytest.mark.contract


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


def test_publish_generation_runs_on_schedule_or_manual_dispatch_only() -> None:
    workflow = _load_publish_workflow()
    triggers = _workflow_triggers(workflow)
    jobs = workflow["jobs"]

    generator_if = (
        "${{ github.event_name == 'schedule' || "
        "(github.event_name == 'workflow_dispatch' && "
        "inputs.publish_existing == false) }}"
    )
    generator_retry_prefix = (
        "${{ (github.event_name == 'schedule' || "
        "(github.event_name == 'workflow_dispatch' && "
        "inputs.publish_existing == false)) && "
    )
    publish_if = (
        "${{ needs.release.outputs.release_created == 'true' || "
        "(github.event_name == 'workflow_dispatch' && "
        "inputs.publish_existing == true) }}"
    )

    assert "push" not in triggers
    assert triggers["schedule"] == [{"cron": "17 */3 * * *"}]
    assert triggers["workflow_dispatch"]["inputs"]["publish_existing"] == {
        "description": "Publish the existing release version recorded on master",
        "type": "boolean",
        "required": True,
        "default": False,
    }

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
    assert release_please_steps[0]["if"] == generator_if
    assert release_please_steps[1]["if"] == (
        generator_retry_prefix + "steps.release1.outcome == 'failure' }}"
    )
    assert release_please_steps[2]["if"] == (
        generator_retry_prefix + "steps.release2.outcome == 'failure' }}"
    )
    assert any(
        step.get("name") == "Back off before release-please retry 2"
        and step.get("if")
        == generator_retry_prefix + "steps.release1.outcome == 'failure' }}"
        for step in release_steps
    )
    assert any(
        step.get("name") == "Back off before release-please retry 3"
        and step.get("if")
        == generator_retry_prefix + "steps.release2.outcome == 'failure' }}"
        for step in release_steps
    )
    assert jobs["build"]["if"] == publish_if
    assert jobs["publish"]["if"] == publish_if


def test_publish_sync_release_metadata_applies_ratchet_before_lock_refresh() -> None:
    workflow = _load_publish_workflow()
    jobs = workflow["jobs"]

    assert "sync-lockfile" not in jobs
    job = jobs["sync-release-metadata"]
    assert job["needs"] == "release"
    assert job["if"] == (
        "${{ always() && (github.event_name == 'schedule' || "
        "(github.event_name == 'workflow_dispatch' && "
        "inputs.publish_existing == false)) }}"
    )
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

    run_text = _job_run_text(job)
    assert (
        "python tools/ratchet_core_window --allow-transitive-lock-refresh "
        "|| ratchet_status=$?"
    ) in run_text
    assert "python tools/ratchet_core_window --report-only" not in run_text
    assert 'if [ "$ratchet_status" -eq 2 ]; then' in run_text
    assert "ratchet applied dependency metadata changes" in run_text
    assert "uv lock" in run_text
    assert (
        "python tools/ratchet_core_window --allow-transitive-lock-refresh"
        in run_text.split("uv lock")[0]
    )
    assert "git diff --quiet -- pyproject.toml uv.lock" in run_text
    assert "git add pyproject.toml uv.lock" in run_text
    assert 'git commit -m "chore: sync release metadata"' in run_text
    assert "git push origin HEAD:release-please--branches--master" in run_text

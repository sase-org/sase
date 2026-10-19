"""Contract tests for the family install canary (phase sase-1my.2).

The canary extends ``install-smoke.yml`` to a Linux + macOS matrix that
installs sase plus the family plugins, asserts newest and exact versions,
runs the first commands, publishes one result artifact per leg, and opens
or closes a single alert issue.
"""

from __future__ import annotations

import pytest

from tests._github_actions_ci_helpers import _job_run_text
from tests._github_actions_ci_helpers import _load_install_smoke_workflow
from tests._github_actions_ci_helpers import _workflow_triggers


pytestmark = pytest.mark.contract


def test_canary_runs_on_both_oses_without_fail_fast() -> None:
    workflow = _load_install_smoke_workflow()
    job = workflow["jobs"]["install-smoke"]
    assert job["runs-on"] == "${{ matrix.os }}"
    assert job["strategy"]["matrix"]["os"] == ["ubuntu-latest", "macos-latest"]
    assert job["strategy"]["fail-fast"] is False


def test_canary_installs_are_isolated_and_cache_free() -> None:
    workflow = _load_install_smoke_workflow()
    job = workflow["jobs"]["install-smoke"]
    env = job.get("env", {})
    assert env.get("UV_NO_CACHE") == "1"
    run_text = _job_run_text(job)
    assert "canary-tool-dir" in run_text
    assert "canary-exact-tool-dir" in run_text
    assert "GITHUB_ENV" in run_text
    assert "--refresh" in run_text


def test_canary_job_env_uses_no_runner_context() -> None:
    # The `runner` context is not available in job-level `env`; GitHub
    # rejects the whole workflow file with "Unrecognized named-value:
    # 'runner'" and every run fails before any job starts. Isolated paths
    # must be derived from $RUNNER_TEMP inside a step instead.
    workflow = _load_install_smoke_workflow()
    for name, job in workflow["jobs"].items():
        for key, value in job.get("env", {}).items():
            assert "runner." not in str(value), f"{name}.env.{key}"


def test_canary_keeps_the_single_sourced_documented_commands() -> None:
    workflow = _load_install_smoke_workflow()
    job = workflow["jobs"]["install-smoke"]
    run_text = _job_run_text(job)
    assert "tools/render_applicability --install-command" in run_text
    assert "tools/render_applicability --install-family-command" in run_text
    assert "tools/render_applicability --check-installed" in run_text


def test_canary_asserts_newest_and_exact_with_the_helper() -> None:
    workflow = _load_install_smoke_workflow()
    job = workflow["jobs"]["install-smoke"]
    run_text = _job_run_text(job)
    assert "tools/check_family_install" in run_text
    assert "uv run --no-project --with packaging" in run_text
    assert "--step assert-newest-versions" in run_text
    assert "--step assert-exact-versions" in run_text
    assert "--mode exact" in run_text
    assert "--print-pins" in run_text
    assert "--write-result install-canary-newest.json" in run_text
    assert "--write-result install-canary-exact.json" in run_text


def test_canary_runs_health_first_commands_and_plugin_proof() -> None:
    workflow = _load_install_smoke_workflow()
    job = workflow["jobs"]["install-smoke"]
    run_text = _job_run_text(job)
    assert "sase --help" in run_text
    assert "sase version -j" in run_text
    assert "sase core health --json" in run_text
    assert "sase doctor -C llm.default -j" in run_text
    assert "no usable default LLM provider executable was found" in run_text
    assert "sase completion install" in run_text
    assert "--assert-plugins-loaded" in run_text


def test_each_leg_uploads_one_result_artifact() -> None:
    workflow = _load_install_smoke_workflow()
    job = workflow["jobs"]["install-smoke"]
    uploads = [
        step
        for step in job["steps"]
        if isinstance(step, dict)
        and str(step.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    assert len(uploads) == 1
    assert uploads[0]["with"]["name"] == "install-canary-${{ matrix.os }}"
    assert uploads[0]["with"]["path"] == "install-canary-${{ matrix.os }}.json"
    assert uploads[0].get("if") == "always()"


def test_probe_input_forces_the_red_path() -> None:
    workflow = _load_install_smoke_workflow()
    triggers = _workflow_triggers(workflow)
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert "probe_expect" in inputs
    run_text = _job_run_text(workflow["jobs"]["install-smoke"])
    assert "--force-expect" in run_text
    assert "inputs.probe_expect" in run_text


def test_alert_job_holds_the_only_issues_write() -> None:
    workflow = _load_install_smoke_workflow()
    jobs = workflow["jobs"]
    assert "install-canary-alert" in jobs
    alert = jobs["install-canary-alert"]
    assert alert["needs"] == ["install-smoke"]
    assert alert["if"] == "always()"
    assert alert["permissions"] == {"issues": "write"}
    for name, job in jobs.items():
        if name == "install-canary-alert":
            continue
        permissions = job.get("permissions", {})
        assert "issues" not in permissions, name
    assert "issues" not in workflow.get("permissions", {})


def test_alert_opens_comments_and_closes_one_labeled_issue() -> None:
    workflow = _load_install_smoke_workflow()
    run_text = _job_run_text(workflow["jobs"]["install-canary-alert"])
    assert "install-canary" in run_text
    assert "gh issue create" in run_text
    assert "gh issue comment" in run_text
    assert "gh issue close" in run_text
    assert "gh label create install-canary" in run_text


def test_alert_counts_a_missing_artifact_as_red() -> None:
    workflow = _load_install_smoke_workflow()
    run_text = _job_run_text(workflow["jobs"]["install-canary-alert"])
    assert "canary-results" in run_text
    assert "glob" in run_text and "install-canary-*.json" in run_text


def test_probe_runs_stay_quiet_without_the_alert_input() -> None:
    workflow = _load_install_smoke_workflow()
    triggers = _workflow_triggers(workflow)
    assert triggers["workflow_dispatch"]["inputs"]["alert"]["default"] is False
    run_text = _job_run_text(workflow["jobs"]["install-canary-alert"])
    assert "inputs.alert" in run_text
    assert "github.event_name" in run_text and "schedule" in run_text


def test_canary_keeps_its_schedule_and_dispatch_triggers() -> None:
    workflow = _load_install_smoke_workflow()
    triggers = _workflow_triggers(workflow)
    assert triggers["schedule"] == [{"cron": "26 7 * * *"}]
    assert "workflow_dispatch" in triggers
    assert "push" not in triggers

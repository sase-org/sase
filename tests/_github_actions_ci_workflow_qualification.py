from __future__ import annotations

import pytest

from tests._github_actions_ci_helpers import CORE_ARTIFACT_CONSUMER_JOBS
from tests._github_actions_ci_helpers import load_ci_workflow

pytestmark = pytest.mark.contract


def _named_steps(job: dict) -> dict[str, dict]:
    return {step["name"]: step for step in job["steps"] if "name" in step}


def test_prepare_job_rejects_invalid_source_version_manifest_combinations() -> None:
    job = load_ci_workflow()["jobs"]["prepare"]
    validate = _named_steps(job)["Validate qualification inputs"]["run"]

    assert "core-source must be 'source' or 'published'" in validate
    assert "core-version is required when core-source is published" in validate
    assert "probe-core-version requires core-source 'published'" in validate
    assert "core-version is only valid when core-source is published" in validate
    assert "manifest-artifact is only valid when core-source is published" in validate
    bind = _named_steps(job)["Bind published identity from the sealed manifest"]
    assert bind["if"] == "steps.validate.outputs.core-source == 'published'"
    assert "--bind-manifest" in bind["run"]


def test_sase_checkouts_thread_the_explicit_ref_input() -> None:
    jobs = load_ci_workflow()["jobs"]
    for job_name, job in jobs.items():
        if "steps" not in job:
            continue
        for step in job["steps"]:
            if step.get("uses") != "actions/checkout@v4":
                continue
            if step.get("with", {}).get("repository"):
                continue
            assert step.get("with", {}).get("ref") == "${{ inputs.ref }}", job_name


def test_setup_sase_asserts_expected_core_version_in_published_mode() -> None:
    jobs = load_ci_workflow()["jobs"]
    expected = "${{ needs.prepare.outputs.expected-core-version }}"
    for job_name in (*CORE_ARTIFACT_CONSUMER_JOBS, "tutorial-tests"):
        setup = next(
            step
            for step in jobs[job_name]["steps"]
            if step.get("uses") == "./.github/actions/setup-sase"
        )
        assert setup["with"]["expected-core-version"] == expected, job_name


def test_blocking_jobs_report_qualification_evidence_unconditionally() -> None:
    jobs = load_ci_workflow()["jobs"]
    lint = _named_steps(jobs["lint"])
    assert lint["Write qualification evidence"]["if"] == "always()"
    assert "--kind command" in lint["Write qualification evidence"]["run"]
    assert lint["Write qualification evidence"]["env"]["GITHUB_TOKEN"] == (
        "${{ secrets.GITHUB_TOKEN }}"
    )
    assert (
        '--caller-job "${{ inputs.caller-job }}"'
        in (lint["Write qualification evidence"]["run"])
    )
    assert "git rev-parse HEAD" in lint["Write qualification evidence"]["run"]
    assert "preflight-core-version.txt" in lint["Write qualification evidence"]["run"]
    assert lint["Upload qualification evidence"]["if"] == "always()"
    assert (
        lint["Upload qualification evidence"]["with"]["name"]
        == "qualify-evidence-lint-attempt-${{ github.run_attempt }}"
    )
    assert (
        lint["Upload qualification evidence"]["with"]["path"]
        == "${{ runner.temp }}/qualify-evidence/qualify-evidence-lint.json"
    )
    assert lint["Preflight core bindings"]["if"] == (
        "always() && needs.prepare.outputs.core-source == 'published'"
    )
    assert "tools/check_sase_core_rs_bindings" in lint["Preflight core bindings"]["run"]
    assert "preflight-core-version.txt" in lint["Preflight core bindings"]["run"]

    test_steps = _named_steps(jobs["test"])
    assert test_steps["Write qualification evidence"]["if"] == "always()"
    assert "--kind pytest" in test_steps["Write qualification evidence"]["run"]
    assert test_steps["Write qualification evidence"]["env"]["GITHUB_TOKEN"] == (
        "${{ secrets.GITHUB_TOKEN }}"
    )
    assert (
        '--caller-job "${{ inputs.caller-job }}"'
        in (test_steps["Write qualification evidence"]["run"])
    )
    assert (
        "qualify-evidence-test-${{ matrix.python-version }}.json"
        in test_steps["Write qualification evidence"]["run"]
    )
    upload = test_steps["Upload qualification evidence"]
    assert upload["if"] == "always()"
    assert (
        upload["with"]["name"]
        == "qualify-evidence-test-${{ matrix.python-version }}-attempt-${{ github.run_attempt }}"
    )


def test_test_commands_and_plugin_activation_stay_reporting_only() -> None:
    steps = _named_steps(load_ci_workflow()["jobs"]["test"])
    coverage = steps["Run tests (coverage leg)"]
    plain = steps["Run tests"]
    assert coverage["run"] == "just test-cov"
    assert plain["run"] == "just test"
    assert coverage["env"]["PYTEST_ADDOPTS"] == "-p tests._pytest_qualify_evidence"
    assert plain["env"]["PYTEST_ADDOPTS"] == "-p tests._pytest_qualify_evidence"
    session_report = "${{ runner.temp }}/qualify-session.json"
    assert coverage["env"]["SASE_QUALIFY_EVIDENCE_PATH"] == session_report
    assert plain["env"]["SASE_QUALIFY_EVIDENCE_PATH"] == session_report
    assert "env" not in load_ci_workflow()["jobs"]["test"]


def test_advisory_jobs_still_run_for_qualification() -> None:
    jobs = load_ci_workflow()["jobs"]
    for name in (
        "visual-test",
        "perf-floors",
        "tutorial-tests",
        "ace-page-group-isolation",
    ):
        assert name in jobs
    assert jobs["tutorial-tests"]["if"] == (
        "github.event_name != 'pull_request' || inputs.ref"
    )

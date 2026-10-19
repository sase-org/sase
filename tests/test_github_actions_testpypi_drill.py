"""Contract tests for the TestPyPI yank-and-fix-forward drill (phase sase-1my.5).

The drill rehearses the human-only recovery steps on TestPyPI: a dispatch
publishes one throwaway version at a time, a human yanks the broken 0.0.2 in
the TestPyPI UI, and every dispatch asserts the registry state plus the
pip-level consequences (unpinned skips the yank, an exact pin still
resolves). These tests pin the workflow's safety properties: manual-only
triggers, the TestPyPI-only upload URL, the OIDC publisher with no secret,
and the verification tool in the loop.
"""

from __future__ import annotations

import pytest

from tests._github_actions_ci_helpers import _job_run_text
from tests._github_actions_ci_helpers import _load_testpypi_drill_workflow
from tests._github_actions_ci_helpers import _workflow_triggers


pytestmark = pytest.mark.contract

REPO_ROOT_TRIGGERS = ("push", "pull_request", "schedule")


def test_drill_is_manual_only() -> None:
    workflow = _load_testpypi_drill_workflow()
    triggers = _workflow_triggers(workflow)
    assert set(triggers) == {"workflow_dispatch"}
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert inputs["step"]["options"] == [
        "publish-good",
        "publish-broken",
        "publish-fix",
        "verify",
    ]
    assert inputs["expect"]["options"] == ["yanked", "fixed"]
    assert inputs["project"]["default"] == "sase-yank-drill"


def test_drill_runs_are_serialized() -> None:
    workflow = _load_testpypi_drill_workflow()
    assert workflow["concurrency"]["group"] == "testpypi-drill"
    assert workflow["concurrency"]["cancel-in-progress"] is False


def test_publish_uses_the_testpypi_publisher_and_no_secret() -> None:
    workflow = _load_testpypi_drill_workflow()
    job = workflow["jobs"]["publish"]
    assert job["environment"] == "testpypi"
    assert job["permissions"]["id-token"] == "write"
    run_text = _job_run_text(job)
    assert "secrets." not in run_text


def test_publish_never_touches_real_pypi() -> None:
    import pathlib

    raw = (
        pathlib.Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "testpypi-drill.yml"
    ).read_text()
    assert "https://test.pypi.org/legacy/" in raw
    assert "upload.pypi.org" not in raw
    assert "https://pypi.org/legacy/" not in raw


def test_publish_builds_a_throwaway_package_with_a_broken_middle() -> None:
    workflow = _load_testpypi_drill_workflow()
    run_text = _job_run_text(workflow["jobs"]["publish"])
    assert "publish-good" in run_text
    assert "publish-broken" in run_text
    assert "publish-fix" in run_text
    assert "0.0.1" in run_text
    assert "0.0.2" in run_text
    assert "0.0.3" in run_text
    assert "sase-yank-drill-does-not-exist" in run_text
    assert "uv build" in run_text
    assert "twine check" in run_text
    publish_step = next(
        step
        for step in workflow["jobs"]["publish"]["steps"]
        if step.get("name") == "Publish to TestPyPI"
    )
    assert publish_step["with"]["repository-url"] == "https://test.pypi.org/legacy/"
    assert publish_step["with"]["skip-existing"] is True


def test_verify_asserts_the_registry_state_with_the_tool() -> None:
    workflow = _load_testpypi_drill_workflow()
    job = workflow["jobs"]["verify"]
    run_text = _job_run_text(job)
    assert "tools/check_testpypi_drill" in run_text
    assert "uv run --no-project --with packaging" in run_text


def test_verify_proves_unpinned_skips_the_yank_and_pins_survive() -> None:
    workflow = _load_testpypi_drill_workflow()
    job = workflow["jobs"]["verify"]
    assert job["env"]["TESTPYPI_INDEX"] == "https://test.pypi.org/simple/"
    run_text = _job_run_text(job)
    assert "pip download" in run_text
    assert "--only-binary" in run_text
    assert "==0.0.2" in run_text


def test_verify_needs_publish_but_survives_a_skip() -> None:
    workflow = _load_testpypi_drill_workflow()
    job = workflow["jobs"]["verify"]
    assert job["needs"] == "publish"
    assert "needs.publish.result" in job["if"]


def test_drill_jobs_carry_timeouts() -> None:
    workflow = _load_testpypi_drill_workflow()
    for name in ("publish", "verify"):
        assert workflow["jobs"][name]["timeout-minutes"] >= 10

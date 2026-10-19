from __future__ import annotations

import pytest

from tests._github_actions_ci_helpers import _job_run_text
from tests._github_actions_ci_helpers import _load_release_workflow
from tests._github_actions_ci_helpers import _workflow_triggers


pytestmark = pytest.mark.contract


def test_release_dispatch_modes_and_no_push_or_schedule() -> None:
    workflow = _load_release_workflow()
    triggers = _workflow_triggers(workflow)

    assert "push" not in triggers
    assert "schedule" not in triggers
    assert set(triggers) == {"workflow_dispatch"}
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert inputs["mode"] == {
        "description": "Train mode",
        "type": "choice",
        "required": True,
        "default": "rehearse",
        "options": ["release", "resume", "rehearse"],
    }
    assert inputs["core_version"]["required"] is False
    assert inputs["rebuild"] == {
        "description": "Allow a second sealed generation at the same tag",
        "type": "boolean",
        "required": False,
        "default": False,
    }


def test_release_concurrency_never_cancels() -> None:
    workflow = _load_release_workflow()

    assert workflow["concurrency"] == {
        "group": "release-${{ github.ref }}",
        "cancel-in-progress": False,
    }


def test_release_job_graph_and_mode_gates() -> None:
    workflow = _load_release_workflow()
    jobs = workflow["jobs"]

    assert set(jobs) == {"identity", "build", "stash", "not-yet-qualified"}
    assert jobs["build"]["needs"] == "identity"
    assert jobs["stash"]["needs"] == ["identity", "build"]
    assert jobs["stash"]["if"] == "${{ inputs.mode == 'release' }}"
    assert (
        jobs["not-yet-qualified"]["if"]
        == "${{ inputs.mode == 'release' || inputs.mode == 'resume' }}"
    )


def test_release_identity_asserts_source_and_version_match() -> None:
    workflow = _load_release_workflow()
    run_text = _job_run_text(workflow["jobs"]["identity"])

    assert "refs/tags/v*" in run_text
    assert "rehearse mode requires a branch ref" in run_text
    assert "peels to" in run_text
    assert "pyproject.toml" in run_text
    assert "__version__" in run_text
    assert "GITHUB_OUTPUT" in run_text


def test_release_build_checks_dist_set_and_seals() -> None:
    workflow = _load_release_workflow()
    run_text = _job_run_text(workflow["jobs"]["build"])

    assert "uv build" in run_text
    assert "twine check" in run_text
    assert "exactly one wheel plus one sdist" in run_text
    assert "release_candidate core-files" in run_text
    assert "release_candidate core-suffixes" in run_text
    assert "release_candidate seal" in run_text
    assert "release_candidate verify" in run_text
    assert "core_version override is rehearse-only" in run_text


def test_release_stash_refuses_without_draft_or_rebuild() -> None:
    workflow = _load_release_workflow()
    run_text = _job_run_text(workflow["jobs"]["stash"])

    assert "is missing or is not a draft" in run_text
    assert "already has a sealed generation" in run_text
    assert "rebuild: true" in run_text
    assert "gh release upload" in run_text


def test_release_mode_cannot_succeed_without_later_evidence() -> None:
    workflow = _load_release_workflow()
    run_text = _job_run_text(workflow["jobs"]["not-yet-qualified"])

    assert "not yet qualified" in run_text
    assert "exit 1" in run_text

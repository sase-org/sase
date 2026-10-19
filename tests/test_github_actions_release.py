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
    assert inputs["probe"] == {
        "description": "Rehearse-only fault injection for the exercise legs",
        "type": "choice",
        "required": False,
        "default": "none",
        "options": ["none", "break-macos"],
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

    assert set(jobs) == {
        "identity",
        "build",
        "stash",
        "exercise-legs",
        "exercise",
        "not-yet-qualified",
    }
    assert jobs["build"]["needs"] == "identity"
    assert jobs["stash"]["needs"] == ["identity", "build"]
    assert jobs["stash"]["if"] == "${{ inputs.mode == 'release' }}"
    assert jobs["exercise-legs"]["needs"] == ["identity", "build"]
    assert (
        jobs["exercise-legs"]["if"]
        == "${{ inputs.mode == 'release' || inputs.mode == 'rehearse' }}"
    )
    assert jobs["exercise"]["needs"] == ["identity", "exercise-legs"]
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


def test_release_exercise_matrix_covers_os_and_artifact() -> None:
    workflow = _load_release_workflow()
    legs = workflow["jobs"]["exercise-legs"]

    assert legs["runs-on"] == "${{ matrix.os }}"
    assert legs["strategy"]["fail-fast"] is False
    assert legs["strategy"]["matrix"] == {
        "os": ["ubuntu-latest", "macos-latest"],
        "artifact": ["wheel", "sdist"],
    }
    assert legs["env"] == {"UV_NO_CACHE": "1"}


def test_release_exercise_refuses_probes_outside_rehearse() -> None:
    workflow = _load_release_workflow()
    run_text = _job_run_text(workflow["jobs"]["exercise-legs"])

    assert "is rehearse-only" in run_text
    assert "exit 1" in run_text


def test_release_exercise_verifies_digests_before_install() -> None:
    workflow = _load_release_workflow()
    run_text = _job_run_text(workflow["jobs"]["exercise-legs"])

    digest_at = run_text.index("digest mismatch")
    install_at = run_text.index("exercise_release run-leg")
    assert digest_at < install_at
    assert "sha256" in run_text


def test_release_exercise_isolates_the_leg_environment() -> None:
    workflow = _load_release_workflow()
    run_text = _job_run_text(workflow["jobs"]["exercise-legs"])

    for variable in (
        "HOME=$EX_HOME",
        "SASE_HOME=$EX_HOME",
        "XDG_CONFIG_HOME=",
        "XDG_DATA_HOME=",
        "XDG_CACHE_HOME=",
        "UV_TOOL_DIR=",
        "UV_TOOL_BIN_DIR=",
    ):
        assert variable in run_text


def test_release_exercise_upgrades_from_previous_on_wheel_legs() -> None:
    workflow = _load_release_workflow()
    legs = workflow["jobs"]["exercise-legs"]
    run_text = _job_run_text(legs)

    assert "UPGRADE_NO_INSTALLABLE_PREVIOUS" in run_text
    assert "UPGRADE_NMINUS1_UNAVAILABLE" in run_text
    assert "--dry-run" in run_text
    assert "--previous-version" in run_text
    prev_steps = [step for step in legs["steps"] if step.get("id") == "prev"]
    assert len(prev_steps) == 1
    assert prev_steps[0]["if"] == "matrix.artifact == 'wheel'"


def test_release_exercise_leg_uploads_evidence() -> None:
    workflow = _load_release_workflow()
    legs = workflow["jobs"]["exercise-legs"]
    uploads = [
        step
        for step in legs["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact")
    ]

    assert len(uploads) == 1
    assert (
        uploads[0]["with"]["name"] == "exercise-${{ matrix.os }}-${{ matrix.artifact }}"
    )
    assert uploads[0]["if"] == "always()"


def test_release_exercise_summary_merges_legs_into_one_observation() -> None:
    workflow = _load_release_workflow()
    summary = workflow["jobs"]["exercise"]
    run_text = _job_run_text(summary)

    assert "exercise_release merge" in run_text
    assert "release_candidate observe" in run_text
    assert "--kind exercise" in run_text
    assert "exercise red" in run_text
    assert "exit 1" in run_text

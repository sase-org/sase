from __future__ import annotations

import re

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
    assert inputs["probe_core_version"] == {
        "description": "Rehearse-only probe core version, tested but never sealed",
        "type": "string",
        "required": False,
        "default": "",
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
        "qualify-prepare",
        "qualify-ci",
        "qualify",
        "publish",
        "confirm-install",
        "confirm",
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
    qualify_gate = "${{ inputs.mode == 'release' || inputs.mode == 'rehearse' }}"
    assert jobs["qualify-prepare"]["needs"] == ["identity", "build"]
    assert jobs["qualify-prepare"]["if"] == qualify_gate
    assert jobs["qualify-ci"]["needs"] == "qualify-prepare"
    assert jobs["qualify-ci"]["if"] == qualify_gate
    assert jobs["qualify"]["needs"] == ["qualify-prepare", "qualify-ci"]
    assert (
        jobs["qualify"]["if"]
        == "${{ always() && (inputs.mode == 'release' || inputs.mode == 'rehearse') }}"
    )
    # Qualification never waits for the exercise legs: the qualifier reads
    # completed jobs and the publish gate joins both verdicts later.
    assert "exercise" not in jobs["qualify"]["needs"]
    assert "exercise-legs" not in jobs["qualify"]["needs"]
    train_gate = (
        "${{ always() && (inputs.mode == 'release' "
        "|| inputs.mode == 'resume' || inputs.mode == 'rehearse') }}"
    )
    assert jobs["publish"]["needs"] == ["identity", "build", "qualify", "exercise"]
    assert jobs["publish"]["if"] == train_gate
    assert jobs["confirm-install"]["needs"] == ["identity", "publish"]
    assert jobs["confirm-install"]["if"] == (
        "${{ inputs.mode == 'release' || inputs.mode == 'resume' }}"
    )
    assert jobs["confirm"]["needs"] == ["identity", "publish", "confirm-install"]
    assert jobs["confirm"]["if"] == (
        "${{ inputs.mode == 'release' || inputs.mode == 'resume' }}"
    )


def test_release_resume_never_rebuilds_or_requalifies() -> None:
    workflow = _load_release_workflow()
    jobs = workflow["jobs"]

    for name in ("qualify-prepare", "qualify-ci"):
        gate = jobs[name]["if"]
        assert "resume" not in gate
        assert "rehearse" in gate
    assert "resume" not in jobs["qualify"]["if"]
    assert "rehearse" in jobs["qualify"]["if"]
    assert "resume" in jobs["publish"]["if"]
    assert "resume" in jobs["confirm-install"]["if"]
    assert "resume" in jobs["confirm"]["if"]
    assert "rehearse" not in jobs["confirm-install"]["if"]
    assert "rehearse" not in jobs["confirm"]["if"]
    publish_text = _job_run_text(jobs["publish"])
    assert "resume requires passing qualification and exercise evidence" in publish_text


def test_release_identity_asserts_source_and_version_match() -> None:
    workflow = _load_release_workflow()
    run_text = _job_run_text(workflow["jobs"]["identity"])

    assert "refs/tags/v*" in run_text
    assert "rehearse mode requires a branch ref" in run_text
    assert "peels to" in run_text
    assert "pyproject.toml" in run_text
    assert "__version__" in run_text
    assert "GITHUB_OUTPUT" in run_text
    version_command = re.search(
        r'''py_version="\$\(python3 -c '([^']+)'\)"''', run_text
    )
    assert version_command is not None
    compile(version_command.group(1), "release identity version command", "exec")


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


def test_release_publish_runs_the_promotion_predicate() -> None:
    workflow = _load_release_workflow()
    run_text = _job_run_text(workflow["jobs"]["publish"])

    assert "release_candidate evaluate" in run_text
    assert "--observations publish-work/observations.json" in run_text
    assert "PUBLISH_MISSING_ASSET" in run_text
    assert "PUBLISH_STASH_MISMATCH" in run_text
    assert "staged digests match the sealed manifest" in run_text


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


def test_release_exercise_resolver_uses_the_subcommand() -> None:
    workflow = _load_release_workflow()
    legs = workflow["jobs"]["exercise-legs"]
    run_text = _job_run_text(legs)

    assert "tools/exercise_release previous-version" in run_text
    assert "--candidate-version" in run_text
    assert "previous_version" in run_text
    assert "GITHUB_OUTPUT" in run_text
    assert "UPGRADE_NMINUS1_UNAVAILABLE" in run_text
    all_runs = "\n".join(
        _job_run_text(job)
        for job in workflow["jobs"].values()
        if isinstance(job.get("steps"), list)
    )
    assert "--system" not in all_runs


def test_release_exercise_upgrades_from_previous_on_wheel_legs() -> None:
    workflow = _load_release_workflow()
    legs = workflow["jobs"]["exercise-legs"]
    run_text = _job_run_text(legs)

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


def test_release_qualify_prepare_binds_the_sealed_manifest() -> None:
    workflow = _load_release_workflow()
    prepare = workflow["jobs"]["qualify-prepare"]
    run_text = _job_run_text(prepare)

    assert "candidate-manifest.json is missing from candidate-build" in run_text
    assert "write_qualification_evidence" in run_text
    assert "--bind-manifest" in run_text
    assert "sealed sha" in run_text
    assert "sealed repository" in run_text
    assert "sealed manifest carries no core_version" in run_text
    assert "release-qualification.json" in run_text
    assert "probe_core_version is rehearse-only" in run_text
    for output in (
        "sha",
        "candidate-id",
        "generation",
        "core-version",
        "tested-core-version",
        "inventory-digest",
        "probe-core-version",
    ):
        assert output in prepare["outputs"]
    assert "needs.identity.outputs.sha" in str(prepare["steps"])
    bind = next(step for step in prepare["steps"] if step.get("id") == "bind")
    assert bind["env"]["IDENTITY_SHA"] == "${{ needs.identity.outputs.sha }}"


def test_release_qualify_ci_calls_published_core() -> None:
    workflow = _load_release_workflow()
    qualify_ci = workflow["jobs"]["qualify-ci"]

    assert qualify_ci["uses"] == "./.github/workflows/ci.yml"
    assert qualify_ci["with"] == {
        "ref": "${{ needs.qualify-prepare.outputs.sha }}",
        "core-source": "published",
        "core-version": "${{ needs.qualify-prepare.outputs.core-version }}",
        "manifest-artifact": "candidate-build",
        "probe-core-version": "${{ needs.qualify-prepare.outputs.probe-core-version }}",
        "caller-job": "qualify-ci",
    }
    assert qualify_ci["secrets"] == "inherit"
    assert qualify_ci["permissions"] == {"contents": "read", "actions": "read"}
    assert "runs-on" not in qualify_ci


def test_release_qualify_fetches_scoped_attempt_aware_facts() -> None:
    workflow = _load_release_workflow()
    qualify = workflow["jobs"]["qualify"]
    run_text = _job_run_text(qualify)

    assert "collect_qualification_jobs fetch-evidence" in run_text
    assert '--attempts "$attempt"' in run_text
    assert "--jobs-dir jobs-pages" in run_text
    assert '--artifacts-file "artifacts-pages/run.json"' in run_text
    assert "attempts/${n}/artifacts" not in run_text
    assert "tools/collect_qualification_jobs" in run_text
    assert "--caller-job qualify-ci" in run_text
    assert "--attempt-jobs" in run_text
    assert "--attempt-artifacts" in run_text
    assert "--evidence-root evidence" in run_text
    assert "release_candidate qualify" in run_text
    assert "--manifest candidate/candidate-manifest.json" in run_text
    assert "--jobs qualify-work/jobs.json" in run_text
    assert "--evidence-dir evidence" in run_text
    assert '--run-id "$run"' in run_text
    assert '--attempt "$attempt"' in run_text
    assert '--out "$asset"' in run_text
    assert "candidate-gen${generation}-qualification-run" in run_text
    assert "disagrees with its canonical filename" in run_text


def test_release_qualify_treats_fetch_failures_as_typed_red() -> None:
    workflow = _load_release_workflow()
    run_text = _job_run_text(workflow["jobs"]["qualify"])

    assert "failed to fetch qualify-ci facts" in run_text
    assert "qualification fact fetch failed" in run_text
    assert "collect_qualification_jobs refused" in run_text


def test_release_qualify_persists_red_observations_before_failing() -> None:
    workflow = _load_release_workflow()
    qualify = workflow["jobs"]["qualify"]
    run_text = _job_run_text(qualify)
    by_name = {step["name"]: step for step in qualify["steps"] if "name" in step}

    assert "exit 0" in run_text
    assert by_name["Upload the qualification observation"]["if"] == (
        "${{ always() && inputs.mode == 'rehearse' }}"
    )
    assert by_name["Attach the qualification observation to the draft"]["if"] == (
        "${{ always() && inputs.mode == 'release' }}"
    )
    assert "qualification observation was not written" in run_text
    assert "conflicting qualification observation" in run_text
    assert "identical qualification observation is already attached" in run_text
    assert by_name["Fail the verdict when qualification is red"]["if"] == "always()"
    assert "exit 1" in run_text
    assert "steps.evaluate.outputs" in str(qualify["outputs"])


def test_release_qualify_uploads_the_canonical_asset_filename() -> None:
    workflow = _load_release_workflow()
    qualify = workflow["jobs"]["qualify"]
    by_name = {step["name"]: step for step in qualify["steps"] if "name" in step}

    upload = by_name["Upload the qualification observation"]
    assert upload["with"]["path"] == "${{ steps.evaluate.outputs.observation }}"
    assert upload["with"]["name"] == (
        "qualification-observation-run-${{ steps.evaluate.outputs.run-id }}"
        "-attempt-${{ steps.evaluate.outputs.attempt }}"
    )
    attach = by_name["Attach the qualification observation to the draft"]
    assert attach["env"]["ASSET"] == "${{ steps.evaluate.outputs.observation }}"
    assert 'gh release upload "${TAG}" "$ASSET"' in attach["run"]


def test_release_qualify_probe_never_qualifies() -> None:
    workflow = _load_release_workflow()
    qualify = workflow["jobs"]["qualify"]
    run_text = _job_run_text(qualify)
    steps_text = str(qualify["steps"])

    assert "probe core" in run_text
    assert "never qualifies the intended" in run_text
    assert "Intended core" in run_text
    assert "tested core" in run_text
    assert "needs.qualify-prepare.outputs.probe-core-version" in steps_text
    assert "needs.qualify-prepare.outputs.tested-core-version" in steps_text
    assert "needs.qualify-prepare.outputs.core-version" in steps_text
    evaluate = next(step for step in qualify["steps"] if step.get("id") == "evaluate")
    assert (
        evaluate["env"]["TESTED_CORE"]
        == "${{ needs.qualify-prepare.outputs.tested-core-version }}"
    )


def test_release_qualify_exposes_verdict_and_locator() -> None:
    workflow = _load_release_workflow()
    qualify = workflow["jobs"]["qualify"]

    assert qualify["outputs"] == {
        "verdict": "${{ steps.evaluate.outputs.verdict }}",
        "observation": "${{ steps.evaluate.outputs.observation }}",
        "token": "${{ steps.evaluate.outputs.token }}",
        "run-id": "${{ steps.evaluate.outputs.run-id }}",
        "attempt": "${{ steps.evaluate.outputs.attempt }}",
        "candidate-id": "${{ steps.evaluate.outputs.candidate-id }}",
        "generation": "${{ steps.evaluate.outputs.generation }}",
        "intended-core-version": "${{ steps.evaluate.outputs.intended-core-version }}",
        "tested-core-version": "${{ steps.evaluate.outputs.tested-core-version }}",
    }


def test_release_qualify_permissions_scope_the_draft_attach() -> None:
    workflow = _load_release_workflow()
    jobs = workflow["jobs"]

    assert jobs["qualify-prepare"]["permissions"] == {
        "contents": "read",
        "actions": "read",
    }
    assert jobs["qualify"]["permissions"] == {
        "contents": "write",
        "actions": "read",
    }


def test_release_qualify_mounts_the_sealed_candidate() -> None:
    workflow = _load_release_workflow()
    qualify = workflow["jobs"]["qualify"]
    run_text = _job_run_text(qualify)

    assert "needs.qualify-prepare.outputs.sha" in str(qualify["steps"])
    assert "candidate-build" in str(qualify["steps"])
    assert "candidate/candidate-manifest.json" in run_text


def test_release_publish_serializes_resumes_and_plans_uploads() -> None:
    workflow = _load_release_workflow()
    jobs = workflow["jobs"]
    publish = jobs["publish"]

    assert publish["concurrency"] == {
        "group": "publish-${{ github.ref }}",
        "cancel-in-progress": False,
    }
    assert publish["permissions"] == {"contents": "write", "id-token": "write"}
    assert publish["environment"] == "${{ inputs.mode != 'rehearse' && 'pypi' || '' }}"
    run_text = _job_run_text(publish)
    assert "release_candidate publish-plan" in run_text
    assert "release_candidate observe" in run_text
    assert "--kind publication" in run_text
    assert "PUBLISH_CONFLICT" in run_text
    assert "pypa/gh-action-pypi-publish@release/v1" in str(publish["steps"])
    pypi_step = next(
        step
        for step in publish["steps"]
        if step.get("uses", "").startswith("pypa/gh-action-pypi-publish")
    )
    assert pypi_step["with"]["skip-existing"] is False
    assert "attestations" not in str(pypi_step["with"])
    assert "packages-dir" in str(pypi_step["with"])
    assert "verify-only plan" in run_text
    assert "already present on PyPI" in run_text
    assert "publication-observation-run-" in str(publish["steps"])


def test_release_confirm_matrix_proves_the_exact_install() -> None:
    workflow = _load_release_workflow()
    jobs = workflow["jobs"]
    legs = jobs["confirm-install"]

    assert legs["runs-on"] == "${{ matrix.os }}"
    assert legs["strategy"]["fail-fast"] is False
    assert legs["strategy"]["matrix"] == {"os": ["ubuntu-latest", "macos-latest"]}
    run_text = _job_run_text(legs)
    assert "sase==${version}" in run_text
    assert "UV_TOOL_DIR=" in run_text
    assert "UV_TOOL_BIN_DIR=" in run_text
    assert "manifest core" in run_text
    assert "sase core health --json" in run_text
    assert "confirm-install-${{ matrix.os }}" in str(legs["steps"])


def test_release_confirm_never_undrafts_before_every_check() -> None:
    workflow = _load_release_workflow()
    jobs = workflow["jobs"]
    confirm = jobs["confirm"]

    assert confirm["concurrency"] == {
        "group": "publish-${{ github.ref }}",
        "cancel-in-progress": False,
    }
    assert confirm["permissions"] == {"contents": "write"}
    run_text = _job_run_text(confirm)
    undraft_at = run_text.index('gh release edit "${TAG}" --draft=false --latest')
    assert run_text.index("release_candidate confirm") < undraft_at
    assert run_text.index("check_family_install") < undraft_at
    assert run_text.index("--mode exact") < undraft_at
    assert "confirm-install-" in str(confirm["steps"])
    download = next(
        step
        for step in confirm["steps"]
        if "confirm-install-" in str(step.get("with", ""))
    )
    assert "Poll PyPI until every file confirms" in str(
        [step.get("name", "") for step in confirm["steps"]]
    )
    assert download["name"] == "Require the Linux and macOS install evidence"
    assert "PUBLISH_PARTIAL" in run_text
    assert "PUBLISH_CONFLICT: refusing without un-drafting" in run_text
    assert "bounded wait" in run_text or "CDN lag" in run_text
    assert "--kind confirmation" in run_text
    assert "candidate-gen${generation}-confirmation-run" in run_text
    assert "draft tag" in run_text and "refusing to un-draft" in run_text

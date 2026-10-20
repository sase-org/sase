from __future__ import annotations

import pytest

from tests._github_actions_ci_helpers import load_ci_workflow
from tests._github_actions_ci_helpers import load_master_gate_workflow
from tests._github_actions_ci_helpers import workflow_triggers

pytestmark = pytest.mark.contract


def test_ci_workflow_is_pull_request_and_reusable_only() -> None:
    workflow = load_ci_workflow()
    triggers = workflow_triggers(workflow)

    assert set(triggers) == {"pull_request", "workflow_call"}
    assert triggers["pull_request"] == {"branches": ["master"]}
    inputs = triggers["workflow_call"]["inputs"]
    assert inputs["ref"]["default"] == ""
    assert inputs["core-source"]["default"] == "source"
    assert inputs["core-version"]["default"] == ""
    assert inputs["manifest-artifact"]["default"] == "candidate-build"
    assert inputs["probe-core-version"]["default"] == ""
    assert inputs["caller-job"]["default"] == ""
    assert not any(details.get("required", False) for details in inputs.values())
    assert workflow["concurrency"] == {
        "group": (
            "${{ inputs.ref && format('qualify-{0}', inputs.ref) || "
            "format('ci-{0}', github.ref) }}"
        ),
        "cancel-in-progress": "${{ !inputs.ref }}",
    }
    assert workflow["permissions"] == {"contents": "read", "actions": "read"}


def test_lint_job_initializes_sase_home_before_lint() -> None:
    workflow = load_ci_workflow()
    steps = workflow["jobs"]["lint"]["steps"]

    install_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Install dependencies"
    )
    init_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Initialize SASE home"
    )
    lint_index = next(
        index for index, step in enumerate(steps) if step.get("name") == "Lint"
    )

    assert install_index < init_index < lint_index
    init_step = steps[init_index]
    # The drift gate (E4 readable-projection): home init runs outside the
    # checkout with absolute binary paths so the committed project
    # instruction files are never rewritten before `just validate` checks
    # them as committed.
    assert init_step.get("working-directory") == "${{ runner.temp }}"
    assert init_step["run"] == (
        "$GITHUB_WORKSPACE/.venv/bin/sase init memory --no-commit\n"
        "$GITHUB_WORKSPACE/.venv/bin/sase skill init --force\n"
    )


def test_lint_job_never_regenerates_committed_project_files() -> None:
    """No lint-job step may rewrite project memory before validation.

    Any step that runs `sase init memory` or `sase memory init` without
    `--check` must run outside the checkout (a temp working directory with
    absolute binary paths); otherwise it would mask drift in the committed
    project instruction files from the later `just validate` check.
    """

    for workflow in (load_ci_workflow(), load_master_gate_workflow()):
        steps = workflow["jobs"]["lint"]["steps"]
        for step in steps:
            run_text = str(step.get("run", ""))
            if "init memory" not in run_text and "memory init" not in run_text:
                continue
            if "--check" in run_text:
                continue
            assert step.get("working-directory") == "${{ runner.temp }}", (
                f"step {step.get('name')!r} regenerates memory inside the checkout"
            )
            assert "./.venv/bin/sase" not in run_text, (
                f"step {step.get('name')!r} uses a checkout-relative binary path"
            )


def test_lint_job_uses_single_lint_command() -> None:
    workflow = load_ci_workflow()
    steps = workflow["jobs"]["lint"]["steps"]

    assert any(
        step.get("name") == "Lint" and step.get("run") == "just lint" for step in steps
    )
    assert not any(step.get("run") == "just symvision" for step in steps)
    assert not any(step.get("run") == "just toobig" for step in steps)


def test_lint_job_checks_pinned_core_bindings_before_sidecars() -> None:
    """The pinned revision's failure mode must be legible, not a bare AttributeError.

    If sase's source now needs a binding the pin from sase-core-revision.txt
    doesn't provide yet, this must fail with the missing binding names and a
    named remedy, not a generic sidecar or test crash further into the job.
    """
    workflow = load_ci_workflow()
    steps = workflow["jobs"]["lint"]["steps"]

    install_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Install dependencies"
    )
    check_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Check pinned core bindings"
    )
    sidecar_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Bootstrap SDD sidecars"
    )
    assert install_index < check_index < sidecar_index

    run_text = steps[check_index]["run"]
    assert "tools/check_sase_core_rs_bindings" in run_text
    assert "--remedy" in run_text
    assert "sase-core-revision.txt" in run_text
    assert "ratchet-core-revision" in run_text

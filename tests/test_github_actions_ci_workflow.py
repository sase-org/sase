from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests._github_actions_ci_helpers import CORE_ARTIFACT_CONSUMER_JOBS
from tests._github_actions_ci_helpers import REPO_ROOT
from tests._github_actions_ci_helpers import _job_run_text
from tests._github_actions_ci_helpers import _load_ci_workflow
from tests._github_actions_ci_helpers import _workflow_triggers
from tests._test_selection_contexts import ARTIFACT_PREFIX


pytestmark = pytest.mark.contract


def test_ci_workflow_is_pull_request_and_reusable_only() -> None:
    workflow = _load_ci_workflow()
    triggers = _workflow_triggers(workflow)

    assert set(triggers) == {"pull_request", "workflow_call"}
    assert triggers["pull_request"] == {"branches": ["master"]}
    assert triggers["workflow_call"] is None
    assert workflow["concurrency"] == {
        "group": "ci-${{ github.ref }}",
        "cancel-in-progress": True,
    }


def test_lint_job_initializes_sase_home_before_lint() -> None:
    workflow = _load_ci_workflow()
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
    assert steps[init_index]["run"] == (
        "./.venv/bin/sase init memory --no-commit\n"
        "./.venv/bin/sase skill init --force\n"
    )


def test_lint_job_uses_single_lint_command() -> None:
    workflow = _load_ci_workflow()
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
    workflow = _load_ci_workflow()
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


def test_rust_core_is_built_once_and_shared_with_source_based_jobs() -> None:
    workflow = _load_ci_workflow()
    jobs = workflow["jobs"]
    build_core = jobs["build-core"]
    build_steps = build_core["steps"]
    build_run_text = _job_run_text(build_core)

    core_checkouts = [
        step
        for step in build_steps
        if step.get("with", {}).get("repository") == "sase-org/sase-core"
    ]
    assert len(core_checkouts) == 1
    assert core_checkouts[0]["with"]["path"] == "sase-core"
    assert core_checkouts[0]["with"]["ref"] == "${{ steps.core-sha.outputs.sha }}"
    assert "sase-core-revision.txt" in build_run_text
    assert "git -C sase-core rev-parse HEAD" not in build_run_text
    assert build_core["env"] == {
        "CARGO_HTTP_MULTIPLEXING": "false",
        "CARGO_NET_RETRY": "10",
    }
    assert (
        'uvx maturin build --release --out "$GITHUB_WORKSPACE/dist"' in build_run_text
    )
    assert "cargo build --release -p sase_xprompt_lsp" in build_run_text
    assert (
        'install -m 0755 target/release/sase-xprompt-lsp "$GITHUB_WORKSPACE/dist/sase-xprompt-lsp"'
        in build_run_text
    )
    assert not any(
        step.get("with", {}).get("repository") == "sase-org/sase-core"
        for step in build_steps
        if step not in core_checkouts
    )
    upload_step = next(
        step
        for step in build_steps
        if step.get("uses") == "actions/upload-artifact@v4"
        and step.get("with", {}).get("name") == "sase-core-wheel"
    )
    assert upload_step["with"]["path"] == "dist/"
    assert (
        "maturin build --release" in build_run_text
        and "cargo build --release -p sase_xprompt_lsp" in build_run_text
    )

    for job_name in CORE_ARTIFACT_CONSUMER_JOBS:
        job = jobs[job_name]
        assert job["needs"] == "build-core"
        assert any(
            step.get("uses") == "./.github/actions/setup-sase" for step in job["steps"]
        )
        assert not any(
            step.get("with", {}).get("repository") == "sase-org/sase-core"
            for step in job["steps"]
        )
        assert not any(
            step.get("uses") == "dtolnay/rust-toolchain@stable" for step in job["steps"]
        )
        assert not any("rust-check" in step.get("run", "") for step in job["steps"])


def test_build_core_resolves_pinned_revision_before_checking_out_sase_core() -> None:
    """A pinned source-of-truth: not sase-core's HEAD at build time.

    An unpinned checkout let an ordinary sase-core push redden sase master
    with no sase commit involved, and made two runs of the same sase SHA
    build different Rust cores.
    """
    build_core = _load_ci_workflow()["jobs"]["build-core"]
    steps = build_core["steps"]

    resolve_index = next(
        index for index, step in enumerate(steps) if step.get("id") == "core-sha"
    )
    checkout_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("with", {}).get("repository") == "sase-org/sase-core"
    )
    assert resolve_index < checkout_index

    resolve_run = steps[resolve_index]["run"]
    assert "sase-core-revision.txt" in resolve_run
    assert "^[0-9a-f]{40}$" in resolve_run
    assert "git ls-remote" not in resolve_run


def test_redundant_lanes_are_consolidated_without_dropping_commands() -> None:
    workflow = _load_ci_workflow()
    jobs = workflow["jobs"]

    assert {
        "fmt-md-check",
        "build",
        "bead-backend",
        "phase7-perf-floor",
        "launch-perf-floor",
        "view-hints-perf-floor",
        "install-smoke",
    }.isdisjoint(jobs)

    lint_steps = jobs["lint"]["steps"]
    assert any(step.get("run") == "just fmt-md-check" for step in lint_steps)
    assert any(step.get("run") == "just build-check" for step in lint_steps)
    assert any(
        step.get("uses") == "actions/cache@v4"
        and step.get("with", {}).get("path") == "node_modules"
        and "hashFiles('package-lock.json')" in step.get("with", {}).get("key", "")
        for step in lint_steps
    )

    perf_steps = jobs["perf-floors"]["steps"]
    commands = {
        step.get("run") for step in perf_steps if isinstance(step.get("run"), str)
    }
    assert {
        ".venv/bin/sase core health --json",
        "just phase7-perf-check",
        "just launch-perf-check",
        "just view-hints-perf-check",
        "just bead-perf-smoke",
    } <= commands
    floor_steps = [
        step for step in perf_steps if step.get("run", "").startswith("just ")
    ]
    assert all(step.get("if") == "always()" for step in floor_steps)
    artifact_names = {
        step.get("with", {}).get("name")
        for step in perf_steps
        if step.get("uses") == "actions/upload-artifact@v4"
    }
    assert {
        "phase7-perf-floor-report",
        "launch-perf-floor-report",
        "view-hints-perf-floor-report",
        "bead-perf-smoke",
    } <= artifact_names


def test_test_job_timeout_allows_slow_3_12_leg() -> None:
    workflow = _load_ci_workflow()
    assert workflow["jobs"]["test"]["timeout-minutes"] == 90


def test_test_job_only_collects_coverage_on_3_12_leg() -> None:
    workflow = _load_ci_workflow()
    steps = workflow["jobs"]["test"]["steps"]

    coverage_step = next(
        step for step in steps if step.get("name") == "Run tests (coverage leg)"
    )
    assert coverage_step["if"] == "matrix.python-version == '3.12'"
    assert coverage_step["run"] == "just test-cov"

    cost_step = next(
        step
        for step in steps
        if step.get("name") == "Run tests" and step.get("run") == "just test-cost"
    )
    assert cost_step["if"] == "matrix.python-version == '3.13'"

    plain_step = next(
        step
        for step in steps
        if step.get("name") == "Run tests" and step.get("run") == "just test"
    )
    assert plain_step["if"] == "matrix.python-version == '3.14'"


def test_contexts_job_publishes_the_per_test_database_on_master_only() -> None:
    """The scoped lane's ground-truth source only exists if CI publishes it.

    Master-only because baselines are resolved as ancestors of an agent's
    ``HEAD``: a per-PR database is one nobody would ever look up. The artifact
    name carries the commit SHA because the local cache is keyed by it, and
    asserting the prefix against the consumer's own constant keeps the producer
    and consumer from drifting apart silently.
    """
    job = _load_ci_workflow()["jobs"]["coverage-contexts"]
    fetcher_text = (REPO_ROOT / "tools" / "fetch_coverage_contexts").read_text(
        encoding="utf-8"
    )

    assert job["if"] == "github.ref == 'refs/heads/master'"
    assert any(step.get("run") == "just test-contexts" for step in job["steps"])
    assert 'WORKFLOW = "full.yml"' in fetcher_text

    step = next(
        step
        for step in job["steps"]
        if step.get("name") == "Upload coverage contexts database"
    )
    assert step["uses"] == "actions/upload-artifact@v4"
    assert step["with"]["name"] == f"{ARTIFACT_PREFIX}-${{{{ github.sha }}}}"
    assert step["with"]["path"] == ".coverage"
    # `always()` so a red suite still publishes: contexts are unioned into the
    # selection, so partial ground truth is strictly better than none.
    assert step["if"] == "always()"


def test_contexts_job_does_not_slow_the_per_pr_coverage_leg() -> None:
    """Contexts cost 68s and 889 MB when folded into the branch-coverage leg."""
    steps = _load_ci_workflow()["jobs"]["test"]["steps"]

    assert not any(
        "contexts" in str(step.get("with", {}).get("name", "")) for step in steps
    )
    assert not any("test-contexts" in str(step.get("run", "")) for step in steps)


def test_contexts_databases_are_portable_between_machines() -> None:
    """The artifact is read on a different checkout than the one that wrote it."""
    config = (REPO_ROOT / "coverage_contexts.toml").read_text()

    assert "relative_files = true" in config
    # Branch coverage times per-test contexts is the 906 MB artifact.
    assert "branch = false" in config


def test_release_branch_core_floor_lane_uses_published_floor() -> None:
    workflow = _load_ci_workflow()
    job = workflow["jobs"]["release-core-floor-smoke"]

    assert job["if"] == (
        "github.event_name == 'pull_request' && "
        "github.event.pull_request.head.ref == "
        "'release-please--branches--master'"
    )
    assert "needs" not in job
    assert job["timeout-minutes"] == 30
    assert not any(
        step.get("uses") == "./.github/actions/setup-sase" for step in job["steps"]
    )
    assert not any(
        step.get("with", {}).get("name") == "sase-core-wheel"
        for step in job["steps"]
        if step.get("uses") == "actions/download-artifact@v4"
    )

    install_just_index = next(
        index
        for index, step in enumerate(job["steps"])
        if step.get("name") == "Install just"
    )
    contract_index = next(
        index
        for index, step in enumerate(job["steps"])
        if step.get("name") == "Run contract set"
    )
    assert install_just_index < contract_index

    run_text = _job_run_text(job)
    assert "just-1.50.0-x86_64-unknown-linux-musl.tar.gz" in run_text
    assert (
        "27e011cd6328fadd632e59233d2cf5f18460b8a8c4269acd324c1a8669f34db0" in run_text
    )
    assert "sudo install -m 0755 /tmp/just /usr/local/bin/just" in run_text
    assert "just --version" in run_text
    assert (
        "tools/smoke_sase_core_rs_telemetry --print-minimum pyproject.toml" in run_text
    )
    assert '"sase-core-rs==${core_minimum}"' in run_text
    assert 'importlib.metadata.version("sase-core-rs")' in run_text
    assert "actual != expected" in run_text
    assert "tools/check_sase_core_rs_bindings" in run_text
    assert "tools/validate_sase_core_rs" in run_text
    assert "tools/smoke_sase_core_rs_telemetry" in run_text
    assert "tools/smoke_sase_core_rs_at_reference_file_gate" in run_text
    assert "tools/smoke_sase_core_rs_bead_resolution" in run_text
    assert "tools/smoke_sase_core_rs_feature_flag_state" in run_text
    assert "tools/smoke_sase_core_rs_plan_header" in run_text
    assert "tools/smoke_sase_core_rs_glossary_line_break" in run_text
    assert "mapfile -t contract_files < tests/contract_manifest.txt" in run_text
    assert "python -m pytest -m contract" in run_text


def test_ci_and_master_gate_never_run_the_diff_scoped_test_lane() -> None:
    """Both gates always exercise exhaustive lanes; the scoped lane is a local, agent-only fast path.

    A diff-scoped selection is a heuristic backstopped by CI (and now the
    master gate) running everything on every push; neither gate may be the
    thing that skips tests.
    """
    for workflow_name in ("ci.yml", "master-gate.yml", "full.yml"):
        workflow_text = (
            REPO_ROOT / ".github" / "workflows" / workflow_name
        ).read_text()

        assert "test-scoped" not in workflow_text
        assert "run_pytest scoped" not in workflow_text
        assert "just check\n" not in workflow_text


def test_visual_suite_runs_only_in_dedicated_job() -> None:
    workflow = _load_ci_workflow()
    jobs = workflow["jobs"]

    assert not any(
        "VISUAL" in name
        for step in jobs["test"]["steps"]
        for name in step.get("env", {})
    )
    assert not any(
        "sase-visual" in step.get("with", {}).get("path", "")
        for step in jobs["test"]["steps"]
    )
    assert any(
        step.get("run") == "just test-visual" for step in jobs["visual-test"]["steps"]
    )


def test_ace_page_group_isolation_job_runs_dedicated_lane() -> None:
    steps = _load_ci_workflow()["jobs"]["ace-page-group-isolation"]["steps"]

    assert any(step.get("run") == "just test-ace-page-group-isolated" for step in steps)


def test_perf_floors_job_runs_slow_lane() -> None:
    workflow = _load_ci_workflow()
    steps = workflow["jobs"]["perf-floors"]["steps"]

    slow_step = next(step for step in steps if step.get("run") == "just test-slow")
    assert slow_step["if"] == "always()"


def test_docs_build_once_per_event_and_deploys_are_serialized() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    ci = _load_ci_workflow()
    docs_build = ci["jobs"]["docs-build"]
    assert docs_build["if"] == (
        "github.event_name == 'pull_request' && "
        "github.event.pull_request.head.ref != "
        "'release-please--branches--master'"
    )
    assert any(
        step.get("uses") == "actions/cache@v4"
        and step.get("with", {}).get("path") == "~/.cache/ms-playwright"
        for step in docs_build["steps"]
    )

    deploy_path = repo_root / ".github" / "workflows" / "docs-deploy.yml"
    deploy = yaml.safe_load(deploy_path.read_text())
    assert deploy["concurrency"] == {
        "group": "docs-deploy",
        "cancel-in-progress": False,
    }
    assert any(
        step.get("uses") == "actions/cache@v4"
        and step.get("with", {}).get("path") == "~/.cache/ms-playwright"
        for step in deploy["jobs"]["deploy"]["steps"]
    )


def test_core_artifact_consumer_jobs_run_just_recipes_after_setup() -> None:
    """The export matters only because later steps re-enter `_setup`."""
    jobs = _load_ci_workflow()["jobs"]

    for job_name in CORE_ARTIFACT_CONSUMER_JOBS:
        steps = jobs[job_name]["steps"]
        setup_index = next(
            index
            for index, step in enumerate(steps)
            if step.get("uses") == "./.github/actions/setup-sase"
        )
        assert any(
            "just " in step.get("run", "") for step in steps[setup_index + 1 :]
        ), f"{job_name} runs no just recipe after setup-sase"

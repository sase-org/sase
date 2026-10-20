from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests._github_actions_ci_helpers import CORE_ARTIFACT_CONSUMER_JOBS
from tests._github_actions_ci_helpers import REPO_ROOT
from tests._github_actions_ci_helpers import _job_run_text
from tests._github_actions_ci_helpers import _load_build_core_workflow
from tests._github_actions_ci_helpers import _load_ci_workflow
from tests._github_actions_ci_helpers import _load_telemetry_workflow
from tests._github_actions_ci_helpers import _workflow_triggers
from tests._test_selection_contexts import ARTIFACT_PREFIX
from tests._test_shards import SHARD_TIMINGS_ARTIFACT_NAME


pytestmark = pytest.mark.contract


def test_ci_workflow_is_pull_request_and_reusable_only() -> None:
    workflow = _load_ci_workflow()
    triggers = _workflow_triggers(workflow)

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
    from tests._github_actions_ci_helpers import _load_master_gate_workflow

    for workflow in (_load_ci_workflow(), _load_master_gate_workflow()):
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


def test_ci_build_core_job_delegates_to_the_reusable_build_core_workflow() -> None:
    """ci.yml builds the wheel through one shared reusable workflow, not inline steps.

    telemetry.yml needs the identical artifact from the identical steps; a
    `uses:` call is what keeps the two from drifting into copies.
    """
    build_core = _load_ci_workflow()["jobs"]["build-core"]

    assert build_core["uses"] == "./.github/workflows/build-core.yml"
    assert build_core["needs"] == "prepare"
    assert build_core["with"] == {
        "ref": "${{ inputs.ref }}",
        "core-source": "${{ needs.prepare.outputs.core-source }}",
        "core-version": "${{ needs.prepare.outputs.core-version }}",
        "manifest-artifact": "${{ needs.prepare.outputs.manifest-artifact }}",
        "probe-core-version": "${{ inputs.probe-core-version }}",
    }


def test_rust_core_is_built_once_and_shared_with_source_based_jobs() -> None:
    jobs = _load_ci_workflow()["jobs"]
    build_core = _load_build_core_workflow()["jobs"]["build-core"]
    build_steps = build_core["steps"]
    build_run_text = _job_run_text(build_core)

    core_checkouts = [
        step
        for step in build_steps
        if step.get("with", {}).get("repository") == "sase-org/sase-core"
    ]
    assert len(core_checkouts) == 2
    source_checkout = next(
        step
        for step in core_checkouts
        if "core-sha" in str(step.get("with", {}).get("ref", ""))
    )
    published_checkout = next(
        step
        for step in core_checkouts
        if "core-sha" not in str(step.get("with", {}).get("ref", ""))
    )
    assert source_checkout["with"]["path"] == "sase-core"
    assert source_checkout["with"]["ref"] == "${{ steps.core-sha.outputs.sha }}"
    assert source_checkout.get("if") == "inputs.core-source == 'source'"
    assert published_checkout["with"]["path"] == "sase-core"
    assert (
        published_checkout["with"]["ref"]
        == "v${{ steps.resolve-core.outputs.version }}"
    )
    assert published_checkout.get("if") == "inputs.core-source == 'published'"
    assert "sase-core-revision.txt" in build_run_text
    provenance_steps = [
        step for step in build_steps if "sase-core-sha.txt" in str(step.get("run", ""))
    ]
    assert any(
        "git -C sase-core rev-parse HEAD" in step.get("run", "")
        and step.get("if") == "inputs.core-source == 'published'"
        for step in provenance_steps
    )
    assert build_core["env"] == {
        "CARGO_HTTP_MULTIPLEXING": "false",
        "CARGO_NET_RETRY": "10",
    }
    assert (
        'uvx maturin build --release --out "$GITHUB_WORKSPACE/dist"' in build_run_text
    )
    assert 'cargo build --release -p "$lsp_pkg"' in build_run_text
    assert (
        'install -m 0755 "target/release/$lsp_bin" "$GITHUB_WORKSPACE/dist/$lsp_bin"'
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
        and 'cargo build --release -p "$lsp_pkg"' in build_run_text
    )

    for job_name in CORE_ARTIFACT_CONSUMER_JOBS:
        job = jobs[job_name]
        assert job["needs"] == ["prepare", "build-core"]
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
    build_core = _load_build_core_workflow()["jobs"]["build-core"]
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
    """120, not 90: headroom for the 3.12 coverage leg's 74-79 of 90 minutes."""
    workflow = _load_ci_workflow()
    assert workflow["jobs"]["test"]["timeout-minutes"] == 120


def test_test_job_only_collects_coverage_on_3_12_leg() -> None:
    workflow = _load_ci_workflow()
    steps = workflow["jobs"]["test"]["steps"]

    coverage_step = next(
        step for step in steps if step.get("name") == "Run tests (coverage leg)"
    )
    assert coverage_step["if"] == "matrix.python-version == '3.12'"
    assert coverage_step["run"] == "just test-cov"

    plain_step = next(
        step
        for step in steps
        if step.get("name") == "Run tests" and step.get("run") == "just test"
    )
    assert (
        plain_step["if"]
        == "matrix.python-version == '3.13' || matrix.python-version == '3.14'"
    )
    assert not any("test-cost" in str(step.get("run", "")) for step in steps)


def test_test_job_publishes_shard_timings_from_the_master_fast_leg() -> None:
    """The master gate's balance table has to come from CI, not a laptop.

    Full CI's 3.14 `just test` leg is the same command the gate shards, so its
    per-file recordings are the right source. Master-only because a per-PR
    table would jitter the split on every push; `always()` so a red suite
    still publishes whatever it measured.
    """
    steps = _load_ci_workflow()["jobs"]["test"]["steps"]
    master_fast = (
        "always() && matrix.python-version == '3.14' "
        "&& github.ref == 'refs/heads/master'"
    )

    build_step = next(
        step for step in steps if step.get("name") == "Build shard timings table"
    )
    assert build_step["if"] == master_fast
    assert "tools/refresh_shard_timings" in build_step["run"]
    assert "--output" in build_step["run"]

    upload_step = next(
        step for step in steps if step.get("name") == "Upload shard timings"
    )
    assert upload_step["if"] == master_fast
    assert upload_step["uses"] == "actions/upload-artifact@v4"
    assert upload_step["with"]["name"] == SHARD_TIMINGS_ARTIFACT_NAME
    assert upload_step["with"]["path"] == (
        "${{ runner.temp }}/shard-timings/shard_timings.json"
    )


def test_contexts_job_publishes_the_per_test_database_on_master_only() -> None:
    """The scoped lane's ground-truth source only exists if CI publishes it.

    Master-only because baselines are resolved as ancestors of an agent's
    ``HEAD``: a per-PR database is one nobody would ever look up. The artifact
    name carries the commit SHA because the local cache is keyed by it, and
    asserting the prefix against the consumer's own constant keeps the producer
    and consumer from drifting apart silently. The job lives in the scheduled
    CI Telemetry workflow, not ci.yml: it is a measurement lane, not a
    correctness gate, so it must not be able to block a release on its own.
    """
    job = _load_telemetry_workflow()["jobs"]["coverage-contexts"]
    fetcher_text = (REPO_ROOT / "tools" / "fetch_coverage_contexts").read_text(
        encoding="utf-8"
    )

    assert job["if"] == "github.ref == 'refs/heads/master'"
    assert any(step.get("run") == "just test-contexts" for step in job["steps"])
    assert 'WORKFLOW = "telemetry.yml"' in fetcher_text

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


def test_ci_does_not_invoke_plugin_release_dependency_floor() -> None:
    """sase's release PR keeps release-core-floor-smoke.

    Family plugins call tools/check_release_dependency_floor through the
    shared reusable workflow; this check must not grow onto sase CI.
    """
    raw = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "tools/check_release_dependency_floor" not in raw
    assert "release-dependency-floor.yml" not in raw
    assert "release-core-floor-smoke" in raw


def test_ci_and_publish_never_invoke_the_testpypi_drill() -> None:
    """The yank-and-fix-forward drill is manual-only rehearsal.

    tools/check_testpypi_drill runs only from the workflow_dispatch
    testpypi-drill.yml against TestPyPI; it must never grow onto sase CI or
    the real PyPI publish path.
    """
    for workflow_name in ("ci.yml", "publish.yml"):
        raw = (REPO_ROOT / ".github" / "workflows" / workflow_name).read_text(
            encoding="utf-8"
        )

        assert "tools/check_testpypi_drill" not in raw
        assert "testpypi-drill.yml" not in raw


def test_ci_and_master_gate_never_run_the_diff_scoped_test_lane() -> None:
    """Both gates always exercise exhaustive lanes; the scoped lane is a local, agent-only fast path.

    A diff-scoped selection is a heuristic backstopped by CI (and now the
    master gate) running everything on every push; neither gate may be the
    thing that skips tests.
    """
    for workflow_name in (
        "ci.yml",
        "master-gate.yml",
        "full.yml",
        "build-core.yml",
        "telemetry.yml",
    ):
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
    visual_runs = [
        step.get("run", "") for step in jobs["visual-test"]["steps"] if "run" in step
    ]
    assert any(run == "just fix-tui-screenshots --check" for run in visual_runs)
    check_step = next(
        step
        for step in jobs["visual-test"]["steps"]
        if step.get("run") == "just fix-tui-screenshots --check"
    )
    assert (
        check_step.get("env", {}).get("SASE_VISUAL_RECAPTURE_BUDGET_SECONDS") == "600"
    )
    assert all("just test-visual" not in run for run in visual_runs)
    assert all("just check-full" not in run for run in visual_runs)
    assert all("just fix-tui-screenshots\n" not in run for run in visual_runs)
    workflow_text = "\n".join(visual_runs)
    assert "latest-report.json" in workflow_text
    assert "--manifest" in workflow_text
    assert "do not accept goldens from this run" in workflow_text
    assert "SASE_VISUAL_REPORT_STATUS=" in workflow_text
    assert "unstable_count" in workflow_text
    assert any(
        "first-attempt-diffs" in str(step.get("with", {}).get("path", ""))
        for step in jobs["visual-test"]["steps"]
    )
    locate = next(
        step
        for step in jobs["visual-test"]["steps"]
        if step.get("id") == "visual_report"
    )
    assert locate["if"] == "always()"
    assert any(
        step.get("name") == "Publish unstable recapture summary"
        for step in jobs["visual-test"]["steps"]
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


def test_ci_workflow_no_longer_contains_the_telemetry_lanes() -> None:
    """The three measurement/soak lanes moved to telemetry.yml.

    ``ci_watch`` only reads Full CI's own run, which is ``ci.yml`` reused
    through ``full.yml``; a lane that never runs inside ``ci.yml`` can never
    time out that run, regardless of what telemetry.yml does on its own
    schedule.
    """
    jobs = _load_ci_workflow()["jobs"]

    assert "coverage-contexts" not in jobs
    assert "contention-test" not in jobs
    assert "test-cost" not in jobs
    assert not any(
        "test-cost" in str(step.get("run", "")) for step in jobs["test"]["steps"]
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


def _named_steps(job: dict) -> dict[str, dict]:
    return {step["name"]: step for step in job["steps"] if "name" in step}


def test_prepare_job_rejects_invalid_source_version_manifest_combinations() -> None:
    job = _load_ci_workflow()["jobs"]["prepare"]
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
    jobs = _load_ci_workflow()["jobs"]
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
    jobs = _load_ci_workflow()["jobs"]
    expected = "${{ needs.prepare.outputs.expected-core-version }}"
    for job_name in (*CORE_ARTIFACT_CONSUMER_JOBS, "tutorial-tests"):
        setup = next(
            step
            for step in jobs[job_name]["steps"]
            if step.get("uses") == "./.github/actions/setup-sase"
        )
        assert setup["with"]["expected-core-version"] == expected, job_name


def test_blocking_jobs_report_qualification_evidence_unconditionally() -> None:
    jobs = _load_ci_workflow()["jobs"]
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
    steps = _named_steps(_load_ci_workflow()["jobs"]["test"])
    coverage = steps["Run tests (coverage leg)"]
    plain = steps["Run tests"]
    assert coverage["run"] == "just test-cov"
    assert plain["run"] == "just test"
    assert coverage["env"]["PYTEST_ADDOPTS"] == "-p tests._pytest_qualify_evidence"
    assert plain["env"]["PYTEST_ADDOPTS"] == "-p tests._pytest_qualify_evidence"
    assert (
        _load_ci_workflow()["jobs"]["test"]["env"]["SASE_QUALIFY_EVIDENCE_PATH"]
        == "${{ runner.temp }}/qualify-session.json"
    )


def test_advisory_jobs_still_run_for_qualification() -> None:
    jobs = _load_ci_workflow()["jobs"]
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

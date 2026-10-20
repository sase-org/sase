from __future__ import annotations

import pytest

from tests._github_actions_ci_helpers import CORE_ARTIFACT_CONSUMER_JOBS
from tests._github_actions_ci_helpers import job_run_text
from tests._github_actions_ci_helpers import load_build_core_workflow
from tests._github_actions_ci_helpers import load_ci_workflow

pytestmark = pytest.mark.contract


def test_ci_build_core_job_delegates_to_the_reusable_build_core_workflow() -> None:
    """ci.yml builds the wheel through one shared reusable workflow, not inline steps.

    telemetry.yml needs the identical artifact from the identical steps; a
    `uses:` call is what keeps the two from drifting into copies.
    """
    build_core = load_ci_workflow()["jobs"]["build-core"]

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
    jobs = load_ci_workflow()["jobs"]
    build_core = load_build_core_workflow()["jobs"]["build-core"]
    build_steps = build_core["steps"]
    build_run_text = job_run_text(build_core)

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
    build_core = load_build_core_workflow()["jobs"]["build-core"]
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

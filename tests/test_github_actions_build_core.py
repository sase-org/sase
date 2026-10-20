"""Contract tests for the reusable build-core workflow's published-core mode.

Published mode supplies the CI setup action with the sealed manifest's hashed
PyPI wheel and a tag-built LSP while preserving default source builds: exact
ref plumbing, validated inputs, manifest download, PyPI digest verification,
tag-only LSP provenance, and the rehearse-only probe path.
"""

from __future__ import annotations

import pytest

from tests._github_actions_ci_helpers import _job_run_text
from tests._github_actions_ci_helpers import _load_build_core_workflow
from tests._github_actions_ci_helpers import _workflow_triggers


pytestmark = pytest.mark.contract


def _build_core() -> dict:
    return _load_build_core_workflow()["jobs"]["build-core"]


def _steps_by_name() -> dict[str, dict]:
    return {
        step.get("name", f"uses:{step.get('uses', '?')}"): step
        for step in _build_core()["steps"]
    }


def test_published_core_inputs_are_all_optional_with_source_defaults() -> None:
    """Inputless callers (ci.yml, telemetry.yml) keep source builds unchanged."""
    inputs = _workflow_triggers(_load_build_core_workflow())["workflow_call"]["inputs"]
    assert inputs["ref"] == {
        "description": inputs["ref"]["description"],
        "type": "string",
        "required": False,
        "default": "",
    }
    assert inputs["core-source"]["default"] == "source"
    assert inputs["core-version"]["default"] == ""
    assert inputs["manifest-artifact"]["default"] == "candidate-build"
    assert inputs["probe-core-version"]["default"] == ""
    assert not any(details.get("required", False) for details in inputs.values())


def test_published_builds_run_while_source_keeps_the_release_please_exclusion() -> None:
    job_if = _build_core()["if"]
    assert "inputs.core-source == 'published'" in job_if
    assert "release-please--branches--master" in job_if


def test_sase_checkout_follows_the_explicit_ref_input() -> None:
    sase_checkout = next(
        step
        for step in _build_core()["steps"]
        if step.get("uses") == "actions/checkout@v4"
        and "repository" not in step.get("with", {})
    )
    assert sase_checkout["with"]["ref"] == "${{ inputs.ref }}"


def test_resolve_core_fails_closed_on_bad_inputs() -> None:
    run_text = _steps_by_name()["Resolve core mode"]["run"]
    assert "source|published" in run_text
    assert "core-source must be" in run_text
    assert "core-version is required when core-source is published" in run_text
    assert "probe-core-version requires core-source 'published'" in run_text


def test_resolve_core_exposes_version_and_probe_outputs() -> None:
    resolve = _steps_by_name()["Resolve core mode"]
    assert resolve["id"] == "resolve-core"
    assert 'echo "version=$effective" >> "$GITHUB_OUTPUT"' in resolve["run"]
    assert 'echo "probe=$probe" >> "$GITHUB_OUTPUT"' in resolve["run"]
    job_outputs = _build_core()["outputs"]
    assert job_outputs["core-version"] == "${{ steps.resolve-core.outputs.version }}"
    assert job_outputs["probe"] == "${{ steps.resolve-core.outputs.probe }}"
    workflow_outputs = _workflow_triggers(_load_build_core_workflow())["workflow_call"][
        "outputs"
    ]
    assert (
        workflow_outputs["core-version"]["value"]
        == "${{ jobs.build-core.outputs.core-version }}"
    )
    assert workflow_outputs["probe"]["value"] == "${{ jobs.build-core.outputs.probe }}"


def test_source_steps_are_gated_while_published_skips_maturin() -> None:
    steps = _steps_by_name()
    assert steps["Resolve pinned Rust core revision"]["if"] == (
        "inputs.core-source == 'source'"
    )
    assert steps["Build abi3 Rust core wheel"]["if"] == "inputs.core-source == 'source'"
    assert (
        'uvx maturin build --release --out "$GITHUB_WORKSPACE/dist"'
        in steps["Build abi3 Rust core wheel"]["run"]
    )
    maturin_runs = [
        step.get("run", "")
        for step in _build_core()["steps"]
        if "maturin" in str(step.get("run", ""))
    ]
    assert len(maturin_runs) == 1
    published_steps = [
        step
        for step in _build_core()["steps"]
        if step.get("if") == "inputs.core-source == 'published'"
    ]
    assert not any("maturin" in str(step.get("run", "")) for step in published_steps)


def test_published_mode_downloads_the_sealed_manifest() -> None:
    download = _steps_by_name()["Download the sealed candidate manifest"]
    assert download["if"] == "inputs.core-source == 'published'"
    assert download["uses"] == "actions/download-artifact@v4"
    assert download["with"]["name"] == "${{ inputs.manifest-artifact }}"
    assert download["with"]["path"] == "published-core/"


def test_published_mode_verifies_the_wheel_before_advertising_it() -> None:
    fetch = _steps_by_name()["Fetch and verify the published core wheel"]
    assert fetch["if"] == "inputs.core-source == 'published'"
    run_text = fetch["run"]
    assert "release_candidate core-files" in run_text
    assert "release_candidate core-suffixes" in run_text
    assert "release_candidate published-core" in run_text
    assert "--manifest published-core/candidate-manifest.json" in run_text
    assert '--expect-version "${{ inputs.core-version }}"' in run_text
    assert '--probe-version "${{ inputs.probe-core-version }}"' in run_text
    assert '"${probe_args[@]}"' in run_text
    assert "release-plz.yml" in run_text


def test_lsp_builds_in_both_modes_without_other_cargo_builds() -> None:
    steps = _steps_by_name()
    lsp = steps["Build macro LSP"]
    assert "if" not in lsp
    assert 'cargo build --release -p "$lsp_pkg"' in lsp["run"]
    cargo_builds = [
        step.get("run", "")
        for step in _build_core()["steps"]
        if "cargo build" in str(step.get("run", ""))
    ]
    assert len(cargo_builds) == 1


def test_provenance_records_the_pin_or_the_tag_commit() -> None:
    steps = _steps_by_name()
    source = steps["Record wheel provenance"]
    assert source["if"] == "inputs.core-source == 'source'"
    assert "steps.core-sha.outputs.sha" in source["run"]
    published = steps["Record published tag provenance"]
    assert published["if"] == "inputs.core-source == 'published'"
    assert "git -C sase-core rev-parse HEAD" in published["run"]
    assert "sase-core-sha.txt" in published["run"]


def test_artifact_shape_still_matches_what_setup_sase_consumes() -> None:
    upload = next(
        step
        for step in _build_core()["steps"]
        if step.get("uses") == "actions/upload-artifact@v4"
    )
    assert upload["with"]["name"] == "sase-core-wheel"
    assert upload["with"]["path"] == "dist/"
    assert upload["with"]["if-no-files-found"] == "error"
    run_text = _job_run_text(_build_core())
    # The probe marker file itself is written by the published-core helper
    # (tool-tested); the workflow announces probe mode in its provenance log.
    assert "probe-core-version.txt" in run_text

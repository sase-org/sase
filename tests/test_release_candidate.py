"""Seal/verify/observe/evaluate tests for the release_candidate tool."""

from __future__ import annotations

from types import ModuleType

import pytest

from tests._release_candidate_tool_helpers import dists as _dists
from tests._release_candidate_tool_helpers import load_tool as _load_tool
from tests._release_candidate_tool_helpers import seal_kwargs as _seal_kwargs


pytestmark = pytest.mark.contract


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    return _load_tool()


def test_candidate_id_stable_across_observations(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    before = manifest["candidate_id"]
    tool.append_observation(
        manifest,
        kind="qualification",
        run_id=1,
        attempt=1,
        verdict="pass",
        reason="",
    )
    assert tool.verify_manifest(manifest) == []
    assert manifest["candidate_id"] == before


def test_candidate_id_changes_with_generation(tool: ModuleType) -> None:
    first = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    second = tool.seal_manifest(**_seal_kwargs(generation=2))  # type: ignore[arg-type]
    assert first["candidate_id"] != second["candidate_id"]


def test_each_identity_mismatch_refuses(tool: ModuleType) -> None:
    with pytest.raises(tool.Refusal):
        tool.seal_manifest(**_seal_kwargs(repository=""))  # type: ignore[arg-type]
    with pytest.raises(tool.Refusal):
        tool.seal_manifest(**_seal_kwargs(version=""))  # type: ignore[arg-type]


def test_extra_or_missing_dist_refuses(tool: ModuleType) -> None:
    with pytest.raises(tool.Refusal):
        tool.seal_manifest(**_seal_kwargs(dists=_dists()[:1]))  # type: ignore[arg-type]
    with pytest.raises(tool.Refusal):
        tool.seal_manifest(
            **_seal_kwargs(dists=_dists() + [_dists()[0]])  # type: ignore[arg-type]
        )
    wrong_name = _dists()
    wrong_name[0] = dict(wrong_name[0], filename="sase-9.9.9-py3-none-any.whl")
    with pytest.raises(tool.Refusal):
        tool.seal_manifest(**_seal_kwargs(dists=wrong_name))  # type: ignore[arg-type]


def test_incomplete_core_file_set_refuses_to_seal(tool: ModuleType) -> None:
    from tests._release_candidate_tool_helpers import core_files

    partial = [entry for entry in core_files() if entry["packagetype"] == "sdist"]
    with pytest.raises(tool.Refusal, match="incomplete core file set"):
        tool.seal_manifest(**_seal_kwargs(core_files=partial))  # type: ignore[arg-type]


def test_yanked_only_core_file_set_refuses_to_seal(tool: ModuleType) -> None:
    from tests._release_candidate_tool_helpers import core_files

    yanked = core_files(yanked=True)
    with pytest.raises(tool.Refusal, match="incomplete core file set"):
        tool.seal_manifest(**_seal_kwargs(core_files=yanked))  # type: ignore[arg-type]


def test_second_stash_generation_must_requalify(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    result = tool.evaluate_manifest(manifest, manifest["observations"])
    assert result["publishable"] is False
    assert any(
        clause["name"] == "qualification"
        and "required evidence missing" in clause["detail"]
        for clause in result["clauses"]
    )


def test_evaluate_reports_missing_evidence_red(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    result = tool.evaluate_manifest(manifest, [])
    assert result["publishable"] is False
    missing = [
        clause["name"]
        for clause in result["clauses"]
        if not clause["ok"] and "required evidence missing" in clause["detail"]
    ]
    assert missing == ["qualification", "exercise"]


def test_evaluate_veto_blocks(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    tool.append_observation(
        manifest,
        kind="qualification",
        run_id=1,
        attempt=1,
        verdict="pass",
        reason="green",
    )
    tool.append_observation(
        manifest,
        kind="exercise",
        run_id=2,
        attempt=1,
        verdict="pass",
        reason="green",
    )
    tool.append_observation(
        manifest,
        kind="veto",
        run_id=3,
        attempt=1,
        verdict="hold",
        reason="human hold",
    )
    result = tool.evaluate_manifest(manifest, manifest["observations"])
    assert result["publishable"] is False
    veto = next(
        clause
        for clause in result["clauses"]
        if clause["name"] == "no_confirmed_release_veto"
    )
    assert veto["ok"] is False


def test_observe_reappend_is_idempotent(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    first = tool.append_observation(
        manifest,
        kind="qualification",
        run_id=7,
        attempt=1,
        verdict="pass",
        reason="green",
    )
    second = tool.append_observation(
        manifest,
        kind="qualification",
        run_id=7,
        attempt=1,
        verdict="pass",
        reason="green again",
    )
    assert first["asset"] == second["asset"]
    assert second["asset"].startswith("candidate-gen1-qualification-run7-attempt1")
    assert len(manifest["observations"]) == 1


def test_unknown_observation_kind_refuses(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    with pytest.raises(tool.Refusal, match="unknown observation kind"):
        tool.append_observation(
            manifest,
            kind="smoke",
            run_id=1,
            attempt=1,
            verdict="pass",
        )


def test_unsupported_locator_fails_closed(tool: ModuleType, tmp_path) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(tool.Refusal, match="unsupported asset locator"):
        tool.resolve_locator("s3://bucket/key", tmp_path / "out.bin")


def test_missing_file_locator_fails_closed(tool: ModuleType, tmp_path) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(tool.Refusal, match="asset not found"):
        tool.resolve_locator("file:/does/not/exist.bin", tmp_path / "out.bin")


def test_parse_expected_suffixes_reads_single_source(tool: ModuleType) -> None:
    text = "jobs:\n  x:\n    env:\n      EXPECTED_DIST_SUFFIXES: ['.tar.gz', '-py3-none-any.whl']\n"
    assert tool.parse_expected_suffixes(text) == [".tar.gz", "-py3-none-any.whl"]
    with pytest.raises(tool.Refusal, match="EXPECTED_DIST_SUFFIXES not found"):
        tool.parse_expected_suffixes("no suffixes here\n")


def test_cross_check_lock_hashes_catches_mismatch(tool: ModuleType, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from tests._release_candidate_tool_helpers import core_files

    lock = tmp_path / "uv.lock"
    files = core_files()
    first = files[0]
    lock.write_text(
        '[[package]]\nname = "sase-core-rs"\nversion = "0.42.0"\n'
        f'[package.metadata]\n[package.sdist]\nurl = "{first["url"]}"\n'
        'hash = "sha256:deadbeef"\n',
        encoding="utf-8",
    )
    problems = tool.cross_check_lock_hashes(files, lock, "0.42.0")
    assert problems == [f"HASH_MISMATCH {first['filename']}"]

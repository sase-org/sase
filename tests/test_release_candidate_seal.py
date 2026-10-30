"""Seal/observe/locator tests for the release_candidate tool."""

from __future__ import annotations

from types import ModuleType

import pytest

from tests._release_candidate_tool_helpers import core_files
from tests._release_candidate_tool_helpers import dists
from tests._release_candidate_tool_helpers import load_tool
from tests._release_candidate_tool_helpers import seal_kwargs


pytestmark = pytest.mark.contract


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    return load_tool()


def test_candidate_id_stable_across_observations(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**seal_kwargs())  # type: ignore[arg-type]
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
    first = tool.seal_manifest(**seal_kwargs())  # type: ignore[arg-type]
    second = tool.seal_manifest(**seal_kwargs(generation=2))  # type: ignore[arg-type]
    assert first["candidate_id"] != second["candidate_id"]


def test_each_identity_mismatch_refuses(tool: ModuleType) -> None:
    with pytest.raises(tool.Refusal):
        tool.seal_manifest(**seal_kwargs(repository=""))  # type: ignore[arg-type]
    with pytest.raises(tool.Refusal):
        tool.seal_manifest(**seal_kwargs(version=""))  # type: ignore[arg-type]


def test_extra_or_missing_dist_refuses(tool: ModuleType) -> None:
    with pytest.raises(tool.Refusal):
        tool.seal_manifest(**seal_kwargs(dists=dists()[:1]))  # type: ignore[arg-type]
    with pytest.raises(tool.Refusal):
        tool.seal_manifest(
            **seal_kwargs(dists=dists() + [dists()[0]])  # type: ignore[arg-type]
        )
    wrong_name = dists()
    wrong_name[0] = dict(wrong_name[0], filename="sase-9.9.9-py3-none-any.whl")
    with pytest.raises(tool.Refusal):
        tool.seal_manifest(**seal_kwargs(dists=wrong_name))  # type: ignore[arg-type]


def test_incomplete_core_file_set_refuses_to_seal(tool: ModuleType) -> None:
    partial = [entry for entry in core_files() if entry["packagetype"] == "sdist"]
    with pytest.raises(tool.Refusal, match="incomplete core file set"):
        tool.seal_manifest(**seal_kwargs(core_files=partial))  # type: ignore[arg-type]


_MACOS_0_43_0 = (
    "sase_core_rs-0.43.0-cp312-abi3-"
    "macosx_10_12_x86_64.macosx_11_0_arm64.macosx_10_12_universal2.whl"
)
_MACOS_0_43_1 = (
    "sase_core_rs-0.43.1-cp312-abi3-"
    "macosx_10_12_universal2.macosx_10_12_x86_64.macosx_11_0_arm64.whl"
)
_MACOS_ARM64_ONLY = "sase_core_rs-0.43.1-cp312-abi3-macosx_11_0_arm64.whl"
_COMPRESSED_SUFFIXES = (
    ".tar.gz",
    "manylinux_2_28_x86_64.whl",
    "manylinux_2_28_aarch64.whl",
    "universal2.whl",
)


def _compressed_core_files(
    version: str, macos_filename: str, *, yanked_macos: bool = False
) -> list[dict[str, object]]:
    files = core_files(version)
    files.append(
        {
            "filename": macos_filename,
            "packagetype": "bdist_wheel",
            "yanked": yanked_macos,
            "sha256": "c26d3d23780e261ef0d8b40bf954bb3a61b10197b8d9978184b33b0a966f8a0f",
            "url": f"https://files.pythonhosted.org/packages/{macos_filename}",
        }
    )
    return files


def test_seal_accepts_live_compressed_macos_tag_orders(tool: ModuleType) -> None:
    for version, macos_filename in (
        ("0.43.0", _MACOS_0_43_0),
        ("0.43.1", _MACOS_0_43_1),
    ):
        manifest = tool.seal_manifest(
            **seal_kwargs(  # type: ignore[arg-type]
                core_version=version,
                core_files=_compressed_core_files(version, macos_filename),
                expected_core_suffixes=list(_COMPRESSED_SUFFIXES),
            )
        )
        assert manifest["core_version"] == version
        assert any(
            entry["filename"] == macos_filename for entry in manifest["core_files"]
        )


def test_seal_refuses_arm64_only_macos_when_universal2_is_required(
    tool: ModuleType,
) -> None:
    with pytest.raises(tool.Refusal, match="incomplete core file set"):
        tool.seal_manifest(
            **seal_kwargs(  # type: ignore[arg-type]
                core_version="0.43.1",
                core_files=_compressed_core_files("0.43.1", _MACOS_ARM64_ONLY),
                expected_core_suffixes=list(_COMPRESSED_SUFFIXES),
            )
        )


def test_seal_refuses_yanked_compressed_macos_wheel(tool: ModuleType) -> None:
    with pytest.raises(tool.Refusal, match="incomplete core file set"):
        tool.seal_manifest(
            **seal_kwargs(  # type: ignore[arg-type]
                core_version="0.43.1",
                core_files=_compressed_core_files(
                    "0.43.1", _MACOS_0_43_1, yanked_macos=True
                ),
                expected_core_suffixes=list(_COMPRESSED_SUFFIXES),
            )
        )


def test_yanked_only_core_file_set_refuses_to_seal(tool: ModuleType) -> None:
    yanked = core_files(yanked=True)
    with pytest.raises(tool.Refusal, match="incomplete core file set"):
        tool.seal_manifest(**seal_kwargs(core_files=yanked))  # type: ignore[arg-type]


def test_second_stash_generation_must_requalify(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**seal_kwargs())  # type: ignore[arg-type]
    result = tool.evaluate_manifest(manifest, manifest["observations"])
    assert result["publishable"] is False
    assert any(
        clause["name"] == "qualification"
        and "required evidence missing" in clause["detail"]
        for clause in result["clauses"]
    )


def test_evaluate_reports_missing_evidence_red(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**seal_kwargs())  # type: ignore[arg-type]
    result = tool.evaluate_manifest(manifest, [])
    assert result["publishable"] is False
    missing = [
        clause["name"]
        for clause in result["clauses"]
        if not clause["ok"] and "required evidence missing" in clause["detail"]
    ]
    assert missing == ["qualification", "exercise"]


def test_evaluate_veto_blocks(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**seal_kwargs())  # type: ignore[arg-type]
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
    manifest = tool.seal_manifest(**seal_kwargs())  # type: ignore[arg-type]
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
        reason="green",
    )
    assert first["asset"] == second["asset"]
    assert second["asset"].startswith("candidate-gen1-qualification-run7-attempt1")
    assert len(manifest["observations"]) == 1


def test_observe_refuses_to_replace_a_conflicting_asset(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**seal_kwargs())  # type: ignore[arg-type]
    tool.append_observation(
        manifest,
        kind="qualification",
        run_id=7,
        attempt=1,
        verdict="pass",
        reason="green",
    )
    with pytest.raises(tool.Refusal, match="conflicting observation"):
        tool.append_observation(
            manifest,
            kind="qualification",
            run_id=7,
            attempt=1,
            verdict="red",
            reason="different payload",
        )


def test_unknown_observation_kind_refuses(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**seal_kwargs())  # type: ignore[arg-type]
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


_V042_SUFFIXES = [
    "manylinux_2_28_x86_64.whl",
    "manylinux_2_28_aarch64.whl",
    "universal2.whl",
    "win_amd64.whl",
    ".tar.gz",
]


def _jobs_env_suffix_block(*suffixes: str) -> str:
    body = "".join(f"        {suffix}\n" for suffix in suffixes)
    return "jobs:\n  x:\n    env:\n      EXPECTED_DIST_SUFFIXES: |\n" + body


def test_parse_expected_suffixes_reads_block_form(tool: ModuleType) -> None:
    suffixes = tool.parse_expected_suffixes(_jobs_env_suffix_block(*_V042_SUFFIXES))
    assert suffixes == _V042_SUFFIXES
    assert isinstance(suffixes, list)


def test_parse_expected_suffixes_refuses_missing_block(tool: ModuleType) -> None:
    with pytest.raises(tool.Refusal, match="cannot find EXPECTED_DIST_SUFFIXES"):
        tool.parse_expected_suffixes("no suffixes here\n")


def test_parse_expected_suffixes_refuses_empty_block(tool: ModuleType) -> None:
    with pytest.raises(tool.Refusal, match="is empty"):
        tool.parse_expected_suffixes(_jobs_env_suffix_block())


def test_parse_expected_suffixes_refuses_duplicate_suffix(tool: ModuleType) -> None:
    with pytest.raises(tool.Refusal, match="duplicate"):
        tool.parse_expected_suffixes(_jobs_env_suffix_block(".tar.gz", ".tar.gz"))


def test_cross_check_lock_hashes_catches_mismatch(tool: ModuleType, tmp_path) -> None:  # type: ignore[no-untyped-def]
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

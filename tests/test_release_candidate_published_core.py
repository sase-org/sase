"""Published-core selection and verification tests for release_candidate.

Covers the `published-core` subcommand used by the reusable `build-core`
workflow's published mode: exact-one wheel selection, filename/version/size/
SHA-256 validation against the sealed manifest, and the rehearse-only probe
path that records a probe without rewriting the candidate manifest.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from tests._release_candidate_tool_helpers import CORE_SUFFIXES
from tests._release_candidate_tool_helpers import core_files as _sealed_core_files
from tests._release_candidate_tool_helpers import dists as _dists
from tests._release_candidate_tool_helpers import load_tool as _load_tool
from tests._release_candidate_tool_helpers import seal_kwargs as _seal_kwargs


pytestmark = pytest.mark.contract


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    return _load_tool()


WHEEL_SUFFIX = "manylinux_2_28_x86_64"
WHEEL_FILENAME = f"sase_core_rs-0.42.0-cp312-abi3-{WHEEL_SUFFIX}.whl"
PROBE_VERSION = "0.41.0"
PROBE_WHEEL_FILENAME = f"sase_core_rs-{PROBE_VERSION}-cp312-abi3-{WHEEL_SUFFIX}.whl"


def _payload(marker: bytes = b"wheel-bytes") -> bytes:
    return marker


def _fresh_files(
    version: str = "0.42.0",
    payload: bytes = b"wheel-bytes",
    *,
    yank_wheel: bool = False,
    drop_suffixes: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Build a fresh PyPI-style file list whose wheel digest matches payload."""
    digest = hashlib.sha256(payload).hexdigest()
    files: list[dict[str, Any]] = []
    for entry in _sealed_core_files(version=version):
        if any(entry["filename"].endswith(suffix) for suffix in drop_suffixes):
            continue
        record = dict(entry)
        if record["filename"].endswith(f"{WHEEL_SUFFIX}.whl"):
            record = {
                **record,
                "yanked": yank_wheel,
                "sha256": digest,
                "size": len(payload),
                "url": f"https://files.pythonhosted.org/packages/{record['filename']}",
            }
        else:
            record = {
                **record,
                "size": 100,
                "url": f"https://files.pythonhosted.org/packages/{record['filename']}",
            }
        files.append(record)
    return files


def _sealed_files(
    version: str = "0.42.0",
    payload: bytes = b"wheel-bytes",
) -> list[dict[str, Any]]:
    """Sealed-manifest file list whose wheel digest matches the fresh payload."""
    digest = hashlib.sha256(payload).hexdigest()
    files = []
    for entry in _sealed_core_files(version=version):
        record = dict(entry)
        if record["filename"].endswith(f"{WHEEL_SUFFIX}.whl"):
            record = {**record, "sha256": digest, "size": len(payload)}
        else:
            record = {**record, "size": 100}
        files.append(record)
    return files


def _write_inputs(
    tmp_path: Path,
    tool: ModuleType,
    *,
    core_version: str = "0.42.0",
    payload: bytes = b"wheel-bytes",
    mutate_manifest: Any = None,
    mutate_files: Any = None,
) -> dict[str, Path]:
    sealed = _sealed_files(version=core_version, payload=payload)
    manifest = tool.seal_manifest(
        **_seal_kwargs(core_version=core_version, core_files=sealed)
    )
    if mutate_manifest is not None:
        mutate_manifest(manifest)
        manifest["candidate_id"] = tool.candidate_id(manifest)
    files = _fresh_files(version=core_version, payload=payload)
    if mutate_files is not None:
        mutate_files(files, manifest)
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    files_path = tmp_path / "core-files.json"
    files_path.write_text(json.dumps(files), encoding="utf-8")
    suffixes_path = tmp_path / "core-suffixes.json"
    suffixes_path.write_text(json.dumps(list(CORE_SUFFIXES)), encoding="utf-8")
    return {
        "manifest": manifest_path,
        "files": files_path,
        "suffixes": suffixes_path,
        "out": tmp_path / "dist",
    }


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def _urlopen_for(payload: bytes, seen: dict[str, str]) -> Any:
    def _fake(url: str, timeout: int = 0) -> _FakeResponse:
        seen["url"] = url
        return _FakeResponse(payload)

    return _fake


def test_published_core_downloads_and_verifies_the_sealed_wheel(
    tool: ModuleType,
    tmp_path: Path,
) -> None:
    payload = _payload()
    paths = _write_inputs(tmp_path, tool, payload=payload)
    before = paths["manifest"].read_bytes()
    manifest = json.loads(before.decode("utf-8"))

    plan = tool.published_core_plan(
        manifest,
        json.loads(paths["files"].read_text(encoding="utf-8")),
        list(CORE_SUFFIXES),
        expect_version="0.42.0",
    )
    assert plan["version"] == "0.42.0"
    assert plan["probe"] is False
    assert plan["filename"] == WHEEL_FILENAME
    assert plan["tag"] == "v0.42.0"

    seen: dict[str, str] = {}
    wheel_path = tool.fetch_and_verify_wheel(
        plan, paths["out"], urlopen=_urlopen_for(payload, seen)
    )
    assert wheel_path.read_bytes() == payload
    assert seen["url"].endswith(WHEEL_FILENAME)
    assert not (paths["out"] / "probe-core-version.txt").exists()
    assert paths["manifest"].read_bytes() == before


def test_published_core_refuses_when_expect_version_differs(
    tool: ModuleType,
    tmp_path: Path,
) -> None:
    paths = _write_inputs(tmp_path, tool)
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    files = json.loads(paths["files"].read_text(encoding="utf-8"))
    with pytest.raises(tool.Refusal, match="differs from the sealed manifest core"):
        tool.published_core_plan(
            manifest, files, list(CORE_SUFFIXES), expect_version="0.42.1"
        )


def test_published_core_refuses_a_red_manifest(
    tool: ModuleType,
    tmp_path: Path,
) -> None:
    paths = _write_inputs(tmp_path, tool)
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    manifest["candidate_id"] = "tampered"
    files = json.loads(paths["files"].read_text(encoding="utf-8"))
    with pytest.raises(tool.Refusal, match="sealed manifest is red"):
        tool.published_core_plan(manifest, files, list(CORE_SUFFIXES))


def test_published_core_refuses_a_missing_platform_wheel(
    tool: ModuleType,
    tmp_path: Path,
) -> None:
    paths = _write_inputs(tmp_path, tool)
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    files = json.loads(paths["files"].read_text(encoding="utf-8"))
    # Point the platform wheel at another version: the suffix set stays
    # complete, but nothing matches this candidate's version stem.
    for entry in files:
        if entry["filename"] == WHEEL_FILENAME:
            entry["filename"] = entry["filename"].replace("0.42.0", "0.99.0")
    with pytest.raises(tool.Refusal, match="no live .* wheel"):
        tool.published_core_plan(manifest, files, list(CORE_SUFFIXES))


def test_published_core_refuses_duplicate_live_wheels(
    tool: ModuleType,
    tmp_path: Path,
) -> None:
    def _duplicate(files: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
        wheel = next(
            entry
            for entry in files
            if entry["filename"].endswith(f"{WHEEL_SUFFIX}.whl")
        )
        files.append({**wheel, "url": wheel["url"] + "?copy=1"})

    paths = _write_inputs(tmp_path, tool, mutate_files=_duplicate)
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    files = json.loads(paths["files"].read_text(encoding="utf-8"))
    with pytest.raises(tool.Refusal, match="duplicate live"):
        tool.published_core_plan(manifest, files, list(CORE_SUFFIXES))


def test_published_core_refuses_a_yanked_fresh_wheel(
    tool: ModuleType,
    tmp_path: Path,
) -> None:
    paths = _write_inputs(tmp_path, tool, payload=b"wheel-bytes")
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    files = _fresh_files(yank_wheel=True)
    # A yanked wheel is not live, so its suffix counts as missing from the
    # fresh set: yanked files can never supply the published wheel.
    with pytest.raises(tool.Refusal, match="incomplete core file set"):
        tool.published_core_plan(manifest, files, list(CORE_SUFFIXES))


def test_published_core_refuses_a_yanked_sealed_record(
    tool: ModuleType,
    tmp_path: Path,
) -> None:
    def _yank_sealed(manifest: dict[str, Any]) -> None:
        for entry in manifest["core_files"]:
            if entry["filename"] == WHEEL_FILENAME:
                entry["yanked"] = True

    paths = _write_inputs(tmp_path, tool, mutate_manifest=_yank_sealed)
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    files = json.loads(paths["files"].read_text(encoding="utf-8"))
    with pytest.raises(tool.Refusal, match="no live record"):
        tool.published_core_plan(manifest, files, list(CORE_SUFFIXES))


def test_published_core_refuses_a_sealed_digest_mismatch(
    tool: ModuleType,
    tmp_path: Path,
) -> None:
    paths = _write_inputs(tmp_path, tool, payload=b"fresh-bytes")
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    files = json.loads(paths["files"].read_text(encoding="utf-8"))
    for entry in files:
        if entry["filename"] == WHEEL_FILENAME:
            entry["sha256"] = "0" * 64
    with pytest.raises(tool.Refusal, match="SHA-256 mismatch"):
        tool.published_core_plan(manifest, files, list(CORE_SUFFIXES))


def test_published_core_refuses_a_sealed_size_mismatch(
    tool: ModuleType,
    tmp_path: Path,
) -> None:
    def _grow_sealed(manifest: dict[str, Any]) -> None:
        for entry in manifest["core_files"]:
            if entry["filename"] == WHEEL_FILENAME:
                entry["size"] = 999999

    paths = _write_inputs(tmp_path, tool, mutate_manifest=_grow_sealed)
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    files = json.loads(paths["files"].read_text(encoding="utf-8"))
    with pytest.raises(tool.Refusal, match="size mismatch"):
        tool.published_core_plan(manifest, files, list(CORE_SUFFIXES))


def test_published_core_refuses_an_incomplete_fresh_file_set(
    tool: ModuleType,
    tmp_path: Path,
) -> None:
    paths = _write_inputs(tmp_path, tool)
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    files = [
        entry
        for entry in json.loads(paths["files"].read_text(encoding="utf-8"))
        if not entry["filename"].endswith(".tar.gz")
    ]
    with pytest.raises(tool.Refusal, match="incomplete core file set"):
        tool.published_core_plan(manifest, files, list(CORE_SUFFIXES))


def test_published_core_refuses_a_corrupt_download(
    tool: ModuleType,
    tmp_path: Path,
) -> None:
    paths = _write_inputs(tmp_path, tool, payload=b"good-bytes")
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    plan = tool.published_core_plan(
        manifest,
        json.loads(paths["files"].read_text(encoding="utf-8")),
        list(CORE_SUFFIXES),
    )
    seen: dict[str, str] = {}
    with pytest.raises(tool.Refusal, match="SHA-256 mismatch"):
        tool.fetch_and_verify_wheel(
            plan, paths["out"], urlopen=_urlopen_for(b"tampered", seen)
        )
    assert not (paths["out"] / WHEEL_FILENAME).exists()


def test_published_core_refuses_a_short_download(
    tool: ModuleType,
    tmp_path: Path,
) -> None:
    payload = b"exactly-eight"
    assert len(payload) == 13
    paths = _write_inputs(tmp_path, tool, payload=payload)
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    plan = tool.published_core_plan(
        manifest,
        json.loads(paths["files"].read_text(encoding="utf-8")),
        list(CORE_SUFFIXES),
    )
    assert plan["size"] == len(payload)
    short = payload[: len(payload) - 1]
    tampered_plan = {**plan, "sha256": hashlib.sha256(short).hexdigest()}
    seen: dict[str, str] = {}
    with pytest.raises(tool.Refusal, match="size mismatch"):
        tool.fetch_and_verify_wheel(
            tampered_plan, paths["out"], urlopen=_urlopen_for(short, seen)
        )


def test_published_core_refuses_an_unreachable_wheel(
    tool: ModuleType,
    tmp_path: Path,
) -> None:
    import urllib.error

    paths = _write_inputs(tmp_path, tool)
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    plan = tool.published_core_plan(
        manifest,
        json.loads(paths["files"].read_text(encoding="utf-8")),
        list(CORE_SUFFIXES),
    )

    def _broken(url: str, timeout: int = 0) -> Any:
        raise urllib.error.URLError("offline")

    with pytest.raises(tool.Refusal, match="cannot download"):
        tool.fetch_and_verify_wheel(plan, paths["out"], urlopen=_broken)


def test_published_core_probe_records_an_older_core_without_touching_the_manifest(
    tool: ModuleType,
    tmp_path: Path,
) -> None:
    payload = b"probe-bytes"
    paths = _write_inputs(tmp_path, tool, payload=b"wheel-bytes")
    before = paths["manifest"].read_bytes()
    manifest = json.loads(before.decode("utf-8"))
    probe_files = _fresh_files(version=PROBE_VERSION, payload=payload)

    plan = tool.published_core_plan(
        manifest,
        probe_files,
        list(CORE_SUFFIXES),
        expect_version="0.42.0",
        probe_version=PROBE_VERSION,
    )
    assert plan["probe"] is True
    assert plan["version"] == PROBE_VERSION
    assert plan["manifest_version"] == "0.42.0"
    assert plan["filename"] == PROBE_WHEEL_FILENAME
    assert plan["tag"] == f"v{PROBE_VERSION}"

    seen: dict[str, str] = {}
    wheel_path = tool.fetch_and_verify_wheel(
        plan, paths["out"], urlopen=_urlopen_for(payload, seen)
    )
    assert wheel_path.read_bytes() == payload
    marker = paths["out"] / "probe-core-version.txt"
    assert marker.read_text(encoding="utf-8") == f"{PROBE_VERSION}\n"
    assert paths["manifest"].read_bytes() == before


def test_published_core_probe_refuses_same_or_newer_versions(
    tool: ModuleType,
    tmp_path: Path,
) -> None:
    paths = _write_inputs(tmp_path, tool)
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    files = json.loads(paths["files"].read_text(encoding="utf-8"))
    with pytest.raises(tool.Refusal, match="must differ"):
        tool.published_core_plan(
            manifest, files, list(CORE_SUFFIXES), probe_version="0.42.0"
        )
    with pytest.raises(tool.Refusal, match="must be older"):
        tool.published_core_plan(
            manifest, files, list(CORE_SUFFIXES), probe_version="0.42.1"
        )
    with pytest.raises(tool.Refusal, match="numeric dot-separated"):
        tool.published_core_plan(
            manifest, files, list(CORE_SUFFIXES), probe_version="not-a-version"
        )


def test_published_core_selects_the_requested_platform(
    tool: ModuleType,
    tmp_path: Path,
) -> None:
    paths = _write_inputs(tmp_path, tool)
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    files = json.loads(paths["files"].read_text(encoding="utf-8"))
    plan = tool.published_core_plan(
        manifest,
        files,
        list(CORE_SUFFIXES),
        platform_suffix="manylinux_2_28_aarch64",
    )
    assert plan["filename"].endswith("manylinux_2_28_aarch64.whl")


def test_published_core_cli_writes_the_verified_wheel(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import urllib.request

    payload = b"cli-wheel-bytes"
    paths = _write_inputs(tmp_path, tool, payload=payload)
    monkeypatch.setattr(
        urllib.request, "urlopen", _urlopen_for(payload, {}), raising=True
    )
    assert (
        tool.main(
            [
                "published-core",
                "--manifest",
                str(paths["manifest"]),
                "--core-files",
                str(paths["files"]),
                "--expected-core-suffixes",
                str(paths["suffixes"]),
                "--out-dir",
                str(paths["out"]),
                "--expect-version",
                "0.42.0",
            ]
        )
        == 0
    )
    summary = json.loads(capsys.readouterr().out)
    assert summary["filename"] == WHEEL_FILENAME
    assert summary["path"].endswith(WHEEL_FILENAME)
    assert (paths["out"] / WHEEL_FILENAME).read_bytes() == payload


def test_published_core_cli_refuses_an_expect_mismatch(
    tool: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _write_inputs(tmp_path, tool)
    assert (
        tool.main(
            [
                "published-core",
                "--manifest",
                str(paths["manifest"]),
                "--core-files",
                str(paths["files"]),
                "--expected-core-suffixes",
                str(paths["suffixes"]),
                "--out-dir",
                str(paths["out"]),
                "--expect-version",
                "0.42.1",
            ]
        )
        == tool.EXIT_REFUSED
    )
    assert "REFUSED" in capsys.readouterr().err
    assert not (paths["out"] / WHEEL_FILENAME).exists()


def test_fetch_pypi_core_files_now_carries_sizes(
    tool: ModuleType,
) -> None:
    payload = {
        "releases": {
            "0.42.0": [
                {
                    "filename": WHEEL_FILENAME,
                    "packagetype": "bdist_wheel",
                    "yanked": False,
                    "digests": {"sha256": "a" * 64},
                    "size": 1234,
                    "url": "https://example.invalid/wheel",
                }
            ]
        }
    }

    class _Response:
        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

    files = tool.fetch_pypi_core_files(
        "0.42.0", urlopen=lambda url, timeout=0: _Response()
    )
    assert files[0]["size"] == 1234
    plan_files = _fresh_files()
    assert all("size" in entry for entry in plan_files)
    assert _dists()[0]["size"] == 1024

"""Publish-plan and confirm tests for the release_candidate tool."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

import pytest

from tests._release_candidate_tool_helpers import dists
from tests._release_candidate_tool_helpers import load_tool
from tests._release_candidate_tool_helpers import seal_kwargs


pytestmark = pytest.mark.contract


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    return load_tool()


def _stage_manifest(tool: ModuleType, tmp_path: Path, **overrides: object):
    manifest = tool.seal_manifest(**seal_kwargs(**overrides))  # type: ignore[arg-type]
    staged = tmp_path / "staged"
    staged.mkdir(parents=True, exist_ok=True)
    for dist in manifest["dists"]:
        assert isinstance(dist, dict)
        data = (dist["filename"] + "\n").encode() * 64
        digest = __import__("hashlib").sha256(data).hexdigest()
        dist["sha256"] = digest
        dist["size"] = len(data)
        (staged / dist["filename"]).write_bytes(data)
    manifest["candidate_id"] = tool.candidate_id(manifest)
    return manifest, staged


def _pypi_entry(filename: str, sha256: str) -> dict[str, object]:
    return {
        "filename": filename,
        "packagetype": "bdist_wheel" if filename.endswith(".whl") else "sdist",
        "digests": {"sha256": sha256},
    }


def test_publish_plan_uploads_missing_and_skips_identical(
    tool: ModuleType, tmp_path: Path
) -> None:
    manifest, staged = _stage_manifest(tool, tmp_path)
    names = [d["filename"] for d in manifest["dists"]]
    pypi = [
        _pypi_entry(names[0], manifest["dists"][0]["sha256"]),
    ]
    plan = tool.compute_publish_plan(manifest, pypi, staged)
    by_name = {f["filename"]: f["action"] for f in plan["files"]}
    assert by_name[names[0]] == "already-present"
    assert by_name[names[1]] == "upload"


def test_publish_plan_resume_after_one_upload(tool: ModuleType, tmp_path: Path) -> None:
    manifest, staged = _stage_manifest(tool, tmp_path)
    names = [d["filename"] for d in manifest["dists"]]
    pypi = [
        _pypi_entry(name, manifest["dists"][i]["sha256"])
        for i, name in enumerate(names[:1])
    ]
    first = tool.compute_publish_plan(manifest, pypi, staged)
    assert [f["action"] for f in first["files"]] == ["already-present", "upload"]
    pypi_all = [
        _pypi_entry(name, manifest["dists"][i]["sha256"])
        for i, name in enumerate(names)
    ]
    second = tool.compute_publish_plan(manifest, pypi_all, staged)
    assert [f["action"] for f in second["files"]] == [
        "already-present",
        "already-present",
    ]


def test_publish_plan_refuses_different_hash(tool: ModuleType, tmp_path: Path) -> None:
    manifest, staged = _stage_manifest(tool, tmp_path)
    name = manifest["dists"][0]["filename"]
    with pytest.raises(tool.Refusal, match="PUBLISH_CONFLICT"):
        tool.compute_publish_plan(manifest, [_pypi_entry(name, "0" * 64)], staged)


def test_publish_plan_refuses_extra_pypi_file(tool: ModuleType, tmp_path: Path) -> None:
    manifest, staged = _stage_manifest(tool, tmp_path)
    names = [d["filename"] for d in manifest["dists"]]
    pypi = [
        _pypi_entry(name, manifest["dists"][i]["sha256"])
        for i, name in enumerate(names)
    ]
    pypi.append(_pypi_entry("sase-0.18.0-extra.tar.gz", "f" * 64))
    with pytest.raises(tool.Refusal, match="PUBLISH_CONFLICT"):
        tool.compute_publish_plan(manifest, pypi, staged)


def test_publish_plan_refuses_missing_staged_asset(
    tool: ModuleType, tmp_path: Path
) -> None:
    manifest, staged = _stage_manifest(tool, tmp_path)
    missing = manifest["dists"][0]["filename"]
    (staged / missing).unlink()
    with pytest.raises(tool.Refusal, match="PUBLISH_MISSING_ASSET"):
        tool.compute_publish_plan(manifest, [], staged)


def test_publish_plan_accepts_both_pypi_shapes(
    tool: ModuleType, tmp_path: Path
) -> None:
    manifest, staged = _stage_manifest(tool, tmp_path)
    version = manifest["version"]
    names = [d["filename"] for d in manifest["dists"]]
    urls_payload = {
        "urls": [
            _pypi_entry(name, manifest["dists"][i]["sha256"])
            for i, name in enumerate(names)
        ]
    }
    releases_payload = {"releases": {version: urls_payload["urls"]}}
    assert tool._pypi_sase_entries(urls_payload, version) == urls_payload["urls"]
    assert tool._pypi_sase_entries(releases_payload, version) == urls_payload["urls"]
    assert tool._pypi_sase_entries({"releases": {}}, version) == []


def test_confirm_requires_every_file_and_refuses_extra(
    tool: ModuleType, tmp_path: Path
) -> None:
    manifest, _staged = _stage_manifest(tool, tmp_path)
    names = [d["filename"] for d in manifest["dists"]]
    full = [
        _pypi_entry(name, manifest["dists"][i]["sha256"])
        for i, name in enumerate(names)
    ]
    report = tool.confirm_pypi_files(manifest, full)
    assert report["complete"] is True
    with pytest.raises(tool.Refusal, match="PUBLISH_PARTIAL"):
        tool.confirm_pypi_files(manifest, full[:1])
    with pytest.raises(tool.Refusal, match="PUBLISH_CONFLICT"):
        tool.confirm_pypi_files(manifest, [_pypi_entry(names[0], "0" * 64), full[1]])


def test_dist_helpers_still_cover_publish_fixtures() -> None:
    assert len(dists()) == 2

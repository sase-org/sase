"""Tests for the public launch-bundle locator and shared integrity check."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.instructions.manifests import (
    check_bundle_integrity,
    launch_root_bundle,
    run_bundle_paths,
)
from tests.instructions.fixture_shadow import write_helper_shadow, write_shadow_run


@pytest.fixture(autouse=True)
def _passthrough_manifest_normalize(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.core.instruction_manifest.normalize_instruction_manifest",
        lambda payload: payload,
    )


def _set_delivery(manifest_path: Path, *, status: str, channel: str | None) -> None:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["delivery"]["status"] = status
    payload["delivery"]["channel"] = channel
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def test_launch_root_bundle_picks_lowest_non_helper_with_path(
    tmp_path: Path,
) -> None:
    artifacts, root, _bundle = write_shadow_run(
        tmp_path, provider="claude", seq=1, artifacts_dir=tmp_path / "art"
    )
    write_shadow_run(tmp_path, provider="claude", seq=0, artifacts_dir=artifacts)
    write_helper_shadow(
        artifacts,
        provider="claude",
        seq=0,
        parent_invocation_id=str(root["delivery"]["invocation_id"]),
    )
    located = launch_root_bundle(artifacts)
    assert located is not None
    assert located.entry.seq == 0
    assert located.entry.is_helper is False
    assert located.entry.bundle_path is not None
    assert located.entry.bundle_path.name == "00-claude.md"


def test_launch_root_bundle_skips_root_without_bundle_path(tmp_path: Path) -> None:
    artifacts, _root, _bundle = write_shadow_run(
        tmp_path, provider="codex", seq=0, artifacts_dir=tmp_path / "art"
    )
    (artifacts / "instructions" / "00-codex.md").unlink()
    write_shadow_run(tmp_path, provider="codex", seq=1, artifacts_dir=artifacts)
    located = launch_root_bundle(artifacts)
    assert located is not None
    assert located.entry.seq == 1


def test_launch_root_bundle_returns_none_without_manifests(tmp_path: Path) -> None:
    assert launch_root_bundle(tmp_path / "missing") is None


def test_launch_root_bundle_reports_explicit_delivery(tmp_path: Path) -> None:
    artifacts, _root, _bundle = write_shadow_run(
        tmp_path, provider="claude", artifacts_dir=tmp_path / "art"
    )
    _set_delivery(
        artifacts / "instructions" / "00-claude.json",
        status="explicit",
        channel="claude.append_system_prompt_file",
    )
    located = launch_root_bundle(artifacts)
    assert located is not None
    assert located.is_explicit
    assert located.delivery_status == "explicit"
    assert located.integrity.ok


def test_launch_root_bundle_fallback_is_not_explicit(tmp_path: Path) -> None:
    artifacts, _root, _bundle = write_shadow_run(
        tmp_path, provider="agy", artifacts_dir=tmp_path / "art"
    )
    _set_delivery(
        artifacts / "instructions" / "00-agy.json",
        status="inherits_native",
        channel=None,
    )
    located = launch_root_bundle(artifacts)
    assert located is not None
    assert located.is_explicit is False
    assert located.delivery_status == "inherits_native"


def test_check_bundle_integrity_mismatch(tmp_path: Path) -> None:
    artifacts, _root, _bundle = write_shadow_run(
        tmp_path, provider="codex", artifacts_dir=tmp_path / "art"
    )
    bundle = artifacts / "instructions" / "00-codex.md"
    bundle.write_text(bundle.read_text(encoding="utf-8") + "tamper\n", encoding="utf-8")
    located = launch_root_bundle(artifacts)
    assert located is not None
    assert located.integrity.label == "MISMATCH"
    assert not located.integrity.ok
    assert check_bundle_integrity(located.entry).label == "MISMATCH"


def test_run_bundle_paths_orders_root_then_helper(tmp_path: Path) -> None:
    artifacts, root, _bundle = write_shadow_run(
        tmp_path, provider="claude", artifacts_dir=tmp_path / "art"
    )
    write_helper_shadow(
        artifacts,
        provider="claude",
        parent_invocation_id=str(root["delivery"]["invocation_id"]),
    )
    paths = run_bundle_paths(artifacts)
    names = [Path(path).name for path in paths]
    assert names == ["00-claude.md", "00-claude.helper.md"]

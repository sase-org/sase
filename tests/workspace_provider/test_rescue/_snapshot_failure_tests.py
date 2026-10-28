from __future__ import annotations

import json
from pathlib import Path

import pytest

import sase.workspace_provider as workspace_provider
from sase.workspace_provider._snapshot_model import SourceState
from sase.workspace_provider.snapshot import (
    PreservationError,
    snapshot_source_fingerprint,
)
from tests.workspace_provider.test_rescue._helpers import (
    redirect_state,
    rescue_entries,
    seed_remote_clone,
)
from tests.workspace_provider.test_rescue._snapshot_helpers import (
    assert_source_unchanged,
    head,
    index_bytes,
    make_dirty_wiring,
    snapshot,
    source_probe,
)

payload_module = workspace_provider._snapshot_capture_payload
payload_objects_module = workspace_provider._snapshot_capture_payload_objects
source_module = workspace_provider._snapshot_capture_source


def test_snapshot_capture_failure_leaves_source_and_prior_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _notified = redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    make_dirty_wiring(clone)
    first = snapshot(clone, workspace, reason="first")
    assert first is not None
    first_manifest = first.manifest_path.read_text(encoding="utf-8")
    before = source_probe(clone)

    def boom(*_args: object, **_kwargs: object) -> object:
        raise OSError("injected pack failure")

    monkeypatch.setattr(payload_module, "write_pack", boom)
    with pytest.raises(PreservationError, match="injected pack failure"):
        snapshot(clone, workspace, reason="second")
    assert_source_unchanged(clone, before)
    assert first.rescue_dir.is_dir()
    assert first.manifest_path.read_text(encoding="utf-8") == first_manifest
    published = [
        entry for entry in rescue_entries(home) if (entry / "manifest.json").is_file()
    ]
    assert published == [first.rescue_dir]


def test_snapshot_manifest_failure_does_not_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _notified = redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    make_dirty_wiring(clone)
    before = source_probe(clone)

    def boom(*_args: object, **_kwargs: object) -> object:
        raise OSError("injected manifest failure")

    monkeypatch.setattr(payload_module, "publish_manifest", boom)
    with pytest.raises(PreservationError, match="injected manifest failure"):
        snapshot(clone, workspace)
    assert_source_unchanged(clone, before)
    assert rescue_entries(home) == []


def test_snapshot_size_cap_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _notified = redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    make_dirty_wiring(clone)
    (clone / "src" / "dispatch.py").write_text("x" * 200, encoding="utf-8")
    before = source_probe(clone)
    monkeypatch.setattr(payload_objects_module, "SNAPSHOT_MAX_BYTES", 16)

    with pytest.raises(PreservationError, match="cap"):
        snapshot(clone, workspace, reason="cap")
    assert_source_unchanged(clone, before)
    assert rescue_entries(home) == []


def test_snapshot_detects_source_change_during_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _notified = redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    make_dirty_wiring(clone)
    before = source_probe(clone)
    original = source_module.read_source_state
    calls = {"n": 0}

    def flipped(repo: Path) -> SourceState:
        calls["n"] += 1
        state = original(repo)
        if calls["n"] >= 2:
            (repo / "src" / "dispatch.py").write_text(
                "changed-during-capture\n", encoding="utf-8"
            )
            return original(repo)
        return state

    monkeypatch.setattr(source_module, "read_source_state", flipped)
    with pytest.raises(PreservationError, match="changed during snapshot"):
        snapshot(clone, workspace, reason="race")
    assert calls["n"] >= 2
    assert rescue_entries(home) == []
    assert (clone / "src" / "dispatch.py").read_text(encoding="utf-8") == (
        "changed-during-capture\n"
    )
    assert head(clone) == before[0]
    assert index_bytes(clone) == before[1]


def test_snapshot_source_fingerprint_tracks_untracked_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    _workspace, clone, _remote = seed_remote_clone(tmp_path)
    untracked = clone / "src" / "new.py"
    untracked.parent.mkdir()
    untracked.write_bytes(b"first version\n")

    first = snapshot_source_fingerprint(clone)
    untracked.write_bytes(b"second version\n")
    second = snapshot_source_fingerprint(clone)

    assert first != second


def test_snapshot_detects_untracked_source_change_during_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, _notified = redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    untracked = clone / "src" / "new.py"
    untracked.parent.mkdir()
    untracked.write_bytes(b"before capture\n")
    original = source_module.read_source_state
    calls = {"n": 0}

    def flipped(repo: Path) -> SourceState:
        calls["n"] += 1
        state = original(repo)
        if calls["n"] >= 2:
            (repo / "src" / "new.py").write_bytes(b"changed during capture\n")
            return original(repo)
        return state

    monkeypatch.setattr(source_module, "read_source_state", flipped)
    with pytest.raises(PreservationError, match="changed during snapshot"):
        snapshot(clone, workspace, reason="untracked-race")

    assert calls["n"] >= 2
    assert rescue_entries(home) == []
    assert untracked.read_bytes() == b"changed during capture\n"


def test_snapshot_ids_are_unique_for_same_head_and_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_state(tmp_path, monkeypatch)
    workspace, clone, _remote = seed_remote_clone(tmp_path)
    make_dirty_wiring(clone)
    first = snapshot(clone, workspace, reason="one")
    second = snapshot(clone, workspace, reason="two")
    assert first is not None and second is not None
    assert first.snapshot_id != second.snapshot_id
    assert first.rescue_dir != second.rescue_dir
    assert first.manifest_path != second.manifest_path
    assert first.rescue_dir.is_dir()
    assert second.rescue_dir.is_dir()

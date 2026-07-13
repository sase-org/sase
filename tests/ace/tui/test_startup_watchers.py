"""Startup watcher path selection tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.actions._startup_watchers import StartupWatchersMixin
from tests.sdd_policy_helpers import set_sdd_policy


class _Harness(StartupWatchersMixin):
    def __init__(self) -> None:
        self._fs_watcher = None
        self._sdd_beads_dir = None

    def _on_artifact_change(
        self, changed_paths: tuple[Path, ...] | None = None
    ) -> None:
        del changed_paths

    def call_from_thread(self, callback: Any, *args: Any, **kwargs: Any) -> None:
        del callback, args, kwargs


def test_artifact_watcher_targets_resolved_local_sdd_beads_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase_home"))
    (tmp_path / "sase_home" / "projects").mkdir(parents=True)
    beads_dir = tmp_path / ".sase" / "sdd" / "beads"
    beads_dir.mkdir(parents=True)
    set_sdd_policy(monkeypatch, "local")
    captured_paths: list[Path] = []

    class _FakeWatcher:
        def __init__(self, watch_paths: list[Path], **kwargs: Any) -> None:
            del kwargs
            captured_paths.extend(watch_paths)

        def start(self) -> bool:
            return True

    monkeypatch.setattr(
        "sase.ace.tui.actions._startup_watchers.ArtifactWatcher",
        _FakeWatcher,
    )
    app = _Harness()

    app._start_artifact_watcher()

    assert app._sdd_beads_dir == beads_dir
    assert beads_dir in captured_paths


def test_artifact_watcher_targets_plans_sidecar_beads_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.sdd.store import write_sdd_store_record

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase_home"))
    (tmp_path / "sase_home" / "projects").mkdir(parents=True)
    write_sdd_store_record(
        tmp_path,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                "plans": {
                    "repo": "acme/project--plans",
                    "remote_url": "git@example.com:acme/project--plans.git",
                },
                "research": {
                    "repo": "acme/project--research",
                    "remote_url": "git@example.com:acme/project--research.git",
                },
            },
        },
    )
    beads_dir = tmp_path / "sase" / "repos" / "plans" / "beads"
    beads_dir.mkdir(parents=True)
    captured_paths: list[Path] = []

    class _FakeWatcher:
        def __init__(self, watch_paths: list[Path], **kwargs: Any) -> None:
            del kwargs
            captured_paths.extend(watch_paths)

        def start(self) -> bool:
            return True

    monkeypatch.setattr(
        "sase.ace.tui.actions._startup_watchers.ArtifactWatcher",
        _FakeWatcher,
    )
    app = _Harness()

    app._start_artifact_watcher()

    assert app._sdd_beads_dir == beads_dir
    assert beads_dir in captured_paths

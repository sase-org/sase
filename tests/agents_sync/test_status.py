from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import status
from sase.agents_sync.io import write_manifest
from sase.agents_sync.models import (
    AgentsManifest,
    ProjectSyncStatus,
    ProjectTarget,
    SyncStatusSnapshot,
    TargetSelection,
)


def _target(tmp_path: Path) -> ProjectTarget:
    primary = tmp_path / "primary"
    primary.mkdir()
    repo = tmp_path / "agents"
    (repo / ".git").mkdir(parents=True)
    write_manifest(repo / "manifest.json", AgentsManifest())
    return ProjectTarget(
        "proj",
        "Project",
        primary,
        (primary.resolve(),),
        repo,
        "remote",
    )


def test_fresh_status_revalidates_without_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _target(tmp_path)
    cache = tmp_path / "status.json"
    previous = SyncStatusSnapshot(
        100.0,
        (ProjectSyncStatus("proj", "Project", "ready", 0, 0, 0, last_fetch_time=90.0),),
    )
    status._write_agents_sync_status_snapshot(previous, path=cache)
    calls: list[tuple[str, bool]] = []

    def runner(
        _cwd: Path, args: list[str], *, network: bool = False, op: str = ""
    ) -> subprocess.CompletedProcess[str]:
        calls.append((args[0], network))
        if args[:2] == ["rev-parse", "--verify"]:
            return subprocess.CompletedProcess(args, 0, "upstream\n", "")
        if args[0] == "rev-list":
            return subprocess.CompletedProcess(args, 0, "2 3\n", "")
        raise AssertionError(args)

    monkeypatch.setattr(
        status, "resolve_sync_targets", lambda _projects: TargetSelection((target,), ())
    )
    monkeypatch.setattr(status, "require_machine_name", lambda: "athena")
    monkeypatch.setattr(status, "count_unexported_local_agents", lambda *_a, **_k: 4)

    snapshot = status.get_agents_sync_status(
        now=101.0, ttl_seconds=10.0, git_runner=runner, path=cache
    )

    assert calls == [("rev-parse", False), ("rev-list", False)]
    current = snapshot.projects[0]
    assert (current.ahead, current.behind, current.unexported_agents) == (2, 3, 4)
    assert current.last_fetch_time == 90.0


@pytest.mark.parametrize("cache_contents", [None, "{broken"])
def test_stale_or_corrupt_status_fetches_then_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cache_contents: str | None,
) -> None:
    target = _target(tmp_path)
    cache = tmp_path / "status.json"
    if cache_contents is None:
        status._write_agents_sync_status_snapshot(
            SyncStatusSnapshot(1.0, ()), path=cache
        )
    else:
        cache.write_text(cache_contents)
    calls: list[tuple[str, bool]] = []

    def runner(
        _cwd: Path, args: list[str], *, network: bool = False, op: str = ""
    ) -> subprocess.CompletedProcess[str]:
        calls.append((args[0], network))
        if args[0] == "fetch":
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:2] == ["rev-parse", "--verify"]:
            return subprocess.CompletedProcess(args, 0, "upstream\n", "")
        if args[0] == "rev-list":
            return subprocess.CompletedProcess(args, 0, "0 1\n", "")
        raise AssertionError(args)

    monkeypatch.setattr(
        status, "resolve_sync_targets", lambda _projects: TargetSelection((target,), ())
    )
    monkeypatch.setattr(status, "require_machine_name", lambda: "athena")
    monkeypatch.setattr(status, "count_unexported_local_agents", lambda *_a, **_k: 0)

    snapshot = status.get_agents_sync_status(
        now=1000.0, ttl_seconds=10.0, git_runner=runner, path=cache
    )

    assert calls[0] == ("fetch", True)
    assert snapshot.projects[0].behind == 1
    assert snapshot.projects[0].last_fetch_time == 1000.0
    assert status._read_agents_sync_status_snapshot(path=cache) == snapshot


def test_post_sync_rewrite_never_fetches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _target(tmp_path)

    def runner(
        _cwd: Path, args: list[str], *, network: bool = False, op: str = ""
    ) -> subprocess.CompletedProcess[str]:
        assert not network
        assert args[0] != "fetch"
        if args[:2] == ["rev-parse", "--verify"]:
            return subprocess.CompletedProcess(args, 0, "upstream\n", "")
        return subprocess.CompletedProcess(args, 0, "0 0\n", "")

    monkeypatch.setattr(
        status, "resolve_sync_targets", lambda _projects: TargetSelection((target,), ())
    )
    monkeypatch.setattr(status, "require_machine_name", lambda: "athena")
    monkeypatch.setattr(status, "count_unexported_local_agents", lambda *_a, **_k: 0)
    monkeypatch.setattr(
        status, "_status_snapshot_path", lambda: tmp_path / "cache.json"
    )

    snapshot = status.rewrite_agents_sync_status_after_sync(now=50.0, git_runner=runner)

    assert snapshot.projects[0].state == "ready"

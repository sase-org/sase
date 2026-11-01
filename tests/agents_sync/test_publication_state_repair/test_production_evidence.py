"""Production-path state repair through filesystem observations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.agents_sync.agent_state_refresh import run_agent_state_refresh
from sase.agents_sync.inventory_models import InventoryRun, ProjectHoodInventory
from sase.agents_sync.publication import publish_agent_hood
from sase.agents_sync.publication_state_repair import repair_project_run_states
from sase.agents_sync.publication_validation import read_hood_snapshot
from sase.core.agent_identity_facade import AgentIdentitySnapshot
from tests.agents_sync.test_publication_state_repair._helpers import (
    FINISHED,
    OWNER,
    STARTED,
    SeedBuilder,
    commit_push,
    install_repair_home,
    rebuild_repair_artifact_index,
    remote_head,
    remote_state,
    repair_run_id,
    setup_repair,
    write_repair_artifact,
)

from tests.agents_sync.git_sync_fixtures import setup_repo, target


def _run_id(timestamp: str) -> str:
    return repair_run_id(timestamp)


def _install_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return install_repair_home(tmp_path, monkeypatch)


def _write_artifact(
    home: Path,
    *,
    timestamp: str,
    name: str,
    outcome: str | None,
    extra_done: dict[str, object] | None = None,
    extra_files: dict[str, str] | None = None,
) -> Path:
    return write_repair_artifact(
        home,
        timestamp=timestamp,
        name=name,
        outcome=outcome,
        extra_done=extra_done,
        extra_files=extra_files,
    )


def _rebuild_index(home: Path) -> Path:
    return rebuild_repair_artifact_index(home)


def _work(tmp_path: Path) -> Path:
    work = tmp_path / "sidecar-work"
    work.mkdir(exist_ok=True)
    return work


def test_production_completed_marker_repairs_selected_run_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _install_home(tmp_path, monkeypatch)
    keep_ts = "20260723120000"
    other_ts = "20260723120001"
    keep_id = _run_id(keep_ts)
    other_id = _run_id(other_ts)
    _write_artifact(
        home,
        timestamp=keep_ts,
        name="foo.keep",
        outcome="completed",
        extra_files={"raw_prompt.md": "keep prompt\n", "chat.md": "keep chat\n"},
    )
    _write_artifact(
        home,
        timestamp=other_ts,
        name="foo.other",
        outcome="completed",
        extra_files={"raw_prompt.md": "other prompt\n", "chat.md": "other chat\n"},
    )
    _rebuild_index(home)

    remote, sync_target = setup_repair(
        _work(tmp_path),
        runs=[
            ("foo", "foo.keep", keep_id, "active"),
            ("foo", "foo.other", other_id, "active"),
        ],
    )
    reads: list[Path] = []

    def track(path: Path) -> None:
        reads.append(path)

    import sase.agents_sync._publication_state_repair_observations_io as observations_io

    monkeypatch.setattr(observations_io, "_READ_HOOK", track)
    report = repair_project_run_states(sync_target, OWNER, apply=True, state_limit=1)

    assert report.error is None
    assert report.examined == 1
    assert report.changed == 1
    assert report.window
    selected_id = report.window[0].source_run_id
    keep_selected = selected_id == keep_id
    assert remote_state(remote, "alice.athena.foo.keep") == (
        "completed" if keep_selected else "active"
    )
    assert remote_state(remote, "alice.athena.foo.other") == (
        "completed" if not keep_selected else "active"
    )
    read_names = {path.name for path in reads}
    assert "done.json" in read_names or "agent_meta.json" in read_names
    assert "raw_prompt.md" not in read_names
    assert "chat.md" not in read_names
    artifact_root = home / "projects" / "proj" / "artifacts" / "ace-run"
    selected_root = artifact_root / (keep_ts if keep_selected else other_ts)
    sibling_root = artifact_root / (other_ts if keep_selected else keep_ts)
    assert any(selected_root in path.parents or path == selected_root for path in reads)
    assert not any(
        sibling_root in path.parents or path == sibling_root for path in reads
    )

    remaining = repair_project_run_states(
        sync_target, OWNER, apply=True, state_after=report.next_cursor
    )
    assert remaining.error is None
    assert remaining.changed == 1
    assert remote_state(remote, "alice.athena.foo.keep") == "completed"
    assert remote_state(remote, "alice.athena.foo.other") == "completed"
    noop = repair_project_run_states(sync_target, OWNER, apply=True)
    assert noop.error is None
    assert noop.changed == 0
    assert noop.pass_complete is True


def test_production_malformed_and_mismatched_markers_stay_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _install_home(tmp_path, monkeypatch)
    empty_ts = "20260723130000"
    bad_ts = "20260723130001"
    mismatch_ts = "20260723130002"
    empty_id = _run_id(empty_ts)
    bad_id = _run_id(bad_ts)
    mismatch_id = _run_id(mismatch_ts)
    _write_artifact(home, timestamp=empty_ts, name="foo.empty", outcome=None)
    (
        home / "projects" / "proj" / "artifacts" / "ace-run" / empty_ts / "done.json"
    ).write_text("{}", encoding="utf-8")
    _write_artifact(home, timestamp=bad_ts, name="foo.bad", outcome="mystery")
    _write_artifact(
        home,
        timestamp=mismatch_ts,
        name="foo.mismatch",
        outcome="completed",
        extra_done={"name": "other.job"},
    )
    _rebuild_index(home)
    remote, sync_target = setup_repair(
        _work(tmp_path),
        runs=[
            ("foo", "foo.empty", empty_id, "active"),
            ("foo", "foo.bad", bad_id, "waiting"),
            ("foo", "foo.mismatch", mismatch_id, "active"),
        ],
    )

    report = repair_project_run_states(sync_target, OWNER, apply=True)

    assert report.error is None
    assert report.changed == 0
    assert report.unresolved >= 1
    assert remote_state(remote, "alice.athena.foo.empty") == "active"
    assert remote_state(remote, "alice.athena.foo.bad") == "waiting"
    assert remote_state(remote, "alice.athena.foo.mismatch") == "active"


def test_production_stopped_and_failed_markers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _install_home(tmp_path, monkeypatch)
    stopped_ts = "20260723140000"
    failed_ts = "20260723140001"
    stopped_id = _run_id(stopped_ts)
    failed_id = _run_id(failed_ts)
    _write_artifact(home, timestamp=stopped_ts, name="foo.stop", outcome="stopped")
    _write_artifact(home, timestamp=failed_ts, name="foo.fail", outcome="failed")
    _rebuild_index(home)
    remote, sync_target = setup_repair(
        _work(tmp_path),
        runs=[
            ("foo", "foo.stop", stopped_id, "active"),
            ("foo", "foo.fail", failed_id, "waiting"),
        ],
    )

    report = repair_project_run_states(sync_target, OWNER, apply=True)

    assert report.error is None
    assert report.changed == 2
    assert remote_state(remote, "alice.athena.foo.stop") == "stopped"
    assert remote_state(remote, "alice.athena.foo.fail") == "failed"


def test_later_publication_does_not_regress_repaired_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _install_home(tmp_path, monkeypatch)
    timestamp = "20260723150000"
    run_id = _run_id(timestamp)
    _write_artifact(home, timestamp=timestamp, name="foo.job", outcome="completed")
    _rebuild_index(home)
    work = _work(tmp_path)
    remote, _seed, sidecar = setup_repo(work)
    builder = SeedBuilder(sidecar)
    builder.add_run("foo", "foo.job", run_id, "active")
    builder.write_manifest()
    commit_push(sidecar)
    sync_target = target(work, remote, sidecar)

    first = repair_project_run_states(sync_target, OWNER, apply=True)
    assert first.changed == 1
    assert remote_state(remote, "alice.athena.foo.job") == "completed"

    stale = InventoryRun(
        run_id,
        "foo.job",
        "alice.athena.foo.job",
        "active",
        STARTED,
        None,
        None,
        (),
        (),
        b"prompt\n",
        b"chat\n",
        None,
        None,
        (),
        timestamp,
    )
    publish_agent_hood(
        sync_target,
        sidecar,
        "foo.job",
        identity=AgentIdentitySnapshot(OWNER),
        inventory=ProjectHoodInventory(OWNER, "proj", (stale,)),
    )
    snapshot = read_hood_snapshot(
        sidecar
        / "users"
        / "alice"
        / "machines"
        / "athena"
        / "hoods"
        / "foo"
        / "snapshot.json"
    )
    assert snapshot is not None
    assert snapshot.runs[0].state == "completed"


def test_scheduler_freezes_cursor_on_unreadable_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_home(tmp_path, monkeypatch)
    work = _work(tmp_path)
    remote, _seed, sidecar = setup_repo(work)
    builder = SeedBuilder(sidecar)
    builder.add_run("foo", "foo.job", "run-1", "active")
    builder.write_manifest()
    (sidecar / "users" / "alice" / "machines" / "athena" / "manifest.json").write_bytes(
        b"{not json"
    )
    commit_push(sidecar)
    sync_target = target(work, remote, sidecar)
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    summary = run_agent_state_refresh(
        state_dir=state_dir,
        list_targets=lambda: ([sync_target], []),
        require_owner=lambda: OWNER,
    )

    assert summary.reason == "project_failed"
    assert summary.pass_complete is False
    payload = json.loads((state_dir / "agent_state_refresh.json").read_text())
    cursor = payload["projects"]["proj:alice@athena"]["cursor"]
    assert cursor is None
    assert remote_head(remote) is not None

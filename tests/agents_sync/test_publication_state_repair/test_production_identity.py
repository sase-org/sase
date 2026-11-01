"""Identity, symlink, and imported-evidence production regressions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.agents_sync.publication_state_repair import repair_project_run_states
from tests.agents_sync.test_publication_state_repair._helpers import (
    OWNER,
    install_repair_home,
    rebuild_repair_artifact_index,
    remote_state,
    repair_run_id,
    setup_repair,
    write_repair_artifact,
)


def _work(tmp_path: Path) -> Path:
    work = tmp_path / "sidecar-work"
    work.mkdir(exist_ok=True)
    return work


def test_changed_artifact_id_after_index_stays_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = install_repair_home(tmp_path, monkeypatch)
    timestamp = "20260723160000"
    run_id = repair_run_id(timestamp)
    artifact = write_repair_artifact(
        home, timestamp=timestamp, name="foo.job", outcome="completed"
    )
    rebuild_repair_artifact_index(home)
    meta_path = artifact / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["artifact_agent_id"] = "20260723999999"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    remote, sync_target = setup_repair(
        _work(tmp_path), runs=[("foo", "foo.job", run_id, "active")]
    )

    report = repair_project_run_states(sync_target, OWNER, apply=True)

    assert report.error is None
    assert report.changed == 0
    assert report.unresolved >= 1
    assert remote_state(remote, "alice.athena.foo.job") == "active"


def test_conflicting_meta_and_done_names_stay_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = install_repair_home(tmp_path, monkeypatch)
    timestamp = "20260723160001"
    run_id = repair_run_id(timestamp)
    artifact = write_repair_artifact(
        home, timestamp=timestamp, name="foo.job", outcome="completed"
    )
    rebuild_repair_artifact_index(home)
    meta_path = artifact / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["name"] = "other.job"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    remote, sync_target = setup_repair(
        _work(tmp_path), runs=[("foo", "foo.job", run_id, "active")]
    )

    report = repair_project_run_states(sync_target, OWNER, apply=True)

    assert report.error is None
    assert report.changed == 0
    assert report.unresolved >= 1
    assert remote_state(remote, "alice.athena.foo.job") == "active"


def test_malformed_identity_metadata_does_not_accept_anonymous_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = install_repair_home(tmp_path, monkeypatch)
    timestamp = "20260723160002"
    run_id = repair_run_id(timestamp)
    artifact = write_repair_artifact(
        home, timestamp=timestamp, name="foo.job", outcome="completed"
    )
    rebuild_repair_artifact_index(home)
    (artifact / "agent_meta.json").write_bytes(b"{not json")
    remote, sync_target = setup_repair(
        _work(tmp_path), runs=[("foo", "foo.job", run_id, "active")]
    )

    report = repair_project_run_states(sync_target, OWNER, apply=True)

    assert report.error is None
    assert report.changed == 0
    assert remote_state(remote, "alice.athena.foo.job") == "active"


def test_imported_marker_does_not_repair_local_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = install_repair_home(tmp_path, monkeypatch)
    timestamp = "20260723160003"
    run_id = repair_run_id(timestamp)
    write_repair_artifact(
        home,
        timestamp=timestamp,
        name="foo.job",
        outcome="completed",
        extra_meta={"imported_from_machine": "other@host"},
    )
    rebuild_repair_artifact_index(home)
    remote, sync_target = setup_repair(
        _work(tmp_path), runs=[("foo", "foo.job", run_id, "active")]
    )

    report = repair_project_run_states(sync_target, OWNER, apply=True)

    assert report.error is None
    assert report.changed == 0
    assert remote_state(remote, "alice.athena.foo.job") == "active"


def test_symlink_escape_outside_projects_root_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = install_repair_home(tmp_path, monkeypatch)
    timestamp = "20260723160004"
    run_id = repair_run_id(timestamp)
    artifact = write_repair_artifact(
        home, timestamp=timestamp, name="foo.job", outcome="completed"
    )
    rebuild_repair_artifact_index(home)
    outside = tmp_path / "outside-artifact"
    artifact.rename(outside)
    artifact.symlink_to(outside)
    remote, sync_target = setup_repair(
        _work(tmp_path), runs=[("foo", "foo.job", run_id, "active")]
    )

    report = repair_project_run_states(sync_target, OWNER, apply=True)

    assert report.error is None
    assert report.changed == 0
    assert report.unresolved >= 1
    assert remote_state(remote, "alice.athena.foo.job") == "active"

"""Real dismissed-archive lookup regressions for state repair."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.ace.dismissed_bundle_index import (
    INDEX_FILENAME,
    rebuild_index,
    upsert_bundle_summary,
)
from sase.agents_sync.publication_state_repair import repair_project_run_states
from tests.agents_sync.test_publication_state_repair._helpers import (
    FINISHED,
    OWNER,
    STARTED,
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


def _write_dismissed_bundle(
    home: Path,
    *,
    timestamp: str,
    agent_name: str | None,
    cl_name: str,
    run_id: str,
    extra: dict[str, object] | None = None,
    index: bool = True,
) -> Path:
    root = home / "dismissed_bundles"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{timestamp}.json"
    payload: dict[str, object] = {
        "raw_suffix": timestamp,
        "source_username": "alice",
        "source_machine": "athena",
        "source_run_id": run_id,
        "agent_type": "agent",
        "cl_name": cl_name,
        "agent_name": agent_name,
        "status": "DONE",
        "project_name": "proj",
        "project_file": "/projects/proj/proj.sase",
        "archive_visibility": "hidden",
        "archive_schema_version": 1,
        "start_time": STARTED,
        "stop_time": FINISHED,
    }
    if extra:
        payload.update(extra)
    path.write_text(json.dumps(payload), encoding="utf-8")
    if index:
        rebuild_index(root)
        assert upsert_bundle_summary(root, path, payload)
    return path


def test_dismissed_bundle_with_distinct_patch_name_repairs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = install_repair_home(tmp_path, monkeypatch)
    timestamp = "20260723170000"
    run_id = repair_run_id(timestamp)
    _write_dismissed_bundle(
        home,
        timestamp=timestamp,
        agent_name="foo.job",
        cl_name="SomePatch",
        run_id=run_id,
    )
    remote, sync_target = setup_repair(
        _work(tmp_path), runs=[("foo", "foo.job", run_id, "active")]
    )

    report = repair_project_run_states(sync_target, OWNER, apply=True)

    assert report.error is None
    assert report.changed == 1
    assert remote_state(remote, "alice.athena.foo.job") == "dismissed"


def test_dismissed_lookup_finds_target_after_more_than_sixty_four_unrelated_bundles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = install_repair_home(tmp_path, monkeypatch)
    root = home / "dismissed_bundles"
    for index in range(70):
        _write_dismissed_bundle(
            home,
            timestamp=f"202607231710{index:02d}",
            agent_name=f"unrelated.{index}",
            cl_name="OtherPatch",
            run_id=f"unrelated-run-{index}",
            index=False,
        )
    timestamp = "20260723171999"
    run_id = repair_run_id(timestamp)
    _write_dismissed_bundle(
        home,
        timestamp=timestamp,
        agent_name="foo.job",
        cl_name="SomePatch",
        run_id=run_id,
        index=False,
    )
    rebuild_index(root)
    remote, sync_target = setup_repair(
        _work(tmp_path), runs=[("foo", "foo.job", run_id, "active")]
    )

    report = repair_project_run_states(sync_target, OWNER, apply=True)

    assert report.error is None
    assert report.changed == 1
    assert remote_state(remote, "alice.athena.foo.job") == "dismissed"


def test_dismissed_lookup_uses_run_id_when_agent_name_was_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = install_repair_home(tmp_path, monkeypatch)
    root = home / "dismissed_bundles"
    target_timestamp = "20260723172000"
    target_run_id = repair_run_id(target_timestamp)
    stale_timestamp = "20260723172001"
    _write_dismissed_bundle(
        home,
        timestamp=stale_timestamp,
        agent_name="foo.job",
        cl_name="SomePatch",
        run_id=repair_run_id(stale_timestamp),
        index=False,
    )
    _write_dismissed_bundle(
        home,
        timestamp=target_timestamp,
        agent_name=None,
        cl_name="SomePatch",
        run_id=target_run_id,
        index=False,
    )
    rebuild_index(root)
    remote, sync_target = setup_repair(
        _work(tmp_path), runs=[("foo", "foo.job", target_run_id, "active")]
    )

    report = repair_project_run_states(sync_target, OWNER, apply=True)

    assert report.error is None
    assert report.changed == 1
    assert remote_state(remote, "alice.athena.foo.job") == "dismissed"


def test_stale_dismissed_summary_is_not_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = install_repair_home(tmp_path, monkeypatch)
    timestamp = "20260723170001"
    run_id = repair_run_id(timestamp)
    path = _write_dismissed_bundle(
        home,
        timestamp=timestamp,
        agent_name="foo.job",
        cl_name="SomePatch",
        run_id=run_id,
    )
    stale = json.loads(path.read_text(encoding="utf-8"))
    stale["agent_name"] = "other.job"
    stale["raw_suffix"] = "20260723999999"
    stale["source_run_id"] = repair_run_id("20260723999999")
    path.write_text(json.dumps(stale), encoding="utf-8")
    remote, sync_target = setup_repair(
        _work(tmp_path), runs=[("foo", "foo.job", run_id, "active")]
    )

    report = repair_project_run_states(sync_target, OWNER, apply=True)

    assert report.error is None
    assert report.changed == 0
    assert remote_state(remote, "alice.athena.foo.job") == "active"


def test_completion_then_dismissal_repairs_to_dismissed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = install_repair_home(tmp_path, monkeypatch)
    timestamp = "20260723170003"
    run_id = repair_run_id(timestamp)
    write_repair_artifact(
        home, timestamp=timestamp, name="foo.job", outcome="completed"
    )
    rebuild_repair_artifact_index(home)
    _write_dismissed_bundle(
        home,
        timestamp=timestamp,
        agent_name="foo.job",
        cl_name="SomePatch",
        run_id=run_id,
        extra={"stop_time": "2026-07-23T12:02:00+00:00"},
    )
    remote, sync_target = setup_repair(
        _work(tmp_path), runs=[("foo", "foo.job", run_id, "active")]
    )

    report = repair_project_run_states(sync_target, OWNER, apply=True)

    assert report.error is None
    assert report.changed == 1
    assert remote_state(remote, "alice.athena.foo.job") == "dismissed"


def test_preview_does_not_rebuild_missing_dismissed_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = install_repair_home(tmp_path, monkeypatch)
    timestamp = "20260723170002"
    run_id = repair_run_id(timestamp)
    rebuild_calls: list[str] = []
    load_calls: list[str] = []

    def forbid_rebuild(*_args: object, **_kwargs: object) -> object:
        rebuild_calls.append("rebuild")
        raise AssertionError("missing dismissed index must not rebuild")

    def forbid_load(*_args: object, **_kwargs: object) -> object:
        load_calls.append("load")
        raise AssertionError("preview must not rebuild dismissed summaries")

    monkeypatch.setattr("sase.ace.dismissed_bundle_index.rebuild_index", forbid_rebuild)
    monkeypatch.setattr(
        "sase.ace.dismissed_agents.load_dismissed_bundle_summaries", forbid_load
    )
    monkeypatch.setattr(
        "sase.core.dismissed_agents_facade.load_dismissed_bundle_summaries",
        forbid_load,
    )
    _remote, sync_target = setup_repair(
        _work(tmp_path), runs=[("foo", "foo.job", run_id, "active")]
    )

    report = repair_project_run_states(sync_target, OWNER, apply=False)

    assert report.error is None
    assert report.changed == 0
    assert rebuild_calls == []
    assert load_calls == []
    assert not (home / "dismissed_bundles" / INDEX_FILENAME).exists()

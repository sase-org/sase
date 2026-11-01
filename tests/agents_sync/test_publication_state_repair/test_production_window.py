"""Bounded window, hydration, and deadline production regressions."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from sase.agents_sync.agent_state_refresh import run_agent_state_refresh
from sase.agents_sync.publication_state_repair import repair_project_run_states
from tests.agents_sync.git_sync_fixtures import setup_repo, target
from tests.agents_sync.test_publication_state_repair._helpers import (
    OWNER,
    SeedBuilder,
    commit_push,
    install_repair_home,
    rebuild_repair_artifact_index,
    remote_head,
    remote_state,
    repair_run_id,
    setup_repair,
    track_path_reads,
    write_repair_artifact,
)


def _work(tmp_path: Path) -> Path:
    work = tmp_path / "sidecar-work"
    work.mkdir(exist_ok=True)
    return work


def _patch_monotonic(monkeypatch: pytest.MonkeyPatch, clock: dict[str, float]) -> None:
    def monotonic() -> float:
        return clock["now"]

    monkeypatch.setattr(time, "monotonic", monotonic)


def test_state_limit_one_does_not_hydrate_sibling_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = install_repair_home(tmp_path, monkeypatch)
    keep_ts = "20260723180000"
    other_ts = "20260723180001"
    keep_id = repair_run_id(keep_ts)
    other_id = repair_run_id(other_ts)
    write_repair_artifact(
        home,
        timestamp=keep_ts,
        name="foo.keep",
        outcome="completed",
        extra_files={"raw_prompt.md": "keep prompt\n", "chat.md": "keep chat\n"},
    )
    write_repair_artifact(
        home,
        timestamp=other_ts,
        name="foo.other",
        outcome="completed",
        extra_files={"raw_prompt.md": "other prompt\n", "chat.md": "other chat\n"},
    )
    rebuild_repair_artifact_index(home)
    extra = {
        "foo.keep": {"prompt": b"published keep prompt\n", "chat": b"keep chat\n"},
        "foo.other": {"prompt": b"published other prompt\n", "chat": b"other chat\n"},
    }
    work = _work(tmp_path)
    remote, _seed, sidecar = setup_repo(work)
    builder = SeedBuilder(sidecar)
    builder.add_run("foo", "foo.keep", keep_id, "active", extra_files=extra["foo.keep"])
    builder.add_run(
        "foo", "foo.other", other_id, "active", extra_files=extra["foo.other"]
    )
    for suffix in range(8):
        hood = f"hood-{suffix}"
        builder.add_run(hood, f"{hood}.job", f"run-{suffix}", "active")
    builder.write_manifest()
    commit_push(sidecar)
    sync_target = target(work, remote, sidecar)
    reads = track_path_reads(monkeypatch)

    report = repair_project_run_states(sync_target, OWNER, apply=True, state_limit=1)

    assert report.error is None
    assert report.examined == 1
    assert report.changed == 1
    names = {path.name for path in reads}
    assert "prompt.md" not in names
    assert "chat.md" not in names
    snapshot_reads = [
        path for path in reads if path.name == "snapshot.json" and "hoods" in path.parts
    ]
    assert len({path.parent.name for path in snapshot_reads}) <= 5
    selected_id = report.window[0].source_run_id
    if selected_id == keep_id:
        assert remote_state(remote, "alice.athena.foo.keep") == "completed"
        assert remote_state(remote, "alice.athena.foo.other") == "active"
        sibling_prompt = sidecar / "agents" / "alice.athena.foo.other" / "prompt.md"
        assert sibling_prompt.read_bytes() == extra["foo.other"]["prompt"]
    else:
        assert remote_state(remote, "alice.athena.foo.other") == "completed"
        assert remote_state(remote, "alice.athena.foo.keep") == "active"
        sibling_prompt = sidecar / "agents" / "alice.athena.foo.keep" / "prompt.md"
        assert sibling_prompt.read_bytes() == extra["foo.keep"]["prompt"]


def test_deadline_during_last_evidence_read_freezes_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = install_repair_home(tmp_path, monkeypatch)
    timestamp = "20260723180002"
    run_id = repair_run_id(timestamp)
    write_repair_artifact(
        home, timestamp=timestamp, name="foo.job", outcome="completed"
    )
    rebuild_repair_artifact_index(home)
    remote, sync_target = setup_repair(
        _work(tmp_path), runs=[("foo", "foo.job", run_id, "active")]
    )
    clock = {"now": 0.0}
    _patch_monotonic(monkeypatch, clock)
    import sase.agents_sync._publication_state_repair_observations as observations

    original = observations.filesystem_observations_for_run

    def expire_after_read(*args: object, **kwargs: object):
        result = original(*args, **kwargs)
        clock["now"] = 10_000.0
        return result

    monkeypatch.setattr(
        observations, "filesystem_observations_for_run", expire_after_read
    )
    before = remote_head(remote)
    report = repair_project_run_states(
        sync_target, OWNER, apply=True, work_budget_seconds=90.0
    )

    assert report.error is not None
    assert "work budget exceeded" in report.error
    assert report.pass_complete is False
    assert report.next_cursor is None
    assert report.changed == 0
    assert remote_head(remote) == before
    assert remote_state(remote, "alice.athena.foo.job") == "active"


def test_deadline_during_page_generation_freezes_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = install_repair_home(tmp_path, monkeypatch)
    timestamp = "20260723180003"
    run_id = repair_run_id(timestamp)
    write_repair_artifact(
        home, timestamp=timestamp, name="foo.job", outcome="completed"
    )
    rebuild_repair_artifact_index(home)
    remote, sync_target = setup_repair(
        _work(tmp_path), runs=[("foo", "foo.job", run_id, "active")]
    )
    clock = {"now": 0.0}
    _patch_monotonic(monkeypatch, clock)
    import sase.agents_sync._publication_state_repair_payload as payload

    original = payload._plan_state_pages

    def expire_during_pages(*args: object, **kwargs: object):
        result = original(*args, **kwargs)
        clock["now"] = 10_000.0
        return result

    monkeypatch.setattr(payload, "_plan_state_pages", expire_during_pages)
    before = remote_head(remote)
    report = repair_project_run_states(
        sync_target, OWNER, apply=True, work_budget_seconds=90.0
    )

    assert report.error is not None
    assert "work budget exceeded" in report.error
    assert report.pass_complete is False
    assert report.next_cursor is None
    assert report.changed == 0
    assert remote_head(remote) == before


def test_scheduler_preserves_checkpoint_on_budget_expiry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = install_repair_home(tmp_path, monkeypatch)
    timestamp = "20260723180004"
    run_id = repair_run_id(timestamp)
    write_repair_artifact(
        home, timestamp=timestamp, name="foo.job", outcome="completed"
    )
    rebuild_repair_artifact_index(home)
    work = _work(tmp_path)
    remote, _seed, sidecar = setup_repo(work)
    builder = SeedBuilder(sidecar)
    builder.add_run("foo", "foo.job", run_id, "active")
    builder.write_manifest()
    commit_push(sidecar)
    sync_target = target(work, remote, sidecar)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    clock = {"now": 0.0}
    _patch_monotonic(monkeypatch, clock)
    import sase.agents_sync._publication_state_repair_observations as observations

    original = observations.filesystem_observations_for_run

    def expire_after_read(*args: object, **kwargs: object):
        result = original(*args, **kwargs)
        clock["now"] = 10_000.0
        return result

    monkeypatch.setattr(
        observations, "filesystem_observations_for_run", expire_after_read
    )

    summary = run_agent_state_refresh(
        state_dir=state_dir,
        list_targets=lambda: ([sync_target], []),
        require_owner=lambda: OWNER,
        work_budget_seconds=90.0,
    )

    assert summary.pass_complete is False
    payload = json_payload(state_dir)
    cursor = payload["projects"]["proj:alice@athena"]["cursor"]
    assert cursor is None
    assert payload["projects"]["proj:alice@athena"]["failure_count"] >= 1
    assert payload["projects"]["proj:alice@athena"]["retry_after_ms"] > 0
    assert remote_state(remote, "alice.athena.foo.job") == "active"


def json_payload(state_dir: Path) -> dict[str, object]:
    import json

    return json.loads((state_dir / "agent_state_refresh.json").read_text())

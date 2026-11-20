"""Root-blocker grouping and frozen notices for the wait_checks chop."""

import json
from pathlib import Path
from uuid import uuid4

from sase.core.wait_dependency_resolution._artifact_state import artifact_dir_key
from sase.notifications.models import Notification
from sase.notifications.store import (
    append_notification,
    load_notifications,
    mark_dismissed,
    mark_read,
    notifications_file_path,
)
from sase.scripts._chop_wait_checks_common import TerminalBlocker
from sase.scripts._chop_wait_checks_roots import (
    MAX_ROOT_WALK_DEPTH,
    UnresolvedWaiter,
    group_by_root_blocker,
)

from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent, run_wait_checks

_MARKER = "wait_checks_auto_dismissed"


def _waiter(tmp_path: Path, suffix: str, name: str, *waiting_for: str) -> Path:
    waiter_dir = make_waiting_agent(tmp_path, *waiting_for, suffix=suffix)
    (waiter_dir / "agent_meta.json").write_text(
        json.dumps({"name": name}), encoding="utf-8"
    )
    return waiter_dir


def _failed(tmp_path: Path, name: str = "foo") -> Path:
    return make_agent(
        tmp_path, "proj", "20260506010101", name, done=True, outcome="failed"
    )


def _root_rows(blocker_dir: Path) -> list[Notification]:
    key = f"wait_checks:terminal-blocker:{blocker_dir}"
    return [
        row
        for row in load_notifications(include_dismissed=True)
        if row.sender == "wait_checks" and row.dedup_key == key
    ]


def _only_root_row(blocker_dir: Path) -> Notification:
    rows = _root_rows(blocker_dir)
    assert len(rows) == 1
    return rows[0]


def _listed(row: Notification) -> dict[str, str | None]:
    return {
        entry["name"]: entry.get("via")
        for entry in json.loads(row.action_data["waiters"])
    }


def test_many_waiters_on_one_failed_blocker_share_one_row(
    tmp_path: Path, monkeypatch
) -> None:
    blocker_dir = _failed(tmp_path)
    for index in range(3):
        _waiter(tmp_path, f"2026050602000{index}", f"waiter-{index}", "foo")

    run_wait_checks(tmp_path, monkeypatch)

    rows = [row for row in load_notifications() if row.sender == "wait_checks"]
    assert len(rows) == 1
    row = rows[0]
    assert row.dedup_key == f"wait_checks:terminal-blocker:{blocker_dir}"
    assert row.action == "ExpireWaiters"
    assert row.action_data["waiter_count"] == "3"
    assert _listed(row) == {"waiter-0": None, "waiter-1": None, "waiter-2": None}
    assert "Waiters blocked: 3" in row.notes
    assert any("Enter expires every named waiter" in note for note in row.notes)
    assert row.files[0] == str(blocker_dir)
    assert row.plus_one_count == 0


def test_transitive_waiter_groups_under_root(tmp_path: Path, monkeypatch) -> None:
    blocker_dir = _failed(tmp_path)
    mid_dir = _waiter(tmp_path, "20260506020001", "mid", "foo")
    leaf_dir = _waiter(tmp_path, "20260506020002", "leaf", "mid")

    run_wait_checks(tmp_path, monkeypatch)

    rows = [row for row in load_notifications() if row.sender == "wait_checks"]
    assert len(rows) == 1
    row = rows[0]
    assert row.dedup_key == f"wait_checks:terminal-blocker:{blocker_dir}"
    assert _listed(row) == {"mid": None, "leaf": str(mid_dir)}
    assert "Waiter: leaf (via mid)" in row.notes
    assert str(leaf_dir) in row.files


def test_waiter_on_healthy_waiter_is_not_grouped(tmp_path: Path, monkeypatch) -> None:
    _failed(tmp_path)
    _waiter(tmp_path, "20260506020001", "direct", "foo")
    _waiter(tmp_path, "20260506020002", "healthy", "late-dep")
    _waiter(tmp_path, "20260506020003", "leaf", "healthy")

    run_wait_checks(tmp_path, monkeypatch)

    rows = [row for row in load_notifications() if row.sender == "wait_checks"]
    assert len(rows) == 1
    assert _listed(rows[0]) == {"direct": None}


def test_repeated_passes_write_nothing(tmp_path: Path, monkeypatch) -> None:
    blocker_dir = _failed(tmp_path)
    _waiter(tmp_path, "20260506020001", "waiter-a", "foo")
    _waiter(tmp_path, "20260506020002", "waiter-b", "foo")

    run_wait_checks(tmp_path, monkeypatch)
    path = notifications_file_path()
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    run_wait_checks(tmp_path, monkeypatch)
    run_wait_checks(tmp_path, monkeypatch)

    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    row = _only_root_row(blocker_dir)
    assert row.plus_one_count == 0


def test_joining_waiter_updates_row_in_place_and_marks_unread(
    tmp_path: Path, monkeypatch
) -> None:
    blocker_dir = _failed(tmp_path)
    _waiter(tmp_path, "20260506020001", "first", "foo")
    run_wait_checks(tmp_path, monkeypatch)
    original = _only_root_row(blocker_dir)
    assert mark_read(original.id)

    _waiter(tmp_path, "20260506020002", "second", "foo")
    run_wait_checks(tmp_path, monkeypatch)

    row = _only_root_row(blocker_dir)
    assert row.id == original.id
    assert row.timestamp == original.timestamp
    assert row.read is False
    assert row.dismissed is False
    assert row.plus_one_count == 0
    assert row.action_data["waiter_count"] == "2"
    assert _MARKER not in row.action_data


def test_leaving_waiter_updates_row_without_marking_unread(
    tmp_path: Path, monkeypatch
) -> None:
    blocker_dir = _failed(tmp_path)
    _waiter(tmp_path, "20260506020001", "stays", "foo")
    leaving_dir = _waiter(tmp_path, "20260506020002", "leaves", "foo")
    run_wait_checks(tmp_path, monkeypatch)
    assert mark_read(_only_root_row(blocker_dir).id)

    (leaving_dir / "waiting.json").unlink()
    run_wait_checks(tmp_path, monkeypatch)

    row = _only_root_row(blocker_dir)
    assert row.read is True
    assert row.dismissed is False
    assert row.plus_one_count == 0
    assert _listed(row) == {"stays": None}


def test_root_settles_when_waiters_leave_and_resurfaces_on_return(
    tmp_path: Path, monkeypatch
) -> None:
    blocker_dir = _failed(tmp_path)
    waiter_dir = _waiter(tmp_path, "20260506020001", "only", "foo")
    run_wait_checks(tmp_path, monkeypatch)
    original = _only_root_row(blocker_dir)
    assert mark_read(original.id)

    (waiter_dir / "ready.json").write_text("{}", encoding="utf-8")
    run_wait_checks(tmp_path, monkeypatch)
    settled = _only_root_row(blocker_dir)
    assert settled.dismissed is True
    assert settled.action_data[_MARKER] == "true"

    _waiter(tmp_path, "20260506020002", "returning", "foo")
    run_wait_checks(tmp_path, monkeypatch)
    row = _only_root_row(blocker_dir)
    assert row.id == original.id
    assert row.dismissed is False
    assert row.read is False
    assert _MARKER not in row.action_data
    assert _listed(row) == {"returning": None}


def test_user_dismissal_holds_when_a_waiter_joins(tmp_path: Path, monkeypatch) -> None:
    blocker_dir = _failed(tmp_path)
    _waiter(tmp_path, "20260506020001", "first", "foo")
    run_wait_checks(tmp_path, monkeypatch)
    assert mark_dismissed(_only_root_row(blocker_dir).id)

    _waiter(tmp_path, "20260506020002", "second", "foo")
    run_wait_checks(tmp_path, monkeypatch)

    row = _only_root_row(blocker_dir)
    assert row.dismissed is True
    assert _MARKER not in row.action_data
    assert row.action_data["waiter_count"] == "2"
    assert row.plus_one_count == 0


def _legacy_row(waiter_dir: str) -> Notification:
    return Notification(
        id=str(uuid4()),
        timestamp="2026-11-01T00:00:00+00:00",
        sender="wait_checks",
        notes=["Wait dependency can never self-resolve", f"Waiter: {waiter_dir}"],
        tags=["wait", "blocked", "terminal-dependency"],
        dedup_key=f"wait_checks:terminal-blocked:{waiter_dir}",
    )


def test_legacy_per_waiter_rows_settle_once(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _failed(tmp_path)
    covered_dir = _waiter(tmp_path, "20260506020001", "covered", "foo")
    live_dir = _waiter(tmp_path, "20260506020002", "healthy", "late-dep")
    gone_dir = tmp_path / "gone-waiter"
    for waiter_dir in (covered_dir, live_dir, gone_dir):
        append_notification(_legacy_row(str(waiter_dir)))

    run_wait_checks(tmp_path, monkeypatch)
    path = notifications_file_path()
    after_first = path.read_bytes()
    run_wait_checks(tmp_path, monkeypatch)

    assert path.read_bytes() == after_first
    legacy = {
        row.dedup_key: row
        for row in load_notifications(include_dismissed=True)
        if (row.dedup_key or "").startswith("wait_checks:terminal-blocked:")
    }
    for settled_dir in (covered_dir, gone_dir):
        row = legacy[f"wait_checks:terminal-blocked:{settled_dir}"]
        assert row.dismissed is True
        assert row.action_data[_MARKER] == "true"
    kept = legacy[f"wait_checks:terminal-blocked:{live_dir}"]
    assert kept.dismissed is False


def test_waiter_cycle_terminates_and_groups_once(tmp_path: Path, monkeypatch) -> None:
    blocker_dir = _failed(tmp_path)
    a_dir = _waiter(tmp_path, "20260506020001", "a", "foo", "b")
    _waiter(tmp_path, "20260506020002", "b", "a")

    run_wait_checks(tmp_path, monkeypatch)

    row = _only_root_row(blocker_dir)
    assert _listed(row) == {"a": None, "b": str(a_dir)}


def test_failed_release_check_keeps_stored_waiter_listed(
    tmp_path: Path, monkeypatch
) -> None:
    import sase.scripts._chop_wait_checks_run as run_module

    blocker_dir = _failed(tmp_path)
    _waiter(tmp_path, "20260506020001", "steady", "foo")
    flaky_dir = _waiter(tmp_path, "20260506020002", "flaky", "foo")
    run_wait_checks(tmp_path, monkeypatch)
    path = notifications_file_path()
    before = path.read_bytes()

    real = run_module.process_one_waiter

    def flaky(waiter, index, tick):  # type: ignore[no-untyped-def]
        if waiter.waiting_marker.waiting_path.parent == flaky_dir:
            raise RuntimeError("transient read failure")
        return real(waiter, index, tick)

    monkeypatch.setattr(run_module, "process_one_waiter", flaky)
    run_wait_checks(tmp_path, monkeypatch)

    assert path.read_bytes() == before
    assert _listed(_only_root_row(blocker_dir)) == {"steady": None, "flaky": None}


def _record(
    name: str,
    *,
    blockers: tuple[TerminalBlocker, ...] = (),
    upstream: tuple[str, ...] = (),
) -> UnresolvedWaiter:
    keys = frozenset(artifact_dir_key(f"/runs/{item}") for item in upstream)
    return UnresolvedWaiter(
        artifact_dir=f"/runs/{name}",
        name=name,
        project_name="proj",
        blockers=blockers,
        upstream=lambda: keys,
    )


def test_cycle_without_root_groups_nothing() -> None:
    assert (
        group_by_root_blocker(
            [_record("a", upstream=("b",)), _record("b", upstream=("a",))]
        )
        == {}
    )


def test_root_walk_is_depth_bounded() -> None:
    blocker = TerminalBlocker(
        dependency="root", artifact_dir="/runs/root", outcome="failed"
    )
    chain_length = MAX_ROOT_WALK_DEPTH + 5
    records = [_record("w0", blockers=(blocker,))]
    records.extend(
        _record(f"w{index}", upstream=(f"w{index - 1}",))
        for index in range(1, chain_length)
    )

    groups = group_by_root_blocker(records)

    (group,) = groups.values()
    assert len(group.waiters) == MAX_ROOT_WALK_DEPTH + 1

"""Expire waiters named by a wait_checks root-blocker notice."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.agent.expire_blocked_waiters import (
    expire_blocked_waiters,
    expire_blocked_waiters_summary,
)
from sase.agent.running import KillResult
from sase.notifications import Notification, append_notification, load_notifications
from sase.scripts._chop_wait_checks_root_notice import EXPIRE_WAITERS_ACTION
from tests._kill_named_agent_dismiss_helpers import (
    _isolated_dismissed_index as _isolated_dismissed_index,
)
from tests._kill_named_agent_dismiss_helpers import patch_home, setup_waiting_agent


def _root_notice(
    blocker_dir: Path,
    waiters: list[tuple[Path, str]],
    *,
    notice_id: str = "n-expire",
    project: str = "myproj",
) -> Notification:
    return Notification(
        id=notice_id,
        timestamp="2026-11-20T12:00:00+00:00",
        sender="wait_checks",
        action=EXPIRE_WAITERS_ACTION,
        action_data={
            "blocker_artifact_dir": str(blocker_dir),
            "blocker_outcome": "failed",
            "blocker_dependency": "foo",
            "blocker_name": "foo",
            "waiter_count": str(len(waiters)),
            "waiters": json.dumps(
                [
                    {
                        "artifact_dir": str(path),
                        "name": name,
                        "project": project,
                    }
                    for path, name in waiters
                ],
                separators=(",", ":"),
            ),
        },
        dedup_key=f"wait_checks:terminal-blocker:{blocker_dir}",
    )


def _stored(notice_id: str) -> Notification:
    rows = [
        row for row in load_notifications(include_dismissed=True) if row.id == notice_id
    ]
    assert len(rows) == 1
    return rows[0]


def test_expire_settles_named_waiters_and_notice(tmp_path: Path) -> None:
    blocker_dir = tmp_path / "blocker"
    blocker_dir.mkdir()
    first = setup_waiting_agent(
        tmp_path,
        project_name="myproj",
        timestamp="20260510140000",
        name="waiter-a",
        pid=None,
        cl_name="waiter-a",
    )
    second = setup_waiting_agent(
        tmp_path,
        project_name="myproj",
        timestamp="20260510140001",
        name="waiter-b",
        pid=None,
        cl_name="waiter-b",
    )
    notice = _root_notice(blocker_dir, [(first, "waiter-a"), (second, "waiter-b")])
    append_notification(notice)

    with patch_home(tmp_path):
        result = expire_blocked_waiters(notice)

    assert result.expired_count == 2
    assert result.skipped_count == 0
    assert result.failed_count == 0
    assert result.notice_settled is True
    assert not (first / "waiting.json").exists()
    assert not (second / "waiting.json").exists()
    assert _stored(notice.id).dismissed is True
    assert expire_blocked_waiters_summary(result) == (
        "Expired 2 waiter(s); notice settled"
    )


def test_already_started_waiter_is_skipped(tmp_path: Path) -> None:
    blocker_dir = tmp_path / "blocker"
    blocker_dir.mkdir()
    started = setup_waiting_agent(
        tmp_path,
        project_name="myproj",
        timestamp="20260510140000",
        name="started",
        pid=None,
        cl_name="started",
    )
    meta = json.loads((started / "agent_meta.json").read_text(encoding="utf-8"))
    meta["wait_completed_at"] = "2026-11-20T12:00:00+00:00"
    (started / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    parked = setup_waiting_agent(
        tmp_path,
        project_name="myproj",
        timestamp="20260510140001",
        name="parked",
        pid=None,
        cl_name="parked",
    )
    notice = _root_notice(blocker_dir, [(started, "started"), (parked, "parked")])
    append_notification(notice)

    with patch_home(tmp_path):
        result = expire_blocked_waiters(notice)

    statuses = {item.name: item.status for item in result.results}
    assert statuses == {"started": "skipped_started", "parked": "expired"}
    assert (started / "waiting.json").exists()
    assert not (parked / "waiting.json").exists()
    assert result.notice_settled is True
    assert _stored(notice.id).dismissed is True


def test_runner_slot_queue_marker_is_skipped_as_started(tmp_path: Path) -> None:
    blocker_dir = tmp_path / "blocker"
    blocker_dir.mkdir()
    queued = setup_waiting_agent(
        tmp_path,
        project_name="myproj",
        timestamp="20260510140000",
        name="queued",
        pid=None,
        cl_name="queued",
    )
    waiting = json.loads((queued / "waiting.json").read_text(encoding="utf-8"))
    waiting["slot_requested_at"] = "2026-11-20T12:00:00+00:00"
    (queued / "waiting.json").write_text(json.dumps(waiting), encoding="utf-8")
    notice = _root_notice(blocker_dir, [(queued, "queued")])
    append_notification(notice)

    with patch_home(tmp_path):
        result = expire_blocked_waiters(notice)

    assert [item.status for item in result.results] == ["skipped_started"]
    assert (queued / "waiting.json").exists()
    assert result.notice_settled is True


def test_waiter_that_resolved_between_render_and_confirm_is_skipped(
    tmp_path: Path,
) -> None:
    blocker_dir = tmp_path / "blocker"
    blocker_dir.mkdir()
    waiter = setup_waiting_agent(
        tmp_path,
        project_name="myproj",
        timestamp="20260510140000",
        name="resolved",
        pid=None,
        cl_name="resolved",
    )
    notice = _root_notice(blocker_dir, [(waiter, "resolved")])
    append_notification(notice)
    (waiter / "done.json").write_text(
        json.dumps({"outcome": "completed"}), encoding="utf-8"
    )

    with patch_home(tmp_path):
        result = expire_blocked_waiters(notice)

    assert [item.status for item in result.results] == ["skipped_settled"]
    assert (waiter / "waiting.json").exists()
    assert result.notice_settled is True
    assert _stored(notice.id).dismissed is True


def test_missing_artifact_dir_is_skipped(tmp_path: Path) -> None:
    blocker_dir = tmp_path / "blocker"
    blocker_dir.mkdir()
    missing = tmp_path / "gone-waiter"
    notice = _root_notice(blocker_dir, [(missing, "gone")])
    append_notification(notice)

    with patch_home(tmp_path):
        result = expire_blocked_waiters(notice)

    assert [item.status for item in result.results] == ["skipped_missing"]
    assert result.notice_settled is True


def test_failed_kill_leaves_notice_open(tmp_path: Path) -> None:
    blocker_dir = tmp_path / "blocker"
    blocker_dir.mkdir()
    waiter = setup_waiting_agent(
        tmp_path,
        project_name="myproj",
        timestamp="20260510140000",
        name="live",
        pid=None,
        cl_name="live",
    )
    notice = _root_notice(blocker_dir, [(waiter, "live")])
    append_notification(notice)

    with (
        patch_home(tmp_path),
        patch(
            "sase.agent.expire_blocked_waiters.kill_located_agent",
            return_value=KillResult(False, "could not stop", status="survivors"),
        ),
    ):
        result = expire_blocked_waiters(notice)

    assert [item.status for item in result.results] == ["failed"]
    assert result.notice_settled is False
    assert _stored(notice.id).dismissed is False
    assert (waiter / "waiting.json").exists()
    assert expire_blocked_waiters_summary(result) == ("Expired 0 waiter(s); failed 1")

"""Exercise payload readers against real Rust sidecars, not resolver mocks."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from sase.agent.expire_blocked_waiters import expire_blocked_waiters
from sase.integrations.mobile_notifications import read_mobile_notification_snapshot
from sase.notifications import Notification
from sase.notifications.store import (
    append_notification,
    load_notifications,
    mark_read,
    notifications_file_path,
)
from sase.scripts._chop_wait_checks_common import TerminalBlocker
from sase.scripts._chop_wait_checks_root_notice import (
    reconcile_root_blocker_notifications,
    waiters_from_root_notice,
)
from sase.scripts._chop_wait_checks_roots import RootGroup, RootWaiter


def _large_group(tmp_path: Path) -> RootGroup:
    blocker = tmp_path / "blocker"
    blocker.mkdir()
    group = RootGroup(
        blocker=TerminalBlocker(
            dependency="blocker", artifact_dir=str(blocker), outcome="failed"
        )
    )
    for index in range(100):
        path = tmp_path / f"waiter-{index}"
        path.mkdir()
        group.waiters[str(path)] = RootWaiter(
            artifact_dir=str(path), name=path.name, project_name="test"
        )
    return group


def _reconcile(group: RootGroup):
    return reconcile_root_blocker_notifications(
        {group.blocker.artifact_dir: group},
        fail_open_dirs=(),
        live_waiter_dirs=tuple(group.waiters),
    )


def test_large_waiter_list_resolves_and_unchanged_pass_does_not_write(
    tmp_path: Path,
) -> None:
    group = _large_group(tmp_path)
    assert _reconcile(group).created == 1
    row = load_notifications()[0]
    assert row.action_data["waiters"].startswith("sase-notification-blob:v1:")
    assert {waiter.artifact_dir for waiter in waiters_from_root_notice(row)} == set(
        group.waiters
    )
    mark_read(row.id)
    path = notifications_file_path()
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    assert not _reconcile(group).changed()
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before

    newcomer = tmp_path / "new-waiter"
    newcomer.mkdir()
    group.waiters[str(newcomer)] = RootWaiter(
        artifact_dir=str(newcomer), name=newcomer.name, project_name="test"
    )
    assert _reconcile(group).resurfaced == 1
    assert not load_notifications()[0].read


@pytest.mark.parametrize("missing_blob", [False, True])
def test_expire_reads_sidecar_waiters_and_keeps_notice_if_payload_missing(
    tmp_path: Path, missing_blob: bool
) -> None:
    group = _large_group(tmp_path)
    _reconcile(group)
    row = load_notifications()[0]
    if missing_blob:
        for path in (notifications_file_path().parent / "blobs").iterdir():
            path.unlink()
    result = expire_blocked_waiters(row)
    # These fixture directories are already settled, so no process is killed.
    assert len(result.results) == (1 if missing_blob else 100)
    assert result.failed_count == (1 if missing_blob else 0)
    assert result.notice_settled is not missing_blob
    assert load_notifications(include_dismissed=True)[0].dismissed is not missing_blob


def test_mobile_card_keeps_preview_and_short_action_keys() -> None:
    append_notification(
        Notification(
            id="large-mobile",
            timestamp="2026-11-21T12:00:00+00:00",
            sender="user-agent",
            action="JumpToAgent",
            notes=["A useful preview " + "x" * 200_000],
            action_data={"cl_name": "target", "prompt": "p" * 200_000},
        )
    )
    snapshot = read_mobile_notification_snapshot()
    row = snapshot.rows[0]
    assert row.notes[0].startswith("A useful preview ")
    assert len(row.notes[0]) < 250
    assert row.host_action_data["cl_name"] == "target"
    assert row.host_action_data["prompt"].startswith("sase-notification-blob:v1:")


def test_gate_failure_fallback_resolves_full_message_and_recovery_command() -> None:
    from sase.ace.tui.actions.agents._notification_handlers import (
        handle_view_error_report,
    )

    message = "failure details " * 1000
    command = "sase gate answer " + "--option an-option " * 1000
    append_notification(
        Notification(
            id="large-failure",
            timestamp="2026-11-21T12:00:00+00:00",
            sender="gate",
            action="GateExecutionFailed",
            action_data={"message": message, "resume_command": command},
        )
    )
    app = Mock()
    assert handle_view_error_report(app, load_notifications()[0]) is False
    summary = app.notify.call_args.args[0]
    assert message in summary
    assert command in summary
    assert "sase-notification-blob" not in summary

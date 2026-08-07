"""CLI coverage for ``sase bead snooze`` and its refused status shortcut."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone, UTC
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import Issue, IssueType, Status
from sase.bead.project import BeadProject
from sase.bead.snooze_time import SnoozeTimeError, parse_snooze_until
from sase.core.time import get_timezone

# Both clocks are pinned together: the Python surfaces resolve "now" through
# `sase.core.time`, while the Rust store is handed the timestamp
# `sase.bead.project._now` produces. Pinning only one makes a wake time that
# is three days out by one clock already past by the other.
FROZEN_LOCAL = datetime(2026, 8, 6, 12, 0)


@pytest.fixture(autouse=True)
def frozen_clocks(monkeypatch: pytest.MonkeyPatch) -> None:
    frozen_utc = (
        FROZEN_LOCAL.replace(tzinfo=get_timezone())
        .astimezone(UTC)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    monkeypatch.setattr("sase.core.time.local_now", lambda: FROZEN_LOCAL)
    monkeypatch.setattr("sase.bead.project._now", lambda: frozen_utc)


def _ready_task(project_dir: Path, title: str = "Deferrable") -> Issue:
    with BeadProject(project_dir) as proj:
        issue = proj.create(title, IssueType.TASK, size="small")
        proj.update(issue.id, status=Status.READY.value)
        return proj.show(issue.id)


def _snooze_args(ids: list[str], **fields: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "ids": ids,
        "cancel": False,
        "until": None,
        "plus_ones": None,
        "reason": None,
    }
    base.update(fields)
    return argparse.Namespace(**base)


def test_relative_duration_snoozes_and_reports_the_resolved_wake_time(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    task = _ready_task(project_dir)

    bead_cli.handle_bead_snooze(_snooze_args([task.id], until="3d"))

    output = capsys.readouterr().out
    assert output.splitlines() == [
        f"◈ Snoozed {task.id} until 2026-08-09 12:00:00 EDT (in 3d)"
    ]
    with BeadProject(project_dir) as proj:
        stored = proj.show(task.id)
    assert stored.status is Status.SNOOZED
    assert stored.snooze is not None
    assert stored.snooze.reason == ""
    assert stored.snooze.plus_one_target is None


def test_plus_ones_and_reason_are_recorded_and_summarized(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    task = _ready_task(project_dir)

    bead_cli.handle_bead_snooze(
        _snooze_args(
            [task.id],
            until="2h",
            plus_ones=2,
            reason="waiting on the upstream fix",
        )
    )

    assert "wakes early at 2 more (2 total)" in capsys.readouterr().out
    with BeadProject(project_dir) as proj:
        stored = proj.show(task.id)
    assert stored.snooze is not None
    assert stored.snooze.plus_one_target == 2
    assert stored.snooze.reason == "waiting on the upstream fix"


def test_absolute_iso_timestamp_is_stored_verbatim(project_dir: Path) -> None:
    task = _ready_task(project_dir)
    until = (FROZEN_LOCAL + timedelta(days=5)).replace(tzinfo=get_timezone())

    bead_cli.handle_bead_snooze(_snooze_args([task.id], until=until.isoformat()))

    with BeadProject(project_dir) as proj:
        stored = proj.show(task.id)
    assert stored.snooze is not None
    assert stored.snooze.until == until.isoformat()


def test_cancel_returns_the_bead_to_ready(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    task = _ready_task(project_dir)
    bead_cli.handle_bead_snooze(_snooze_args([task.id], until="3d"))
    capsys.readouterr()

    bead_cli.handle_bead_snooze(_snooze_args([task.id], cancel=True))

    assert capsys.readouterr().out.splitlines() == [
        f"○ Woken: {task.id} — {task.title}"
    ]
    with BeadProject(project_dir) as proj:
        stored = proj.show(task.id)
    assert stored.status is Status.READY
    assert stored.snooze is None


def test_batch_snooze_commits_once_with_ids_in_argument_order(
    project_dir: Path,
) -> None:
    first = _ready_task(project_dir, "First")
    second = _ready_task(project_dir, "Second")

    with patch("sase.bead.cli_crud.auto_commit_bead_store") as auto_commit:
        bead_cli.handle_bead_snooze(_snooze_args([second.id, first.id], until="1d"))

    auto_commit.assert_called_once_with(
        f"chore(beads): snooze {second.id} {first.id}",
        push_after_commit=False,
        already_locked=False,
    )


def test_cancel_commits_under_its_own_wake_message(project_dir: Path) -> None:
    task = _ready_task(project_dir)
    bead_cli.handle_bead_snooze(_snooze_args([task.id], until="1d"))

    with patch("sase.bead.cli_crud.auto_commit_bead_store") as auto_commit:
        bead_cli.handle_bead_snooze(_snooze_args([task.id], cancel=True))

    auto_commit.assert_called_once_with(
        f"chore(beads): wake {task.id}",
        push_after_commit=False,
        already_locked=False,
    )


def test_an_unknown_id_in_a_batch_snoozes_nothing(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    task = _ready_task(project_dir)

    with pytest.raises(SystemExit) as exc_info:
        bead_cli.handle_bead_snooze(_snooze_args([task.id, "sase-nope"], until="3d"))

    assert exc_info.value.code == 1
    assert "issue not found: sase-nope" in capsys.readouterr().err
    with BeadProject(project_dir) as proj:
        assert proj.show(task.id).status is Status.READY


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"until": "not-a-time"},
        {"until": "0m"},
        {"until": "2020-01-01T00:00:00-05:00"},
        {"until": "3d", "plus_ones": 0},
        {"cancel": True, "until": "3d"},
    ],
)
def test_unusable_arguments_are_refused_before_any_mutation(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
    fields: dict[str, object],
) -> None:
    task = _ready_task(project_dir)

    with pytest.raises(SystemExit) as exc_info:
        bead_cli.handle_bead_snooze(_snooze_args([task.id], **fields))

    assert exc_info.value.code == 1
    assert capsys.readouterr().err.startswith("Error: ")
    with BeadProject(project_dir) as proj:
        assert proj.show(task.id).status is Status.READY


def test_update_refuses_the_status_shortcut_and_names_the_snooze_command(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    task = _ready_task(project_dir)

    with pytest.raises(SystemExit) as exc_info:
        bead_cli.handle_bead_update(
            argparse.Namespace(
                ids=[task.id],
                status="snoozed",
                title=None,
                description=None,
                notes=None,
                design=None,
                assignee=None,
                tier=None,
                model=None,
                size=None,
            )
        )

    assert exc_info.value.code == 1
    assert "sase bead snooze <id> -u <time>" in capsys.readouterr().err
    with BeadProject(project_dir) as proj:
        assert proj.show(task.id).status is Status.READY


def test_only_the_query_parsers_offer_a_snoozed_status_choice() -> None:
    from sase.main.parser import create_parser

    parser = create_parser(only="bead")

    for command in ("list", "search"):
        argv = ["bead", command, "-s", "snoozed"]
        if command == "search":
            argv.insert(2, "auth")
        args = parser.parse_args(argv)
        assert args.status == ["snoozed"]

    # `snoozed` needs a wake time, so argparse refuses it before the handler.
    with pytest.raises(SystemExit):
        parser.parse_args(["bead", "update", "sase-a1", "-s", "snoozed"])


def test_the_snooze_parser_accepts_its_documented_argument_shapes() -> None:
    from sase.main.parser import create_parser

    parser = create_parser(only="bead")

    args = parser.parse_args(
        ["bead", "snooze", "sase-a1", "sase-a2", "-u", "3d", "-p", "2", "-r", "why"]
    )
    assert args.ids == ["sase-a1", "sase-a2"]
    assert (args.until, args.plus_ones, args.reason) == ("3d", 2, "why")
    assert args.cancel is False

    assert parser.parse_args(["bead", "snooze", "sase-a1", "--cancel"]).cancel is True


def test_parse_snooze_until_accepts_the_documented_vocabulary() -> None:
    now = FROZEN_LOCAL.replace(tzinfo=get_timezone())

    assert (
        parse_snooze_until("30m", now=now) == (now + timedelta(minutes=30)).isoformat()
    )
    assert (
        parse_snooze_until("1h30m", now=now)
        == (now + timedelta(hours=1, minutes=30)).isoformat()
    )
    assert parse_snooze_until("3d", now=now) == (now + timedelta(days=3)).isoformat()
    assert (
        parse_snooze_until("1d12h", now=now)
        == (now + timedelta(days=1, hours=12)).isoformat()
    )
    assert parse_snooze_until("2026-08-09T09:00:00-04:00", now=now) == (
        "2026-08-09T09:00:00-04:00"
    )

    # An offset-less absolute time is read in the configured timezone, since
    # the store rejects a wake time that names no instant.
    assert parse_snooze_until("2026-08-09T09:00", now=now).endswith(
        datetime(2026, 8, 9, 9, 0, tzinfo=get_timezone()).isoformat()[-6:]
    )


@pytest.mark.parametrize(
    "value", ["", "nope", "0m", "3dx", "2020-01-01T00:00:00-05:00"]
)
def test_parse_snooze_until_rejects_unusable_values(value: str) -> None:
    now = FROZEN_LOCAL.replace(tzinfo=get_timezone())

    with pytest.raises(SnoozeTimeError) as exc_info:
        parse_snooze_until(value, now=now)

    assert "30m" in str(exc_info.value)

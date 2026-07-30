"""Read-side CLI coverage for the claimed bead status."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from sase.bead import cli_query
from sase.bead.cli_common import status_icon
from sase.bead.model import Issue, IssueType, Status
from sase.main.parser import create_parser


class _ReadView:
    def __init__(self, issue: Issue) -> None:
        self.issue = issue
        self.list_statuses: list[Status] | None = None

    def list_issues(
        self,
        statuses: list[Status] | None = None,
        **_kwargs: object,
    ) -> list[Issue]:
        self.list_statuses = statuses
        return [self.issue]

    def show(self, issue_id: str) -> Issue:
        if issue_id != self.issue.id:
            raise KeyError(issue_id)
        return self.issue

    def get_epic_children(self, _issue_id: str) -> list[Issue]:
        return []

    def stats(self) -> dict[str, int]:
        return {
            "total": 1,
            "open": 0,
            "claimed": 1,
            "ready": 0,
            "in_progress": 0,
            "closed": 0,
            "plan": 1,
            "phase": 0,
            "task": 0,
        }


@contextmanager
def _read_view(view: _ReadView) -> Iterator[_ReadView]:
    yield view


@pytest.fixture
def claimed_view(monkeypatch: pytest.MonkeyPatch) -> _ReadView:
    view = _ReadView(
        Issue(
            id="sase-claimed",
            title="Reserved phase",
            status=Status.CLAIMED,
            issue_type=IssueType.PLAN,
            assignee="sase-claimed",
        )
    )
    monkeypatch.setattr(cli_query, "get_read_view", lambda: _read_view(view))
    return view


def test_default_list_includes_claimed_with_shared_glyph(
    claimed_view: _ReadView,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli_query.handle_bead_list(
        argparse.Namespace(
            status=None,
            type=None,
            tier=None,
            limit=None,
            format="compact",
        )
    )

    assert claimed_view.list_statuses == [
        Status.OPEN,
        Status.CLAIMED,
        Status.READY,
        Status.IN_PROGRESS,
    ]
    assert capsys.readouterr().out == "◎ sase-claimed · Reserved phase\n"
    assert status_icon(Status.CLAIMED) == "◎"


def test_show_explains_claim_owner(
    claimed_view: _ReadView,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(["bead", "show", claimed_view.issue.id])
    cli_query.handle_bead_show(args)

    output = capsys.readouterr().out
    assert "◎ sase-claimed · Reserved phase   [CLAIMED]" in output
    assert "Assignee: sase-claimed" in output
    assert "Claimed by: sase-claimed (agent has not started working yet)" in output


def test_stats_prints_claimed_between_open_and_in_progress(
    claimed_view: _ReadView,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli_query.handle_bead_stats(argparse.Namespace())

    assert capsys.readouterr().out.splitlines()[2:6] == [
        "  Open:        0",
        "  Claimed:     1",
        "  Ready:       0",
        "  In Progress: 0",
    ]


@pytest.mark.parametrize("subcommand", ["list", "search", "update"])
@pytest.mark.parametrize("status", ["claimed", "ready"])
def test_status_parsers_accept_new_statuses(subcommand: str, status: str) -> None:
    argv = ["bead", subcommand]
    if subcommand == "search":
        argv.append("claim")
    elif subcommand == "update":
        argv.append("sase-claimed")
    argv.extend(["--status", status])

    args = create_parser().parse_args(argv)

    expected = [status] if subcommand != "update" else status
    assert args.status == expected

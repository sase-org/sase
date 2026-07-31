"""Shared helpers for ``sase bead show`` CLI tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import Issue
from sase.main.parser import create_parser


def show(issue: Issue, capsys: pytest.CaptureFixture[str]) -> str:
    args = create_parser().parse_args(["bead", "show", issue.id])
    bead_cli.handle_bead_show(args)
    return capsys.readouterr().out


def show_with_format(
    issue: Issue,
    output_format: str,
    capsys: pytest.CaptureFixture[str],
) -> str:
    args = create_parser().parse_args(
        ["bead", "show", issue.id, "--format", output_format]
    )
    bead_cli.handle_bead_show(args)
    return capsys.readouterr().out


def use_single_issue_view(
    monkeypatch: pytest.MonkeyPatch,
    issue: Issue,
) -> None:
    class _SingleIssueView:
        def show(self, issue_id: str) -> Issue:
            if issue_id == issue.id:
                return issue
            raise KeyError(issue_id)

        def get_epic_children(self, _issue_id: str) -> list[Issue]:
            return []

        def list_issues(self) -> list[Issue]:
            return [issue]

    @contextmanager
    def read_view() -> Iterator[_SingleIssueView]:
        yield _SingleIssueView()

    monkeypatch.setattr("sase.bead.cli_query.get_read_view", read_view)
    monkeypatch.setattr(
        "sase.bead.cli_query.design_paths_are_relative",
        lambda: False,
    )
    monkeypatch.setattr("sase.bead.cli_query.resolve_bead_page_url", lambda _id: None)

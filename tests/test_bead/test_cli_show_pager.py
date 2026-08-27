"""``sase bead show`` pager wiring tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import Issue, IssueType
from sase.cli_pager import PagerMode
from sase.main.parser import create_parser


@contextmanager
def _view() -> Iterator[object]:
    issues = {
        "sase-1": Issue(id="sase-1", title="First", issue_type=IssueType.TASK),
        "sase-2": Issue(id="sase-2", title="Second", issue_type=IssueType.TASK),
    }

    class _View:
        def show(self, issue_id: str) -> Issue:
            try:
                return issues[issue_id]
            except KeyError:
                raise KeyError(issue_id) from None

        def get_epic_children(self, _issue_id: str) -> list[Issue]:
            return []

        def list_issues(self) -> list[Issue]:
            return list(issues.values())

    yield _View()


def _install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sase.bead.cli_query.get_read_view", _view)
    monkeypatch.setattr("sase.bead.cli_query.design_paths_are_relative", lambda: False)
    monkeypatch.setattr("sase.bead.cli_query.resolve_bead_page_url", lambda _id: None)
    monkeypatch.setattr(
        "sase.bead.cli_query.resolve_bead_creator_url",
        lambda _name: None,
    )


def test_pager_never_writes_stdout_for_one_and_many(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install(monkeypatch)
    args = create_parser().parse_args(["bead", "show", "sase-1", "--pager", "never"])
    bead_cli.handle_bead_show(args)
    assert "sase-1" in capsys.readouterr().out

    args = create_parser().parse_args(
        ["bead", "show", "sase-1", "sase-2", "--pager", "never"]
    )
    bead_cli.handle_bead_show(args)
    out = capsys.readouterr().out
    assert "── 1/2 " in out
    assert "── 2/2 " in out


def test_pager_always_receives_assembled_body_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch)
    calls: list[tuple[str, PagerMode | str]] = []

    documents: list[Any] = []

    def fake_page_or_print(
        text: str, *, mode: PagerMode | str, document: object | None = None
    ) -> None:
        calls.append((text, mode))
        documents.append(document)

    monkeypatch.setattr("sase.bead.cli_query.page_or_print", fake_page_or_print)
    args = create_parser().parse_args(
        ["bead", "show", "sase-1", "sase-2", "--pager", "always"]
    )

    bead_cli.handle_bead_show(args)

    assert len(calls) == 1
    assert calls[0][1] is PagerMode.ALWAYS
    assert "── 1/2 " in calls[0][0]
    assert "── 2/2 " in calls[0][0]
    assert documents[0].title == "2 beads"


def test_missing_id_errors_are_printed_after_pager_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch)
    events: list[tuple[str, str]] = []

    class _EventStderr:
        def write(self, text: str) -> int:
            if text.strip():
                events.append(("stderr", text))
            return len(text)

        def flush(self) -> None:
            return None

    def fake_page_or_print(
        text: str, *, mode: PagerMode | str, document: object | None = None
    ) -> None:
        assert document is not None
        assert mode is PagerMode.ALWAYS
        events.append(("pager", text))

    monkeypatch.setattr("sase.bead.cli_query.page_or_print", fake_page_or_print)
    monkeypatch.setattr("sase.bead.cli_query.sys.stderr", _EventStderr())
    args = create_parser().parse_args(
        ["bead", "show", "sase-1", "sase-2", "missing", "--pager", "always"]
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_show(args)

    assert excinfo.value.code == 1
    assert events[0][0] == "pager"
    assert "── 1/2 " in events[0][1]
    assert events[1] == ("stderr", "Error: issue not found: missing")

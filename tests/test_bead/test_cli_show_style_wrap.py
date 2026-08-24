"""Parser and prose-wrapping tests for ``sase bead show``."""

from __future__ import annotations

import os

import pytest

from sase.bead.model import BeadNote, Issue, IssueType, TaskPlusOneEvidence
from sase.main.parser import create_parser
from tests.test_bead.cli_show_style_test_helpers import render, strip_sgr


def test_style_alias_is_lowercase_and_removed_values_error() -> None:
    parser = create_parser()

    assert parser.parse_args(["bead", "show", "bd-1", "-s", "rich"]).style == "rich"
    with pytest.raises(SystemExit) as short_exc:
        parser.parse_args(["bead", "show", "bd-1", "-S", "rich"])
    with pytest.raises(SystemExit) as color_exc:
        parser.parse_args(["bead", "show", "bd-1", "--style", "color"])

    assert short_exc.value.code == 2
    assert color_exc.value.code == 2


@pytest.mark.parametrize(
    "value,expected",
    [("none", None), ("0", None), ("20", 20), ("120", 120), ("auto", -1)],
)
def test_wrap_parser_accepts_supported_values(
    value: str,
    expected: int | None,
) -> None:
    args = create_parser().parse_args(["bead", "show", "bd-1", "--wrap", value])

    assert args.wrap == expected


@pytest.mark.parametrize("value", ["19", "-5", "wide"])
def test_wrap_parser_rejects_bad_values(value: str) -> None:
    with pytest.raises(SystemExit) as excinfo:
        create_parser().parse_args(["bead", "show", "bd-1", "--wrap", value])

    assert excinfo.value.code == 2


def test_blank_lines_stay_blank_at_every_style(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue(
        id="bd-blank",
        title="Blank Lines",
        issue_type=IssueType.TASK,
        description="first line\n\nsecond line",
    )
    issues = {issue.id: issue}

    plain = render(
        issue.id,
        issues,
        style="plain",
        color="always",
        wrap="40",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    rich = render(
        issue.id,
        issues,
        style="rich",
        color="always",
        wrap="40",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert "\nDESCRIPTION\n  first line\n\n  second line\n" in plain
    assert strip_sgr(rich) == plain


def test_description_continuation_lines_keep_two_space_indent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue(
        id="bd-wrap",
        title="Wrapped Description",
        issue_type=IssueType.TASK,
        description="alpha beta gamma delta epsilon zeta eta theta iota kappa lambda",
    )

    out = render(
        issue.id,
        {issue.id: issue},
        style="plain",
        color="always",
        wrap="30",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    lines = out.split("\n")
    body = lines[lines.index("DESCRIPTION") + 1 : -1]
    assert body == [
        "  alpha beta gamma delta",
        "  epsilon zeta eta theta iota",
        "  kappa lambda",
    ]


def test_description_trailing_newline_survives(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue(
        id="bd-trailing",
        title="Trailing Newline",
        issue_type=IssueType.TASK,
        description="line\n",
    )

    out = render(
        issue.id,
        {issue.id: issue},
        style="plain",
        color="always",
        wrap="40",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert out.endswith("\nDESCRIPTION\n  line\n\n")


def test_wrap_total_budget_includes_description_indent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue(
        id="bd-budget",
        title="Budget",
        issue_type=IssueType.TASK,
        description=" ".join(f"word{i}" for i in range(20)),
    )

    out = render(
        issue.id,
        {issue.id: issue},
        style="plain",
        color="always",
        wrap="60",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    lines = out.split("\n")
    body = lines[lines.index("DESCRIPTION") + 1 : -1]
    assert all(len(line) <= 60 for line in body)


def test_wrap_none_and_zero_disable_wrapping(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    description = " ".join(["word"] * 40)
    issue = Issue(
        id="bd-none",
        title="No Wrap",
        issue_type=IssueType.TASK,
        description=description,
    )
    issues = {issue.id: issue}

    none = render(
        issue.id,
        issues,
        style="plain",
        color="always",
        wrap="none",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    zero = render(
        issue.id,
        issues,
        style="plain",
        color="always",
        wrap="0",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert zero == none
    assert f"\n  {description}\n" in none


def test_wrap_auto_uses_terminal_width(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue(
        id="bd-auto",
        title="Auto Wrap",
        issue_type=IssueType.TASK,
        description=" ".join(f"word{i}" for i in range(20)),
    )
    monkeypatch.setattr(
        "sase.main.parser_bead_common.shutil.get_terminal_size",
        lambda fallback=(80, 24): os.terminal_size((50, 24)),
    )

    out = render(
        issue.id,
        {issue.id: issue},
        style="plain",
        color="always",
        wrap="auto",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    lines = out.split("\n")
    body = lines[lines.index("DESCRIPTION") + 1 : -1]
    assert len(body) > 1
    assert all(len(line) <= 50 for line in body)


def test_plus_one_evidence_notes_wrap_with_four_space_indent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue(
        id="bd-plus-one",
        title="Plus One",
        issue_type=IssueType.TASK,
        plus_one_evidence=[
            TaskPlusOneEvidence(
                timestamp="2026-08-03T12:00:00",
                reporter="agent.alpha",
                note=" ".join(f"evidence{i}" for i in range(12)),
            )
        ],
    )

    out = render(
        issue.id,
        {issue.id: issue},
        style="plain",
        color="always",
        wrap="50",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert all(len(line) <= 50 for line in out.splitlines())
    evidence_lines = [line for line in out.splitlines() if "evidence" in line]
    assert len(evidence_lines) > 1
    assert all(line.startswith("    ") for line in evidence_lines)


def test_note_bodies_wrap_with_five_space_indent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue(
        id="bd-note-wrap",
        title="Note Wrap",
        issue_type=IssueType.TASK,
        notes=[
            BeadNote(
                id="note-1",
                timestamp="2026-08-01T11:00:00Z",
                author="agent.alpha",
                text=" ".join(f"note{i}" for i in range(12)),
            )
        ],
    )

    out = render(
        issue.id,
        {issue.id: issue},
        style="plain",
        color="always",
        wrap="50",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    note_lines = [
        line for line in out.splitlines() if line.startswith("     ") and "note" in line
    ]
    assert len(note_lines) > 1
    assert all(len(line) <= 50 for line in note_lines)

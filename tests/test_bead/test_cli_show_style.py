"""Tests for ``sase bead show`` style and prose wrapping."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
import re
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.cli_detail_prose import highlight_prose
from sase.bead.cli_detail_style import DetailStyle, resolve_detail_style
from sase.bead.model import (
    BeadTier,
    Dependency,
    Issue,
    IssueType,
    PhaseSize,
    Resolution,
    Status,
    TaskPlusOneEvidence,
)
from sase.main.parser import create_parser
from sase.phase_size_presentation import PHASE_SIZE_ACCENTS, PHASE_SIZE_STYLES
from tests.test_bead.cli_show_test_helpers import show_with_format

STRIP_SGR = re.compile(r"\x1b\[[0-9;]*m")
GOLDEN = Path(__file__).parent / "golden"


def strip_sgr(text: str) -> str:
    return STRIP_SGR.sub("", text)


@contextmanager
def _multi_issue_view(issues: dict[str, Issue]) -> Iterator[object]:
    class _View:
        def show(self, issue_id: str) -> Issue:
            try:
                return issues[issue_id]
            except KeyError:
                raise KeyError(issue_id) from None

        def get_epic_children(self, issue_id: str) -> list[Issue]:
            return [
                candidate
                for candidate in issues.values()
                if candidate.parent_id == issue_id
            ]

        def list_issues(self) -> list[Issue]:
            return list(issues.values())

    yield _View()


def _install_view(monkeypatch: pytest.MonkeyPatch, issues: dict[str, Issue]) -> None:
    monkeypatch.setattr(
        "sase.bead.cli_query.get_read_view",
        lambda: _multi_issue_view(issues),
    )
    monkeypatch.setattr("sase.bead.cli_query.design_paths_are_relative", lambda: False)
    monkeypatch.setattr("sase.bead.cli_query.resolve_bead_page_url", lambda _id: None)
    monkeypatch.setattr(
        "sase.bead.cli_query.resolve_bead_creator_url", lambda _id: None
    )


def _render(
    issue_id: str,
    issues: dict[str, Issue],
    *,
    style: str,
    color: str,
    wrap: str | None = None,
    format_: str = "full",
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> str:
    _install_view(monkeypatch, issues)
    argv = [
        "bead",
        "show",
        issue_id,
        "--format",
        format_,
        "--style",
        style,
        "--color",
        color,
    ]
    if wrap is not None:
        argv.extend(["--wrap", wrap])
    args = create_parser().parse_args(argv)
    bead_cli.handle_bead_show(args)
    return capsys.readouterr().out


# --- Corpus of bead shapes for the invariant test ---


def _minimal_task() -> tuple[dict[str, Issue], str]:
    issue = Issue(id="bd-task", title="Minimal Task", issue_type=IssueType.TASK)
    return {issue.id: issue}, issue.id


def _closed_with_resolution() -> tuple[dict[str, Issue], str]:
    issue = Issue(
        id="bd-closed",
        title="Closed Phase",
        issue_type=IssueType.PHASE,
        status=Status.CLOSED,
        resolution=Resolution.DONE,
        close_reason="Landed in main",
        closed_at="2026-01-01T00:00:00",
        size=PhaseSize.MEDIUM,
        owner="owner@example.com",
    )
    return {issue.id: issue}, issue.id


def _legacy_closed_without_resolution() -> tuple[dict[str, Issue], str]:
    issue = Issue(
        id="bd-legacy-closed",
        title="Legacy Closed Task",
        issue_type=IssueType.TASK,
        status=Status.CLOSED,
    )
    return {issue.id: issue}, issue.id


def _deps_and_blockers() -> tuple[dict[str, Issue], str]:
    target = Issue(
        id="bd-target",
        title="Target Task",
        issue_type=IssueType.TASK,
        dependencies=[
            Dependency(
                issue_id="bd-target",
                depends_on_id="bd-dep",
                created_at="2026-01-01T00:00:00",
            )
        ],
    )
    dep = Issue(id="bd-dep", title="Dependency Task", issue_type=IssueType.TASK)
    blocked = Issue(
        id="bd-blocked",
        title="Blocked Task",
        issue_type=IssueType.TASK,
        dependencies=[
            Dependency(
                issue_id="bd-blocked",
                depends_on_id="bd-target",
                created_at="2026-01-01T00:00:00",
            )
        ],
    )
    return {i.id: i for i in (target, dep, blocked)}, target.id


def _dangling_refs() -> tuple[dict[str, Issue], str]:
    issue = Issue(
        id="bd-dangling",
        title="Dangling Refs Task",
        issue_type=IssueType.TASK,
        parent_id="bd-missing-parent",
        dependencies=[
            Dependency(
                issue_id="bd-dangling",
                depends_on_id="bd-missing-dep",
                created_at="2026-01-01T00:00:00",
            )
        ],
    )
    return {issue.id: issue}, issue.id


def _changespec() -> tuple[dict[str, Issue], str]:
    issue = Issue(
        id="bd-plan",
        title="Plan With ChangeSpec",
        issue_type=IssueType.PLAN,
        changespec_name="my_changespec",
        changespec_bug_id="BUG-42",
    )
    return {issue.id: issue}, issue.id


def _with_refs() -> tuple[dict[str, Issue], str]:
    issue = Issue(
        id="bd-refs",
        title="Task With Refs",
        issue_type=IssueType.TASK,
        refs=["research:202607/report.md"],
    )
    return {issue.id: issue}, issue.id


def _markdown_description() -> tuple[dict[str, Issue], str]:
    issue = Issue(
        id="bd-markdown",
        title="Task With Markdown Description",
        issue_type=IssueType.TASK,
        description=(
            "# Heading\n\n"
            "Some *emphasis* and a list:\n\n"
            "- one\n"
            "- two\n\n"
            "```python\n"
            "def foo(x):\n"
            "    return x + 1\n"
            "```\n"
        ),
    )
    return {issue.id: issue}, issue.id


def _cjk_emoji_title() -> tuple[dict[str, Issue], str]:
    issue = Issue(
        id="bd-cjk",
        title="修复错误 🐛 emoji title",
        issue_type=IssueType.TASK,
    )
    return {issue.id: issue}, issue.id


_CORPUS = [
    ("minimal_task", _minimal_task),
    ("closed_with_resolution", _closed_with_resolution),
    ("legacy_closed_without_resolution", _legacy_closed_without_resolution),
    ("deps_and_blockers", _deps_and_blockers),
    ("dangling_refs", _dangling_refs),
    ("changespec", _changespec),
    ("with_refs", _with_refs),
    ("markdown_description", _markdown_description),
    ("cjk_emoji_title", _cjk_emoji_title),
]


@pytest.mark.parametrize("name,build", _CORPUS, ids=[c[0] for c in _CORPUS])
def test_style_invariant_over_corpus(
    name: str,
    build: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issues, target_id = build()  # type: ignore[operator]

    plain = _render(
        target_id,
        issues,
        style="plain",
        color="always",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    rich = _render(
        target_id,
        issues,
        style="rich",
        color="always",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert strip_sgr(rich) == plain


@pytest.mark.parametrize("wrap", ["none", "40", "120"])
@pytest.mark.parametrize("name,build", _CORPUS, ids=[c[0] for c in _CORPUS])
def test_style_invariant_over_corpus_per_wrap_width(
    name: str,
    build: object,
    wrap: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issues, target_id = build()  # type: ignore[operator]

    plain = _render(
        target_id,
        issues,
        style="plain",
        color="always",
        wrap=wrap,
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    rich = _render(
        target_id,
        issues,
        style="rich",
        color="always",
        wrap=wrap,
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert strip_sgr(rich) == plain


@pytest.mark.parametrize("name,build", _CORPUS, ids=[c[0] for c in _CORPUS])
def test_compact_style_invariant_over_corpus(
    name: str,
    build: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--format compact`` responds to style like ``full`` does: rich output
    with SGR stripped reproduces the plain bytes exactly, across every bead
    shape in the corpus."""
    issues, target_id = build()  # type: ignore[operator]

    plain = _render(
        target_id,
        issues,
        style="plain",
        color="always",
        format_="compact",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    rich = _render(
        target_id,
        issues,
        style="rich",
        color="always",
        format_="compact",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert strip_sgr(rich) == plain


@pytest.mark.parametrize("name,build", _CORPUS, ids=[c[0] for c in _CORPUS])
def test_json_format_ignores_style_over_corpus(
    name: str,
    build: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--format json`` is never styled: it renders identically regardless
    of ``--style``, and it stays valid JSON for every bead shape in the
    corpus — including markdown descriptions, CJK/emoji titles, and dangling
    references."""
    issues, target_id = build()  # type: ignore[operator]

    plain = _render(
        target_id,
        issues,
        style="plain",
        color="always",
        format_="json",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    rich = _render(
        target_id,
        issues,
        style="rich",
        color="always",
        format_="json",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert rich == plain
    assert json.loads(plain)["issue"]["id"] == target_id


def test_style_invariant_epic_with_phases_and_child_epics(
    nested_store: dict[str, Issue],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = nested_store["root"]

    plain = show_with_format(root, "full", capsys)
    monkeypatch.setattr(
        "sys.argv",
        ["sase", "bead", "show", root.id, "--style", "rich", "--color", "always"],
    )
    args = create_parser().parse_args(
        ["bead", "show", root.id, "--style", "rich", "--color", "always"]
    )
    bead_cli.handle_bead_show(args)
    rich = capsys.readouterr().out

    assert strip_sgr(rich) == plain


def test_style_invariant_phase_with_parent_epic_plan(
    nested_store: dict[str, Issue],
    capsys: pytest.CaptureFixture[str],
) -> None:
    phase = nested_store["phase"]

    plain = show_with_format(phase, "full", capsys)
    args = create_parser().parse_args(
        ["bead", "show", phase.id, "--style", "rich", "--color", "always"]
    )
    bead_cli.handle_bead_show(args)
    rich = capsys.readouterr().out

    assert strip_sgr(rich) == plain


def test_raw_escape_content_is_passed_through_not_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A literal ``\\x1b[31m`` byte in a description is a known limitation.

    Sanitizing it would change the plain-text byte contract this feature must
    preserve, so ``strip_sgr(render(RICH)) == render(PLAIN)`` cannot hold for
    this one pathological input (``strip_sgr`` cannot distinguish an injected
    SGR escape from an identical raw byte sequence already in the content).
    Instead we assert the content survives unmodified and nothing crashes.
    """
    issue = Issue(
        id="bd-raw-escape",
        title="Task With Raw Escape",
        issue_type=IssueType.TASK,
        description="literal \x1b[31m escape stays as-is",
    )
    issues = {issue.id: issue}

    plain = _render(
        issue.id,
        issues,
        style="plain",
        color="always",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    rich = _render(
        issue.id,
        issues,
        style="rich",
        color="always",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert "\x1b[31m escape stays as-is" in plain
    assert "\x1b[31m escape stays as-is" in rich


def test_rich_has_no_stray_non_sgr_escapes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issues, target_id = _markdown_description()

    rich = _render(
        target_id,
        issues,
        style="rich",
        color="always",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    remainder = STRIP_SGR.sub("", rich)
    assert "\x1b" not in remainder


def test_plain_style_emits_zero_escapes_even_with_color_always(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issues, target_id = _markdown_description()

    plain = _render(
        target_id,
        issues,
        style="plain",
        color="always",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert "\x1b" not in plain


def test_default_non_tty_stdout_emits_zero_escapes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Regression guard for every agent that shells out to this command."""
    issues, target_id = _markdown_description()
    _install_view(monkeypatch, issues)

    args = create_parser().parse_args(["bead", "show", target_id])
    bead_cli.handle_bead_show(args)
    out = capsys.readouterr().out

    assert "\x1b" not in out


def test_json_is_never_styled_even_with_rich_and_color_always(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issues, target_id = _markdown_description()
    _install_view(monkeypatch, issues)

    args = create_parser().parse_args(
        [
            "bead",
            "show",
            target_id,
            "--format",
            "json",
            "--style",
            "rich",
            "--color",
            "always",
            "--wrap",
            "40",
        ]
    )
    bead_cli.handle_bead_show(args)
    out = capsys.readouterr().out

    assert "\x1b" not in out
    payload = json.loads(out)
    assert payload["issue"]["description"] == issues[target_id].description


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

    plain = _render(
        issue.id,
        issues,
        style="plain",
        color="always",
        wrap="40",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    rich = _render(
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

    out = _render(
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

    out = _render(
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

    out = _render(
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

    none = _render(
        issue.id,
        issues,
        style="plain",
        color="always",
        wrap="none",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    zero = _render(
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
    import os

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

    out = _render(
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

    out = _render(
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


@pytest.mark.parametrize(
    "color,style,isatty,expected",
    [
        ("never", "auto", False, DetailStyle.PLAIN),
        ("never", "rich", True, DetailStyle.PLAIN),
        ("auto", "auto", False, DetailStyle.PLAIN),
        ("auto", "auto", True, DetailStyle.RICH),
        ("auto", "rich", False, DetailStyle.PLAIN),
        ("auto", "plain", True, DetailStyle.PLAIN),
        ("always", "auto", False, DetailStyle.RICH),
        ("always", "auto", True, DetailStyle.RICH),
        ("always", "plain", False, DetailStyle.PLAIN),
        ("always", "plain", True, DetailStyle.PLAIN),
    ],
)
def test_resolve_detail_style_gate_matrix(
    color: str,
    style: str,
    isatty: bool,
    expected: DetailStyle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr("sys.stdout.isatty", lambda: isatty)

    assert resolve_detail_style(style=style, color=color) is expected


def test_resolve_detail_style_honors_no_color(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)

    assert resolve_detail_style(style="auto", color="auto") is DetailStyle.PLAIN


def test_resolve_detail_style_rejects_removed_color_style() -> None:
    with pytest.raises(ValueError, match="unknown detail style"):
        resolve_detail_style(style="color", color="always")


# --- highlight_prose robustness ---


def test_highlight_prose_returns_unchanged_for_plain() -> None:
    text = "# Heading\n\nSome text.\n"

    assert highlight_prose(text, style=DetailStyle.PLAIN) == text


def test_highlight_prose_empty_string() -> None:
    assert highlight_prose("", style=DetailStyle.RICH) == ""


def test_highlight_prose_unknown_fence_language_does_not_raise() -> None:
    text = "before\n\n```boguslang123\nsome code\n```\n\nafter\n"

    rendered = highlight_prose(text, style=DetailStyle.RICH)

    assert strip_sgr(rendered) == text


def test_highlight_prose_unterminated_fence_does_not_raise() -> None:
    text = "before\n\n```python\ndef foo():\n    pass\n"

    rendered = highlight_prose(text, style=DetailStyle.RICH)

    assert strip_sgr(rendered) == text


def test_highlight_prose_description_with_trailing_whitespace() -> None:
    text = "trailing whitespace here   \nand here\t\n"

    rendered = highlight_prose(text, style=DetailStyle.RICH)

    assert strip_sgr(rendered) == text


def test_highlight_prose_description_is_only_a_fence() -> None:
    text = "```python\nprint('only a fence')\n```"

    rendered = highlight_prose(text, style=DetailStyle.RICH)

    assert strip_sgr(rendered) == text


# --- Palette drift ---


def test_phase_size_accents_match_phase_size_styles_hex() -> None:
    for size, accent_hex in PHASE_SIZE_ACCENTS.items():
        assert accent_hex.lower() in PHASE_SIZE_STYLES[size].lower()


# --- ANSI golden snapshots ---


def _read_golden(name: str) -> str:
    return (GOLDEN / "cli" / name).read_text(encoding="utf-8")


def _epic_with_children() -> tuple[dict[str, Issue], str]:
    epic = Issue(
        id="epic-1",
        title="Root Epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
    )
    phase = Issue(
        id="epic-1.1",
        title="Build Alpha",
        issue_type=IssueType.PHASE,
        parent_id=epic.id,
        size=PhaseSize.MEDIUM,
    )
    child_epic = Issue(
        id="epic-1.2",
        title="Nested Epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        parent_id=epic.id,
        status=Status.IN_PROGRESS,
    )
    return {i.id: i for i in (epic, phase, child_epic)}, epic.id


def test_show_epic_with_children_rich_ansi_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issues, target_id = _epic_with_children()

    out = _render(
        target_id,
        issues,
        style="rich",
        color="always",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert out == _read_golden("show_style_epic.ansi")


def test_show_closed_phase_with_markdown_rich_ansi_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issues, target_id = _closed_with_resolution()
    issues[target_id].description = (
        "# Summary\n\nFixed the bug:\n\n- root caused by X\n- patched Y\n\n"
        "```python\ndef fixed():\n    return True\n```"
    )
    out = _render(
        target_id,
        issues,
        style="rich",
        color="always",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert out == _read_golden("show_style_closed_phase.ansi")


def test_show_closed_phase_with_markdown_rich_ansi_snapshot_ignores_no_color(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    issues, target_id = _closed_with_resolution()
    issues[target_id].description = (
        "# Summary\n\nFixed the bug:\n\n- root caused by X\n- patched Y\n\n"
        "```python\ndef fixed():\n    return True\n```"
    )
    out = _render(
        target_id,
        issues,
        style="rich",
        color="always",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert out == _read_golden("show_style_closed_phase.ansi")

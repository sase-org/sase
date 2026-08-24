"""End-to-end tests for ``sase bead show`` output styles."""

from __future__ import annotations

import json

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import Issue, IssueType
from tests.test_bead.cli_show_style_test_helpers import (
    CORPUS,
    STRIP_SGR,
    CorpusBuilder,
    build_closed_with_resolution,
    build_epic_with_children,
    build_markdown_description,
    build_with_notes,
    install_view,
    read_golden,
    render,
    strip_sgr,
)
from tests.test_bead.cli_show_test_helpers import show_with_format
from tests.main.parser_cli_helpers import parse_sase_args


@pytest.mark.parametrize("name,build", CORPUS, ids=[case[0] for case in CORPUS])
def test_style_invariant_over_corpus(
    name: str,
    build: CorpusBuilder,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issues, target_id = build()

    plain = render(
        target_id,
        issues,
        style="plain",
        color="always",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    rich = render(
        target_id,
        issues,
        style="rich",
        color="always",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert strip_sgr(rich) == plain


@pytest.mark.parametrize("wrap", ["none", "40", "120"])
@pytest.mark.parametrize("name,build", CORPUS, ids=[case[0] for case in CORPUS])
def test_style_invariant_over_corpus_per_wrap_width(
    name: str,
    build: CorpusBuilder,
    wrap: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issues, target_id = build()

    plain = render(
        target_id,
        issues,
        style="plain",
        color="always",
        wrap=wrap,
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    rich = render(
        target_id,
        issues,
        style="rich",
        color="always",
        wrap=wrap,
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert strip_sgr(rich) == plain


@pytest.mark.parametrize("name,build", CORPUS, ids=[case[0] for case in CORPUS])
def test_compact_style_invariant_over_corpus(
    name: str,
    build: CorpusBuilder,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The compact format responds to style in the same way as full output."""
    issues, target_id = build()

    plain = render(
        target_id,
        issues,
        style="plain",
        color="always",
        format_="compact",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    rich = render(
        target_id,
        issues,
        style="rich",
        color="always",
        format_="compact",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert strip_sgr(rich) == plain


@pytest.mark.parametrize("name,build", CORPUS, ids=[case[0] for case in CORPUS])
def test_json_format_ignores_style_over_corpus(
    name: str,
    build: CorpusBuilder,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """JSON output remains unstyled and valid across every bead shape."""
    issues, target_id = build()

    plain = render(
        target_id,
        issues,
        style="plain",
        color="always",
        format_="json",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    rich = render(
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
    args = parse_sase_args(
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
    args = parse_sase_args(
        ["bead", "show", phase.id, "--style", "rich", "--color", "always"]
    )
    bead_cli.handle_bead_show(args)
    rich = capsys.readouterr().out

    assert strip_sgr(rich) == plain


def test_raw_escape_content_is_passed_through_not_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A literal escape byte is preserved despite breaking the SGR invariant."""
    issue = Issue(
        id="bd-raw-escape",
        title="Task With Raw Escape",
        issue_type=IssueType.TASK,
        description="literal \x1b[31m escape stays as-is",
    )
    issues = {issue.id: issue}

    plain = render(
        issue.id,
        issues,
        style="plain",
        color="always",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    rich = render(
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
    issues, target_id = build_markdown_description()

    rich = render(
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
    issues, target_id = build_markdown_description()

    plain = render(
        target_id,
        issues,
        style="plain",
        color="always",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert "\x1b" not in plain


def test_rich_style_with_color_never_emits_zero_escapes_for_notes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issues, target_id = build_with_notes()

    out = render(
        target_id,
        issues,
        style="rich",
        color="never",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert "\x1b" not in out
    assert "NOTES (2)" in out
    assert "#1 ·" in out


def test_default_non_tty_stdout_emits_zero_escapes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Regression guard for every agent that shells out to this command."""
    issues, target_id = build_markdown_description()
    install_view(monkeypatch, issues)

    args = parse_sase_args(["bead", "show", target_id])
    bead_cli.handle_bead_show(args)
    out = capsys.readouterr().out

    assert "\x1b" not in out


def test_json_is_never_styled_even_with_rich_and_color_always(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issues, target_id = build_markdown_description()
    install_view(monkeypatch, issues)

    args = parse_sase_args(
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


def test_show_epic_with_children_rich_ansi_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issues, target_id = build_epic_with_children()

    out = render(
        target_id,
        issues,
        style="rich",
        color="always",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert out == read_golden("show_style_epic.ansi")


def test_show_closed_phase_with_markdown_rich_ansi_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issues, target_id = build_closed_with_resolution()
    issues[target_id].description = (
        "# Summary\n\nFixed the bug:\n\n- root caused by X\n- patched Y\n\n"
        "```python\ndef fixed():\n    return True\n```"
    )
    out = render(
        target_id,
        issues,
        style="rich",
        color="always",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert out == read_golden("show_style_closed_phase.ansi")


def test_show_closed_phase_with_markdown_rich_ansi_snapshot_ignores_no_color(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    issues, target_id = build_closed_with_resolution()
    issues[target_id].description = (
        "# Summary\n\nFixed the bug:\n\n- root caused by X\n- patched Y\n\n"
        "```python\ndef fixed():\n    return True\n```"
    )
    out = render(
        target_id,
        issues,
        style="rich",
        color="always",
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    assert out == read_golden("show_style_closed_phase.ansi")

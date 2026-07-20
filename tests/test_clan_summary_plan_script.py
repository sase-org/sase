"""Script-level coverage for the generic plan clan summary executable."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path
import re

import pytest
from rich.cells import cell_len
from rich.text import Text

from sase.scripts._rich_summary import serialize_lines
from sase.scripts.sase_clan_summary_plan import (
    PLAN_SUMMARY_MAX_UTF8_BYTES,
    PLAN_SUMMARY_WIDTH,
    _render_plan_summary,
    main,
)
from sase.sdd.plan_display import (
    PlanDisplay,
    PlanDisplayPhase,
    load_plan_display,
    render_plan_lines,
)
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN


def _write_plan(path: Path, content: str, *, title: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        content.replace("Approved implementation", title),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    ("content", "expected_tier", "expected_phase"),
    [
        (VALID_TALE_PLAN, "tale", None),
        (VALID_EPIC_PLAN, "epic", "Implement the requested change"),
    ],
    ids=["tale", "epic"],
)
def test_plan_summary_explicit_argument_renders_valid_plan_lane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    content: str,
    expected_tier: str,
    expected_phase: str | None,
) -> None:
    _write_plan(
        tmp_path / "plans" / "authored plan.md",
        content,
        title="Ship [safely]",
    )
    monkeypatch.chdir(tmp_path)
    plan_ref = "plans/authored plan.md"

    assert main([plan_ref]) == 0

    captured = capsys.readouterr()
    markup = captured.out.rstrip("\n")
    rendered = Text.from_markup(markup)
    assert f"▸ PLAN · {expected_tier}" in rendered.plain
    assert "Title: Ship [safely]" in rendered.plain
    assert f"Path: {plan_ref}" in rendered.plain
    if expected_phase is None:
        assert "◆" not in rendered.plain
    else:
        assert expected_phase in rendered.plain
    assert "\\[safely]" in markup
    assert all(
        cell_len(line) <= PLAN_SUMMARY_WIDTH for line in rendered.plain.splitlines()
    )
    assert captured.err == ""


def test_plan_summary_environment_fallback_and_explicit_argument_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env_plan = _write_plan(
        tmp_path / "env.md", VALID_TALE_PLAN, title="Environment plan"
    )
    explicit_plan = _write_plan(
        tmp_path / "explicit.md",
        VALID_TALE_PLAN,
        title="Explicit plan",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SASE_EPIC_PLAN_REF", env_plan.name)

    assert main([]) == 0
    env_output = Text.from_markup(capsys.readouterr().out).plain
    assert "Environment plan" in env_output

    assert main([explicit_plan.name]) == 0
    explicit_output = Text.from_markup(capsys.readouterr().out).plain
    assert "Explicit plan" in explicit_output
    assert "Environment plan" not in explicit_output


def test_plan_summary_serialization_matches_shared_width_aware_renderer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = _write_plan(tmp_path / "epic.md", VALID_EPIC_PLAN, title="Renderer parity")
    monkeypatch.chdir(tmp_path)
    expected = load_plan_display(plan, display_path=plan.name)

    assert main([plan.name]) == 0

    markup = capsys.readouterr().out.rstrip("\n")
    expected_markup = serialize_lines(
        render_plan_lines(expected, width=PLAN_SUMMARY_WIDTH)
    )
    assert markup == expected_markup
    assert Text.from_markup(markup).plain == Text.from_markup(expected_markup).plain


def test_large_plan_omits_only_complete_tail_phase_blocks_within_utf8_budget() -> None:
    phases = tuple(
        PlanDisplayPhase(
            id=f"phase-{index}",
            title=f"Phase {index} " + "界 roadmap " * 8,
            depends_on=((f"phase-{index - 1}",) if index > 1 else ()),
            description="Preserve [literal] markup while rendering the complete block.",
            size=("small", "medium", "large")[(index - 1) % 3],
            model="codex/gpt-5.6-sol",
        )
        for index in range(1, 1001)
    )
    summary = PlanDisplay(
        title="Large epic",
        goal="Retain complete leading fields and whole phase blocks.",
        authored_tier="epic",
        effective_tier="epic",
        actual_path="/tmp/large.md",
        display_path="plans/large.md",
        committed=True,
        exists=True,
        readable=True,
        frontmatter_readable=True,
        phase_availability="available",
        phases=phases,
        validation_ok=True,
    )

    markup = _render_plan_summary(summary)
    rendered = Text.from_markup(markup)

    assert len(markup.encode("utf-8")) <= PLAN_SUMMARY_MAX_UTF8_BYTES
    omission = re.search(
        r"… (\d+) phase blocks omitted to fit summary size",
        rendered.plain,
    )
    assert omission is not None
    omitted = int(omission.group(1))
    included = len(phases) - omitted
    assert included > 0
    assert f"phase-{included} ·" in rendered.plain
    assert f"phase-{included + 1} ·" not in rendered.plain
    assert all(
        cell_len(line) <= PLAN_SUMMARY_WIDTH for line in rendered.plain.splitlines()
    )


@pytest.mark.parametrize("kind", ["missing", "invalid"])
def test_plan_summary_failures_emit_escaped_successful_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    kind: str,
) -> None:
    plan_ref = "missing[plan].md"
    if kind == "invalid":
        plan_ref = "invalid[plan].md"
        (tmp_path / plan_ref).write_text(
            "---\ntier: tale\ntitle: Invalid\n---\n# Plan\n",
            encoding="utf-8",
        )
    monkeypatch.chdir(tmp_path)

    assert main([plan_ref]) == 0

    captured = capsys.readouterr()
    assert captured.out == f"[bold]PLAN {plan_ref.replace('[', r'\[')}[/]\n"
    assert Text.from_markup(captured.out).plain == f"PLAN {plan_ref}\n"
    assert "Unable to load plan clan summary" in captured.err


def test_console_entry_point_is_registered() -> None:
    matches = [
        entry
        for entry in importlib.metadata.entry_points(group="console_scripts")
        if entry.name == "sase_clan_summary_plan"
    ]

    assert len(matches) == 1
    assert matches[0].value == "sase.scripts.sase_clan_summary_plan:main"

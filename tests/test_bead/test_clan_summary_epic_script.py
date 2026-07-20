"""Tests for the built-in epic clan-summary console script."""

from __future__ import annotations

from pathlib import Path
import re

import pytest
from rich.cells import cell_len
from rich.text import Text

from sase.bead.config import load_config
from sase.bead.model import BeadTier, Issue, IssueType, PhaseSize, Status
from sase.bead.project import BeadProject
from sase.scripts._rich_summary import render_markdown_lines
from sase.scripts.sase_clan_summary_epic import (
    _SUMMARY_MAX_UTF8_BYTES,
    _render_epic_summary,
    _render_plan_summary,
    main,
)
from sase.sdd.plan_display import PlanDisplay, PlanDisplayPhase
from tests.plan_validation_helpers import VALID_EPIC_PLAN


def _write_epic_plan(path: Path, *, title: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        VALID_EPIC_PLAN.replace("Approved implementation", title),
        encoding="utf-8",
    )
    return path


def _patch_unexpected_bead_load(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_bead_load(_epic_id: str) -> None:
        raise AssertionError("a valid authored plan must bypass the bead store")

    monkeypatch.setattr(
        "sase.scripts.sase_clan_summary_epic._load_epic_with_refresh",
        unexpected_bead_load,
    )


def test_epic_summary_renders_valid_environment_plan_before_bead_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan_ref = "plans/authored[epic].md"
    plan = _write_epic_plan(tmp_path / plan_ref, title="Ship [safe] clan context")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SASE_CLAN_NAME", "sase-[epic]")
    monkeypatch.setenv("SASE_EPIC_PLAN_REF", plan_ref)
    _patch_unexpected_bead_load(monkeypatch)

    assert main() == 0

    captured = capsys.readouterr()
    markup = captured.out.rstrip("\n")
    rendered = Text.from_markup(markup)
    assert rendered.plain.splitlines()[0] == "◆ EPIC sase-[epic]"
    assert "▸ PLAN" not in rendered.plain
    assert "Title: Ship [safe] clan context" in rendered.plain
    assert "Goal: Deliver the approved implementation in ordered phases" in (
        rendered.plain
    )
    assert f"Path: {plan_ref}" in rendered.plain
    assert "implementation · no dependencies" in rendered.plain
    assert "Implement the requested change' section" in rendered.plain
    assert "PHASES ·" not in rendered.plain
    assert str(plan) not in rendered.plain
    assert "\\[epic]" in markup
    assert "\\[safe]" in markup
    assert all(cell_len(line) <= 76 for line in rendered.plain.splitlines())
    assert len(markup.encode("utf-8")) <= _SUMMARY_MAX_UTF8_BYTES
    assert captured.err == ""


def test_epic_summary_resolves_absolute_plan_reference_directly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = _write_epic_plan(tmp_path / "absolute.md", title="Absolute source")
    launch = tmp_path / "launch"
    launch.mkdir()
    monkeypatch.chdir(launch)
    monkeypatch.setenv("SASE_CLAN_NAME", "sase-absolute")
    monkeypatch.setenv("SASE_EPIC_PLAN_REF", str(plan))
    monkeypatch.setattr(
        "sase.scripts.sase_clan_summary_epic._resolve_primary_checkout",
        lambda: (_ for _ in ()).throw(
            AssertionError("absolute references must not resolve project metadata")
        ),
    )
    _patch_unexpected_bead_load(monkeypatch)

    assert main() == 0

    captured = capsys.readouterr()
    rendered = Text.from_markup(captured.out)
    assert "Title: Absolute source" in rendered.plain
    assert "Path: /" in rendered.plain
    assert plan.name in rendered.plain
    assert captured.err == ""


@pytest.mark.parametrize(
    ("current_title", "expected_title"),
    [("Current workspace plan", "Current workspace plan"), (None, "Primary plan")],
    ids=["current-workspace-precedence", "primary-checkout-fallback"],
)
def test_epic_summary_resolves_relative_plan_across_known_checkout_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    current_title: str | None,
    expected_title: str,
) -> None:
    launch = tmp_path / "launch"
    primary = tmp_path / "primary"
    launch.mkdir()
    primary.mkdir()
    plan_ref = "sase/repos/plans/202607/epic.md"
    _write_epic_plan(primary / plan_ref, title="Primary plan")
    if current_title is not None:
        _write_epic_plan(launch / plan_ref, title=current_title)

    monkeypatch.chdir(launch)
    monkeypatch.setenv("SASE_CLAN_NAME", "sase-roots")
    monkeypatch.setenv("SASE_EPIC_PLAN_REF", plan_ref)

    def resolve_primary() -> Path:
        if current_title is not None:
            raise AssertionError(
                "a valid current-workspace plan must win before metadata lookup"
            )
        return primary

    monkeypatch.setattr(
        "sase.scripts.sase_clan_summary_epic._resolve_primary_checkout",
        resolve_primary,
    )
    _patch_unexpected_bead_load(monkeypatch)

    assert main() == 0

    captured = capsys.readouterr()
    rendered = Text.from_markup(captured.out)
    assert f"Title: {expected_title}" in rendered.plain
    unexpected_title = (
        "Primary plan" if expected_title == "Current workspace plan" else None
    )
    if unexpected_title is not None:
        assert f"Title: {unexpected_title}" not in rendered.plain
    assert f"Path: {plan_ref}" in rendered.plain
    assert captured.err == ""


@pytest.mark.parametrize("kind", ["missing", "unreadable", "invalid"])
def test_unusable_plan_reference_falls_back_to_legacy_bead_summary(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    kind: str,
) -> None:
    with BeadProject(project_dir) as project:
        epic = project.create(
            "Stable bead fallback",
            IssueType.PLAN,
            description="Keep the established fallback shape.",
            tier=BeadTier.EPIC,
        )
        project.create(
            "Legacy fallback phase",
            IssueType.PHASE,
            parent_id=epic.id,
            size=PhaseSize.MEDIUM,
        )

    plan_ref = f"{kind}.md"
    if kind == "unreadable":
        (project_dir / plan_ref).write_bytes(b"\xff\xfe")
    elif kind == "invalid":
        (project_dir / plan_ref).write_text(
            "---\ntier: epic\ntitle: Invalid\n---\n# Plan\n",
            encoding="utf-8",
        )
    monkeypatch.setenv("SASE_CLAN_NAME", epic.id)
    monkeypatch.setenv("SASE_EPIC_PLAN_REF", plan_ref)

    assert main() == 0

    captured = capsys.readouterr()
    rendered = Text.from_markup(captured.out)
    assert rendered.plain.splitlines()[0] == (
        f"◆ EPIC {epic.id} · Stable bead fallback"
    )
    assert "PHASES · 0/1 done at launch" in rendered.plain
    assert "○ 1. Legacy fallback phase" in rendered.plain
    assert captured.err == ""


def test_plan_and_bead_failure_emit_diagnostics_and_safe_identity_fallback(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del project_dir
    epic_id = "missing[epic]"
    plan_ref = "missing[plan].md"
    monkeypatch.setenv("SASE_CLAN_NAME", epic_id)
    monkeypatch.setenv("SASE_EPIC_PLAN_REF", plan_ref)
    monkeypatch.setattr(
        "sase.scripts.sase_clan_summary_epic.bead_refresh_mode",
        lambda: "off",
    )

    assert main() == 0

    captured = capsys.readouterr()
    assert captured.out == "[bold]EPIC missing\\[epic][/]\n"
    assert Text.from_markup(captured.out).plain == f"EPIC {epic_id}\n"
    assert "Unable to load epic clan summary for 'missing[epic]'" in captured.err
    assert f"Plan reference {plan_ref!r} was also unavailable" in captured.err
    assert "plan file does not exist" in captured.err
    assert "Traceback (most recent call last):" in captured.err


def test_plan_summary_omits_only_complete_tail_phase_blocks_within_budget() -> None:
    phases = tuple(
        PlanDisplayPhase(
            id=f"phase-{index}",
            title=f"Phase {index} " + "界 roadmap " * 8,
            depends_on=((f"phase-{index - 1}",) if index > 1 else ()),
            description=(
                f"Phase {index} description preserves [literal] markup and the "
                "complete plan block."
            ),
            size=("small", "medium", "large")[(index - 1) % 3],
            model="codex/gpt-5.6-sol",
        )
        for index in range(1, 1001)
    )
    summary = PlanDisplay(
        title="Large authored epic",
        goal="Retain complete leading fields and whole phase blocks.",
        authored_tier="epic",
        effective_tier="epic",
        actual_path="/tmp/large.md",
        display_path="plans/large[epic].md",
        committed=True,
        exists=True,
        readable=True,
        frontmatter_readable=True,
        phase_availability="available",
        phases=phases,
        validation_ok=True,
    )

    markup = _render_plan_summary("sase-large[epic]", summary)
    rendered = Text.from_markup(markup)

    assert len(markup.encode("utf-8")) <= _SUMMARY_MAX_UTF8_BYTES
    omission = re.search(
        r"… (\d+) phase blocks omitted to fit summary size",
        rendered.plain,
    )
    assert omission is not None
    omitted = int(omission.group(1))
    included = len(phases) - omitted
    assert included > 0
    assert f"phase-{included} ·" in rendered.plain
    assert f"Phase {included} description" in rendered.plain
    assert f"phase-{included + 1} ·" not in rendered.plain
    assert f"Phase {included + 1} description" not in rendered.plain
    assert all(cell_len(line) <= 76 for line in rendered.plain.splitlines())


def test_markdown_helper_renders_semantic_styles_and_safe_markup() -> None:
    rendered = render_markdown_lines(
        "**Bold** and `inline[code]` with literal [brackets].\n\n- one\n- two",
        width=32,
    )

    assert rendered.used_markdown is True
    assert rendered.lines
    assert all(not line.plain.endswith(" ") for line in rendered.lines)
    reparsed = Text.from_markup(rendered.markup)
    assert "Bold and inline[code] with\nliteral" in reparsed.plain
    assert " • one" in reparsed.plain
    assert " • two" in reparsed.plain
    assert any("bold" in str(span.style) for span in reparsed.spans)
    assert "\\[code]" in rendered.markup
    assert "\\[brackets]" in rendered.markup


def test_markdown_helper_uses_lightweight_plain_path_and_caps_complete_lines() -> None:
    plain = render_markdown_lines(
        "Literal [brackets] stay safe while ordinary words wrap cleanly.",
        width=18,
    )
    assert plain.used_markdown is False
    assert all(not line.plain.endswith(" ") for line in plain.lines)
    assert Text.from_markup(plain.markup).plain == "\n".join(
        line.plain for line in plain.lines
    )

    capped = render_markdown_lines("\n".join(f"line {i}" for i in range(8)), width=18)
    assert capped.cap(6, width=18).lines[-1].plain.endswith("…")
    assert not capped.cap(8, width=18).lines[-1].plain.endswith("…")


def test_epic_summary_renders_markdown_progress_sizes_children_and_plan(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        epic = project.create(
            "Beautiful [clan] summaries",
            IssueType.PLAN,
            description=(
                "Show the **full goal** with `launch[state]` context.\n\n"
                "- Keep output stable\n"
                "- Preserve literal [brackets]"
            ),
            design="202607/plan[approved].md",
            tier=BeadTier.EPIC,
        )
        open_phase = project.create(
            "Parse [bold]directives[/bold]",
            IssueType.PHASE,
            parent_id=epic.id,
            description="Handle **Rich** descriptions safely.",
            size=PhaseSize.SMALL,
        )
        active_phase = project.create(
            "Render the clan panel",
            IssueType.PHASE,
            parent_id=epic.id,
            description="Keep `launch_time` status stable.",
            size=PhaseSize.MEDIUM,
        )
        closed_phase = project.create(
            "Inspect wide 界 output",
            IssueType.PHASE,
            parent_id=epic.id,
            description="Finish the visual **goldens**.",
            size=PhaseSize.LARGE,
        )
        legacy_phase = project.create(
            "Support legacy sizeless phases",
            IssueType.PHASE,
            parent_id=epic.id,
        )
        child_epic = project.create(
            "Child [epic] summary",
            IssueType.PLAN,
            parent_id=epic.id,
            tier=BeadTier.EPIC,
        )
        ignored_plan = project.create(
            "Ordinary child plan",
            IssueType.PLAN,
            parent_id=epic.id,
            tier=BeadTier.PLAN,
        )
        project.update(active_phase.id, status=Status.IN_PROGRESS.value)
        project.update(closed_phase.id, status=Status.CLOSED.value)
        project.update(child_epic.id, status=Status.IN_PROGRESS.value)

    monkeypatch.setenv("SASE_CLAN_NAME", epic.id)
    refresh_calls = 0

    def unexpected_refresh() -> None:
        nonlocal refresh_calls
        refresh_calls += 1

    monkeypatch.setattr(
        "sase.scripts.sase_clan_summary_epic.refresh_current_bead_store",
        unexpected_refresh,
    )

    assert main() == 0

    captured = capsys.readouterr()
    markup = captured.out.rstrip("\n")
    rendered = Text.from_markup(markup)
    lines = rendered.plain.splitlines()
    assert lines[0] == f"◆ EPIC {epic.id} · Beautiful [clan] summaries"
    assert "Show the full goal with launch[state] context." in lines
    assert " • Keep output stable" in lines
    assert "PHASES · 1/4 done at launch" in lines
    assert any(line.startswith(f"○ 1. {open_phase.title}") for line in lines)
    assert any(line.startswith(f"◐ 2. {active_phase.title}") for line in lines)
    assert any(line.startswith(f"✓ 3. {closed_phase.title}") for line in lines)
    assert any(line.startswith(f"○ 4. {legacy_phase.title}") for line in lines)
    assert sum(line.endswith(" small ") for line in lines) == 2
    assert any(line.endswith(" medium ") for line in lines)
    assert any(line.endswith(" large ") for line in lines)
    assert "  └ Handle Rich descriptions safely." in lines
    assert "  └ Keep launch_time status stable." in lines
    assert "CHILD EPICS · 1" in lines
    assert f"◐ {child_epic.id} · Child [epic] summary" in lines
    assert ignored_plan.title not in rendered.plain
    assert "Plan: 202607/plan[approved].md" in lines
    assert all(cell_len(line) <= 76 for line in lines)
    assert len(markup.encode("utf-8")) < _SUMMARY_MAX_UTF8_BYTES
    assert "\\[clan]" in markup
    assert "\\[approved]" in markup
    assert any("bold" in str(span.style) for span in rendered.spans)
    assert any(" on " in str(span.style) for span in rendered.spans)
    assert captured.err == ""
    assert refresh_calls == 0


def test_epic_summary_omits_absent_optional_sections() -> None:
    epic = Issue(
        id="sase-empty",
        title="No optional sections",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
    )

    markup = _render_epic_summary(epic, ())
    plain = Text.from_markup(markup).plain
    assert plain.splitlines() == [
        "◆ EPIC sase-empty · No optional sections",
        "PHASES · 0/0 done at launch",
    ]
    assert "CHILD EPICS" not in plain
    assert "Plan:" not in plain


def test_epic_summary_many_phases_stays_parseable_and_below_internal_budget() -> None:
    epic = Issue(
        id="sase-many",
        title="A very large epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        description="A **bounded** launch summary.",
    )
    phases = tuple(
        Issue(
            id=f"sase-many.{index}",
            title=f"Phase {index} with literal [markup] and a long descriptive title "
            * 2,
            issue_type=IssueType.PHASE,
            parent_id=epic.id,
            description="A `markdown` description with **semantic emphasis**.",
            size=(PhaseSize.SMALL, PhaseSize.MEDIUM, PhaseSize.LARGE)[index % 3],
        )
        for index in range(1, 1001)
    )

    markup = _render_epic_summary(epic, phases)
    rendered = Text.from_markup(markup)
    assert len(markup.encode("utf-8")) < _SUMMARY_MAX_UTF8_BYTES
    assert "phase entries omitted to fit summary size" in rendered.plain
    assert all(cell_len(line) <= 76 for line in rendered.plain.splitlines())


def test_epic_summary_refreshes_once_and_retries_missing_epic(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue_prefix = load_config(project_dir / "sdd/beads")["issue_prefix"]
    epic_id = f"{issue_prefix}-1"
    monkeypatch.setenv("SASE_CLAN_NAME", epic_id)
    monkeypatch.setattr(
        "sase.scripts.sase_clan_summary_epic.bead_refresh_mode",
        lambda: "background",
    )
    refresh_calls = 0

    def create_remote_epic() -> None:
        nonlocal refresh_calls
        refresh_calls += 1
        with BeadProject(project_dir) as project:
            epic = project.create(
                "Fresh remote epic",
                IssueType.PLAN,
                description="Available after integration.",
                tier=BeadTier.EPIC,
            )
            assert epic.id == epic_id
            project.create(
                "Recovered phase",
                IssueType.PHASE,
                parent_id=epic.id,
            )

    monkeypatch.setattr(
        "sase.scripts.sase_clan_summary_epic.refresh_current_bead_store",
        create_remote_epic,
    )

    assert main() == 0

    captured = capsys.readouterr()
    rendered = Text.from_markup(captured.out)
    assert rendered.plain.splitlines()[0] == f"◆ EPIC {epic_id} · Fresh remote epic"
    assert "Available after integration." in rendered.plain.splitlines()
    assert "PHASES · 0/1 done at launch" in rendered.plain.splitlines()
    assert any(
        line.startswith("○ 1. Recovered phase") for line in rendered.plain.splitlines()
    )
    assert captured.err == ""
    assert refresh_calls == 1


def test_epic_summary_refresh_off_falls_back_with_diagnostics(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del project_dir
    monkeypatch.setenv("SASE_CLAN_NAME", "missing-epic")
    monkeypatch.setattr(
        "sase.scripts.sase_clan_summary_epic.bead_refresh_mode",
        lambda: "off",
    )

    def unexpected_refresh() -> None:
        raise AssertionError("refresh mode off must not integrate")

    monkeypatch.setattr(
        "sase.scripts.sase_clan_summary_epic.refresh_current_bead_store",
        unexpected_refresh,
    )

    assert main() == 0

    captured = capsys.readouterr()
    assert captured.out == "[bold]EPIC missing-epic[/]\n"
    assert "Unable to load epic clan summary for 'missing-epic'" in captured.err
    assert "Traceback (most recent call last):" in captured.err
    assert "KeyError" in captured.err


def test_epic_summary_invalid_bead_does_not_refresh(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        plan = project.create(
            "Not an epic",
            IssueType.PLAN,
            tier=BeadTier.PLAN,
        )
    monkeypatch.setenv("SASE_CLAN_NAME", plan.id)

    def unexpected_refresh() -> None:
        raise AssertionError("invalid bead types must not trigger integration")

    monkeypatch.setattr(
        "sase.scripts.sase_clan_summary_epic.refresh_current_bead_store",
        unexpected_refresh,
    )

    assert main() == 0

    captured = capsys.readouterr()
    assert captured.out == f"[bold]EPIC {plan.id}[/]\n"
    assert "ValueError" in captured.err
    assert "is not an epic plan" in captured.err


@pytest.mark.parametrize("failure", ["refresh", "retry"])
def test_epic_summary_refresh_failure_falls_back_with_diagnostics(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    del project_dir
    monkeypatch.setenv("SASE_CLAN_NAME", "missing-epic")
    monkeypatch.setattr(
        "sase.scripts.sase_clan_summary_epic.bead_refresh_mode",
        lambda: "background",
    )

    def refresh() -> None:
        if failure == "refresh":
            raise RuntimeError("remote integration failed")

    monkeypatch.setattr(
        "sase.scripts.sase_clan_summary_epic.refresh_current_bead_store",
        refresh,
    )

    assert main() == 0

    captured = capsys.readouterr()
    assert captured.out == "[bold]EPIC missing-epic[/]\n"
    assert "Unable to load epic clan summary for 'missing-epic'" in captured.err
    assert "Traceback (most recent call last):" in captured.err
    expected_error = (
        "RuntimeError: remote integration failed"
        if failure == "refresh"
        else "KeyError"
    )
    assert expected_error in captured.err

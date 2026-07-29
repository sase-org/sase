"""Tests for bead-store handling in the epic clan-summary script."""

from __future__ import annotations

from pathlib import Path

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
    main,
)


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
        xsmall_phase = project.create(
            "Sketch the smallest presentation",
            IssueType.PHASE,
            parent_id=epic.id,
            size=PhaseSize.XSMALL,
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
        xlarge_phase = project.create(
            "Reframe the largest presentation",
            IssueType.PHASE,
            parent_id=epic.id,
            size=PhaseSize.XLARGE,
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
        project.update(open_phase.id, status=Status.CLAIMED.value)
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
    assert "PHASES · 1/6 done at launch" in lines
    assert any(line.startswith(f"○ 1. {xsmall_phase.title}") for line in lines)
    assert any(line.startswith(f"◎ 2. {open_phase.title}") for line in lines)
    assert any(line.startswith(f"◐ 3. {active_phase.title}") for line in lines)
    assert any(line.startswith(f"✓ 4. {closed_phase.title}") for line in lines)
    assert any(line.startswith(f"○ 5. {xlarge_phase.title}") for line in lines)
    assert any(line.startswith(f"○ 6. {legacy_phase.title}") for line in lines)
    assert any(line.endswith(" xsmall ") for line in lines)
    assert sum(line.endswith(" small ") for line in lines) == 2
    assert any(line.endswith(" medium ") for line in lines)
    assert any(line.endswith(" large ") for line in lines)
    assert any(line.endswith(" xlarge ") for line in lines)
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
    assert "Page:" not in plain


def test_epic_summary_places_bead_page_after_plan_reference() -> None:
    page_url = (
        "https://github.com/sase-org/sase--beads/blob/main/pages/sase-page/README.md"
    )
    epic = Issue(
        id="sase-page",
        title="Hosted bead page",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        design="plans:202607/hosted.md",
    )

    rendered = Text.from_markup(_render_epic_summary(epic, (), page_url=page_url))
    lines = rendered.plain.splitlines()
    plan_index = next(
        index for index, line in enumerate(lines) if line.startswith("Plan: ")
    )
    page_index = next(
        index for index, line in enumerate(lines) if line.startswith("Page: ")
    )

    assert page_index > plan_index
    assert lines[page_index - 1]
    assert lines[page_index].endswith("/")
    assert lines[page_index + 1] == "      README.md"
    assert all(cell_len(line) <= 76 for line in lines)


def test_epic_summary_separates_page_region_without_plan_reference() -> None:
    page_url = (
        "https://github.com/sase-org/sase--beads/blob/main/pages/sase-page/README.md"
    )
    epic = Issue(
        id="sase-page",
        title="Hosted bead page",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
    )

    rendered = Text.from_markup(_render_epic_summary(epic, (), page_url=page_url))
    lines = rendered.plain.splitlines()
    page_index = next(
        index for index, line in enumerate(lines) if line.startswith("Page: ")
    )

    assert lines[page_index - 1] == ""
    assert lines[page_index].endswith("/")
    assert lines[page_index + 1] == "      README.md"
    assert "Plan:" not in rendered.plain
    assert all(cell_len(line) <= 76 for line in lines)


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

    markup = _render_epic_summary(
        epic,
        phases,
        page_url=(
            "https://github.com/sase-org/sase--beads/blob/main/pages/"
            "sase-many/README.md"
        ),
    )
    rendered = Text.from_markup(markup)
    assert len(markup.encode("utf-8")) < _SUMMARY_MAX_UTF8_BYTES
    assert "phase entries" in rendered.plain
    assert "bead page link" in rendered.plain
    assert "omitted to fit summary size" in rendered.plain
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


def test_epic_summary_shows_where_the_plan_reference_resolves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plans_root = tmp_path / "plans"
    (plans_root / "202607").mkdir(parents=True)
    plan = plans_root / "202607/durable.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.sdd.plan_refs.resolve_plan_roots",
        lambda *_args, **_kwargs: (plans_root,),
    )
    epic = Issue(
        id="sase-ref",
        title="Durable link",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        design="plans:202607/durable.md",
    )

    plain = Text.from_markup(_render_epic_summary(epic, ())).plain
    lines = plain.splitlines()

    assert "Plan: plans:202607/durable.md" in lines
    resolved_line = next(line for line in lines if line.lstrip().startswith("→"))
    body = resolved_line.strip().removeprefix("→ ").rstrip("…")
    assert str(plan).startswith(body)
    assert all(cell_len(line) <= 76 for line in lines)


def test_epic_summary_says_plainly_when_the_plan_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.sdd.plan_refs.resolve_plan_roots",
        lambda *_args, **_kwargs: (tmp_path / "plans",),
    )
    epic = Issue(
        id="sase-gone",
        title="Broken link",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        design="plans:202607/gone.md",
    )

    plain = Text.from_markup(_render_epic_summary(epic, ())).plain

    assert "Plan: plans:202607/gone.md" in plain
    assert "→ (unresolved: no plan file found)" in plain

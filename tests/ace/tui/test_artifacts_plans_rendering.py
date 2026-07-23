"""List and detail rendering coverage for the Artifacts Plans pane."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
from rich.console import Console
from textual.color import Color
from textual.widgets import Markdown, OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts import plans_detail, plans_pane
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsPlansPane
from sase.ace.tui.widgets.artifacts.plans_data import ProjectIssue
from sase.bead.model import PhaseSize, Status
from sase.phase_size_presentation import PHASE_SIZE_STYLES
from tests.ace.tui._artifacts_plans_helpers import (
    _all_projects_snapshot,
    _choices,
    _snapshot,
)


def _render_detail(renderable: object) -> str:
    console = Console(width=100, color_system=None)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def test_plan_list_rows_are_compact_single_line_labels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(tmp_path)
    proposal = snapshot.proposals[0]
    epic = replace(
        snapshot.epics[0].issue,
        title="A very long epic title that must never wrap onto a second row",
        created_at="2026-05-16T12:00:00Z",
    )
    phases = tuple(
        replace(
            item.issue,
            title="A very long phase title that must never wrap onto a second row",
        )
        for item in snapshot.phases_by_epic[("alpha", "alpha-1")]
    )
    monkeypatch.setattr(
        "sase.core.time.local_now",
        lambda: datetime(2026, 7, 16, 12, 0, 0),
    )

    labels = (
        plans_pane._proposal_text(proposal),
        plans_pane._epic_text(
            epic,
            phases,
            expanded=False,
            project="alpha",
            ready_ids=snapshot.ready_ids,
            blocked_ids=snapshot.blocked_ids,
        ),
        plans_pane._phase_text(
            phases[0],
            project="alpha",
            ready_ids=snapshot.ready_ids,
            blocked_ids=snapshot.blocked_ids,
        ),
        plans_pane._archive_text(snapshot.archive[0].match),
    )
    console = Console(width=24)

    for label in labels:
        assert label.no_wrap is True
        assert label.overflow == "ellipsis"
        assert len(label.wrap(console, 24)) == 1
        assert "\n" not in label.plain

    assert labels[0].plain.endswith("epic  2m")
    assert "phases" not in labels[1].plain
    assert "alpha-cl" not in labels[1].plain
    assert "#42" not in labels[1].plain
    assert labels[1].plain.startswith("▸ ○ alpha-1 0/2 ► ")
    assert labels[1].plain.endswith("  2mo")
    assert "codex/gpt-5" not in labels[2].plain
    assert labels[2].plain.startswith("↳ ○ alpha-1.1 ►  small  ")
    assert labels[3].plain.endswith("epic  done  07-04")


def test_plan_list_rows_use_fixed_width_state_glyphs(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    epic = snapshot.epics[0].issue
    phases = tuple(item.issue for item in snapshot.phases_by_epic[("alpha", epic.id)])

    def epic_label(
        *,
        ready: bool = False,
        blocked: bool = False,
        launched: bool = False,
    ) -> str:
        issue = replace(epic, is_ready_to_work=launched)
        key = ("alpha", issue.id)
        return plans_pane._epic_text(
            issue,
            phases,
            expanded=False,
            project="alpha",
            ready_ids=frozenset({key}) if ready else frozenset(),
            blocked_ids=frozenset({key}) if blocked else frozenset(),
        ).plain

    assert " 0/2 ⊜ " in epic_label(blocked=True)
    assert " 0/2 ► " in epic_label(ready=True)
    assert " 0/2 ▶ " in epic_label(launched=True)
    assert " 0/2 · " in epic_label()

    ready_phase = plans_pane._phase_text(
        phases[0],
        project="alpha",
        ready_ids=frozenset({("alpha", phases[0].id)}),
        blocked_ids=frozenset(),
    ).plain
    blocked_phase = plans_pane._phase_text(
        phases[1],
        project="alpha",
        ready_ids=frozenset(),
        blocked_ids=frozenset({("alpha", phases[1].id)}),
    ).plain
    active_phase = plans_pane._phase_text(
        replace(phases[0], status=Status.IN_PROGRESS),
        project="alpha",
        ready_ids=frozenset(),
        blocked_ids=frozenset(),
    ).plain

    assert ready_phase.startswith("↳ ○ alpha-1.1 ►  small  ")
    assert blocked_phase.startswith("↳ ○ alpha-1.2 ⊜  medium ")
    assert active_phase.startswith("↳ ◐ alpha-1.1 ·  small  ")
    assert "active" not in active_phase


@pytest.mark.parametrize(
    ("size", "label"),
    [
        (PhaseSize.XSMALL, "xsmall"),
        (PhaseSize.SMALL, "small"),
        (PhaseSize.MEDIUM, "medium"),
        (PhaseSize.LARGE, "large"),
        (PhaseSize.XLARGE, "xlarge"),
        (None, "small"),
    ],
)
def test_phase_rows_show_persisted_size_with_legacy_small_fallback(
    tmp_path: Path,
    size: PhaseSize | None,
    label: str,
) -> None:
    snapshot = _snapshot(tmp_path)
    phase = replace(
        snapshot.phases_by_epic[("alpha", "alpha-1")][0].issue,
        size=size,
        title="A flexible title that yields to ellipsis",
    )

    row = plans_pane._phase_text(
        phase,
        project="alpha",
        ready_ids=snapshot.ready_ids,
        blocked_ids=snapshot.blocked_ids,
    )
    rendered = row.wrap(Console(width=31), 31)[0]

    assert f"►  {label}" in rendered.plain
    assert "flexible title" not in rendered.plain
    assert any(str(span.style) == PHASE_SIZE_STYLES[label] for span in row.spans)


async def test_plan_list_options_stay_single_line_when_narrow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda _project, **_kwargs: snapshot,
    )

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("2")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        option_list = pane.query_one("#plans-list", OptionList)

        option_list._line_cache.clear()
        option_list._update_lines()

        assert option_list.styles.text_wrap == "nowrap"
        assert option_list.styles.text_overflow == "ellipsis"
        assert option_list.option_count > 0
        assert set(option_list._line_cache.heights.values()) == {1}
        assert len(option_list._line_cache.lines) == option_list.option_count


def test_epics_section_header_explains_state_glyphs(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    options, _rows = plans_pane.build_plan_options(
        snapshot,
        project_scope="alpha",
        loading=False,
        expanded_epics=set(),
    )
    header = next(option for option in options if option.id == "header:epics")

    assert header.prompt.plain == ("── Epics (1) · ⊜ blocked ► ready ▶ launched ──")


def test_project_badges_render_only_for_all_projects_scope(tmp_path: Path) -> None:
    single = _snapshot(tmp_path)
    all_projects = _all_projects_snapshot(tmp_path)
    proposal = all_projects.proposals[0]
    epic = all_projects.epics[0].issue
    phases = tuple(
        item.issue for item in all_projects.phases_by_epic[("beta", epic.id)]
    )
    archive = all_projects.archive[0].match

    all_labels = (
        plans_pane._proposal_text(
            proposal,
            project_badge=plans_pane._project_badge(all_projects, "beta"),
        ),
        plans_pane._epic_text(
            epic,
            phases,
            expanded=False,
            project="beta",
            ready_ids=all_projects.ready_ids,
            blocked_ids=all_projects.blocked_ids,
            project_badge=plans_pane._project_badge(all_projects, "beta"),
        ),
        plans_pane._archive_text(
            archive,
            project_badge=plans_pane._project_badge(all_projects, "beta"),
        ),
    )
    single_labels = (
        plans_pane._proposal_text(
            single.proposals[0],
            project_badge=plans_pane._project_badge(single, "alpha"),
        ),
        plans_pane._epic_text(
            single.epics[0].issue,
            tuple(
                item.issue
                for item in single.phases_by_epic[("alpha", single.epics[0].issue.id)]
            ),
            expanded=False,
            project="alpha",
            ready_ids=single.ready_ids,
            blocked_ids=single.blocked_ids,
            project_badge=plans_pane._project_badge(single, "alpha"),
        ),
        plans_pane._archive_text(
            single.archive[0].match,
            project_badge=plans_pane._project_badge(single, "alpha"),
        ),
    )

    assert all(label.plain.endswith("[Beta]") for label in all_labels)
    assert all("[Alpha]" not in label.plain for label in single_labels)


def test_all_projects_status_names_projects_with_load_errors(tmp_path: Path) -> None:
    pane = ArtifactsPlansPane()
    pane._snapshot = replace(
        _all_projects_snapshot(tmp_path),
        errors={"beta": "Unable to read beads"},
    )

    status = pane._status_text().plain

    assert status.startswith("2 projects")
    assert "Load errors: Beta" in status


def test_detail_properties_render_all_frontmatter_in_stable_order(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    frontmatter = {
        "zeta": "last",
        "goal": "A long goal that remains readable and wraps inside the value column.",
        "create_time": "2026-07-16 12:00:00",
        "status": "wip",
        "tier": "epic",
        "title": "Property-rich plan",
        "alpha": "first extra",
        "phases": "one(size=small) · two(size=medium) · three(size=large)",
    }
    proposal = replace(snapshot.proposals[0], frontmatter=frontmatter)
    archive = replace(
        snapshot.archive[0].match,
        plan=replace(snapshot.archive[0].match.plan, frontmatter=frontmatter),
    )

    ordered_keys = [
        key for key, _value in plans_detail._ordered_frontmatter_items(frontmatter)
    ]
    proposal_detail = _render_detail(
        plans_detail.proposal_properties_header(proposal, project_name="Alpha")
    )
    archive_detail = _render_detail(
        plans_detail.archive_properties_header(archive, project_name="Alpha")
    )

    assert ordered_keys == [
        "title",
        "tier",
        "status",
        "create_time",
        "goal",
        "alpha",
        "phases",
        "zeta",
    ]
    for value in frontmatter.values():
        assert value in proposal_detail
        assert value in archive_detail
    assert "Source" in archive_detail
    assert "Project" in archive_detail
    assert "archive.md" in "".join(archive_detail.split())
    assert proposal_detail.count("Phases") == 1
    assert archive_detail.count("Phases") == 1
    for label in ("small", "medium", "large"):
        assert proposal_detail.count(label) == 1
        assert archive_detail.count(label) == 1


def test_bead_detail_uses_persisted_phase_sizes_and_fixed_epic_breakdown(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    epic = snapshot.epics[0].issue
    first, second = snapshot.phases_by_epic[("alpha", epic.id)]
    xsmall_issue = replace(
        first.issue,
        id="alpha-1.0",
        title="Extra-small phase",
        size=PhaseSize.XSMALL,
        dependencies=[],
    )
    third_issue = replace(
        second.issue,
        id="alpha-1.3",
        title="Large phase",
        size=PhaseSize.LARGE,
        dependencies=[],
    )
    xlarge_issue = replace(
        second.issue,
        id="alpha-1.4",
        title="Extra-large phase",
        size=PhaseSize.XLARGE,
        dependencies=[],
    )
    legacy_issue = replace(
        second.issue,
        id="alpha-1.5",
        title="Legacy phase",
        size=None,
        dependencies=[],
    )
    snapshot = replace(
        snapshot,
        phases_by_epic={
            ("alpha", epic.id): (
                ProjectIssue("alpha", xsmall_issue),
                first,
                second,
                ProjectIssue("alpha", third_issue),
                ProjectIssue("alpha", xlarge_issue),
                ProjectIssue("alpha", legacy_issue),
            )
        },
    )

    epic_detail = _render_detail(
        plans_detail.bead_properties_header(
            epic,
            snapshot,
            project="alpha",
            project_name="Alpha",
        )
    )
    phase_detail = _render_detail(
        plans_detail.bead_properties_header(
            third_issue,
            snapshot,
            project="alpha",
            project_name="Alpha",
        )
    )
    legacy_detail = _render_detail(
        plans_detail.bead_properties_header(
            legacy_issue,
            snapshot,
            project="alpha",
            project_name="Alpha",
        )
    )

    assert "Phase sizes" in epic_detail
    assert "1 xsmall · 2 small · 1 medium · 1 large · 1 xlarge" in epic_detail
    assert "\n       Size" not in epic_detail
    assert "Size" in phase_detail and "large" in phase_detail
    assert "Phase sizes" not in phase_detail
    assert "Size" in legacy_detail and "small" in legacy_detail

    epic_preview = plans_detail.bead_preview_markdown(
        epic,
        snapshot,
        project="alpha",
    )
    phase_preview = plans_detail.bead_preview_markdown(
        legacy_issue,
        snapshot,
        project="alpha",
    )
    assert (
        "**Phase sizes:** 1 xsmall · 2 small · 1 medium · 1 large · 1 xlarge"
        in epic_preview
    )
    assert "**Size:** small" in phase_preview


def test_epic_detail_omits_size_breakdown_without_direct_phase_context(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    epic = snapshot.epics[0].issue
    snapshot = replace(snapshot, phases_by_epic={})

    detail = _render_detail(
        plans_detail.bead_properties_header(
            epic,
            snapshot,
            project="alpha",
            project_name="Alpha",
        )
    )

    assert "Phase sizes" not in detail


def test_bead_detail_keeps_dependency_states_in_properties(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    dependent = snapshot.phases_by_epic[("alpha", "alpha-1")][1].issue

    detail = _render_detail(
        plans_detail.bead_properties_header(
            dependent,
            snapshot,
            project="alpha",
            project_name="Alpha",
        )
    )

    assert "Dependencies" in detail
    assert "alpha-1.1" in detail
    assert "open" in detail
    assert "blocked" in detail
    assert "Render dependency state" in detail


async def test_proposal_detail_markdown_excludes_frontmatter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(tmp_path)
    body = "# Proposal body\n\nUse `inline code` here.\n"
    proposal = replace(
        snapshot.proposals[0],
        content="---\ntitle: Hidden properties\ntier: epic\n---\n" + body,
        frontmatter={"title": "Hidden properties", "tier": "epic"},
        body=body,
    )
    snapshot = replace(snapshot, proposals=(proposal,))
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda _project, **_kwargs: snapshot,
    )

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("2")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        detail = pane.query_one("#plans-detail", Markdown)

        assert detail.source == body
        assert "---" not in detail.source
        assert "title: Hidden properties" not in detail.source
        assert pane._detail_debouncer is not None
        await page.wait_for(lambda _state: bool(list(detail.query("MarkdownBlock"))))
        markdown_block = list(detail.query("MarkdownBlock"))[0]
        inline_style = markdown_block.get_component_rich_style(
            "code_inline", partial=True
        )
        expected_background = Color.parse(
            page.app.get_css_variables()["foreground"]
        ).rich_color
        assert inline_style.bgcolor == expected_background
        resolved_style = markdown_block.get_component_rich_style("code_inline")
        assert resolved_style.color is not None
        assert resolved_style.bgcolor is not None
        foreground = resolved_style.color.triplet
        background = resolved_style.bgcolor.triplet
        assert foreground is not None
        assert background is not None
        assert (
            sum(abs(foreground[index] - background[index]) for index in range(3)) > 300
        )

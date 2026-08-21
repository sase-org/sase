"""Pure presentation coverage for the Statistics scope header."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from rich.text import Text

from sase.ace.tui.modals.statistics_pane import StatisticsPane
from sase.ace.tui.modals.statistics_pane_data import (
    STATISTICS_VIEW_BY_ID,
    STATISTICS_VIEW_SPECS,
    VIEW_COMPACT_LABELS,
    VIEW_DESCRIPTIONS,
    VIEW_LABELS,
    VIEW_MICRO_LABELS,
    VIEW_ORDER,
    StatisticsViewSpec,
    statistics_view_description_text,
    statistics_view_supports_grouping,
)
from sase.ace.tui.modals.statistics_pane_layout import _StatisticsDescription
from sase.project_display_names import ProjectDisplaySnapshot

_REVIEWED_COPY: dict[str, tuple[str, str, str, str, str]] = {
    "overview": (
        "Overview",
        "Overview",
        "Ovr",
        (
            "Scan run volume and outcomes, commits, plans, questions, "
            "and trends at a glance."
        ),
        "Scan run outcomes, work totals, and trends.",
    ),
    "runners": (
        "Runners",
        "Runners",
        "Rnrs",
        (
            "Track runner concurrency, occupancy, idle time, peaks, "
            "and today's global limit."
        ),
        "Track occupancy, peaks, idle time, and limits.",
    ),
    "projects": (
        "Projects",
        "Projects",
        "Proj",
        ("Compare run outcomes, commits, Patches, and wall time across projects."),
        "Compare outcomes, Patches, and wall time.",
    ),
    "providers": (
        "Providers",
        "Providers",
        "Prov",
        (
            "Compare provider, model, and effort usage, success rates, "
            "and average runtime."
        ),
        "Compare model usage, success, and runtime.",
    ),
    "activity": (
        "Activity",
        "Activity",
        "Act",
        "See which skills, memories, and workspaces agents use most.",
        "See top skills, memories, and workspaces.",
    ),
    "xprompts": (
        "XPrompts",
        "XPrompts",
        "XP",
        (
            "Explore XPrompt adoption, model and project breakdowns, "
            "pairings, and focused details."
        ),
        "Explore XPrompt usage, pairings, and focus.",
    ),
    "plans_questions": (
        "Plans & Questions",
        "Plans/Q",
        "P&Q",
        (
            "Review plan decisions, epic structure, and how agents ask "
            "for clarification."
        ),
        "Review plan outcomes, epic shape, and questions.",
    ),
    "perf": (
        "Perf",
        "Perf",
        "Prf",
        (
            "Assess TUI responsiveness, launch and agent latency, stalls, "
            "and data health."
        ),
        "Assess responsiveness, latency, stalls, and health.",
    ),
}


def test_statistics_view_catalog_is_the_authoritative_ordered_source() -> None:
    assert tuple(spec.id for spec in STATISTICS_VIEW_SPECS) == (
        "overview",
        "runners",
        "projects",
        "providers",
        "activity",
        "xprompts",
        "plans_questions",
        "perf",
    )
    assert len(STATISTICS_VIEW_SPECS) == 8
    assert VIEW_ORDER == tuple(spec.id for spec in STATISTICS_VIEW_SPECS)
    assert VIEW_LABELS == {spec.id: spec.label for spec in STATISTICS_VIEW_SPECS}
    assert VIEW_COMPACT_LABELS == {
        spec.id: spec.compact_label for spec in STATISTICS_VIEW_SPECS
    }
    assert VIEW_MICRO_LABELS == {
        spec.id: spec.micro_label for spec in STATISTICS_VIEW_SPECS
    }
    assert VIEW_DESCRIPTIONS == {
        spec.id: spec.description for spec in STATISTICS_VIEW_SPECS
    }
    assert set(VIEW_DESCRIPTIONS) == set(VIEW_ORDER)
    assert {view for view in VIEW_ORDER if statistics_view_supports_grouping(view)} == {
        "projects",
        "xprompts",
        "perf",
    }
    for spec in STATISTICS_VIEW_SPECS:
        label, compact_label, micro_label, full, compact = _REVIEWED_COPY[spec.id]
        assert spec.label == label
        assert spec.compact_label == compact_label
        assert spec.micro_label == micro_label
        assert spec.description == full
        assert spec.compact_description == compact
        assert STATISTICS_VIEW_BY_ID[spec.id] is spec


def test_statistics_view_description_text_uses_cell_width() -> None:
    spec = STATISTICS_VIEW_BY_ID["overview"]
    full = statistics_view_description_text(spec, width=10_000)
    compact = statistics_view_description_text(spec, width=1)
    assert full.plain == f"› {spec.description}"
    assert compact.plain == f"› {spec.compact_description}"
    assert str(full.style) == "#FF87D7"
    assert str(compact.style) == "#FF87D7"
    assert statistics_view_description_text(spec, width=full.cell_len).plain == (
        full.plain
    )
    assert statistics_view_description_text(spec, width=full.cell_len - 1).plain == (
        compact.plain
    )
    assert statistics_view_description_text(spec, width=0).plain == full.plain


def test_statistics_view_description_text_uses_terminal_cells_not_python_len() -> None:
    spec = StatisticsViewSpec(
        "overview",
        "Overview",
        "Overview",
        "Ovr",
        "abcdefgh寬",
        "short",
    )
    full = statistics_view_description_text(spec, width=10_000)
    python_len = len(full.plain)
    assert full.cell_len == python_len + 1
    assert statistics_view_description_text(spec, width=python_len).plain == (
        f"› {spec.compact_description}"
    )
    assert statistics_view_description_text(spec, width=full.cell_len).plain == (
        full.plain
    )


def test_description_rail_repaints_only_when_the_variant_changes() -> None:
    spec = STATISTICS_VIEW_BY_ID["overview"]
    rail = _StatisticsDescription(spec)
    updates: list[str] = []

    def capture(content: object) -> None:
        assert isinstance(content, Text)
        updates.append(content.plain)

    rail.update = capture  # type: ignore[method-assign]
    full = statistics_view_description_text(spec, width=10_000)
    compact = statistics_view_description_text(spec, width=1)

    rail.on_resize(SimpleNamespace(size=SimpleNamespace(width=full.cell_len)))
    rail.on_resize(SimpleNamespace(size=SimpleNamespace(width=full.cell_len + 12)))
    assert updates == []

    rail.on_resize(SimpleNamespace(size=SimpleNamespace(width=full.cell_len - 1)))
    assert updates == [compact.plain]

    rail.on_resize(SimpleNamespace(size=SimpleNamespace(width=1)))
    rail.on_resize(SimpleNamespace(size=SimpleNamespace(width=compact.cell_len)))
    assert updates == [compact.plain]

    rail.on_resize(SimpleNamespace(size=SimpleNamespace(width=full.cell_len)))
    assert updates == [compact.plain, full.plain]
    assert rail.can_focus is False


def test_scope_renderables_cover_range_group_project_and_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pane = StatisticsPane(auto_load=False)
    absolute_span = pane._range.label

    assert pane._range_scope_text().plain == (
        f" t/T  Range {pane._range.display_label} · {absolute_span}"
    )
    pane._compact_scope = True
    assert pane._range_scope_text().plain == f" t/T  Range {pane._range.display_label}"

    pane._preset_key = None
    assert pane._range_scope_text().plain == (
        f" t/T  Range Custom · {pane._range.display_label}"
    )

    assert pane._group_scope_text().plain == " g  Group —"
    pane._view = "projects"
    assert pane._group_scope_text().plain == " g  Group Projects · By Project"
    pane._view = "xprompts"
    assert pane._group_scope_text().plain == " g  Group XPrompts · By Usage"
    pane._view = "perf"
    assert pane._group_scope_text().plain == " g  Group Perf · By Subsystem"
    pane._view = "xprompts"
    assert pane._xprompt_scope_text().plain == " x/X  XPrompt All xprompts"
    pane._xprompt_focus = "split_file"
    assert pane._xprompt_scope_text().plain == " x/X  XPrompt ■ #split_file"

    assert pane._project_scope_text().plain == " p/P  Project All projects"
    pane._view = "perf"
    assert pane._project_scope_text().plain == (
        " p/P  Project All projects · not applied"
    )
    pane._view = "overview"
    project_key = "gh_acme__widgets"
    pane._project_filter = project_key
    pane._last_result = SimpleNamespace(  # type: ignore[assignment]
        project_display_snapshot=ProjectDisplaySnapshot({project_key: "widgets"})
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.statistics_pane_rendering.categorical_color",
        lambda _key: "#123456",
    )
    project_scope = pane._project_scope_text()
    swatch_offset = project_scope.plain.index("■")
    assert project_scope.plain == " p/P  Project ■ widgets"
    assert any(
        span.start <= swatch_offset < span.end and str(span.style) == "#123456"
        for span in project_scope.spans
    )

    pane._view = "perf"
    perf_project = pane._project_scope_text()
    assert perf_project.plain == " p/P  Project widgets · not applied"
    assert "■" not in perf_project.plain
    pane._view = "overview"

    pane._loading = True
    assert pane._status_text().plain == "refreshing…"
    pane._loading = False
    pane._last_error = "boom"
    assert pane._status_text().plain == "load failed"


def test_scope_resize_only_repaints_when_compact_mode_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pane = StatisticsPane(auto_load=False)
    repaints: list[bool] = []
    monkeypatch.setattr(pane, "_update_scope", lambda: repaints.append(True))

    pane.on_resize(SimpleNamespace(size=SimpleNamespace(width=120)))  # type: ignore[arg-type]
    pane.on_resize(SimpleNamespace(size=SimpleNamespace(width=99)))  # type: ignore[arg-type]
    pane.on_resize(SimpleNamespace(size=SimpleNamespace(width=80)))  # type: ignore[arg-type]
    pane.on_resize(SimpleNamespace(size=SimpleNamespace(width=100)))  # type: ignore[arg-type]

    assert repaints == [True, True]


def test_runner_resize_only_repaints_when_composition_threshold_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pane = StatisticsPane(auto_load=False)
    pane._view = "runners"
    pane._last_result = object()  # type: ignore[assignment]
    repaints: list[bool] = []
    monkeypatch.setattr(pane, "_paint_current_view", lambda: repaints.append(True))

    pane.on_resize(SimpleNamespace(size=SimpleNamespace(width=120)))  # type: ignore[arg-type]
    pane.on_resize(SimpleNamespace(size=SimpleNamespace(width=107)))  # type: ignore[arg-type]
    pane.on_resize(SimpleNamespace(size=SimpleNamespace(width=90)))  # type: ignore[arg-type]
    pane.on_resize(SimpleNamespace(size=SimpleNamespace(width=108)))  # type: ignore[arg-type]

    assert repaints == [True, True]


def test_perf_resize_only_repaints_when_composition_threshold_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pane = StatisticsPane(auto_load=False)
    pane._view = "perf"
    pane._last_result = object()  # type: ignore[assignment]
    repaints: list[bool] = []
    monkeypatch.setattr(pane, "_paint_current_view", lambda: repaints.append(True))

    pane.on_resize(SimpleNamespace(size=SimpleNamespace(width=120)))  # type: ignore[arg-type]
    pane.on_resize(SimpleNamespace(size=SimpleNamespace(width=107)))  # type: ignore[arg-type]
    pane.on_resize(SimpleNamespace(size=SimpleNamespace(width=90)))  # type: ignore[arg-type]
    pane.on_resize(SimpleNamespace(size=SimpleNamespace(width=108)))  # type: ignore[arg-type]

    assert repaints == [True, True]


def test_description_width_changes_do_not_repaint_statistics_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pane = StatisticsPane(auto_load=False)
    pane._view = "runners"
    pane._last_result = object()  # type: ignore[assignment]
    pane._runners_stacked = True
    pane._compact_scope = True
    repaints: list[bool] = []
    monkeypatch.setattr(pane, "_paint_current_view", lambda: repaints.append(True))

    pane.on_resize(SimpleNamespace(size=SimpleNamespace(width=90)))  # type: ignore[arg-type]
    pane.on_resize(SimpleNamespace(size=SimpleNamespace(width=70)))  # type: ignore[arg-type]

    assert repaints == []

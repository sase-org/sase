"""Pure presentation coverage for the Statistics scope header."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sase.ace.tui.modals.statistics_pane import StatisticsPane
from sase.ace.tui.modals.statistics_pane_data import VIEW_DESCRIPTIONS, VIEW_ORDER
from sase.project_display_names import ProjectDisplaySnapshot


def test_every_ordered_statistics_view_has_a_description() -> None:
    assert set(VIEW_DESCRIPTIONS) == set(VIEW_ORDER)
    assert all(VIEW_DESCRIPTIONS[view].strip() for view in VIEW_ORDER)


def test_scope_renderables_cover_range_group_project_and_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pane = StatisticsPane(auto_load=False)
    absolute_span = pane._range.label

    assert pane._range_scope_text().plain == (
        f" t  Range {pane._range.display_label} · {absolute_span}"
    )
    pane._compact_scope = True
    assert pane._range_scope_text().plain == f" t  Range {pane._range.display_label}"

    pane._preset_key = None
    assert pane._range_scope_text().plain == (
        f" t  Range Custom · {pane._range.display_label}"
    )

    assert pane._group_scope_text().plain == " g  Group —"
    pane._view = "runtime"
    assert pane._group_scope_text().plain == " g  Group Runtime · Tribe"
    pane._view = "projects"
    assert pane._group_scope_text().plain == " g  Group Projects · By Project"

    assert pane._project_scope_text().plain == " p  Project All projects"
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
    assert project_scope.plain == " p  Project ■ widgets"
    assert any(
        span.start <= swatch_offset < span.end and str(span.style) == "#123456"
        for span in project_scope.spans
    )

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

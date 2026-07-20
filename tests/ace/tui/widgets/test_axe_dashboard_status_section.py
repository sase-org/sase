"""Phase 4: AXE status-section rendering for chop runs."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from rich.text import Text

from sase.ace.tui.bgcmd import BackgroundCommandInfo
from sase.ace.tui.actions.axe_display._data import (
    AxeStatusDegradation,
    ChopRunSnapshot,
)
from sase.ace.tui.widgets import axe_dashboard
from sase.ace.tui.widgets.axe_dashboard import AxeDashboard
from sase.axe.state import LumberjackStatus

from ._axe_dashboard_helpers import _entry, _snapshot_with_runs


def test_render_chop_display_running_run_shows_elapsed_and_pid() -> None:
    """Running runs show Elapsed/PID/source instead of Took/Exit."""
    running = ChopRunSnapshot(
        entry=_entry(
            "live",
            status="running",
            finished_at=None,
            duration_ms=0,
            exit_code=None,
            pid=12345,
            source="manual",
        ),
        output_tail="",
    )
    snap = _snapshot_with_runs(running)

    captured: dict[str, object] = {}

    class _OutputSection:
        def update_display(self, *args: object, **kwargs: object) -> None:
            captured["display"] = (args, kwargs)

        def update(self, content: object) -> None:
            captured["update"] = content

    # Reuse the real status section so we can inspect its rendered Text.
    section = axe_dashboard._AxeStatusSection.__new__(axe_dashboard._AxeStatusSection)
    section.__init__()  # type: ignore[misc]

    rendered: dict[str, object] = {}

    def _capture_update(content: object) -> None:
        rendered["content"] = content

    section.update = _capture_update  # type: ignore[assignment]

    dashboard = AxeDashboard.__new__(AxeDashboard)

    def _query_one(selector: str, _cls: type) -> object:
        if "status" in selector:
            return section
        return _OutputSection()

    dashboard.query_one = _query_one  # type: ignore[assignment]
    dashboard.update_chop_run_display(snapshot=snap, run_idx=0, countdown=0)

    text = rendered["content"]
    assert isinstance(text, Text)
    plain = text.plain
    assert "running" in plain.lower()
    assert "Elapsed:" in plain
    assert "Took:" not in plain
    assert "PID:" in plain
    assert "12345" in plain
    # Manual source surfaces a marker so the user can tell why it ran.
    assert "manual" in plain
    # Exit code is suppressed for active runs.
    assert "Exit:" not in plain


def test_render_chop_display_scheduled_run_hides_source_marker() -> None:
    """The default scheduled source stays compact (no Source: chip)."""
    running = ChopRunSnapshot(
        entry=_entry(
            "live",
            status="running",
            finished_at=None,
            duration_ms=0,
            exit_code=None,
            pid=4242,
            source="scheduled",
        ),
        output_tail="",
    )
    snap = _snapshot_with_runs(running)

    rendered: dict[str, object] = {}
    section = axe_dashboard._AxeStatusSection.__new__(axe_dashboard._AxeStatusSection)
    section.__init__()  # type: ignore[misc]
    section.update = lambda content: rendered.__setitem__("content", content)  # type: ignore[assignment]

    class _OutputSection:
        def update_display(self, *_a: object, **_kw: object) -> None:
            pass

        def update(self, *_a: object, **_kw: object) -> None:
            pass

    dashboard = AxeDashboard.__new__(AxeDashboard)
    dashboard.query_one = lambda sel, _cls: (  # type: ignore[assignment]
        section if "status" in sel else _OutputSection()
    )
    dashboard.update_chop_run_display(snapshot=snap, run_idx=0, countdown=0)

    plain = rendered["content"].plain  # type: ignore[union-attr]
    assert "Source:" not in plain


def test_render_chop_display_when_shows_local_time_with_relative_age() -> None:
    """The selected-run header shows wall-clock time and existing relative age."""
    from sase.core.time import get_timezone

    local_tz = get_timezone()
    started_at = datetime(2026, 5, 11, 18, 5, 9, tzinfo=UTC)
    now = datetime(2026, 5, 11, 15, 10, 9, tzinfo=local_tz)
    run = ChopRunSnapshot(
        entry=_entry("a", started_at=started_at.isoformat()),
        output_tail="",
    )

    rendered: dict[str, object] = {}
    section = axe_dashboard._AxeStatusSection.__new__(axe_dashboard._AxeStatusSection)
    section.__init__()  # type: ignore[misc]
    section.update = lambda content: rendered.__setitem__("content", content)  # type: ignore[assignment]

    with patch("sase.ace.tui.widgets._axe_dashboard_render.datetime") as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.fromisoformat = datetime.fromisoformat
        section.update_chop_display(
            lumberjack_name="hooks",
            chop_name="fast",
            run=run,
            run_idx=0,
            run_total=1,
        )

    plain = rendered["content"].plain  # type: ignore[union-attr]
    assert "When: 14:05:09 (1h ago)" in plain


def test_render_chop_display_when_invalid_timestamp_stays_unknown() -> None:
    """Invalid timestamp input preserves the existing unknown fallback."""
    run = ChopRunSnapshot(
        entry=_entry("a", started_at="not-a-date"),
        output_tail="",
    )

    rendered: dict[str, object] = {}
    section = axe_dashboard._AxeStatusSection.__new__(axe_dashboard._AxeStatusSection)
    section.__init__()  # type: ignore[misc]
    section.update = lambda content: rendered.__setitem__("content", content)  # type: ignore[assignment]

    section.update_chop_display(
        lumberjack_name="hooks",
        chop_name="fast",
        run=run,
        run_idx=0,
        run_total=1,
    )

    plain = rendered["content"].plain  # type: ignore[union-attr]
    assert "When: unknown" in plain


def test_status_section_renders_no_wrap_text() -> None:
    """All status renderers construct ``Text`` with ``no_wrap`` so the 1-cell
    status bar truncates cleanly rather than wrapping into the output panel."""
    section = axe_dashboard._AxeStatusSection.__new__(axe_dashboard._AxeStatusSection)
    section.__init__()  # type: ignore[misc]

    captured: list[Text] = []
    section.update = lambda content: captured.append(content)  # type: ignore[assignment,arg-type]

    section.update_lumberjack_display(
        status=LumberjackStatus(
            name="hooks",
            pid=1,
            started_at="2026-05-11T00:00:00",
            status="running",
            interval=60,
            cycles_run=2,
            errors_encountered=0,
        ),
        name="hooks",
        idx=0,
        total=1,
    )
    section.update_chop_display(
        lumberjack_name="hooks",
        chop_name="fast",
        run=None,
        run_idx=0,
        run_total=0,
    )
    section.update_display(status=None, is_running=True, full_cycles=0)
    section.update_bgcmd_display(info=None, is_running=False)

    assert captured, "status section never emitted a Text"
    for text in captured:
        assert text.no_wrap is True
        assert text.overflow == "ellipsis"


def test_status_section_renders_degraded_axe_status() -> None:
    """A collector degradation replaces misleading runtime counters."""
    section = axe_dashboard._AxeStatusSection.__new__(axe_dashboard._AxeStatusSection)
    section.__init__()  # type: ignore[misc]
    captured: list[Text] = []
    section.update = lambda content: captured.append(content)  # type: ignore[assignment,arg-type]

    section.update_display(
        status=None,
        is_running=True,
        full_cycles=0,
        countdown=17,
        degraded_status=AxeStatusDegradation(
            "axe config invalid: [unknown_key] axe.extra: unsupported setting"
        ),
    )

    assert captured
    assert "axe config invalid: [unknown_key] axe.extra: unsupported setting" in (
        captured[-1].plain
    )
    assert "Runtime:" not in captured[-1].plain
    assert "auto-refresh in 17s" in captured[-1].plain


def test_bgcmd_status_section_uses_display_project() -> None:
    """Background-command status shows PROJECT_NAME when available."""
    section = axe_dashboard._AxeStatusSection.__new__(axe_dashboard._AxeStatusSection)
    section.__init__()  # type: ignore[misc]
    captured: list[Text] = []
    section.update = lambda content: captured.append(content)  # type: ignore[assignment,arg-type]
    info = BackgroundCommandInfo(
        command="make test",
        project="gh_acme__widgets",
        workspace_num=1,
        workspace_dir="/path",
        started_at="2025-01-01T12:00:00",
        project_display_name="widgets",
    )

    section.update_bgcmd_display(info=info, is_running=True)

    assert captured
    plain = captured[-1].plain
    assert "Project: widgets" in plain
    assert "gh_acme__widgets" not in plain


def test_chop_status_header_colors_names_with_sidebar_taxonomy() -> None:
    """The chop status header colors the lumberjack and chop names with the
    sidebar gold/copper hues so the header echoes the sidebar tree."""
    run = ChopRunSnapshot(
        entry=_entry("a", status="success"),
        output_tail="",
    )
    snap = _snapshot_with_runs(run)

    rendered: dict[str, object] = {}
    section = axe_dashboard._AxeStatusSection.__new__(axe_dashboard._AxeStatusSection)
    section.__init__()  # type: ignore[misc]
    section.update = lambda content: rendered.__setitem__("content", content)  # type: ignore[assignment]

    class _OutputSection:
        def update_display(self, *_a: object, **_kw: object) -> None:
            pass

        def update(self, *_a: object, **_kw: object) -> None:
            pass

    dashboard = AxeDashboard.__new__(AxeDashboard)
    dashboard.query_one = lambda sel, _cls: (  # type: ignore[assignment]
        section if "status" in sel else _OutputSection()
    )
    dashboard.update_chop_run_display(snapshot=snap, run_idx=0, countdown=0)

    text = rendered["content"]
    assert isinstance(text, Text)
    spans = {(s.style, text.plain[s.start : s.end]) for s in text.spans}
    # Lumberjack name colored in the sidebar's gold accent.
    assert any(
        "FFD700" in str(style) and "hooks" in fragment for style, fragment in spans
    )
    # Chop name colored in the sidebar's copper child hue.
    assert any(
        "D7AF87" in str(style) and "fast" in fragment for style, fragment in spans
    )

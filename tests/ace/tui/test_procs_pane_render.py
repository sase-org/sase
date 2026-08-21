"""Tests for the pure Procs pane rendering helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from sase.ace.tui.modals import procs_pane_render
from sase.ace.tui.modals.procs_pane_render import (
    BodyCache,
    MonitorStatusChip,
    output_body,
    output_header,
    task_row_label,
)
from sase.ace.tui.proc_observer import DETAIL_LOG_LINES, ObservedProc
from sase.monitor_state import MONITOR_GLYPH, MONITOR_GLYPH_COLOR, MONITOR_PROC_ORIGIN

_STARTED = datetime(2026, 6, 26, 12, 0, 0)
_GEAR_STYLE = f"bold {MONITOR_GLYPH_COLOR}"


def _row(**overrides: Any) -> ObservedProc:
    fields: dict[str, Any] = {
        "proc_id": "p1",
        "proc_type": "command",
        "cl_name": "",
        "project_file": "",
        "status": "running",
        "message": "",
        "started_at": _STARTED,
    }
    fields.update(overrides)
    return ObservedProc(**fields)


def test_task_row_label_marks_monitor_rows_with_the_canonical_gear() -> None:
    monitor = _row(origin=MONITOR_PROC_ORIGIN, display_name="just check-full")
    plain = _row(display_name="sync sase-42")

    monitor_label = task_row_label(monitor)
    plain_label = task_row_label(plain)

    assert f"{MONITOR_GLYPH} just check-full" in monitor_label.plain
    assert any(span.style == _GEAR_STYLE for span in monitor_label.spans)
    assert MONITOR_GLYPH not in plain_label.plain


def test_output_header_prefixes_the_label_with_the_monitor_gear() -> None:
    monitor = _row(origin=MONITOR_PROC_ORIGIN, display_name="just check-full")
    plain = _row(display_name="sync sase-42")

    monitor_header = output_header(monitor, spinner_index=0)
    plain_header = output_header(plain, spinner_index=0)

    assert monitor_header.plain.startswith(f"{MONITOR_GLYPH} just check-full")
    assert any(span.style == _GEAR_STYLE for span in monitor_header.spans)
    assert MONITOR_GLYPH not in plain_header.plain


def test_task_row_label_shows_agent_name_from_the_rebuild_index() -> None:
    monitor = _row(
        origin=MONITOR_PROC_ORIGIN, display_name="just check-full", phase=None
    )
    label = task_row_label(monitor, agent_names={"p1": "acme--mon"})

    assert "\n   acme--mon · Working..." in label.plain
    assert any(
        span.style == MONITOR_GLYPH_COLOR
        and label.plain[span.start : span.end] == "acme--mon"
        for span in label.spans
    )


def test_task_row_label_carries_just_the_name_when_no_secondary_text() -> None:
    monitor = _row(
        origin=MONITOR_PROC_ORIGIN,
        display_name="just check-full",
        status="success",
        message="",
    )
    label = task_row_label(monitor, agent_names={"p1": "acme--mon"})

    assert label.plain.endswith("\n   acme--mon")


def test_task_row_label_omits_name_when_row_is_absent_from_the_index() -> None:
    monitor = _row(origin=MONITOR_PROC_ORIGIN, display_name="just check-full")
    label = task_row_label(monitor, agent_names={})

    assert "acme" not in label.plain


def test_task_row_label_shows_the_status_chip_between_name_and_secondary() -> None:
    monitor = _row(
        origin=MONITOR_PROC_ORIGIN, display_name="just check-full", phase=None
    )
    chip = MonitorStatusChip(label="TESTING", style="bold #6FC4FF", glyph="")
    label = task_row_label(
        monitor,
        agent_names={"p1": "acme--mon"},
        status_chips={"p1": chip},
    )

    assert "\n   acme--mon · TESTING · Working..." in label.plain
    assert any(
        span.style == "bold #6FC4FF" and label.plain[span.start : span.end] == "TESTING"
        for span in label.spans
    )


def test_task_row_label_appends_the_outcome_glyph_to_the_status_chip() -> None:
    monitor = _row(
        origin=MONITOR_PROC_ORIGIN,
        display_name="just check-full",
        status="success",
        message="",
    )
    chip = MonitorStatusChip(label="TESTED", style="#6FC4FF", glyph="✓")
    label = task_row_label(monitor, status_chips={"p1": chip})

    assert label.plain.endswith("\n   TESTED ✓")


def test_task_row_label_omits_the_chip_for_a_non_monitor_row() -> None:
    plain = _row(display_name="sync sase-42")
    chip = MonitorStatusChip(label="TESTING", style="bold #6FC4FF", glyph="")
    label = task_row_label(plain, status_chips={"p1": chip})

    assert "TESTING" not in label.plain


def test_task_row_label_omits_the_chip_when_row_is_absent_from_the_index() -> None:
    monitor = _row(origin=MONITOR_PROC_ORIGIN, display_name="just check-full")
    label = task_row_label(monitor, status_chips={})

    assert "TESTING" not in label.plain


def test_output_header_gains_an_agent_line_under_the_command_line() -> None:
    monitor = _row(
        origin=MONITOR_PROC_ORIGIN,
        display_name="just check-full",
        command=["just", "check-full"],
    )
    header = output_header(monitor, spinner_index=0, agent_names={"p1": "acme--mon"})

    lines = header.plain.splitlines()
    command_idx = next(i for i, line in enumerate(lines) if line.startswith("$ "))
    assert lines[command_idx + 1] == "agent  acme--mon"


def test_output_header_adds_the_status_chip_after_the_agent_name() -> None:
    monitor = _row(
        origin=MONITOR_PROC_ORIGIN,
        display_name="just check-full",
        command=["just", "check-full"],
    )
    chip = MonitorStatusChip(label="TESTING", style="bold #6FC4FF", glyph="")
    header = output_header(
        monitor,
        spinner_index=0,
        agent_names={"p1": "acme--mon"},
        status_chips={"p1": chip},
    )

    lines = header.plain.splitlines()
    command_idx = next(i for i, line in enumerate(lines) if line.startswith("$ "))
    assert lines[command_idx + 1] == "agent  acme--mon  TESTING"


def test_output_header_shows_the_chip_alone_without_an_agent_name() -> None:
    monitor = _row(origin=MONITOR_PROC_ORIGIN, display_name="just check-full")
    chip = MonitorStatusChip(label="TESTING", style="bold #6FC4FF", glyph="")
    header = output_header(monitor, spinner_index=0, status_chips={"p1": chip})

    lines = header.plain.splitlines()
    agent_idx = next(i for i, line in enumerate(lines) if line.startswith("agent"))
    assert lines[agent_idx] == "agent  TESTING"


def test_output_header_skips_command_already_logged_by_the_reporter() -> None:
    row = _row(display_name="sase update", command=["uv", "tool", "upgrade", "sase"])
    row.log.append("$ uv tool upgrade sase", stream="header")
    row.log.append("Resolving packages", stream="stdout")

    header = output_header(row, spinner_index=0)

    assert header.plain.count("$ uv tool upgrade sase") == 0
    body = output_body(row, {})
    assert "$ uv tool upgrade sase" in body.plain


def test_output_header_omits_agent_line_for_a_plain_row() -> None:
    plain = _row(display_name="sync sase-42", command=["sase", "bead", "work"])
    header = output_header(plain, spinner_index=0, agent_names={"p1": "acme--mon"})

    assert "agent" not in header.plain


def test_detached_marker_and_session_chip_are_unchanged_by_monitor_support() -> None:
    from sase.procs import DETACHED_PROC_KIND

    detached = _row(proc_type=DETACHED_PROC_KIND, display_name="global sync")
    label = task_row_label(detached)
    header = output_header(detached, spinner_index=0)

    assert "◆ detached" in label.plain
    assert "◆ detached" in header.plain
    assert MONITOR_GLYPH not in label.plain
    assert MONITOR_GLYPH not in header.plain


def test_output_body_routes_a_store_backed_tail_through_the_shared_ansi_renderer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    original = procs_pane_render.render_axe_output

    def spy(source_id: str, output: str, source_type: Any) -> Any:
        calls.append((source_id, source_type))
        return original(source_id, output, source_type)

    monkeypatch.setattr(procs_pane_render, "render_axe_output", spy)

    row = _row(store_backed=True, output="hello\n")
    body = output_body(row, {})

    assert calls == [("proc:p1", "ansi")]
    assert body.plain.rstrip("\n") == "hello"


def test_output_body_notes_the_tail_cap_only_when_the_read_came_back_capped() -> None:
    capped_text = "".join(f"line {i}\n" for i in range(DETAIL_LOG_LINES))
    under_text = "".join(f"line {i}\n" for i in range(DETAIL_LOG_LINES - 1))

    capped_row = _row(proc_id="capped", store_backed=True, output=capped_text)
    under_row = _row(proc_id="under", store_backed=True, output=under_text)

    capped_body = output_body(capped_row, {})
    under_body = output_body(under_row, {})

    notice = f"… showing the last {DETAIL_LOG_LINES} lines …"
    assert capped_body.plain.startswith(notice)
    assert notice not in under_body.plain


def test_output_body_never_notes_the_cap_for_non_store_backed_rows() -> None:
    capped_text = "".join(f"line {i}\n" for i in range(DETAIL_LOG_LINES))
    row = _row(store_backed=False, output=capped_text)

    body = output_body(row, {})

    assert "showing the last" not in body.plain


def test_output_body_cache_reuses_the_rendered_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    original = procs_pane_render.render_axe_output

    def spy(source_id: str, output: str, source_type: Any) -> Any:
        calls.append((source_id, source_type))
        return original(source_id, output, source_type)

    monkeypatch.setattr(procs_pane_render, "render_axe_output", spy)

    row = _row(store_backed=True, output="hello\n")
    cache: BodyCache = {}
    output_body(row, cache)
    output_body(row, cache)

    assert len(calls) == 1

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from rich.text import Text

from sase.ace.tui.models.fold_scale import AGENT_FOLD_SCALE
from sase.ace.tui.widgets.prompt_panel import _agent_context_common
from sase.ace.tui.widgets.prompt_panel._agent_display_state import HeaderHintState
from sase.ace.tui.widgets.prompt_panel._agent_slow_tools import (
    append_slow_tool_calls_section,
)
from tests.ace.tui.widgets._agent_slow_tools_helpers import (
    make_entry as _entry,
    make_source as _source,
)


@pytest.fixture(autouse=True)
def _pin_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _agent_context_common,
        "get_timezone",
        lambda: ZoneInfo("UTC"),
    )


def test_completed_slow_tools_get_hint_markers_and_report_specs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    text = Text()
    state = HeaderHintState(
        hint_counter=12,
        hint_mappings={},
        workspace_dir=None,
        tool_call_reports={},
    )
    failed = _entry(
        status="failure",
        tool_use_id="failed",
        duration_ms=45_000,
        tool_input_summary={"command": "just fail"},
        source_path="/artifacts/tool_calls.jsonl",
        line_number=33,
    )
    success = _entry(
        status="success",
        tool_use_id="success",
        duration_ms=50_000,
        recorded_at="2026-07-03T14:00:01+00:00",
        tool_input_summary={"command": "just ok"},
    )

    append_slow_tool_calls_section(
        text,
        sources=(_source(failed, success, label="code"),),
        agent=SimpleNamespace(agent_name="root"),
        now=datetime(2026, 7, 3, 14, 2, tzinfo=UTC),
        hint_state=state,
    )

    plain = text.plain
    lines = [line for line in plain.splitlines() if "just " in line]
    assert "✘ [12] code" in plain
    assert "✔ [13] code" in plain
    assert lines[0].index("Bash") == lines[1].index("Bash")
    assert state.hint_counter == 14
    failed_report_path = state.hint_mappings[12]
    success_report_path = state.hint_mappings[13]
    assert failed_report_path.startswith(str(tmp_path / ".sase" / "tool_call_reports"))
    assert success_report_path.startswith(str(tmp_path / ".sase" / "tool_call_reports"))
    failed_spec = state.tool_call_reports[failed_report_path]
    success_spec = state.tool_call_reports[success_report_path]
    assert failed_spec.entry is failed
    assert success_spec.entry is success
    assert failed_spec.source_label == "code"
    assert success_spec.source_label == "code"
    assert failed_spec.agent_name == "root"
    assert success_spec.agent_name == "root"


def test_slow_tool_hints_ignore_non_reportable_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    text = Text()
    state = HeaderHintState(
        hint_counter=1,
        hint_mappings={},
        workspace_dir=None,
        tool_call_reports={},
    )

    append_slow_tool_calls_section(
        text,
        sources=(
            _source(
                _entry(
                    status="success",
                    tool_use_id="success",
                    duration_ms=45_000,
                    tool_input_summary={"command": "just ok"},
                ),
                _entry(
                    status="pending",
                    tool_use_id="pending",
                    duration_ms=None,
                    recorded_at="2026-07-03T14:00:01+00:00",
                    tool_input_summary={"command": "still running"},
                ),
                _entry(
                    status="incomplete",
                    tool_use_id="incomplete",
                    duration_ms=50_000,
                    recorded_at="2026-07-03T14:00:02+00:00",
                    tool_input_summary={"command": "partial"},
                ),
                active=True,
            ),
        ),
        agent=SimpleNamespace(status="RUNNING", stop_time=None),
        now=datetime(2026, 7, 3, 14, 2, tzinfo=UTC),
        hint_state=state,
    )

    plain = text.plain
    lines = [line for line in plain.splitlines() if "Bash" in line]
    assert "✔ [1] Bash" in plain
    assert "⏳     Bash" in plain
    assert "◼     Bash" in plain
    assert lines[0].index("Bash") == lines[1].index("Bash")
    assert lines[0].index("Bash") == lines[2].index("Bash")
    assert state.hint_counter == 2
    assert set(state.hint_mappings) == {1}
    spec = state.tool_call_reports[state.hint_mappings[1]]
    assert spec.entry.tool_use_id == "success"


def test_hint_markers_and_report_specs_are_identical_across_detail_tiers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    entries = (
        _entry(tool_use_id="first", source_path="/tmp/tools.jsonl", line_number=1),
        _entry(
            tool_use_id="second",
            recorded_at="2026-07-03T14:00:01+00:00",
            source_path="/tmp/tools.jsonl",
            line_number=2,
        ),
    )
    snapshots: list[tuple[str, tuple[int, ...], tuple[str, ...]]] = []
    for level in AGENT_FOLD_SCALE:
        state = HeaderHintState(7, {}, None, {})
        text = Text()
        append_slow_tool_calls_section(
            text,
            sources=(_source(*entries),),
            agent=SimpleNamespace(agent_name="root"),
            now=datetime(2026, 7, 3, 14, 2, tzinfo=UTC),
            hint_state=state,
            panel_level=level,
        )
        marker_lines = "\n".join(
            line for line in text.plain.splitlines() if "Bash" in line
        )
        snapshots.append(
            (
                marker_lines,
                tuple(state.hint_mappings),
                tuple(
                    spec.entry.tool_use_id or ""
                    for spec in state.tool_call_reports.values()
                ),
            )
        )

    assert snapshots == [snapshots[0]] * len(snapshots)

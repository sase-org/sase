"""Effective status-label rendering for the ``sase monitor`` surfaces."""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console

from sase.main.monitor_render import (
    MONITOR_JSON_SCHEMA_VERSION,
    _status_label_text,
    _status_pair_text,
    monitor_detail,
    monitor_list_json,
    monitor_list_markdown,
    status_text,
)
from sase.monitor.models import MonitorRecord
from sase.monitor_status import MONITOR_STATUS_FAILURE_STYLE

_TESTING_ACCENT = "#6FC4FF"


def _record(**overrides: object) -> MonitorRecord:
    values: dict[str, object] = {
        "monitor_id": "aaabbbcccddd",
        "member_agent_name": "acme--mon",
        "lane": "acme",
        "project_name": "proj",
        "artifacts_dir": "/tmp/mon",
        "timestamp": "20260812120000",
        "command": "just check-full",
        "cwd": "/tmp/work",
        "reason": "verify",
        "label": "just",
        "start_status": "TESTING",
        "stop_status": "TESTED",
        "timeout_seconds": 60.0,
        "tail_lines": 200,
        "monitor_state": "running",
    }
    values.update(overrides)
    return MonitorRecord(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("monitor_state", "settled", "plain", "style"),
    [
        ("running", False, "● TESTING", f"bold {_TESTING_ACCENT}"),
        ("completed", True, "✓ TESTED", _TESTING_ACCENT),
        ("stopped", True, "⊘ TESTED", _TESTING_ACCENT),
        ("failed", True, "✗ TESTED", MONITOR_STATUS_FAILURE_STYLE),
        ("timeout", True, "⧖ TESTED", MONITOR_STATUS_FAILURE_STYLE),
        ("lost", True, "⚠ TESTED", MONITOR_STATUS_FAILURE_STYLE),
    ],
)
def test_state_cell_uses_effective_label_and_pair_style(
    monitor_state: str, settled: bool, plain: str, style: str
) -> None:
    text = _status_label_text(_record(monitor_state=monitor_state, settled=settled))
    assert text.plain == plain
    assert str(text.style) == style


def test_detail_pair_row_shows_the_inactive_half_dim() -> None:
    running = _status_pair_text(_record(monitor_state="running"))
    assert running.plain == "TESTING → TESTED"
    assert str(running.spans[0].style) == f"bold {_TESTING_ACCENT}"
    assert str(running.spans[-1].style) == "dim"

    done = _status_pair_text(_record(monitor_state="completed", settled=True))
    assert done.plain == "TESTING → TESTED"
    assert str(done.spans[0].style) == "dim"
    assert str(done.spans[-1].style) == _TESTING_ACCENT


def test_detail_panel_puts_status_label_above_raw_state() -> None:
    record = _record(monitor_state="running")
    buf = StringIO()
    Console(file=buf, force_terminal=False, color_system=None, width=80).print(
        monitor_detail(record)
    )
    out = buf.getvalue()
    label_at = out.index("Status label")
    status_at = out.index("Status", label_at + len("Status label"))
    assert label_at < status_at
    assert "TESTING" in out
    assert "TESTED" in out
    assert "running" in out
    raw = status_text("running")
    assert raw.plain == "● running"


def test_markdown_substitutes_the_effective_label() -> None:
    running = monitor_list_markdown([_record(monitor_state="running")])
    assert "| TESTING |" in running
    assert "| running |" not in running

    done = monitor_list_markdown([_record(monitor_state="completed", settled=True)])
    assert "| TESTED |" in done

    flagged = monitor_list_markdown(
        [
            _record(
                monitor_state="completed",
                settled=True,
                followup_error="workspace missing",
                followup_outcome="not-launchable",
            )
        ]
    )
    assert "⚑" in flagged


def test_json_envelope_includes_status_label_accent_and_schema_v2() -> None:
    assert MONITOR_JSON_SCHEMA_VERSION == 2
    payload = monitor_list_json([_record(monitor_state="running")], scope={})
    assert payload["schema_version"] == 2
    monitor = payload["monitors"][0]
    assert monitor["start_status"] == "TESTING"
    assert monitor["stop_status"] == "TESTED"
    assert monitor["status_label"] == "TESTING"
    assert monitor["status_accent"] == _TESTING_ACCENT
    assert monitor["monitor_state"] == "running"
    assert monitor["next_model"] is None

    done = monitor_list_json([_record(monitor_state="failed", settled=True)], scope={})[
        "monitors"
    ][0]
    assert done["status_label"] == "TESTED"
    assert done["status_accent"] == _TESTING_ACCENT
    assert done["monitor_state"] == "failed"

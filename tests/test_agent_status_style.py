"""CLI status-badge styling for custom monitor status pairs."""

from __future__ import annotations

import pytest

from sase.agents.status_style import agent_status_text
from sase.monitor_status import (
    MONITOR_STATUS_FAILURE_STYLE,
    monitor_status_accent,
    monitor_status_pair,
)

_TESTING = monitor_status_pair("TESTING", "TESTED")
_TESTING_ACCENT = monitor_status_accent(_TESTING)


@pytest.mark.parametrize(
    ("status", "monitor_state", "plain", "style"),
    [
        ("TESTING", "running", "TESTING", f"bold {_TESTING_ACCENT}"),
        ("TESTED", "completed", "TESTED ✓", _TESTING_ACCENT),
        ("TESTED", "stopped", "TESTED ⊘", _TESTING_ACCENT),
        ("TESTED", "failed", "TESTED ✗", MONITOR_STATUS_FAILURE_STYLE),
        ("TESTED", "timeout", "TESTED ⧖", MONITOR_STATUS_FAILURE_STYLE),
        ("TESTED", "lost", "TESTED ⚠", MONITOR_STATUS_FAILURE_STYLE),
    ],
)
def test_agent_status_text_styles_a_matching_monitor_pair(
    status: str, monitor_state: str, plain: str, style: str
) -> None:
    text = agent_status_text(status, monitor=_TESTING, monitor_state=monitor_state)
    assert text.plain == plain
    assert str(text.style) == style


def test_agent_status_text_falls_through_when_status_is_not_a_pair_half() -> None:
    text = agent_status_text("RUNNING", monitor=_TESTING, monitor_state="running")
    assert text.plain == "RUNNING"
    assert str(text.style) == "green"


def test_agent_status_text_falls_through_without_a_pair() -> None:
    text = agent_status_text("TESTING")
    assert text.plain == "TESTING"
    assert text.style is None or str(text.style) in {"", "none"}

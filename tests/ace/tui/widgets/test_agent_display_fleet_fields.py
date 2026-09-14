"""Detail-panel rendering of remote fleet provenance and feed diagnostics."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.prompt_panel._agent_display_header_metadata import (
    _append_fleet_fields,
)


def _remote_agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "remote-fix",
        "project_file": "/fleet/remote-fix/project.yml",
        "status": "RUNNING",
        "start_time": datetime(2026, 9, 14, 12, 0, 0),
        "fleet_origin_alias": "apollo",
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


def test_append_fleet_fields_omits_feed_error_line_when_healthy() -> None:
    agent = _remote_agent(fleet_connection_health="online", fleet_freshness="fresh")

    text = Text()
    _append_fleet_fields(text, agent)

    assert "Feed error:" not in text.plain


def test_append_fleet_fields_surfaces_diagnostic_for_invalid_host() -> None:
    agent = _remote_agent(
        fleet_host_status="invalid",
        fleet_host_feed_error="invalid_envelope",
        fleet_diagnostic="invalid_envelope",
    )

    text = Text()
    _append_fleet_fields(text, agent)

    assert "Feed error: " in text.plain
    assert "invalid_envelope" in text.plain

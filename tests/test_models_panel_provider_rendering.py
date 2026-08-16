"""Models-panel provider-routing rendering tests."""

from __future__ import annotations

from sase.ace.tui.modals.models_panel_provider_rendering import (
    provider_description_text,
    render_provider_row,
)
from tests._models_panel_provider_routing_helpers import disable, status


def testrender_provider_rows_show_all_states() -> None:
    available = render_provider_row(
        status("codex", model_count=3),
        colors={"codex": "#10A37F"},
        now=100.0,
    )
    missing = render_provider_row(
        status("grok", model_count=1, cli_available=False),
        colors={},
        now=100.0,
    )
    disabled = render_provider_row(
        status("claude", active_disable=disable("claude", expires_at=3_820.0)),
        colors={"claude": "#D97757"},
        now=100.0,
    )

    assert available.plain == "CODEX          3 models     available"
    assert missing.plain == "GROK           1 model      CLI missing"
    assert disabled.plain == "CLAUDE         2 models     disabled · 1h2m left"


def test_provider_description_lists_disabled_effect_and_aliases() -> None:
    description = provider_description_text(
        status(
            "claude",
            active_disable=disable("claude", expires_at=None),
            affected_aliases=("large", "medium", "xlarge"),
        ),
        now=100.0,
    )

    assert "New launches and fallbacks route around CLAUDE" in description.plain
    assert "running provider processes continue" in description.plain
    assert "Affected aliases: @large, @medium, @xlarge." in description.plain

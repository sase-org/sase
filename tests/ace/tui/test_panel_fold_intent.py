"""Tests for shared whole-panel fold intent and effective-state helpers."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from sase.ace.tui.actions.agents._panel_fold_intent import effective_panel_collapses
from sase.ace.tui.models.agent import Agent, AgentType


def _agent(*, suffix: str, tribe: str | None) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="cl",
        project_file="/r/p/p.sase",
        status="RUNNING",
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        agent_name=f"agent-{suffix}",
        tribe=tribe,
        raw_suffix=suffix,
    )


def _owner(
    *, agents: list[Agent], collapsed: set[str] | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        _agent_panels_grouped=False,
        _agents=agents,
        _collapsed_panel_keys=collapsed or set(),
        _expanded_panel_keys=set(),
    )


def _install_config(monkeypatch: pytest.MonkeyPatch, tribes: dict[str, object]) -> None:
    import sase.ace.tui.models.tribe_display as display

    monkeypatch.setattr(
        display,
        "load_merged_config",
        lambda: {"ace": {"tribes": tribes}},
    )
    monkeypatch.setattr(display, "current_config_token", lambda: ("config", 1))
    monkeypatch.setattr(
        "sase.config.inventory.discover_layer_inputs",
        lambda: [
            {
                "name": "test",
                "kind": "user",
                "path": "/tmp/sase.yml",
                "value": {"ace": {"tribes": tribes}},
                "list_strategy": "replace",
                "writable": True,
                "exists": True,
                "error": None,
            }
        ],
    )


def test_none_panel_keys_disambiguates_configured_alias_against_loaded_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller passing ``panel_keys=None`` still needs real stored-tribe
    evidence to canonicalize a configured public ``job`` alias correctly.

    Without an independent ``job`` identity among the loaded agents, the
    configured ``job`` entry collapses onto ``chop`` and its own
    ``initially_expanded`` setting is ignored. With one present, ``job``
    stays a distinct panel.
    """
    _install_config(
        monkeypatch,
        {
            "chop": {"initially_expanded": True},
            "job": {"initially_expanded": False},
        },
    )

    owner_without_job = _owner(agents=[_agent(suffix="1", tribe="chop")])
    assert effective_panel_collapses(owner_without_job) == set()

    owner_with_job = _owner(agents=[_agent(suffix="1", tribe="job")])
    assert effective_panel_collapses(owner_with_job) == {"job"}


def test_grouped_panels_short_circuit_to_no_collapses() -> None:
    owner = SimpleNamespace(_agent_panels_grouped=True, _agents=[])

    assert effective_panel_collapses(owner) == set()

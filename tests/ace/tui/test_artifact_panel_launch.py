"""Tests for the `A` keymap that opens the artifacts panel."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from textual.app import App, ComposeResult

from sase.ace.tui.actions.artifacts import ArtifactsMixin
from sase.ace.tui.keymaps import build_app_bindings, load_keymap_registry
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.modals.artifact_panel_modal import ArtifactPanelModal
from sase.core.artifact_wire import (
    ARTIFACT_WIRE_SCHEMA_VERSION,
    ArtifactDetailWire,
    ArtifactLinkWire,
    ArtifactNodeWire,
)


class _ModalTestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


class _FakeApp(ArtifactsMixin):
    """Minimal app stand-in capturing pushed modals."""

    def __init__(
        self,
        *,
        changespecs: list[Any] | None = None,
        agents: list[Agent] | None = None,
        current_tab: str = "changespecs",
    ) -> None:
        self.changespecs: list[Any] = changespecs or []
        self._agents = agents or []
        self.current_idx = 0
        self.current_tab = current_tab  # type: ignore[assignment]
        self.pushed_modals: list[Any] = []
        self.notifications: list[tuple[str, str | None]] = []

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        del callback
        self.pushed_modals.append(modal)

    def notify(self, message: str, severity: str | None = None) -> None:
        self.notifications.append((message, severity))


def _make_cs(name: str) -> MagicMock:
    cs = MagicMock()
    cs.name = name
    return cs


def _make_agent(**overrides: Any) -> Agent:
    data = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "alpha",
        "project_file": "/home/me/.sase/projects/proj/proj.gp",
        "status": "DONE",
        "start_time": datetime(2026, 5, 5, 12, 0, 0),
        "workflow": "ace-run",
        "raw_suffix": "20260505120000",
    }
    data.update(overrides)
    return Agent(**data)


def test_open_artifacts_panel_uses_current_changespec_id() -> None:
    app = _FakeApp(changespecs=[_make_cs("alpha"), _make_cs("beta")])
    app.current_idx = 1

    app.action_open_artifacts_panel()

    assert len(app.pushed_modals) == 1
    modal = app.pushed_modals[0]
    assert isinstance(modal, ArtifactPanelModal)
    assert modal._artifact_id == "beta"


def test_open_artifacts_panel_uses_selected_agent_name() -> None:
    app = _FakeApp(
        agents=[_make_agent(agent_name="named-agent")],
        current_tab="agents",
    )

    app.action_open_artifacts_panel()

    assert app.pushed_modals[0]._artifact_id == "named-agent"


def test_open_artifacts_panel_uses_legacy_agent_fallback_id() -> None:
    app = _FakeApp(
        agents=[
            _make_agent(
                agent_name=None,
                artifacts_dir="/home/me/.sase/projects/proj/artifacts/codex/260505_120000",
            )
        ],
        current_tab="agents",
    )

    app.action_open_artifacts_panel()

    assert app.pushed_modals[0]._artifact_id == "agent:proj:codex:260505_120000"


def test_open_artifacts_panel_uses_root_for_axe_tab() -> None:
    app = _FakeApp(current_tab="axe")

    app.action_open_artifacts_panel()

    assert app.pushed_modals[0]._artifact_id == "/"


def test_open_artifacts_panel_warns_without_context() -> None:
    app = _FakeApp(current_tab="changespecs")

    app.action_open_artifacts_panel()

    assert app.pushed_modals == []
    assert app.notifications == [
        ("No artifact context for the current selection", "warning")
    ]


def test_default_keymap_binds_capital_a_to_open_artifacts_panel() -> None:
    registry = load_keymap_registry({"keymaps": {"app": {}}})
    assert registry.app.open_artifacts_panel == "A"

    bindings = build_app_bindings(registry.app)
    matches = [b for b in bindings if b.action == "open_artifacts_panel"]
    assert len(matches) == 1
    assert matches[0].key == "A"


@pytest.mark.asyncio
async def test_artifact_modal_renders_fake_facade_detail() -> None:
    detail = ArtifactDetailWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        node=ArtifactNodeWire(
            id="alpha",
            kind="changespec",
            display_title="Alpha CL",
            provenance="derived",
        ),
        children=[
            ArtifactNodeWire(
                id="alpha:1",
                kind="commit",
                display_title="Commit 1",
                provenance="derived",
            )
        ],
        outbound_links=[
            ArtifactLinkWire(
                id="link-1",
                link_type="related",
                source_id="alpha",
                target_id="named-agent",
            )
        ],
    )
    calls: list[tuple[str, str]] = []

    def fake_show(index_path: str | Any, artifact_id: str) -> ArtifactDetailWire:
        calls.append((str(index_path), artifact_id))
        return detail

    modal = ArtifactPanelModal(
        artifact_id="alpha",
        index_path="/tmp/fake-artifacts.sqlite",
        show_func=fake_show,
    )

    app = _ModalTestApp()
    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()

    assert calls == [("/tmp/fake-artifacts.sqlite", "alpha")]
    assert modal._detail == detail

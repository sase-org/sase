"""Tests for the `A` keymap that opens the artifacts panel."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, OptionList, Static

from sase.ace.tui.actions.artifacts import ArtifactsMixin
from sase.ace.tui.keymaps import build_app_bindings, load_keymap_registry
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.modals.artifact_panel_modal import ArtifactPanelModal
from sase.ace.tui.modals.artifact_panel_state import build_artifact_panel_rows
from sase.core.artifact_wire import (
    ARTIFACT_WIRE_SCHEMA_VERSION,
    ArtifactDetailWire,
    ArtifactGraphOptionsWire,
    ArtifactGraphWire,
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


def _node(
    artifact_id: str, kind: str = "file", title: str | None = None
) -> ArtifactNodeWire:
    return ArtifactNodeWire(
        id=artifact_id,
        kind=kind,
        display_title=title or artifact_id,
        provenance="derived",
    )


def _detail(
    artifact_id: str,
    *,
    kind: str = "file",
    title: str | None = None,
    metadata: dict[str, Any] | None = None,
    children: list[ArtifactNodeWire] | None = None,
    outbound_links: list[ArtifactLinkWire] | None = None,
    inbound_links: list[ArtifactLinkWire] | None = None,
    path_to_root: list[ArtifactNodeWire] | None = None,
) -> ArtifactDetailWire:
    return ArtifactDetailWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        node=ArtifactNodeWire(
            id=artifact_id,
            kind=kind,
            display_title=title or artifact_id,
            provenance="derived",
            metadata=metadata or {},
        ),
        children=children or [],
        outbound_links=outbound_links or [],
        inbound_links=inbound_links or [],
        path_to_root=path_to_root or [],
    )


def test_open_artifacts_panel_uses_current_changespec_id() -> None:
    app = _FakeApp(changespecs=[_make_cs("alpha"), _make_cs("beta")])
    app.current_idx = 1

    app.action_open_artifacts_panel()

    assert len(app.pushed_modals) == 1
    modal = app.pushed_modals[0]
    assert isinstance(modal, ArtifactPanelModal)
    assert modal._artifact_id == "beta"


def test_open_artifacts_panel_passes_changespec_file_context() -> None:
    cs = _make_cs("alpha")
    cs.file_path = "/home/me/.sase/projects/proj/proj.gp"
    app = _FakeApp(changespecs=[cs])

    app.action_open_artifacts_panel()

    assert app.pushed_modals[0]._context_path == Path(
        "/home/me/.sase/projects/proj/proj.gp"
    )


def test_open_artifacts_panel_uses_selected_agent_name() -> None:
    app = _FakeApp(
        agents=[_make_agent(agent_name="named-agent")],
        current_tab="agents",
    )

    app.action_open_artifacts_panel()

    assert app.pushed_modals[0]._artifact_id == "named-agent"


def test_open_artifacts_panel_passes_agent_artifact_dir_context() -> None:
    artifact_dir = "/home/me/.sase/projects/proj/artifacts/codex/260505_120000"
    app = _FakeApp(
        agents=[_make_agent(agent_name="named-agent", artifacts_dir=artifact_dir)],
        current_tab="agents",
    )

    app.action_open_artifacts_panel()

    assert app.pushed_modals[0]._context_artifact_dir == Path(artifact_dir)


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
    assert all(
        binding[1] != "open_legacy_run_log" for binding in ArtifactPanelModal.BINDINGS
    )


def test_capital_a_opens_artifacts_panel_not_agent_run_log() -> None:
    app = _FakeApp(changespecs=[_make_cs("alpha")])

    app.action_open_artifacts_panel()

    assert isinstance(app.pushed_modals[0], ArtifactPanelModal)


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


@pytest.mark.asyncio
async def test_artifact_modal_open_selected_tracks_history_without_duplicate_push() -> (
    None
):
    details = {
        "alpha": _detail(
            "alpha",
            kind="changespec",
            children=[_node("beta", "agent", "Beta agent")],
        ),
        "beta": _detail("beta", kind="agent"),
    }
    calls: list[str] = []

    def fake_show(index_path: str | Any, artifact_id: str) -> ArtifactDetailWire:
        del index_path
        calls.append(artifact_id)
        return details[artifact_id]

    modal = ArtifactPanelModal(artifact_id="alpha", show_func=fake_show)
    app = _ModalTestApp()
    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()

        option_list = modal.query_one("#artifact-panel-list", OptionList)
        option_list.highlighted = 1
        modal.action_open_selected()
        await pilot.pause()
        await pilot.pause()

        modal.action_open_selected()
        await pilot.pause()
        modal.action_back()
        await pilot.pause()
        await pilot.pause()
        modal.action_forward()
        await pilot.pause()
        await pilot.pause()

    assert calls == ["alpha", "beta", "alpha", "beta"]
    assert modal._state.current_id == "beta"


@pytest.mark.asyncio
async def test_artifact_modal_parent_and_root_use_path_to_root() -> None:
    details = {
        "child": _detail(
            "child",
            path_to_root=[_node("/", "root"), _node("parent", "directory")],
        ),
        "parent": _detail("parent", kind="directory"),
        "/": _detail("/", kind="root"),
    }
    calls: list[str] = []

    def fake_show(index_path: str | Any, artifact_id: str) -> ArtifactDetailWire:
        del index_path
        calls.append(artifact_id)
        return details[artifact_id]

    modal = ArtifactPanelModal(artifact_id="child", show_func=fake_show)
    app = _ModalTestApp()
    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        modal.action_parent()
        await pilot.pause()
        await pilot.pause()
        modal.action_root()
        await pilot.pause()
        await pilot.pause()

    assert calls == ["child", "parent", "/"]


def test_artifact_panel_groups_inbound_and_outbound_link_targets() -> None:
    detail = _detail(
        "alpha",
        outbound_links=[
            ArtifactLinkWire(
                id="out-1",
                link_type="created",
                source_id="alpha",
                target_id="file-a",
            )
        ],
        inbound_links=[
            ArtifactLinkWire(
                id="in-1",
                link_type="related",
                source_id="agent-a",
                target_id="alpha",
            )
        ],
    )

    rows = build_artifact_panel_rows(detail).rows

    assert [row.label for row in rows if row.row_type == "group"] == [
        "Outbound: created",
        "Inbound: related",
    ]
    assert {row.id: row.artifact_id for row in rows if row.selectable} == {
        "outbound:out-1": "file-a",
        "inbound:in-1": "agent-a",
    }


@pytest.mark.asyncio
async def test_artifact_filter_updates_without_requerying() -> None:
    calls: list[str] = []

    def fake_show(index_path: str | Any, artifact_id: str) -> ArtifactDetailWire:
        del index_path
        calls.append(artifact_id)
        return _detail(
            artifact_id,
            children=[
                _node("keep-me", "file", "keep me"),
                _node("hide-me", "file", "hide me"),
            ],
        )

    modal = ArtifactPanelModal(artifact_id="alpha", show_func=fake_show)
    app = _ModalTestApp()
    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()

        filter_input = modal.query_one("#artifact-panel-filter", Input)
        filter_input.value = "keep"
        await pilot.pause()

        option_list = modal.query_one("#artifact-panel-list", OptionList)
        visible_ids = [
            option_list.get_option_at_index(index).id
            for index in range(option_list.option_count)
        ]

    assert calls == ["alpha"]
    assert "child:keep-me" in visible_ids
    assert "child:hide-me" not in visible_ids


@pytest.mark.asyncio
async def test_artifact_graph_calls_happen_only_from_explicit_actions() -> None:
    graph_calls: list[ArtifactGraphOptionsWire] = []
    export_calls: list[tuple[ArtifactGraphOptionsWire, str]] = []

    def fake_show(index_path: str | Any, artifact_id: str) -> ArtifactDetailWire:
        del index_path
        return _detail(artifact_id, children=[_node("beta")])

    def fake_graph(
        index_path: str | Any, options: ArtifactGraphOptionsWire
    ) -> ArtifactGraphWire:
        del index_path
        graph_calls.append(options)
        return ArtifactGraphWire(
            schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
            root_id=options.root_id,
            nodes=[_node(options.root_id or "/")],
            node_count=1,
        )

    def fake_export(
        index_path: str | Any,
        options: ArtifactGraphOptionsWire,
        output_format: str,
    ) -> str:
        del index_path
        export_calls.append((options, output_format))
        return "flowchart TD\n"

    modal = ArtifactPanelModal(
        artifact_id="alpha",
        show_func=fake_show,
        graph_func=fake_graph,
        export_func=fake_export,
    )
    app = _ModalTestApp()
    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        modal.action_next_option()
        modal.action_prev_option()
        await pilot.pause()
        assert graph_calls == []
        assert export_calls == []

        modal.action_preview_graph()
        modal.action_export_graph()

    assert [call.root_id for call in graph_calls] == ["alpha"]
    assert [(call.root_id, output_format) for call, output_format in export_calls] == [
        ("alpha", "mermaid")
    ]


@pytest.mark.asyncio
async def test_artifact_modal_opens_file_artifact_in_editor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[list[str]] = []
    file_path = tmp_path / "agent-output.txt"
    file_path.write_text("artifact preview parity\n", encoding="utf-8")

    def fake_show(index_path: str | Any, artifact_id: str) -> ArtifactDetailWire:
        del index_path, artifact_id
        return _detail(
            "file-artifact",
            kind="file",
            metadata={"path": str(file_path)},
        )

    def fake_run(args: list[str], *, check: bool) -> None:
        del check
        opened.append(args)

    monkeypatch.setenv("EDITOR", "vim")
    monkeypatch.setattr(
        "sase.ace.tui.modals.artifact_panel_modal.subprocess.run",
        fake_run,
    )

    modal = ArtifactPanelModal(artifact_id="file-artifact", show_func=fake_show)
    app = _ModalTestApp()
    monkeypatch.setattr(app, "suspend", lambda: nullcontext())
    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()

        modal.action_open_file_in_editor()

    assert opened == [["vim", str(file_path)]]


@pytest.mark.asyncio
async def test_artifact_modal_footer_hints_fit_small_terminal() -> None:
    def fake_show(index_path: str | Any, artifact_id: str) -> ArtifactDetailWire:
        del index_path
        return _detail(
            artifact_id,
            kind="changespec",
            metadata={"name": artifact_id},
            children=[
                _node("agent-1", "agent", "Agent one"),
                _node("commit-1", "commit", "Commit one"),
            ],
        )

    modal = ArtifactPanelModal(artifact_id="tiny-cl", show_func=fake_show)
    app = _ModalTestApp()
    async with app.run_test(size=(54, 18)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()

        hints = modal.query_one("#artifact-panel-hints", Static)
        rendered_hints = str(hints.render())
        assert "g/G: graph" in rendered_hints
        assert "run log" not in rendered_hints.lower()

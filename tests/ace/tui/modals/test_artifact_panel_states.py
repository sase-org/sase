"""Missing, empty, and error state tests for the artifact panel modal."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from textual.widgets import OptionList, Static

from sase.ace.tui.modals.artifact_panel_modal import ArtifactPanelModal
from sase.core.artifact_wire import (
    ARTIFACT_WIRE_SCHEMA_VERSION,
    ArtifactDetailPagedWire,
    ArtifactDetailWire,
    ArtifactGraphOptionsWire,
    ArtifactGraphWire,
    ArtifactPageRequestWire,
)
from tests.ace.tui.modals._artifact_panel_modal_helpers import (
    _ModalTestApp,
    _detail,
    _missing_detail,
    _node,
    _paged_detail,
)


@pytest.mark.asyncio
async def test_missing_start_artifact_rebuilds_context_and_retries_once(
    tmp_path: Path,
) -> None:
    show_calls: list[str] = []
    refresh_calls: list[tuple[str, str, str | None, str | None]] = []
    context_path = tmp_path / "project.gp"

    def fake_show(index_path: str | Any, artifact_id: str) -> ArtifactDetailWire:
        show_calls.append(artifact_id)
        if len(show_calls) == 1:
            return _missing_detail()
        return _detail(artifact_id, kind="changespec")

    def fake_refresh(
        index_path: str | Any,
        artifact_id: str,
        ctx_path: str | Any | None,
        artifact_dir: str | Any | None,
    ) -> None:
        refresh_calls.append(
            (
                str(index_path),
                artifact_id,
                str(ctx_path) if ctx_path is not None else None,
                str(artifact_dir) if artifact_dir is not None else None,
            )
        )

    modal = ArtifactPanelModal(
        artifact_id="changespec:current",
        index_path="/tmp/artifacts.sqlite",
        show_func=fake_show,
        refresh_missing_func=fake_refresh,
        context_path=context_path,
    )
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()

    assert show_calls == ["changespec:current", "changespec:current"]
    assert refresh_calls == [
        (
            "/tmp/artifacts.sqlite",
            "changespec:current",
            str(context_path),
            None,
        )
    ]
    assert modal._detail is not None
    assert modal._detail.node is not None


@pytest.mark.asyncio
async def test_missing_artifact_state_explains_manual_sync_after_targeted_refresh(
    tmp_path: Path,
) -> None:
    context_path = tmp_path / "project.gp"

    def fake_show(index_path: str | Any, artifact_id: str) -> ArtifactDetailWire:
        del index_path, artifact_id
        return _missing_detail()

    modal = ArtifactPanelModal(
        artifact_id="changespec:missing",
        show_func=fake_show,
        refresh_missing_func=lambda *args: None,
        context_path=context_path,
    )
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        option_list = modal.query_one("#artifact-panel-list", OptionList)
        option = option_list.get_option_at_index(0)
        detail_text = str(modal.query_one("#artifact-panel-detail", Static).render())
        path_text = str(modal.query_one("#artifact-panel-header-path", Static).render())
        option_text = str(option.prompt)

    assert option.id == "__missing__"
    assert "Artifact not found after targeted refresh" in option_text
    assert "ID: changespec:missing" in option_text
    assert f"Refresh context: path {context_path}" in option_text
    assert "not indexed yet" in detail_text
    assert "historical artifacts not synced" in detail_text
    assert "source moved/deleted" in detail_text
    assert "index unavailable" in detail_text
    assert "sase artifact sync -j" in detail_text
    assert f"sase artifact rebuild -j -t {context_path}" in detail_text
    assert f"path {context_path}" in path_text


@pytest.mark.asyncio
async def test_missing_agent_artifact_state_suggests_targeted_artifact_dir_sync(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "projects" / "proj" / "artifacts" / "codex" / "ts"

    def fake_show(index_path: str | Any, artifact_id: str) -> ArtifactDetailWire:
        del index_path, artifact_id
        return _missing_detail()

    modal = ArtifactPanelModal(
        artifact_id="agent:missing",
        show_func=fake_show,
        refresh_missing_func=lambda *args: None,
        artifact_dir=artifact_dir,
    )
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        detail_text = str(modal.query_one("#artifact-panel-detail", Static).render())
        path_text = str(modal.query_one("#artifact-panel-header-path", Static).render())

    assert f"artifact dir {artifact_dir}" in path_text
    assert f"Refresh context: artifact dir {artifact_dir}" in detail_text
    assert f"sase artifact sync -j -a {artifact_dir}" in detail_text


@pytest.mark.asyncio
async def test_empty_relationship_state_is_polished() -> None:
    modal = ArtifactPanelModal(
        artifact_id="alpha",
        index_path="/tmp/fake.sqlite",
        show_paged_func=lambda index_path, artifact_id, request=None: _paged_detail(
            artifact_id,
            kind="changespec",
            title="Alpha",
        ),
    )
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        option_list = modal.query_one("#artifact-panel-list", OptionList)
        option = option_list.get_option_at_index(0)

    assert option.id == "__relationships_empty__"
    assert "No linked artifacts" in str(option.prompt)
    assert "no loaded path, child, outbound, or inbound rows" in str(option.prompt)


@pytest.mark.asyncio
async def test_missing_start_artifact_does_not_refresh_more_than_once(
    tmp_path: Path,
) -> None:
    show_calls: list[str] = []
    refresh_calls: list[str] = []

    def fake_show(index_path: str | Any, artifact_id: str) -> ArtifactDetailWire:
        del index_path
        show_calls.append(artifact_id)
        return _missing_detail()

    def fake_refresh(
        index_path: str | Any,
        artifact_id: str,
        ctx_path: str | Any | None,
        artifact_dir: str | Any | None,
    ) -> None:
        del index_path, ctx_path, artifact_dir
        refresh_calls.append(artifact_id)

    modal = ArtifactPanelModal(
        artifact_id="changespec:missing",
        show_func=fake_show,
        refresh_missing_func=fake_refresh,
        context_path=tmp_path / "project.gp",
    )
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        modal.action_root()
        await pilot.pause()
        await pilot.pause()
        modal._navigate_to("changespec:missing")
        await pilot.pause()
        await pilot.pause()

    assert show_calls == [
        "changespec:missing",
        "changespec:missing",
        "/",
        "/",
        "changespec:missing",
    ]
    assert refresh_calls == ["changespec:missing", "/"]


@pytest.mark.asyncio
async def test_artifact_load_error_renders_error_without_broad_queries() -> None:
    show_calls: list[str] = []
    graph_calls: list[ArtifactGraphOptionsWire] = []
    export_calls: list[tuple[ArtifactGraphOptionsWire, str]] = []

    def fake_show(index_path: str | Any, artifact_id: str) -> ArtifactDetailWire:
        del index_path
        show_calls.append(artifact_id)
        raise RuntimeError("synthetic artifact backend failure")

    def fake_graph(
        index_path: str | Any, options: ArtifactGraphOptionsWire
    ) -> ArtifactGraphWire:
        del index_path
        graph_calls.append(options)
        return ArtifactGraphWire(schema_version=ARTIFACT_WIRE_SCHEMA_VERSION)

    def fake_export(
        index_path: str | Any,
        options: ArtifactGraphOptionsWire,
        output_format: str,
    ) -> str:
        del index_path
        export_calls.append((options, output_format))
        return ""

    modal = ArtifactPanelModal(
        artifact_id="broken",
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
        detail_text = str(modal.query_one("#artifact-panel-detail", Static).render())

    assert show_calls == ["broken"]
    assert graph_calls == []
    assert export_calls == []
    assert "Artifact load failed" in detail_text
    assert "synthetic artifact backend failure" in detail_text


@pytest.mark.asyncio
async def test_sqlite_busy_load_error_is_recoverable_and_keeps_history() -> None:
    show_calls: list[str] = []

    def fake_paged_show(
        index_path: str | Any,
        artifact_id: str,
        request: ArtifactPageRequestWire | None = None,
    ) -> ArtifactDetailPagedWire:
        del index_path, request
        show_calls.append(artifact_id)
        if artifact_id == "agent:beta":
            raise RuntimeError("sqlite error: database is locked")
        return _paged_detail(
            "agent:alpha",
            kind="agent",
            children=[_node("agent:beta", "agent", "Beta agent")],
        )

    modal = ArtifactPanelModal(
        artifact_id="agent:alpha",
        index_path="/tmp/fake.sqlite",
        show_paged_func=fake_paged_show,
    )
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()

        option_list = modal.query_one("#artifact-panel-list", OptionList)
        for index in range(option_list.option_count):
            if option_list.get_option_at_index(index).id == "child:agent:beta":
                option_list.highlighted = index
                break
        else:
            raise AssertionError("agent:beta row was not rendered")

        modal.action_open_selected()
        for _ in range(10):
            await pilot.pause()
            detail_text = str(
                modal.query_one("#artifact-panel-detail", Static).render()
            )
            if "Artifact index busy" in detail_text:
                break

        detail_text = str(modal.query_one("#artifact-panel-detail", Static).render())

    assert show_calls == ["agent:alpha", "agent:beta"]
    assert modal._state.current_id == "agent:beta"
    assert modal._state.back_stack == ["agent:alpha"]
    assert modal._state.forward_stack == []
    assert modal._detail is None
    assert "Artifact index busy" in detail_text
    assert "Try again shortly" in detail_text
    assert "database is locked" in detail_text

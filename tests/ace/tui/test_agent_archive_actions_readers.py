"""Archive read-target and hydrated reader action tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from rich.text import Text

from sase.ace.tui.actions.agents._archive_actions import (
    archive_read_target,
    resolve_agents_read_agent,
)
from sase.ace.tui.actions.agents._archive_view import get_agents_tab_selection
from sase.feature_flags import override_flags
from tests.ace.tui._agent_archive_actions_helpers import make_owner, open_archive


@pytest.mark.asyncio
async def test_mounted_archive_placeholder_covers_prior_detail(
    monkeypatch: Any,
) -> None:
    from textual.widgets import Static

    from sase.ace.testing import AcePage
    from sase.ace.tui.widgets.agent_detail import AgentDetail
    from tests.ace.tui.visual._ace_png_snapshot_helpers import (
        patch_startup_loaders,
        wait_for_startup,
    )

    patch_startup_loaders(monkeypatch, agents=[])
    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        detail = page.app.query_one("#agent-detail-panel", AgentDetail)
        layout = detail.query_one("#agent-detail-layout")
        placeholder = detail.query_one("#agent-archive-placeholder", Static)

        detail.show_archive_placeholder(SimpleNamespace(expanded=Text("Loading")))

        assert "-archive-placeholder-active" in layout.classes
        assert "hidden" not in placeholder.classes
        assert detail._current_agent is None

        detail.show_empty()

        assert "-archive-placeholder-active" not in layout.classes
        assert "hidden" in placeholder.classes


def test_read_target_none_outside_archive() -> None:
    owner = make_owner(inbox_agent=SimpleNamespace(cl_name="live"))
    assert archive_read_target(owner) is None
    assert resolve_agents_read_agent(owner) is owner._inbox_agent


def test_read_target_none_for_nav_items() -> None:
    owner = make_owner(inbox_agent=SimpleNamespace(cl_name="live"))
    open_archive(owner, selected_key="banner:day:2026-10-10")
    selection = get_agents_tab_selection(owner)
    assert selection.row_kind == "none"
    assert archive_read_target(owner) is None
    assert resolve_agents_read_agent(owner) is None


def test_copy_context_resolves_without_raise() -> None:
    from sase.ace.tui.actions.clipboard._palette import build_copy_as_context

    owner = make_owner()
    assert build_copy_as_context(owner) is None


def test_view_files_on_banner_does_not_use_parked_inbox() -> None:
    from sase.ace.tui.actions.hints._files import FileViewingMixin

    inbox = SimpleNamespace(cl_name="parked-inbox")
    owner = make_owner(inbox_agent=inbox)
    open_archive(owner, selected_key="banner:day:2026-10-10")
    extra: dict[str, object] = {}
    app = FileViewingMixin()
    app.__dict__.update(owner.__dict__)
    app._refocus_existing_hint_bar = lambda: False  # type: ignore[attr-defined]
    assert resolve_agents_read_agent(app) is None
    app._view_agent_files_impl(extra)  # type: ignore[attr-defined]
    assert extra["outcome"] == "no_agent"


def test_hydrated_archive_run_is_the_read_target() -> None:
    from sase.ace.tui.models.agent_archive_reader import (
        ArchiveReaderRuntime,
        mark_agent_archive_read_only,
    )
    from tests.ace.agent_artifact_startup_fixtures import make_agent

    archived = mark_agent_archive_read_only(make_agent(cl_name="archived-run"))
    inbox = SimpleNamespace(cl_name="parked-inbox", identity=("parked",))
    owner = make_owner(inbox_agent=inbox)
    open_archive(owner, selected_key="u.m@r1")
    owner._archive_reader_runtime = ArchiveReaderRuntime(
        archive_key="u.m@r1",
        hydrated_agent=archived,
    )
    assert resolve_agents_read_agent(owner) is archived
    assert owner._get_selected_agent() is inbox


def test_moving_between_loading_archive_rows_keeps_loading_card(
    monkeypatch: Any,
) -> None:
    from sase.ace.tui.actions.agents import _archive_reader as reader
    from sase.ace.tui.models.agent_archive_reader import ArchiveReaderRuntime
    from sase.ace.tui.models.agent_archive_view import (
        ARCHIVE_ROW_AGENT,
        AgentsTabSelection,
    )

    owner = make_owner()
    owner._agents_archive_view.generation = 4
    owner._archive_reader_runtime = ArchiveReaderRuntime(
        archive_key="u.m@previous",
        generation=4,
        loading=True,
    )
    detail = object()
    selection = AgentsTabSelection(
        view="archive",
        row_kind=ARCHIVE_ROW_AGENT,
        read_only=True,
        archive_key="u.m@next",
        light_row={"name": "next"},
    )
    painted_headers: list[object] = []
    loading_cards: list[str] = []
    monkeypatch.setattr(reader, "archive_detail_owns_panel", lambda _owner: True)
    monkeypatch.setattr(reader, "get_agents_tab_selection", lambda _owner: selection)
    monkeypatch.setattr(reader, "_detail_widget", lambda _owner: detail)
    monkeypatch.setattr(
        reader,
        "archive_identity_header_from_light_row",
        lambda _row, *, loading: ("header", loading),
    )
    monkeypatch.setattr(
        reader,
        "_paint_identity",
        lambda _detail, header: painted_headers.append(header),
    )
    monkeypatch.setattr(
        reader,
        "_show_titled",
        lambda _detail, title: loading_cards.append(title),
    )

    reader.paint_archive_detail_placeholder(owner)

    assert painted_headers == [("header", True)]
    assert loading_cards == []
    assert owner._archive_reader_runtime.archive_key == "u.m@next"
    assert owner._archive_reader_runtime.loading is True


def test_metadata_pager_and_patch_jump_use_hydrated_archive_agent(
    monkeypatch: Any,
) -> None:
    from sase.ace.tui.actions.agents._metadata_pager import AgentMetadataPagerMixin
    from sase.ace.tui.actions.agents._patch_navigation import AgentPatchNavigationMixin
    from sase.ace.tui.models.agent_archive_reader import (
        ArchiveReaderRuntime,
        mark_agent_archive_read_only,
    )
    from tests.ace.agent_artifact_startup_fixtures import make_agent

    archived = mark_agent_archive_read_only(
        make_agent(cl_name="archived-cl", raw_suffix="20250101120000")
    )
    owner = make_owner(inbox_agent=SimpleNamespace(cl_name="parked-inbox"))
    open_archive(owner, selected_key="u.m@r1")
    owner._archive_reader_runtime = ArchiveReaderRuntime(
        archive_key="u.m@r1",
        hydrated_agent=archived,
    )
    jumped: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_actions.navigate_to_patch_tab",
        lambda _app, name, project: jumped.append((name, project)),
    )
    pager = AgentMetadataPagerMixin()
    pager.__dict__.update(owner.__dict__)
    pager.current_tab = "agents"
    pager.run_worker = lambda coro, **_kwargs: setattr(pager, "_worker", coro)
    pager.action_view_agent_metadata()
    assert getattr(pager, "_worker", None) is not None

    jumper = AgentPatchNavigationMixin()
    jumper.__dict__.update(owner.__dict__)
    jumper.current_tab = "agents"
    jumper._resolve_agent_cl_name = lambda agent: agent.cl_name  # type: ignore[attr-defined]
    jumper.notify = owner.notify
    jumper.action_jump_to_agent_patch()
    assert jumped == [("archived-cl", archived.project_file)]


def test_act_on_agent_routes_to_archive_activate(monkeypatch: Any) -> None:
    from sase.ace.tui.actions.agents._agent_enter_action import AgentEnterActionMixin

    routed: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._agent_enter_action.route_archive_key_if_active",
        lambda _owner, intent: routed.append(intent) or True,
    )
    owner = make_owner(inbox_agent=SimpleNamespace(cl_name="parked-inbox"))
    open_archive(owner, selected_key="u.m@r1")
    app = AgentEnterActionMixin()
    app.__dict__.update(owner.__dict__)
    app.current_tab = "agents"
    app.action_act_on_agent()
    assert routed == ["activate"]

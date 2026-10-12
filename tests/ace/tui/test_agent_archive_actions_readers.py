"""Archive read-target and hydrated reader action tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents._archive_actions import (
    archive_read_target,
    resolve_agents_read_agent,
)
from sase.ace.tui.actions.agents._archive_view import get_agents_tab_selection
from sase.feature_flags import override_flags
from tests.ace.tui._agent_archive_actions_helpers import make_owner, open_archive


def test_read_target_none_outside_archive() -> None:
    owner = make_owner(inbox_agent=SimpleNamespace(cl_name="live"))
    with override_flags(agents_archive_view=True):
        assert archive_read_target(owner) is None
        assert resolve_agents_read_agent(owner) is owner._inbox_agent


def test_read_target_none_for_nav_items() -> None:
    owner = make_owner(inbox_agent=SimpleNamespace(cl_name="live"))
    with override_flags(agents_archive_view=True):
        open_archive(owner, selected_key="banner:day:2026-10-10")
        selection = get_agents_tab_selection(owner)
        assert selection.row_kind == "none"
        assert archive_read_target(owner) is None
        assert resolve_agents_read_agent(owner) is None


def test_copy_context_resolves_without_raise() -> None:
    from sase.ace.tui.actions.clipboard._palette import build_copy_as_context

    owner = make_owner()
    with override_flags(agents_archive_view=True):
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
    with override_flags(agents_archive_view=True):
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
    with override_flags(agents_archive_view=True):
        assert resolve_agents_read_agent(owner) is archived
        assert owner._get_selected_agent() is inbox


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
    with override_flags(agents_archive_view=True):
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
    with override_flags(agents_archive_view=True):
        app.action_act_on_agent()
    assert routed == ["activate"]

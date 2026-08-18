"""Agents-tab current-project query seeding (sase-pw.7)."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.agent_query import project_query_term
from sase.ace.tui.actions.agents._loading import AgentLoadingMixin
from sase.ace.tui.actions.agents._loading_helpers import _AgentDiskLoadResult
from sase.ace.tui.actions.agents._prospective_clan import _apply_active_agent_query
from sase.ace.tui.current_project_settings import CurrentProjectSettings
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_content_search import AgentContentSearchCache
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.ace.tui.widgets.agent_info_panel import AgentInfoPanel
from sase.current_project import CurrentProject

from tests._agents_tab_query_helpers import FakeAgentApp, _make_agent
from tests.ace.tui.widgets.test_agent_info_panel import (
    _collect_rich_text,
    _collect_text,
)


def _current_project(*, display_name: str = "sase") -> CurrentProject:
    return CurrentProject(
        project_key="gh_sase-org__sase",
        display_name=display_name,
        origin="project",
        origin_ref="gh:sase",
        workflow_type="gh",
    )


def _seed_app(
    *,
    seed_agents_query: bool,
    query: str = "",
) -> AgentLoadingMixin:
    app = FakeAgentApp(query=query)
    app._current_project_settings = CurrentProjectSettings(
        seed_agents_query=seed_agents_query
    )
    return app


def _load_state() -> AgentLoadState:
    return AgentLoadState(
        tier="tier1",
        complete_visible_inbox=True,
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
    )


class _SeedLoadApp(AgentLoadingMixin):
    def __init__(self, *, seed_agents_query: bool, query: str = "") -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self.hide_non_run_agents = False
        self._agents = []
        self._agents_with_children = []
        self._agents_last_identity = None
        self._agent_search_query = query
        self._agent_search_query_seeded = False
        self._agent_search_query_seed_attempted = False
        self._current_project_settings = CurrentProjectSettings(
            seed_agents_query=seed_agents_query
        )
        self._agent_content_search_cache = AgentContentSearchCache()
        self._agent_content_search_index = None
        self._agents_seen_complete_history = False
        self._agent_load_state = None
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self._dismissed_agents_disk_signature: tuple[int, int] | None = None
        self._dismissed_agents_disk_identities: set[
            tuple[AgentType, str, str | None]
        ] = set()
        self._dismissed_agents_disk_signature_initialized = True
        self.applied = False
        self.applied_query = ""

    def _apply_loaded_agents(self, *_args: object, **_kwargs: object) -> None:
        self.applied = True
        self.applied_query = self._agent_search_query

    def _apply_loaded_agents_prepared(self, *args: object, **kwargs: object) -> None:
        self.applied = True
        self.applied_query = self._agent_search_query


def test_project_query_term_uses_display_name_through_grammar() -> None:
    assert project_query_term("sase") == "project:sase"
    assert project_query_term("Internal Tools") == 'project:"Internal Tools"'


def test_seed_agents_query_default_leaves_query_empty() -> None:
    app = _seed_app(seed_agents_query=False)

    assert app._should_seed_agent_search_query() is False
    assert app._maybe_seed_agent_search_query(_current_project()) is False
    assert app._agent_search_query == ""
    assert app._agent_search_query_seeded is False
    assert app._agent_search_query_seed_attempted is True


def test_seed_agents_query_true_scopes_with_display_name() -> None:
    app = _seed_app(seed_agents_query=True)

    assert app._should_seed_agent_search_query() is True
    assert app._maybe_seed_agent_search_query(_current_project()) is True
    assert app._agent_search_query == "project:sase"
    assert app._agent_search_query_seeded is True
    assert app._should_seed_agent_search_query() is False


def test_seed_does_not_override_existing_query() -> None:
    app = _seed_app(seed_agents_query=True, query="status:failed")

    assert app._should_seed_agent_search_query() is False
    assert app._maybe_seed_agent_search_query(_current_project()) is False
    assert app._agent_search_query == "status:failed"
    assert app._agent_search_query_seeded is False


def test_seed_happens_once_even_when_resolve_is_empty() -> None:
    app = _seed_app(seed_agents_query=True)

    assert app._maybe_seed_agent_search_query(None) is False
    assert app._agent_search_query == ""
    assert app._maybe_seed_agent_search_query(_current_project()) is False
    assert app._agent_search_query == ""


def test_seeded_query_filters_the_agent_list() -> None:
    matching = _make_agent(
        cl_name="in-scope",
        project_file="/tmp/projects/gh_sase-org__sase/sase.sase",
        project_display_name="sase",
    )
    other = _make_agent(
        cl_name="other",
        project_file="/tmp/projects/gh_acme__widgets/widgets.sase",
        project_display_name="widgets",
    )
    app = _seed_app(seed_agents_query=True)
    app._maybe_seed_agent_search_query(_current_project())
    app._agents = [matching, other]
    app._finalize_agent_list(
        on_agents_tab=False, selected_identity=None, save_unfiltered=True
    )

    assert app._agents == [matching]


def test_info_panel_shows_dim_seeded_tag() -> None:
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_search_query("project:sase", seeded=True)

    plain = _collect_text(panel)
    text = _collect_rich_text(panel)
    assert "filter: project:sase seeded" in plain
    seeded_index = text.plain.index(" seeded")
    matching = [
        str(span.style)
        for span in text.spans
        if span.start <= seeded_index < span.end
        or (span.start <= seeded_index + 1 < span.end)
    ]
    assert any("dim" in style for style in matching)


def test_info_panel_omits_seeded_tag_after_edit() -> None:
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_search_query("project:sase", seeded=True)
        panel.update_search_query("status:done", seeded=False)

    assert "seeded" not in _collect_text(panel)
    assert "filter: status:done" in _collect_text(panel)


def test_update_state_rebuilds_when_seeded_flag_changes() -> None:
    panel = AgentInfoPanel()
    kwargs: dict[str, object] = {
        "position": 0,
        "total": 5,
        "unread": 0,
        "asking": 0,
        "running": 2,
        "waiting": 0,
        "failed": 0,
        "read": 0,
        "sase_agent_count": 5,
        "starting": 0,
        "neighbor_count": 0,
        "countdown": 5,
        "interval": 5,
        "view_mode": "",
        "grouping_mode": "by project",
        "search_query": "project:sase",
        "search_query_seeded": False,
        "runner_limit": 10,
        "runner_queue_count": 0,
    }
    with patch.object(panel, "update"):
        panel.update_state(**kwargs)  # type: ignore[arg-type]

    with (
        patch.object(panel, "_update_display") as full_rebuild,
        patch.object(panel, "update_countdown_only") as cheap_path,
    ):
        panel.update_state(**{**kwargs, "search_query_seeded": True})  # type: ignore[arg-type]

    full_rebuild.assert_called_once()
    cheap_path.assert_not_called()


def test_prospective_clan_applies_seeded_project_query() -> None:
    matching = _make_agent(
        cl_name="in-scope",
        project_file="/tmp/projects/gh_sase-org__sase/sase.sase",
        project_display_name="sase",
    )
    other = _make_agent(
        cl_name="other",
        project_file="/tmp/projects/gh_acme__widgets/widgets.sase",
        project_display_name="widgets",
    )
    owner = _seed_app(seed_agents_query=True)
    owner._maybe_seed_agent_search_query(_current_project())

    assert _apply_active_agent_query(owner, [matching, other]) == [matching]


def test_default_off_load_does_not_resolve_or_seed() -> None:
    app = _SeedLoadApp(seed_agents_query=False)
    resolve_calls: list[str] = []

    def fake_load_agents(*_args: object, **_kwargs: object) -> _AgentDiskLoadResult:
        return _AgentDiskLoadResult(
            all_agents=[],
            dismissed_from_loader=[],
            load_state=_load_state(),
        )

    def fake_resolve() -> CurrentProject | None:
        resolve_calls.append("resolve")
        return _current_project()

    with (
        patch.object(app, "_merge_external_dismissals"),
        patch("sase.ace.patch.find_all_patches_cached", return_value=[]),
        patch(
            "sase.ace.tui.actions.agents._loading.load_agents_from_disk_with_state",
            side_effect=fake_load_agents,
        ),
        patch(
            "sase.current_project.resolve_current_project",
            side_effect=fake_resolve,
        ),
        patch("sase.ace.tui.repro.capture.record_agents_tab_loader_result"),
    ):
        app._load_agents()

    assert resolve_calls == []
    assert app._agent_search_query == ""
    assert app._agent_search_query_seeded is False
    assert app.applied_query == ""


def test_enabled_load_seeds_before_apply() -> None:
    app = _SeedLoadApp(seed_agents_query=True)

    def fake_load_agents(*_args: object, **_kwargs: object) -> _AgentDiskLoadResult:
        return _AgentDiskLoadResult(
            all_agents=[],
            dismissed_from_loader=[],
            load_state=_load_state(),
        )

    with (
        patch.object(app, "_merge_external_dismissals"),
        patch("sase.ace.patch.find_all_patches_cached", return_value=[]),
        patch(
            "sase.ace.tui.actions.agents._loading.load_agents_from_disk_with_state",
            side_effect=fake_load_agents,
        ),
        patch(
            "sase.current_project.resolve_current_project",
            return_value=_current_project(),
        ),
        patch("sase.ace.tui.repro.capture.record_agents_tab_loader_result"),
    ):
        app._load_agents()

    assert app._agent_search_query == "project:sase"
    assert app._agent_search_query_seeded is True
    assert app.applied_query == "project:sase"


async def test_enabled_async_load_seeds_from_worker_resolve() -> None:
    app = _SeedLoadApp(seed_agents_query=True)

    def fake_load_agents(*_args: object, **_kwargs: object) -> _AgentDiskLoadResult:
        return _AgentDiskLoadResult(
            all_agents=[],
            dismissed_from_loader=[],
            load_state=_load_state(),
        )

    with (
        patch(
            "sase.ace.tui.actions.agents._loading_disk."
            "_compute_external_dismissal_merge",
            return_value=None,
        ),
        patch("sase.ace.patch.find_all_patches_cached", return_value=[]),
        patch(
            "sase.ace.tui.actions.agents._loading.load_agents_from_disk_with_state",
            side_effect=fake_load_agents,
        ),
        patch(
            "sase.current_project.resolve_current_project",
            return_value=_current_project(display_name="widgets"),
        ),
        patch("sase.ace.tui.repro.capture.record_agents_tab_loader_result"),
    ):
        await app._load_agents_async()

    assert app._agent_search_query == "project:widgets"
    assert app._agent_search_query_seeded is True
    assert app.applied_query == "project:widgets"


def test_edited_query_survives_a_later_seed_attempt() -> None:
    app = _seed_app(seed_agents_query=True)
    app._maybe_seed_agent_search_query(_current_project())
    app._agent_search_query = "status:done"
    app._agent_search_query_seeded = False

    assert app._maybe_seed_agent_search_query(_current_project()) is False
    assert app._agent_search_query == "status:done"
    assert app._agent_search_query_seeded is False

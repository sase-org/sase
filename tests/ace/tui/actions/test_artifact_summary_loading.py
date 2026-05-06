"""Tests for batched artifact summary loading on CL and Agent refresh paths."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

from sase.ace.changespec.models import ChangeSpec
from sase.ace.tui.actions.artifact_summaries import _load_missing_artifact_summaries
from sase.ace.tui.actions.agents._loading import AgentLoadingMixin
from sase.ace.tui.actions.agents._loading_finalize import finalize_agent_list
from sase.ace.tui.actions.changespec._loading import ChangeSpecLoadingMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.artifact_summary_cache import ArtifactSummaryCache
from sase.ace.tui.models.fold_state import FoldStateManager
from sase.core.artifact_wire import ArtifactSummaryWire


_NOW = datetime(2026, 5, 6, 12, 0, 0)


def _changespec(name: str) -> ChangeSpec:
    return ChangeSpec(
        name=name,
        description="",
        parent=None,
        cl=None,
        status="WIP",
        test_targets=None,
        kickstart=None,
        file_path="/tmp/projects/demo/demo.gp",
        line_number=1,
    )


def _agent(**overrides: Any) -> Agent:
    defaults: dict[str, Any] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "demo",
        "project_file": "/tmp/projects/demo/demo.gp",
        "status": "RUNNING",
        "start_time": _NOW,
    }
    defaults.update(overrides)
    return Agent(**defaults)


class _ChangeSpecSummaryApp(ChangeSpecLoadingMixin):
    def __init__(self, *, mounting: bool = False) -> None:
        self._artifact_summary_cache = ArtifactSummaryCache()
        self._mounting = mounting
        self._all_changespecs: list[ChangeSpec] = []
        self.changespecs: list[ChangeSpec] = []
        self.current_idx = 0
        self.current_tab = "changespecs"
        self.marked_indices: set[int] = set()
        self._changespecs_last_idx = 0
        self._changespecs_last_name = None
        self._current_changespec_group_key = None
        self.update_count = 0
        self.refresh_count = 0

    def _filter_changespecs(self, changespecs: list[ChangeSpec]) -> list[ChangeSpec]:
        return list(changespecs)

    def _update_cls_tab_count(self) -> None:
        self.update_count += 1

    def _refresh_display(self) -> None:
        self.refresh_count += 1

    def _changespec_banner_focus_still_valid(self) -> bool:
        return True


class _FakeContentCache:
    def get_haystack(self, _agent: Agent) -> str:
        return ""

    def prune(self, _agents: list[Agent]) -> None:
        pass


class _FakeFoldRegistry:
    def clear_unknown(self, _keys: Any) -> None:
        pass


class _AgentSummaryApp(AgentLoadingMixin):
    def __init__(self) -> None:
        self.current_tab = "changespecs"
        self.current_idx = 0
        self.hide_non_run_agents = False
        self._agents: list[Agent] = []
        self._agents_with_children: list[Agent] = []
        self._agents_last_idx = 0
        self._has_always_visible = False
        self._hidden_count = 0
        self._hideable_agents: list[Agent] = []
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self._dismissed_agent_objects: list[Agent] = []
        self._agent_status_overrides: dict[tuple[AgentType, str, str | None], str] = {}
        self._agent_pre_question_status: dict[
            tuple[AgentType, str, str | None], str | None
        ] = {}
        self._agent_search_query = ""
        self._agent_content_search_cache = _FakeContentCache()  # type: ignore[assignment]
        self._agent_query_cache = None
        self._agent_query_parse_error = None
        self._fold_manager = FoldStateManager()
        self._fold_counts = {}
        self._group_fold_registry = _FakeFoldRegistry()  # type: ignore[assignment]
        self._grouping_mode = GroupingMode.STANDARD
        self._agents_loading = False
        self._skip_next_agent_artifact_summary_load = False
        self._artifact_summary_cache = ArtifactSummaryCache()
        self.notify = MagicMock()  # type: ignore[assignment]

    def _refresh_agents_display(self, **_kwargs: Any) -> None:
        pass

    def _get_selected_agent(self) -> Agent | None:
        return None

    def _restore_focus_after_removal(self, _prior_pos: int) -> None:
        pass

    def query_one(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("widgets not mounted")


def test_missing_summary_loader_batches_and_caches(monkeypatch: Any) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_summary(_index_path: Any, request: Any) -> list[ArtifactSummaryWire]:
        calls.append(request.artifact_ids)
        return [
            ArtifactSummaryWire(artifact_id="cl-1", state="ok"),
            ArtifactSummaryWire(artifact_id="agent-a", state="ok"),
        ]

    monkeypatch.setattr(
        "sase.ace.tui.actions.artifact_summaries.artifact_facade.artifact_summary",
        fake_summary,
    )
    cache = ArtifactSummaryCache()

    _load_missing_artifact_summaries(cache, ["cl-1", "cl-1", None, "agent-a"])
    _load_missing_artifact_summaries(cache, ["cl-1", "agent-a"])

    assert calls == [("cl-1", "agent-a")]


def test_summary_loader_marks_failures_without_rebuild(
    monkeypatch: Any,
) -> None:
    def fake_summary(_index_path: Any, _request: Any) -> list[ArtifactSummaryWire]:
        raise RuntimeError("missing index")

    rebuild = MagicMock()
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifact_summaries.artifact_facade.artifact_summary",
        fake_summary,
    )
    monkeypatch.setattr(
        "sase.core.artifact_facade.artifact_rebuild",
        rebuild,
    )
    cache = ArtifactSummaryCache()

    _load_missing_artifact_summaries(cache, ["cl-1"])
    _load_missing_artifact_summaries(cache, ["cl-1"])

    assert cache.get("cl-1") == ArtifactSummaryWire(
        artifact_id="cl-1",
        state="error",
        error="missing index",
    )
    rebuild.assert_not_called()


def test_changespec_refresh_loads_one_batched_summary_call(
    monkeypatch: Any,
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_summary(_index_path: Any, request: Any) -> list[ArtifactSummaryWire]:
        calls.append(request.artifact_ids)
        return [
            ArtifactSummaryWire(artifact_id=artifact_id, state="ok")
            for artifact_id in request.artifact_ids
        ]

    monkeypatch.setattr(
        "sase.ace.tui.actions.artifact_summaries.artifact_facade.artifact_summary",
        fake_summary,
    )
    app = _ChangeSpecSummaryApp()

    app._apply_reloaded_changespecs(
        [_changespec("cl-1"), _changespec("cl-2")],
        current_name=None,
    )
    app._apply_reloaded_changespecs(
        [_changespec("cl-1"), _changespec("cl-2")],
        current_name=None,
    )

    assert calls == [("cl-1", "cl-2")]


def test_changespec_startup_apply_does_not_load_summaries(
    monkeypatch: Any,
) -> None:
    summary = MagicMock(return_value=[])
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifact_summaries.artifact_facade.artifact_summary",
        summary,
    )
    app = _ChangeSpecSummaryApp(mounting=True)

    app._apply_changespecs([_changespec("cl-1")])

    summary.assert_not_called()


def test_agent_finalize_loads_one_batched_summary_call(monkeypatch: Any) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_summary(_index_path: Any, request: Any) -> list[ArtifactSummaryWire]:
        calls.append(request.artifact_ids)
        return [
            ArtifactSummaryWire(artifact_id=artifact_id, state="ok")
            for artifact_id in request.artifact_ids
        ]

    monkeypatch.setattr(
        "sase.ace.tui.actions.artifact_summaries.artifact_facade.artifact_summary",
        fake_summary,
    )
    app = _AgentSummaryApp()
    app._agents = [
        _agent(agent_name="named-agent"),
        _agent(
            agent_name=None,
            artifacts_dir="/home/me/.sase/projects/demo/artifacts/ace-run/20260506",
        ),
    ]

    finalize_agent_list(app, False, None, save_unfiltered=True)
    finalize_agent_list(app, False, None, save_unfiltered=True)

    assert calls == [("named-agent", "agent:demo:ace-run:20260506")]


def test_agent_startup_load_can_skip_summary_call(monkeypatch: Any) -> None:
    summary = MagicMock(return_value=[])
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifact_summaries.artifact_facade.artifact_summary",
        summary,
    )
    app = _AgentSummaryApp()
    app._skip_next_agent_artifact_summary_load = True
    app._agents = [_agent(agent_name="named-agent")]

    finalize_agent_list(app, False, None, save_unfiltered=True)

    summary.assert_not_called()
    assert app._skip_next_agent_artifact_summary_load is False

"""Regression guard for apply-path artifact-index maintenance."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.agents._loading_apply import AgentLoadingApplyMixin
from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplyBoundary,
    PreparedApplyData,
    PreparedApplySelectionInputs,
    PreparedFoldFiltering,
)
from sase.ace.tui.models.agent import Agent, AgentType


class _ApplyHarness(AgentLoadingApplyMixin):
    def __init__(self) -> None:
        self.current_tab = "changespecs"
        self.current_idx = 0
        self.hide_non_run_agents = False
        self._agents: list[Agent] = []
        self._agents_with_children: list[Agent] = []
        self._agents_last_idx = 0
        self._agents_last_identity = None
        self._has_always_visible = False
        self._hidden_count = 0
        self._hideable_agents: list[Agent] = []
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self._dismissed_agent_objects: list[Agent] = []
        self._revived_agent_raw_suffixes: set[str] = set()
        self._agents_first_load_done = True
        self._agents_seen_complete_history = False
        self._agents_history_reconcile_pending = False
        self._agents_history_reconcile_armed_mono = 0.0
        self._agent_load_state = None
        self._agents_index_repair_notice_key = None
        self._agent_search_query = ""
        self._agent_query_cache = None
        self._agent_status_overrides = {}
        self._agents_refresh_active_source = "test"
        self._agents_repro_capture = None
        self.finalize_calls = 0
        self.maintenance_calls: list[dict[str, object]] = []

    def _finalize_agent_list(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        self.finalize_calls += 1

    def _schedule_artifact_index_maintenance(
        self,
        *,
        dismissed: Any,
        added: Any = None,
        force: bool = False,
        source: str = "unknown",
    ) -> None:
        self.maintenance_calls.append(
            {
                "dismissed": dismissed,
                "added": added,
                "force": force,
                "source": source,
            }
        )

    def _schedule_live_hint_refresh(self, *, source: str = "unknown") -> None:
        del source

    def _schedule_bead_confirmation_warmup(self, *, source: str = "unknown") -> None:
        del source


def _fail_sync(*args: object, **kwargs: object) -> object:
    del args, kwargs
    raise AssertionError("apply path must not synchronously maintain the index")


def test_apply_schedules_artifact_index_maintenance_offthread() -> None:
    app = _ApplyHarness()
    identity = (AgentType.RUNNING, "done", "20260601010101")
    prep = PreparedApplyData(
        filtered_agents=[],
        has_always_visible=False,
        hidden_count=0,
        hideable_agents=[],
        dismissed_agent_objects=[],
        auto_dismissed_identities={identity},
    )
    boundary = PreparedApplyBoundary(
        prep=prep,
        fold=PreparedFoldFiltering(
            unfiltered_agents=[],
            visible_agents=[],
            fold_counts={},
        ),
        selection=PreparedApplySelectionInputs(
            on_agents_tab=False,
            selected_identity=None,
            prior_visual_row=None,
        ),
        finalize=None,
    )

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_agents", return_value=True),
        patch(
            "sase.core.agent_artifact_index_lifecycle."
            "sync_dismissed_agent_artifact_index",
            _fail_sync,
        ),
        patch(
            "sase.core.agent_artifact_index_lifecycle."
            "sync_dismissed_agent_artifact_index_report",
            _fail_sync,
        ),
        patch(
            "sase.core.agent_artifact_index_lifecycle."
            "terminalize_stale_active_agent_artifact_index_rows",
            _fail_sync,
        ),
    ):
        app._apply_loaded_agents_prepared_inner(
            prep,
            on_agents_tab=False,
            selected_identity=None,
            persist_dismissed_changes=True,
            incomplete_merge_already_applied=True,
            precomputed_boundary=boundary,
            precomputed_fold_levels=None,
        )

    assert app.maintenance_calls == [
        {
            "dismissed": {identity},
            "added": {identity},
            "force": False,
            "source": "apply",
        }
    ]
    assert app.finalize_calls == 1

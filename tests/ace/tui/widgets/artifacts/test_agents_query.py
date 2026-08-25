"""Query wiring for the Artifacts Agent pane."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.query_record import QueryRecord, current_profile_digest
from sase.ace.query_profile import compiled_profile_for_builtin_pane
from sase.ace.tui._artifact_tab_model import PaneCapability
from sase.ace.tui.relations.artifact_links import ArtifactLinksSnapshot
from sase.ace.tui.actions.patch._query import PatchQueryMixin
from sase.ace.tui.widgets.artifacts.agents_data import AgentsSnapshot
from sase.ace.tui.widgets.artifacts.agents_pane import ArtifactsAgentsPane
from sase.ace.tui.widgets.artifacts.query_rows import build_agents_query_index
from sase.agents.catalog import AgentCatalogRow
from sase.core.query_profile_corpus_facade import evaluate_artifact_query_many
from sase.project_display_names import (
    ProjectDisplaySnapshot,
    ProjectRefDisplaySnapshot,
)
from tests._agent_catalog_helpers import make_agent_catalog_row


def _row(name: str, **overrides: Any) -> AgentCatalogRow:
    values: dict[str, Any] = {
        "canonical_global_name": f"bbugyi200.athena.{name}",
        "kind": ("agent",),
        "project": "gh_sase-org__sase",
        "state": "active",
        "raw_suffix": "20260824100000",
        "artifacts_dir": f"/agents/{name}",
        "model": "gpt-5",
        "llm_provider": "codex",
        "status": "DONE",
        "started_at": "2026-08-24T10:00:00+00:00",
        "finished_at": 1798107000.0,
        "retry_attempt": 0,
        "from_artifact_index": True,
    }
    values.update(overrides)
    return make_agent_catalog_row(name, **values)


def _snapshot(
    rows: tuple[AgentCatalogRow, ...],
    *,
    artifact_links: ArtifactLinksSnapshot | None = None,
) -> AgentsSnapshot:
    return AgentsSnapshot(
        project=None,
        rows=rows,
        total_row_count=len(rows),
        artifact_links=artifact_links or ArtifactLinksSnapshot(),
    )


def _project_ref_display() -> ProjectRefDisplaySnapshot:
    return ProjectRefDisplaySnapshot(
        ProjectDisplaySnapshot({"gh_sase-org__sase": "sase"})
    )


def test_agents_query_index_maps_catalog_fields_and_project_display_name() -> None:
    profile = compiled_profile_for_builtin_pane("agents")
    assert profile is not None
    rows = (
        _row(
            "sase-r8.9.land",
            canonical_global_name="bbugyi200.athena.sase-r8.9.land",
            family="sase-r8.9",
            role="code",
            state="dismissed",
            status="failed",
            dismissed=True,
            revivable=True,
            attention=True,
            retry=True,
            retry_attempt=2,
            bundle_path="/dismissed/sase-r8.9.land.json",
            model="gpt-5.6-sol",
        ),
        _row(
            "0b4",
            kind=("family",),
            family=None,
            llm_provider="claude",
            status="WAITING",
            attention=True,
        ),
    )
    index = build_agents_query_index(
        _snapshot(rows),
        pane_id="agents",
        generation=4,
        profile=profile,
        project_ref_display=_project_ref_display(),
    )

    assert evaluate_artifact_query_many(
        "revivable:true AND project:sase AND role:code",
        index,
    ).matched_row_ids == ("agent:sase-r8.9.land",)
    assert evaluate_artifact_query_many("name:0b4", index).matched_row_ids == (
        "agent:0b4",
    )
    assert evaluate_artifact_query_many("status:failed", index).matched_row_ids == (
        "agent:sase-r8.9.land",
    )
    assert "sase" in index.facets["project"]
    assert "codex" in index.facets["provider"]


def test_agents_query_index_filters_artifact_link_facets() -> None:
    profile = compiled_profile_for_builtin_pane("agents")
    assert profile is not None
    rows = (
        _row("alpha"),
        _row("beta"),
        _row("gamma"),
    )
    snapshot = _snapshot(
        rows,
        artifact_links=ArtifactLinksSnapshot(
            rows=(
                {
                    "source_ref": "agent:alpha",
                    "relation": "read",
                    "target_ref": "plan:202608/example.md",
                },
                {
                    "source_ref": "plan:202608/example.md",
                    "relation": "implements",
                    "target_ref": "agent:bbugyi200.athena.beta",
                },
            )
        ),
    )
    index = build_agents_query_index(
        snapshot,
        pane_id="agents",
        generation=4,
        profile=profile,
        project_ref_display=_project_ref_display(),
    )

    assert evaluate_artifact_query_many(
        "relation:read AND linked:true",
        index,
    ).matched_row_ids == ("agent:alpha",)
    assert set(
        evaluate_artifact_query_many(
            "artifact:plan:202608/example.md",
            index,
        ).matched_row_ids
    ) == {"agent:alpha", "agent:beta"}
    linked = evaluate_artifact_query_many("linked:true", index).matched_row_ids
    unlinked = evaluate_artifact_query_many("linked:false", index).matched_row_ids
    assert set(linked) == {"agent:alpha", "agent:beta"}
    assert unlinked == ("agent:gamma",)
    assert len(linked) + len(unlinked) == len(rows)
    assert "read" in index.facets["relation"]
    assert "plan:202608/example.md" in index.facets["artifact"]


def test_agents_query_limit_is_applied_after_full_membership() -> None:
    pane = ArtifactsAgentsPane()
    pane.project_scope = None
    rows = tuple(_row(f"agent-{index}", role="code") for index in range(3))
    pane._snapshot = _snapshot(rows)
    pane._load_generation = 1
    pane.query_source = "role:code limit:2"
    pane._query_index = pane._build_agents_query_index(
        pane._snapshot,
        generation=1,
    )
    pane._query_session.remember(
        evaluate_artifact_query_many(pane.query_source, pane._query_index)
    )

    filtered, exact, pending, truncated, match_count = pane._filtered_agents_snapshot()

    assert filtered is not None
    assert tuple(row.name for row in filtered.rows) == ("agent-0", "agent-1")
    assert exact is True
    assert pending is False
    assert truncated is True
    assert match_count == 3


def test_agents_blank_query_uses_incomplete_head_without_query_index() -> None:
    pane = ArtifactsAgentsPane()
    pane.project_scope = None
    rows = tuple(_row(f"agent-{index}") for index in range(3))
    pane._snapshot = AgentsSnapshot(
        project=None,
        rows=rows,
        total_row_count=7,
        complete=False,
    )
    pane.query_source = "limit:2"
    pane._query_index = None

    filtered, exact, pending, truncated, match_count = pane._filtered_agents_snapshot()

    assert filtered is not None
    assert tuple(row.name for row in filtered.rows) == ("agent-0", "agent-1")
    assert exact is True
    assert pending is False
    assert truncated is True
    assert match_count == 7


def test_agents_filtered_query_waits_for_full_index() -> None:
    pane = ArtifactsAgentsPane()
    pane.project_scope = None
    pane._snapshot = AgentsSnapshot(
        project=None,
        rows=(_row("agent-1", role="code"),),
        total_row_count=3,
        complete=False,
    )
    pane.query_source = "role:code limit:2"
    pane._query_index = None
    requested: list[bool] = []
    pane._request_full_agents_snapshot = lambda: requested.append(True)  # type: ignore[method-assign]

    filtered, exact, pending, truncated, match_count = pane._filtered_agents_snapshot()

    assert filtered is pane._snapshot
    assert exact is False
    assert pending is True
    assert truncated is False
    assert match_count is None
    assert requested == [True]


def test_agents_complete_snapshot_missing_index_rebuilds_index_only() -> None:
    pane = ArtifactsAgentsPane()
    pane.project_scope = None
    pane._snapshot = _snapshot((_row("agent-1", role="code"),))
    pane.query_source = "role:code limit:2"
    pane._query_index = None
    full_requests: list[bool] = []
    rebuilds: list[bool] = []
    pane._request_full_agents_snapshot = lambda: full_requests.append(True)  # type: ignore[method-assign]
    pane._request_agents_query_index_rebuild = lambda: rebuilds.append(True)  # type: ignore[method-assign]

    _filtered, exact, pending, _truncated, match_count = (
        pane._filtered_agents_snapshot()
    )

    assert exact is False
    assert pending is True
    assert match_count is None
    assert full_requests == []
    assert rebuilds == [True]


def test_agents_query_history_record_preserves_host_limit() -> None:
    pane = ArtifactsAgentsPane()
    pane.query_source = "role:code limit:2"

    record = pane.query_history_record()

    assert isinstance(record, QueryRecord)
    assert record.source == "role:code limit:2"
    assert record.canonical == "role:code limit:2"
    assert record.profile_digest == current_profile_digest("agents")


def test_agents_query_rejects_cached_result_from_stale_generation() -> None:
    pane = ArtifactsAgentsPane()
    pane.project_scope = None
    row = _row("agent-1", role="code")
    pane._snapshot = _snapshot((row,))
    pane.query_source = "role:code"
    pane._query_index = pane._build_agents_query_index(
        pane._snapshot,
        generation=1,
    )
    pane._query_session.remember(
        evaluate_artifact_query_many(pane.query_source, pane._query_index)
    )
    pane._load_generation = 2

    _filtered, exact, pending, _truncated, match_count = (
        pane._filtered_agents_snapshot()
    )

    assert exact is False
    assert pending is True
    assert match_count is None


class _SavedQueryHarness(PatchQueryMixin):
    def __init__(self) -> None:
        digest = current_profile_digest("agents")
        self.current_tab = "artifacts"
        self.current_artifacts_pane_key = "agents"
        self._saved_queries = {
            "agents": {
                "1": QueryRecord(
                    source="revivable:true limit:10",
                    canonical="revivable:true limit:10",
                    profile_digest=digest,
                )
            }
        }
        self.applied: list[QueryRecord] = []
        self.restored: list[tuple[str, str]] = []
        self.notifications: list[tuple[str, str | None]] = []
        self.active_artifacts_contract = SimpleNamespace(
            id="agents",
            has=lambda capability: capability == PaneCapability.SAVED_QUERIES,
        )

    def _query_history_pane(self, _contract: object) -> object:
        return self

    def apply_saved_query_record(self, record: QueryRecord) -> bool:
        self.applied.append(record)
        return True

    def _restore_artifacts_query_selection(
        self,
        pane_id: str,
        canonical: str,
        _pane: object,
    ) -> None:
        self.restored.append((pane_id, canonical))

    def notify(self, message: str, *, severity: str | None = None) -> None:
        self.notifications.append((message, severity))


def test_saved_query_slot_loading_delegates_to_active_agent_pane() -> None:
    harness = _SavedQueryHarness()

    harness._load_saved_query("1")

    assert [record.source for record in harness.applied] == ["revivable:true limit:10"]
    assert harness.restored == [("agents", "revivable:true limit:10")]
    assert harness.notifications == []

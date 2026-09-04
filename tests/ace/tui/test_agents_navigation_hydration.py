"""Targeted-hydration coverage for the Agents pane."""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets.artifacts.agents_data import AgentsSnapshot
from sase.ace.tui.widgets.artifacts.agents_navigation import AgentsNavigationMixin
from sase.ace.tui.widgets.artifacts.entry_navigation import (
    ArtifactEntryTarget,
    HydrationOutcome,
)
from sase.agents.catalog import AgentCatalogSnapshot
from tests._agent_catalog_helpers import make_agent_catalog_row


class _Pane(AgentsNavigationMixin):
    """Bare stand-in exposing only what ``hydrate_ref``/``install_hydrated_row`` need."""

    def __init__(self, snapshot: AgentsSnapshot, *, project_scope: str | None) -> None:
        self._snapshot = snapshot
        self.project_scope = project_scope

    def _current_snapshot(self) -> AgentsSnapshot | None:
        snapshot = self._snapshot
        if snapshot is None or snapshot.project != self.project_scope:
            return None
        return snapshot


def _catalog(*rows: object) -> AgentCatalogSnapshot:
    return AgentCatalogSnapshot(
        rows=tuple(rows),  # type: ignore[arg-type]
        registry_entry_count=len(rows),
        artifact_index_row_count=0,
        dismissed_summary_count=0,
        enriched_count=0,
        thin_count=len(rows),
        facets={},
    )


def test_hydrate_ref_resolves_agent_and_merges_one_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = make_agent_catalog_row("sase-alpha.1")
    hydrated = make_agent_catalog_row("sase-beta.2", project="beta")
    monkeypatch.setattr(
        "sase.agents.catalog.build_agent_catalog_snapshot",
        lambda: _catalog(existing, hydrated),
    )

    snapshot = AgentsSnapshot(
        project=None, rows=(existing,), total_row_count=1, truncated=False
    )
    pane = _Pane(snapshot, project_scope=None)

    outcome = pane.hydrate_ref("agent", "sase-beta.2")
    assert outcome.outcome is HydrationOutcome.FETCHED
    assert outcome.payload is hydrated

    target = pane.install_hydrated_row(outcome.payload)
    assert target == ArtifactEntryTarget("agents", ("sase-beta.2",))
    assert pane._snapshot is not None
    assert len(pane._snapshot.rows) == 2
    assert pane._snapshot.total_row_count == 2

    # Idempotent: re-installing the identical row does not duplicate it.
    replay = pane.install_hydrated_row(outcome.payload)
    assert replay == target
    assert len(pane._snapshot.rows) == 2
    assert pane._snapshot.total_row_count == 2


def test_hydrate_ref_scopes_candidates_to_the_current_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A same-named agent in a different project never leaks into a scoped pane."""
    existing = make_agent_catalog_row("sase-alpha.1", project="alpha")
    other_project_match = make_agent_catalog_row("sase-shared.1", project="beta")
    in_scope_match = make_agent_catalog_row("sase-shared.1", project="alpha")
    monkeypatch.setattr(
        "sase.agents.catalog.build_agent_catalog_snapshot",
        lambda: _catalog(existing, other_project_match, in_scope_match),
    )

    snapshot = AgentsSnapshot(
        project="alpha", rows=(existing,), total_row_count=1, truncated=False
    )
    pane = _Pane(snapshot, project_scope="alpha")

    outcome = pane.hydrate_ref("agent", "sase-shared.1")
    assert outcome.outcome is HydrationOutcome.FETCHED
    assert outcome.payload is in_scope_match
    assert outcome.payload.project == "alpha"


def test_hydrate_ref_resolves_via_alias_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare/aliased spelling still resolves the canonical registry row."""
    canonical = make_agent_catalog_row("athena.sase-beta.2")
    monkeypatch.setattr(
        "sase.agents.catalog.build_agent_catalog_snapshot",
        lambda: _catalog(canonical),
    )
    monkeypatch.setattr(
        "sase.core.agent_identity_facade.current_owner_agent_name_lookup_candidates",
        lambda name, _identity: (name, f"athena.{name}"),
    )

    snapshot = AgentsSnapshot(project=None, rows=(), total_row_count=0, truncated=False)
    pane = _Pane(snapshot, project_scope=None)

    outcome = pane.hydrate_ref("agent", "sase-beta.2")
    assert outcome.outcome is HydrationOutcome.FETCHED
    assert outcome.payload is canonical


def test_hydrate_ref_reports_absent_for_unknown_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.agents.catalog.build_agent_catalog_snapshot",
        lambda: _catalog(),
    )
    snapshot = AgentsSnapshot(project=None, rows=(), total_row_count=0, truncated=False)
    pane = _Pane(snapshot, project_scope=None)

    outcome = pane.hydrate_ref("agent", "no-such-agent")
    assert outcome.outcome is HydrationOutcome.ABSENT


def test_hydrate_ref_unsupported_for_non_agent_kind() -> None:
    snapshot = AgentsSnapshot(project=None, rows=(), total_row_count=0, truncated=False)
    pane = _Pane(snapshot, project_scope=None)

    outcome = pane.hydrate_ref("bead", "sase-ug.1")
    assert outcome.outcome is HydrationOutcome.UNSUPPORTED

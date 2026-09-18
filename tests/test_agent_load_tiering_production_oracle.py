"""Production-path diagnostics for the sase-zu load-tiering oracle.

The tests here route through :func:`load_tiered_agents`, the real TUI entry
point (``production_bounded``/``production_full_history`` on
:class:`AgentLoadTieringOracle`), instead of the harness's own raw
index-facade calls. That means they exercise production's actual freshness
parameters (``revalidate`` forced for full history) and query-pushdown
compilation rather than a harness re-implementation of them.

The ``index-freshness`` (sase-zu.8.2) false-completeness and stale-deleted-
row cases and the ``machine-parity`` (sase-zu.8.3) conflicting-provenance
case are now zero-diff regressions.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

from sase.ace.tui.models import _agent_loader_artifacts as loader_artifacts
from sase.feature_flags import override_flags

from tests.perf.agent_load_tiering_fixture import (
    build_synthetic_agent_archive,
    delete_artifact,
    rebuild_index,
    set_artifact_hidden,
    set_artifact_machine_provenance,
    write_completed_artifact,
)
from tests.perf.agent_load_tiering_harness import (
    AgentLoadTieringOracle,
    QUERY_BATTERY,
    VisibleAgentRow,
)

# Both agents-live query dialects: legacy (flag off) and unified (flag on).
_DIALECTS = (False, True)


def test_production_oracle_query_battery_matches_source_scan(tmp_path: Path) -> None:
    """Regression: the real TUI loader matches the authoritative scan today.

    Neither audit defect below is triggered by this fixture (nothing is
    added after the index build, and its one provenance row uses agreeing
    source/owner values per :mod:`agent_load_tiering_fixture`), so both
    production paths should be clean for the whole committed-query battery.

    Deliberately not parametrized over both query dialects: the harness's
    ``source_scan``/``index_*`` "authoritative" paths always filter through
    the unified agents-live engine regardless of the ``agents_unified_query``
    flag, so forcing the legacy dialect here would compare production's
    legacy-language output against a unified-language reference for queries
    whose AST semantics genuinely differ between the two languages (the two
    dialect-specific defect tests below use only queries proven equivalent
    under both).
    """
    fixture = build_synthetic_agent_archive(tmp_path / "fixture", artifact_count=72)
    oracle = AgentLoadTieringOracle(fixture)

    for case in QUERY_BATTERY:
        result = oracle.evaluate(case.query, requested_limit=400)
        for name in ("production_bounded", "production_full_history"):
            diff = result.diff_for(name)
            assert diff.missing == (), (name, case.query)
            assert diff.visible_extra == (), (name, case.query)


@pytest.mark.parametrize("unified_query", _DIALECTS)
def test_production_full_history_oracle_discovers_artifact_added_after_index_build(
    tmp_path: Path, unified_query: bool
) -> None:
    """Post-rebuild artifacts arrive on the production full-history path.

    Marker revalidation cannot discover directories the index has never
    seen; source-directory reconciliation during revalidate full-history
    does. Completeness is claimed only after that discovery.
    """
    fixture = build_synthetic_agent_archive(tmp_path / "fixture", artifact_count=72)
    new_artifact_dir = write_completed_artifact(
        fixture.projects_root, fixture.artifact_count + 1
    )

    oracle = AgentLoadTieringOracle(fixture)
    with override_flags(agents_unified_query=unified_query):
        result = oracle.evaluate("", requested_limit=None)

    assert new_artifact_dir.name in {
        Path(row.artifact_dir).name for row in result.source_scan.visible_rows.values()
    }

    diff = result.diff_for("production_full_history")
    assert diff.ok
    missing_dirs = {Path(row.artifact_dir).name for row in diff.missing}
    assert new_artifact_dir.name not in missing_dirs

    load_state = result.production_full_history.load_state
    assert load_state is not None
    assert load_state.complete_history is True
    assert load_state.needs_full_history_reconcile is False
    assert load_state.rows_discovered >= 1


def _visible_dir_names(rows: Iterable[VisibleAgentRow]) -> set[str]:
    return {Path(row.artifact_dir).name for row in rows}


@pytest.mark.parametrize("unified_query", _DIALECTS)
def test_production_machine_query_oracle_keeps_conflicting_provenance_row(
    tmp_path: Path, unified_query: bool
) -> None:
    """Conflicting source/owner machines stay visible to live ``machine:apollo``.

    Legacy matching does not read ``imported_source_owner.machine_name``, so
    the bounded legacy path may still exclude the row after exact filtering.
    Full history is re-filtered through the live engine in this oracle.
    """
    fixture = build_synthetic_agent_archive(tmp_path / "fixture", artifact_count=72)
    conflicting_dir = write_completed_artifact(
        fixture.projects_root,
        fixture.artifact_count + 1,
        source_machine="athena",
        owner_machine="apollo",
    )
    rebuild_index(fixture)

    oracle = AgentLoadTieringOracle(fixture)
    with override_flags(agents_unified_query=unified_query):
        result = oracle.evaluate("machine:apollo", requested_limit=400)

    assert conflicting_dir.name in _visible_dir_names(
        result.source_scan.visible_rows.values()
    )
    full_missing = _visible_dir_names(
        result.diff_for("production_full_history").missing
    )
    assert conflicting_dir.name not in full_missing
    assert result.diff_for("production_full_history").ok

    bounded_missing = _visible_dir_names(result.diff_for("production_bounded").missing)
    if unified_query:
        assert result.pushdown_window_safe is True
        assert conflicting_dir.name not in bounded_missing
        assert result.diff_for("production_bounded").ok
    else:
        assert conflicting_dir.name in bounded_missing


@pytest.mark.parametrize("query", ("machine:apollo", "not machine:apollo"))
def test_production_machine_query_oracle_keeps_mixed_provenance_tree(
    tmp_path: Path, query: str
) -> None:
    """Workflow children do not inherit a container's machine values."""
    fixture = build_synthetic_agent_archive(tmp_path / "fixture", artifact_count=72)
    parent_dir = write_completed_artifact(
        fixture.projects_root,
        fixture.artifact_count + 1,
        source_machine="athena",
        agent_family="mixed-crew",
        agent_family_role="plan",
    )
    child_dir = write_completed_artifact(
        fixture.projects_root,
        fixture.artifact_count + 2,
        source_machine="athena",
        owner_machine="apollo",
        agent_family="mixed-crew",
        agent_family_role="code",
        parent_timestamp=parent_dir.name,
    )
    rebuild_index(fixture)

    oracle = AgentLoadTieringOracle(fixture)
    with override_flags(agents_unified_query=True):
        result = oracle.evaluate(query, requested_limit=400)

    assert result.pushdown_window_safe is True
    source_dirs = _visible_dir_names(result.source_scan.visible_rows.values())
    assert parent_dir.name in source_dirs
    assert child_dir.name in source_dirs
    for name in ("production_bounded", "production_full_history"):
        diff = result.diff_for(name)
        missing_dirs = _visible_dir_names(diff.missing)
        assert parent_dir.name not in missing_dirs, name
        assert child_dir.name not in missing_dirs, name
        assert diff.ok, (name, query)


def test_production_machine_query_oracle_repairs_owner_after_index(
    tmp_path: Path,
) -> None:
    """Revalidate projects a newly added owner machine without a rebuild."""
    fixture = build_synthetic_agent_archive(tmp_path / "fixture", artifact_count=72)
    target_dir = write_completed_artifact(
        fixture.projects_root,
        fixture.artifact_count + 1,
        source_machine="athena",
    )
    rebuild_index(fixture)
    set_artifact_machine_provenance(
        target_dir, source_machine="athena", owner_machine="apollo"
    )

    oracle = AgentLoadTieringOracle(fixture)
    with override_flags(agents_unified_query=True):
        result = oracle.evaluate("machine:apollo", requested_limit=None)

    assert target_dir.name in _visible_dir_names(
        result.source_scan.visible_rows.values()
    )
    diff = result.diff_for("production_full_history")
    assert target_dir.name not in _visible_dir_names(diff.missing)
    assert diff.ok


def test_production_machine_query_oracle_uses_meta_over_done_source(
    tmp_path: Path,
) -> None:
    """Done-marker source_machine does not override a present meta value."""
    fixture = build_synthetic_agent_archive(tmp_path / "fixture", artifact_count=72)
    target_dir = write_completed_artifact(
        fixture.projects_root,
        fixture.artifact_count + 1,
        meta_source_machine="athena",
        done_source_machine="zeus",
        meta_owner_machine="apollo",
        done_owner_machine="hera",
    )
    rebuild_index(fixture)

    oracle = AgentLoadTieringOracle(fixture)
    with override_flags(agents_unified_query=True):
        apollo = oracle.evaluate("machine:apollo", requested_limit=400)
        zeus = oracle.evaluate("machine:zeus", requested_limit=400)

    assert target_dir.name in _visible_dir_names(
        apollo.source_scan.visible_rows.values()
    )
    assert target_dir.name not in _visible_dir_names(
        zeus.source_scan.visible_rows.values()
    )
    assert apollo.diff_for("production_full_history").ok
    assert target_dir.name not in _visible_dir_names(
        apollo.diff_for("production_full_history").missing
    )
    assert target_dir.name not in _visible_dir_names(
        zeus.diff_for("production_full_history").visible_extra
    )


def test_production_full_history_oracle_drops_deleted_artifact(
    tmp_path: Path,
) -> None:
    """A deleted artifact is removed from full history instead of served stale.

    Source-directory reconciliation drops indexed rows whose directories
    are gone, so the snapshot does not keep the last ``record_json``.
    """
    fixture = build_synthetic_agent_archive(tmp_path / "fixture", artifact_count=72)
    oracle = AgentLoadTieringOracle(fixture)
    baseline = oracle.evaluate("", requested_limit=400)
    target = next(
        row
        for row in baseline.source_scan.visible_rows.values()
        if row.status == "DONE"
    )

    delete_artifact(Path(target.artifact_dir))
    result = oracle.evaluate("", requested_limit=400)

    assert target.key not in result.source_scan.visible_rows
    diff = result.diff_for("production_full_history")
    assert target.key not in {row.key for row in diff.visible_extra}
    assert diff.ok

    load_state = result.production_full_history.load_state
    assert load_state is not None
    assert load_state.complete_history is True
    assert load_state.rows_removed >= 1


def test_production_full_history_oracle_repairs_hidden_toggle_without_rebuild(
    tmp_path: Path,
) -> None:
    """Revalidate does repair an already-indexed row's mutated scalar field.

    Contrast with the post-build-artifact defect above: revalidate handles
    a mutation to a row the index already knows about, just not a row the
    index has never seen. ``production_bounded`` intentionally stays on
    ``cached`` freshness (production only forces ``revalidate`` for
    full-history loads), so this only asserts on ``production_full_history``.
    """
    fixture = build_synthetic_agent_archive(tmp_path / "fixture", artifact_count=72)
    oracle = AgentLoadTieringOracle(fixture)
    baseline = oracle.evaluate("", requested_limit=400)
    target = next(
        row
        for row in baseline.source_scan.visible_rows.values()
        if row.status == "DONE"
    )

    set_artifact_hidden(Path(target.artifact_dir), True)
    result = oracle.evaluate("", requested_limit=400)

    assert target.key not in result.source_scan.visible_rows
    assert target.key not in result.production_full_history.visible_rows
    assert result.diff_for("production_full_history").ok


def test_production_oracle_settles_full_history_beyond_tier1_cap(
    tmp_path: Path,
) -> None:
    """Tier 1's cap is a legitimate, self-resolving gap, not a defect.

    Distinguishes rows temporarily absent from the bounded tier (expected;
    resolved by a full-history load) from rows that never arrive (the
    post-build-artifact defect covered separately above). The fixture size
    intentionally clears ``_TIER1_RECENT_COMPLETED_LIMIT`` by a small
    margin so this stays in the fast test lane rather than archive scale.
    """
    tier1_cap = loader_artifacts._TIER1_RECENT_COMPLETED_LIMIT
    fixture = build_synthetic_agent_archive(
        tmp_path / "fixture", artifact_count=tier1_cap + 120
    )
    oracle = AgentLoadTieringOracle(fixture)
    result = oracle.evaluate("", requested_limit=None)

    bounded_diff = result.diff_for("production_bounded")
    assert bounded_diff.missing, "Tier 1 should legitimately exclude rows past its cap"
    bounded_state = result.production_bounded.load_state
    assert bounded_state is not None
    assert bounded_state.complete_history is False

    full_diff = result.diff_for("production_full_history")
    assert full_diff.ok, "full history must settle rows Tier 1 legitimately excludes"
    full_state = result.production_full_history.load_state
    assert full_state is not None
    assert full_state.complete_history is True


def test_cached_full_history_after_production_reconcile_skips_marker_work(
    tmp_path: Path,
) -> None:
    """After discovery settles, a cached full-history read is complete and cheap."""
    from sase.core.agent_scan_facade import query_agent_artifact_index
    from sase.core.agent_scan_wire import AgentArtifactIndexQueryWire

    fixture = build_synthetic_agent_archive(tmp_path / "fixture", artifact_count=72)
    oracle = AgentLoadTieringOracle(fixture)
    first = oracle.evaluate("", requested_limit=None)
    first_state = first.production_full_history.load_state
    assert first_state is not None
    assert first_state.complete_history is True
    assert first.diff_for("production_full_history").ok

    cached = query_agent_artifact_index(
        fixture.index_path,
        fixture.projects_root,
        AgentArtifactIndexQueryWire(
            include_active=False,
            include_recent_completed=False,
            include_full_history=True,
            freshness="cached",
            record_shape="list",
        ),
        loader_artifacts._TUI_SCAN_OPTIONS,
    )
    completeness = cached.index_completeness
    assert completeness is not None
    assert completeness.complete_history is True
    assert completeness.source_reconciled is True
    assert cached.stats.marker_signatures_checked == 0
    assert cached.stats.rows_repaired == 0
    assert cached.stats.rows_discovered == 0

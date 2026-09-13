"""Production-path diagnostics for the sase-zu load-tiering oracle.

The tests here route through :func:`load_tiered_agents`, the real TUI entry
point (``production_bounded``/``production_full_history`` on
:class:`AgentLoadTieringOracle`), instead of the harness's own raw
index-facade calls. That means they exercise production's actual freshness
parameters (``revalidate`` forced for full history) and query-pushdown
compilation rather than a harness re-implementation of them.

Some of these tests reproduce confirmed sase-zu landing-audit defects and
are *expected to keep passing*, with the defect itself asserted as present,
until the phases that fix them land:

- ``index-freshness`` (sase-zu.8.2) owns the false-completeness-after-index-
  rebuild and stale-deleted-row defects.
- ``machine-parity`` (sase-zu.8.3) owns the conflicting-provenance defect.

This mirrors the plan's instruction not to leave the default test suite
knowingly red between phases: each diagnostic asserts the *current*
(buggy) behavior so the suite stays green, and the phase that fixes the
underlying bug is expected to flip the assertion to a zero-diff regression.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.models import _agent_loader_artifacts as loader_artifacts
from sase.feature_flags import override_flags

from tests.perf.agent_load_tiering_fixture import (
    build_synthetic_agent_archive,
    delete_artifact,
    rebuild_index,
    set_artifact_hidden,
    write_completed_artifact,
)
from tests.perf.agent_load_tiering_harness import (
    AgentLoadTieringOracle,
    QUERY_BATTERY,
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
def test_production_full_history_oracle_misses_artifact_added_after_index_build(
    tmp_path: Path, unified_query: bool
) -> None:
    """sase-zu audit defect: a post-rebuild artifact is silently dropped.

    Revalidate only repairs rows already present in the SQL index; it does
    not discover artifact directories written after the last rebuild. The
    production full-history path both misses the new row *and* falsely
    reports ``complete_history=True``.
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
    missing_dirs = {Path(row.artifact_dir).name for row in diff.missing}
    assert new_artifact_dir.name in missing_dirs

    load_state = result.production_full_history.load_state
    assert load_state is not None
    assert load_state.complete_history is True
    assert load_state.needs_full_history_reconcile is False


@pytest.mark.parametrize("unified_query", _DIALECTS)
def test_production_machine_query_oracle_misses_conflicting_provenance_row(
    tmp_path: Path, unified_query: bool
) -> None:
    """sase-zu audit defect: conflicting machine provenance under-selects.

    A row scanned with ``source_machine=athena`` but
    ``imported_source_owner.machine_name=apollo`` matches the live
    ``machine:apollo`` query (which checks both fields) but is dropped by
    the indexed candidate, which stores a single scalar.
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

    assert result.pushdown_window_safe is True
    assert conflicting_dir.name in {
        Path(row.artifact_dir).name for row in result.source_scan.visible_rows.values()
    }

    for name in ("production_bounded", "production_full_history"):
        diff = result.diff_for(name)
        missing_dirs = {Path(row.artifact_dir).name for row in diff.missing}
        assert conflicting_dir.name in missing_dirs, name


def test_production_full_history_oracle_serves_stale_deleted_artifact(
    tmp_path: Path,
) -> None:
    """A deleted artifact keeps appearing as a stale full-history row.

    Distinct from the two audit failures above: this is not a *missing*
    row but an *extra* one — the index still serves the last known
    ``record_json`` for a directory removed from disk without a rebuild,
    and still claims ``complete_history=True`` while doing so.
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
    assert target.key in {row.key for row in diff.visible_extra}

    load_state = result.production_full_history.load_state
    assert load_state is not None
    assert load_state.complete_history is True


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
        tmp_path / "fixture", artifact_count=tier1_cap + 20
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

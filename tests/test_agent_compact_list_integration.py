"""End-to-end compact list parity against the real Rust projection.

Builds a synthetic archive, queries it through both the full index path
and the new compact list bindings, constructs rows with the full
snapshot loaders and the new compact constructors, and compares
list/filter/action facts per artifact directory.

Skips when the installed ``sase_core_rs`` predates the compact list
contract. Run with a local core build from a ``sase-core-revision.txt``
pin containing the compact contract (``just rust-install``) for full
coverage; the hand-written parity tests in
``test_agent_compact_row_adapters.py`` cover the constructors without it.

Only ordinary done rows and home running rows are compared: workflow
parent/step rows get compact constructors in the workflow-cutover
phase.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.models._loaders._compact_done_loaders import (
    build_done_agent_from_compact_record,
    is_compact_done_record,
)
from sase.ace.tui.models._loaders._compact_running_loaders import (
    load_running_home_agents_from_compact_snapshot,
)
from sase.ace.tui.models._loaders._done_snapshot_loaders import (
    build_done_agent_from_record,
    is_done_record,
)
from sase.ace.tui.models._loaders._running_loaders import (
    load_running_home_agents_from_snapshot,
)
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactScanOptionsWire,
)
from tests._agent_compact_parity_helpers import _assert_parity, _facts
from tests.perf._agent_load_tiering_fixture_build import (
    build_synthetic_agent_archive,
)


def _require_list_bindings() -> None:
    from sase.core.rust import require_rust_binding

    try:
        require_rust_binding("query_agent_artifact_index_list")
    except (ImportError, AttributeError):
        pytest.skip("sase_core_rs predates the compact list contract")


def _tier_query(full_history: bool = False) -> AgentArtifactIndexQueryWire:
    if full_history:
        return AgentArtifactIndexQueryWire(
            include_active=False,
            include_recent_completed=False,
            include_full_history=True,
            include_hidden=False,
            freshness="cached",
            record_shape="list",
            agents_list_projection=True,
        )
    return AgentArtifactIndexQueryWire(
        include_active=True,
        include_recent_completed=True,
        include_hidden=False,
        freshness="cached",
        record_shape="list",
        window_limit=50,
        agents_list_projection=True,
    )


def test_compact_list_end_to_end_parity(tmp_path: Path) -> None:
    _require_list_bindings()
    from sase.core.agent_scan_facade import (
        query_agent_artifact_index,
        query_agent_artifact_index_list,
    )

    fixture = build_synthetic_agent_archive(tmp_path / "fixture", artifact_count=24)

    full_snapshot = query_agent_artifact_index(
        fixture.index_path,
        fixture.projects_root,
        _tier_query(),
        AgentArtifactScanOptionsWire(),
    )
    compact_snapshot = query_agent_artifact_index_list(
        fixture.index_path,
        fixture.projects_root,
        _tier_query(),
        AgentArtifactScanOptionsWire(),
    )

    # The compact response reuses the selection pipeline: same order, same
    # clan context and completeness, compact shape throughout.
    assert [r.artifact_dir for r in compact_snapshot.records] == [
        r.artifact_dir for r in full_snapshot.records
    ]
    assert all(r.record_shape == "compact" for r in compact_snapshot.records)
    assert compact_snapshot.clan_context == full_snapshot.clan_context
    assert compact_snapshot.index_completeness == full_snapshot.index_completeness

    full_by_dir = {r.artifact_dir: r for r in full_snapshot.records}
    compared = 0
    for compact_record in compact_snapshot.records:
        if not is_compact_done_record(compact_record):
            continue
        full_record = full_by_dir[compact_record.artifact_dir]
        assert is_done_record(full_record)
        full = build_done_agent_from_record(full_record, {}, {})
        compact = build_done_agent_from_compact_record(compact_record, {}, {})
        if full is None:
            # No-op outcomes build nothing on either path.
            assert compact is None
            continue
        assert compact is not None
        facts_full, facts_compact = _facts(full), _facts(compact)
        # Deferred detail may differ per row; everything else must match.
        for attr in ("response_path", "error_traceback", "monitor_command"):
            facts_full.pop(attr, None)
            facts_compact.pop(attr, None)
        facts_full.pop("extra_files", None)
        facts_compact.pop("extra_files", None)
        assert facts_full == facts_compact
        compared += 1
    assert compared > 0

    full_running = load_running_home_agents_from_snapshot(full_snapshot)
    compact_running = load_running_home_agents_from_compact_snapshot(compact_snapshot)
    assert len(full_running) == len(compact_running)
    for full_agent, compact_agent in zip(full_running, compact_running, strict=True):
        _assert_parity(full_agent, compact_agent)

"""Tests for the deep doctor check reporting leftover imported local state."""

from __future__ import annotations

from pathlib import Path

from sase.agents_sync.purge_local_state import PurgeLocalStateOutcome
from sase.core.agent_types import AgentType
from sase.doctor.checks_deep_purge_local_state import check_local_import_state


def test_ok_when_no_imported_state_remains(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_deep_purge_local_state.purge_local_import_state",
        lambda apply=False: PurgeLocalStateOutcome(True),
    )

    check = check_local_import_state()

    assert check.status == "OK"
    assert "no locally materialized" in check.summary
    assert check.next_steps == ()


def test_warns_and_lists_next_steps_when_state_remains(monkeypatch) -> None:
    outcome = PurgeLocalStateOutcome(
        True,
        artifact_dirs=(Path("/tmp/proj/artifacts/ace-run/20260601120000"),),
        bundle_files=(Path("/tmp/state/dismissed_bundles/202606/20260601120000.json"),),
        dismissed_identities=((AgentType.RUNNING, "proj", "20260601120000"),),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_deep_purge_local_state.purge_local_import_state",
        lambda apply=False: outcome,
    )

    check = check_local_import_state()

    assert check.status == "WARN"
    assert "artifacts=1" in check.summary
    assert "bundles=1" in check.summary
    assert check.data["artifacts"] == 1
    assert check.data["is_empty"] is False
    assert check.next_steps == (
        "Preview with `sase agent names purge-local-state`.",
        "Apply with `sase agent names purge-local-state --apply`.",
    )

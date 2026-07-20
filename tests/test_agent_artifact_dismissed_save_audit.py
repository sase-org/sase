"""Audit dismissed-agent saves that should sync the Tier 1 projection."""

from __future__ import annotations

import pytest

from tests._agent_artifact_marker_audit_helpers import (
    _SCHEDULE_DISMISSED_INDEX,
    _SYNC_DISMISSED_INDEX,
    _dismissed_save_contexts,
)

_REVIEWED_DISMISSED_SAVE_CONTEXTS: dict[str, tuple[str, ...]] = {
    "src/sase/ace/tui/actions/agents/_dismiss_memory.py:_persist_dismissed_agent": (
        _SYNC_DISMISSED_INDEX,
    ),
    "src/sase/ace/tui/actions/agents/_dismissing.py:_persist_bulk_dismiss_transaction": (
        _SYNC_DISMISSED_INDEX,
    ),
    "src/sase/ace/tui/actions/agents/_dismissing.py:_persist_single_dismiss_transaction": (
        _SYNC_DISMISSED_INDEX,
    ),
    "src/sase/ace/tui/actions/agents/_kill_transactions.py:persist_single_kill_transaction": (
        _SYNC_DISMISSED_INDEX,
    ),
    "src/sase/ace/tui/actions/agents/_kill_persistence.py:persist_bulk_kill_side_effects": (
        _SYNC_DISMISSED_INDEX,
    ),
    "src/sase/ace/tui/actions/agents/_loading_apply.py:_apply_loaded_agents_prepared_inner": (
        _SCHEDULE_DISMISSED_INDEX,
    ),
    "src/sase/ace/tui/actions/agents/_loading_disk_support.py:_run_loader_cleanup": (
        _SCHEDULE_DISMISSED_INDEX,
    ),
    "src/sase/ace/tui/actions/agents/_marking.py:_persist_marked_agent_group_save": (
        _SYNC_DISMISSED_INDEX,
    ),
    "src/sase/ace/tui/actions/agents/_revive_execution.py:_do_revive_agent": (
        _SYNC_DISMISSED_INDEX,
    ),
    "src/sase/ace/tui/actions/agents/_revive_execution.py:_do_revive_agents": (
        _SYNC_DISMISSED_INDEX,
    ),
    "src/sase/ace/tui/actions/agents/_revive_archive.py:_repair_dismissed_projection": (
        _SYNC_DISMISSED_INDEX,
    ),
    "src/sase/agent/running.py:_record_dismissal": (_SYNC_DISMISSED_INDEX,),
    "src/sase/axe/run_agent_runner_lifecycle.py:auto_dismiss_completed_agent": (
        _SYNC_DISMISSED_INDEX,
    ),
}


@pytest.fixture(scope="module")
def _dismissed_context_snapshot() -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple(_dismissed_save_contexts().items())


@pytest.fixture
def dismissed_contexts(
    _dismissed_context_snapshot: tuple[tuple[str, tuple[str, ...]], ...],
) -> dict[str, tuple[str, ...]]:
    return dict(_dismissed_context_snapshot)


def test_dismissed_agent_save_sites_are_reviewed(
    dismissed_contexts: dict[str, tuple[str, ...]],
) -> None:
    assert set(dismissed_contexts) == set(_REVIEWED_DISMISSED_SAVE_CONTEXTS)


def test_reviewed_dismissed_agent_save_sites_sync_projection(
    dismissed_contexts: dict[str, tuple[str, ...]],
) -> None:
    for context, expected_lifecycle_calls in _REVIEWED_DISMISSED_SAVE_CONTEXTS.items():
        missing = set(expected_lifecycle_calls) - set(dismissed_contexts[context])
        assert not missing, f"{context} is missing lifecycle calls: {missing}"

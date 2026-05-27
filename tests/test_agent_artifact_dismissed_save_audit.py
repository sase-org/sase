"""Audit dismissed-agent saves that should sync the Tier 1 projection."""

from __future__ import annotations

from tests._agent_artifact_marker_audit_helpers import (
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
    "src/sase/ace/tui/actions/agents/_killing.py:_run_kill_persistence_async": (
        _SYNC_DISMISSED_INDEX,
    ),
    "src/sase/ace/tui/actions/agents/_kill_persistence.py:persist_bulk_kill_side_effects": (
        _SYNC_DISMISSED_INDEX,
    ),
    "src/sase/ace/tui/actions/agents/_loading_apply.py:_apply_loaded_agents_prepared_inner": (
        _SYNC_DISMISSED_INDEX,
    ),
    "src/sase/ace/tui/actions/agents/_marking.py:_persist_marked_agent_group_save": (
        _SYNC_DISMISSED_INDEX,
    ),
    "src/sase/ace/tui/actions/agents/_revive.py:_do_revive_agent": (
        _SYNC_DISMISSED_INDEX,
    ),
    "src/sase/ace/tui/actions/agents/_revive.py:_do_revive_agents": (
        _SYNC_DISMISSED_INDEX,
    ),
    "src/sase/ace/tui/actions/agents/_revive.py:_load_dismissed_archive": (
        _SYNC_DISMISSED_INDEX,
    ),
    "src/sase/agent/running.py:_record_dismissal": (_SYNC_DISMISSED_INDEX,),
    "src/sase/axe/run_agent_runner.py:_auto_dismiss_completed_agent": (
        _SYNC_DISMISSED_INDEX,
    ),
}


def test_dismissed_agent_save_sites_are_reviewed() -> None:
    assert set(_dismissed_save_contexts()) == set(_REVIEWED_DISMISSED_SAVE_CONTEXTS)


def test_reviewed_dismissed_agent_save_sites_sync_projection() -> None:
    contexts = _dismissed_save_contexts()
    for context, expected_lifecycle_calls in _REVIEWED_DISMISSED_SAVE_CONTEXTS.items():
        missing = set(expected_lifecycle_calls) - set(contexts[context])
        assert not missing, f"{context} is missing lifecycle calls: {missing}"

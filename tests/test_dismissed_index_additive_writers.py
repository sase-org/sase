"""Every dismissed-index writer merges its own identities and loses no one else's.

Persist-cleanup procs, runner lifecycles, and TUIs all write
``dismissed_agents.json`` concurrently. These tests run the real writers against
a real index file so a full-snapshot overwrite (the lost-update bug) fails them.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.dismissed_agents import (
    add_dismissed_agents,
    load_dismissed_agents,
    remove_dismissed_agents,
)
from sase.ace.tui.actions.cleanup_payload import json_identities
from sase.axe.run_agent_runner_lifecycle import auto_dismiss_completed_agent
from sase.core.agent_types import AgentType
from sase.ops.commands._agent_cleanup import apply_cleanup_payload_for_result

_SYNC = "sase.core.agent_artifact_index_lifecycle.sync_dismissed_agent_artifact_index"

_FIRST = (AgentType.RUNNING, "feature_one", "20260601010101")
_SECOND = (AgentType.RUNNING, "feature_two", "20260601020202")
_THIRD = (AgentType.WORKFLOW, "feature_three", "20260601030303")


@pytest.fixture
def dismissed_file(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "dismissed_agents.json"
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", path):
        yield path


def _cleanup_payload(*identities: Any) -> dict[str, Any]:
    return {
        "action": "dismiss",
        "added_identities": json_identities(identities),
    }


@pytest.mark.usefixtures("dismissed_file")
@pytest.mark.parametrize("reverse", [False, True])
def test_two_cleanup_payloads_leave_the_union_in_either_order(reverse: bool) -> None:
    """Two procs, each carrying only its own batch, never erase each other."""
    payloads = [_cleanup_payload(_FIRST), _cleanup_payload(_SECOND, _THIRD)]
    if reverse:
        payloads.reverse()

    with patch(_SYNC):
        for payload in payloads:
            success, message, _ = apply_cleanup_payload_for_result(payload)
            assert success, message

    assert load_dismissed_agents() == {_FIRST, _SECOND, _THIRD}


@pytest.mark.usefixtures("dismissed_file")
def test_legacy_snapshot_payload_is_only_ever_added() -> None:
    """A payload from an older TUI (full snapshot) merges instead of overwriting."""
    add_dismissed_agents({_THIRD})
    payload = {
        "action": "dismiss",
        "dismissed_identities": json_identities([_FIRST, _SECOND]),
    }

    with patch(_SYNC):
        success, message, _ = apply_cleanup_payload_for_result(payload)

    assert success, message
    assert load_dismissed_agents() == {_FIRST, _SECOND, _THIRD}


@pytest.mark.usefixtures("dismissed_file")
def test_index_sync_receives_the_set_that_is_on_disk() -> None:
    """The artifact index syncs what the merge left on disk, not one batch."""
    add_dismissed_agents({_THIRD})

    with patch(_SYNC) as sync_index:
        success, message, _ = apply_cleanup_payload_for_result(_cleanup_payload(_FIRST))

    assert success, message
    sync_index.assert_called_once_with({_FIRST, _THIRD})


@pytest.mark.usefixtures("dismissed_file")
def test_runner_lifecycle_write_racing_a_tui_dismissal_loses_neither() -> None:
    """A runner's auto-dismiss and the TUI's dismissals interleave safely."""
    tui_identities = {
        (AgentType.RUNNING, f"tui_{i}", f"2026060201{i:04d}") for i in range(40)
    }
    runner_identities = {
        identity
        for i in range(40)
        for identity in (
            (AgentType.RUNNING, f"runner_{i}", f"2026060301{i:04d}"),
            (AgentType.WORKFLOW, f"runner_{i}", f"2026060301{i:04d}"),
        )
    }
    errors: list[BaseException] = []

    def _tui() -> None:
        try:
            for identity in tui_identities:
                add_dismissed_agents({identity})
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assert
            errors.append(exc)

    def _runner() -> None:
        try:
            for i in range(40):
                auto_dismiss_completed_agent(f"runner_{i}", f"2026060301{i:04d}")
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assert
            errors.append(exc)

    with patch(
        "sase.axe.run_agent_runner_lifecycle.sync_dismissed_agent_artifact_index"
    ):
        threads = [threading.Thread(target=_tui), threading.Thread(target=_runner)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert errors == []
    assert load_dismissed_agents() == tui_identities | runner_identities


@pytest.mark.usefixtures("dismissed_file")
def test_revive_removes_only_its_own_identities() -> None:
    """Revive drops its identities; a dismissal another writer added survives."""
    from sase.ace.tui.actions.agents._revive_state import AgentReviveStateMixin

    revived_alias = (AgentType.WORKFLOW, "alias", _FIRST[2])
    add_dismissed_agents({_FIRST, revived_alias, _SECOND})
    # A runner dismisses another agent after this TUI last loaded the index.
    add_dismissed_agents({_THIRD})

    mixin = AgentReviveStateMixin()
    remaining = mixin._persist_revived_dismissals({_FIRST}, {_FIRST[2]})

    # The alias sharing the revived suffix goes too, even though the revive
    # only named ``_FIRST``; nothing else moves.
    assert remaining == {_SECOND, _THIRD}
    assert load_dismissed_agents() == {_SECOND, _THIRD}


@pytest.mark.usefixtures("dismissed_file")
def test_revive_reports_none_when_the_index_cannot_be_written() -> None:
    from sase.ace.tui.actions.agents._revive_state import AgentReviveStateMixin

    with patch(
        "sase.ace.dismissed_agents.remove_dismissed_agents",
        side_effect=OSError("disk full"),
    ):
        assert (
            AgentReviveStateMixin()._persist_revived_dismissals({_FIRST}, set()) is None
        )


@pytest.mark.usefixtures("dismissed_file")
def test_loader_cleanup_orphan_removal_keeps_concurrent_additions() -> None:
    """Removing orphans must not drop identities added since the last load."""
    add_dismissed_agents({_FIRST, _SECOND})
    add_dismissed_agents({_THIRD})

    assert remove_dismissed_agents({_FIRST}) == {_SECOND, _THIRD}
    assert load_dismissed_agents() == {_SECOND, _THIRD}

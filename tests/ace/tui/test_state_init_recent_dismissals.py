"""Startup recent-dismissal cache initialization for the ACE TUI.

Locks the cold-start contract from
``sdd/plans/202606/recent_restore_perf_fix.md``: ``__init__`` must not read the
recent dismissed-group store from disk; the revive modal repopulates it lazily.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from sase.ace.tui.app import AceApp


def test_startup_leaves_recent_dismissed_cache_empty(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Cold start must not read the recent dismissed-group store from disk."""
    sase_dir = tmp_path / ".sase"
    sase_dir.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))

    with (
        patch(
            "sase.ace.dismissed_agents.list_recent_dismissed_agent_groups"
        ) as mock_list,
        patch(
            "sase.ace.dismissed_agents.load_recent_dismissed_agent_group"
        ) as mock_load,
    ):
        app = AceApp(auto_start_axe=False)

    assert app._recent_dismissed_agent_groups == []
    mock_list.assert_not_called()
    mock_load.assert_not_called()

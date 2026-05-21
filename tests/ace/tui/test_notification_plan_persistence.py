"""Tests for plan approval metadata persistence."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.ace.tui.actions.agents._notification_plan_persistence import (
    persist_plan_approved,
)


def test_persist_plan_approved_refreshes_artifact_index(tmp_path: Path) -> None:
    meta_path = tmp_path / "agent_meta.json"
    meta_path.write_text(json.dumps({"name": "planner"}), encoding="utf-8")
    agent = SimpleNamespace(artifacts_dir=str(tmp_path))

    with patch(
        "sase.ace.tui.actions.agents._notification_plan_persistence."
        "update_agent_artifact_index_for_marker_mutation"
    ) as update_index:
        persist_plan_approved(agent, action="epic")

    assert json.loads(meta_path.read_text(encoding="utf-8")) == {
        "name": "planner",
        "plan_approved": True,
        "plan_action": "epic",
    }
    update_index.assert_called_once_with(str(tmp_path))

"""Tests for Agents-tab wait application bead-condition handling."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.modals import WaitModalResult
from tests.ace.tui._agent_wait_resume_helpers import (
    FakeWaitResumeApp,
    make_waiting_agent,
)


def test_apply_wait_preserves_bead_conditions(tmp_path: Path) -> None:
    (tmp_path / "raw_xprompt.md").write_text(
        "%wait(old, bead=sase-87.2)\nDo work",
        encoding="utf-8",
    )
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"wait_for": ["old"], "wait_for_beads": ["sase-87.2"]}),
        encoding="utf-8",
    )
    (tmp_path / "waiting.json").write_text(
        json.dumps({"waiting_for": ["old"], "wait_for_beads": ["sase-87.2"]}),
        encoding="utf-8",
    )
    agent = make_waiting_agent(
        artifacts_dir=str(tmp_path),
        waiting_for=["old"],
        waiting_for_beads=["sase-87.2"],
        wait_duration=None,
        wait_until=None,
    )
    app = FakeWaitResumeApp()

    with patch(
        "sase.ace.tui.actions.agents._directive_persistence."
        "update_agent_artifact_index_for_marker_mutation"
    ):
        app._apply_wait(
            str(tmp_path),
            agent,
            WaitModalResult(
                agents=["new"],
                time_token=None,
                beads=["sase-87.2"],
            ),
        )

    assert (tmp_path / "raw_xprompt.md").read_text(encoding="utf-8") == (
        "%wait(new)\n%wait(bead=sase-87.2)\nDo work"
    )
    assert json.loads((tmp_path / "agent_meta.json").read_text()) == {
        "wait_for": ["new"],
        "wait_for_beads": ["sase-87.2"],
    }
    assert json.loads((tmp_path / "waiting.json").read_text()) == {
        "waiting_for": ["new"],
        "wait_for_beads": ["sase-87.2"],
    }
    assert agent.waiting_for_beads == ["sase-87.2"]


def test_apply_wait_bead_only_edit_writes_wait_for_beads_to_meta_and_waiting(
    tmp_path: Path,
) -> None:
    (tmp_path / "raw_xprompt.md").write_text("Do work", encoding="utf-8")
    agent = make_waiting_agent(
        artifacts_dir=str(tmp_path),
        waiting_for=[],
        waiting_for_beads=[],
        wait_duration=None,
        wait_until=None,
    )
    app = FakeWaitResumeApp()

    with patch(
        "sase.ace.tui.actions.agents._directive_persistence."
        "update_agent_artifact_index_for_marker_mutation"
    ):
        app._apply_wait(
            str(tmp_path),
            agent,
            WaitModalResult(agents=[], time_token=None, beads=["sase-1"]),
        )

    meta = json.loads((tmp_path / "agent_meta.json").read_text())
    assert meta["wait_for_beads"] == ["sase-1"]
    waiting = json.loads((tmp_path / "waiting.json").read_text())
    assert waiting["wait_for_beads"] == ["sase-1"]
    assert agent.waiting_for_beads == ["sase-1"]
    assert agent.waiting_for == []


def test_apply_wait_clearing_beads_keeps_agent_dep_removes_key_from_both(
    tmp_path: Path,
) -> None:
    (tmp_path / "raw_xprompt.md").write_text(
        "%wait(old, bead=sase-1)\nDo work", encoding="utf-8"
    )
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"wait_for": ["old"], "wait_for_beads": ["sase-1"]}),
        encoding="utf-8",
    )
    (tmp_path / "waiting.json").write_text(
        json.dumps({"waiting_for": ["old"], "wait_for_beads": ["sase-1"]}),
        encoding="utf-8",
    )
    agent = make_waiting_agent(
        artifacts_dir=str(tmp_path),
        waiting_for=["old"],
        waiting_for_beads=["sase-1"],
        wait_duration=None,
        wait_until=None,
    )
    app = FakeWaitResumeApp()

    with patch(
        "sase.ace.tui.actions.agents._directive_persistence."
        "update_agent_artifact_index_for_marker_mutation"
    ):
        app._apply_wait(
            str(tmp_path),
            agent,
            WaitModalResult(agents=["old"], time_token=None, beads=[]),
        )

    meta = json.loads((tmp_path / "agent_meta.json").read_text())
    assert "wait_for_beads" not in meta
    assert meta["wait_for"] == ["old"]

    waiting = json.loads((tmp_path / "waiting.json").read_text())
    assert "wait_for_beads" not in waiting
    assert waiting["waiting_for"] == ["old"]

    assert agent.waiting_for_beads == []
    assert agent.waiting_for == ["old"]

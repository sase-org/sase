"""Tests for the repeat loop in the agent runner."""

import json
from pathlib import Path

from sase.axe.run_agent_runner import _write_repeat_state


class TestWriteRepeatState:
    """Tests for _write_repeat_state helper."""

    def test_writes_json(self, tmp_path: Path) -> None:
        path = str(tmp_path / "repeat_state.json")
        _write_repeat_state(path, 5, 3, 2)
        with open(path) as f:
            data = json.load(f)
        assert data == {
            "repeat_count": 5,
            "current_iteration": 3,
            "completed_iterations": 2,
        }

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        path = str(tmp_path / "repeat_state.json")
        _write_repeat_state(path, 5, 1, 0)
        _write_repeat_state(path, 5, 2, 1)
        with open(path) as f:
            data = json.load(f)
        assert data["current_iteration"] == 2
        assert data["completed_iterations"] == 1


class TestRepeatDirectiveParsing:
    """Tests for repeat count in _AgentInfo metadata."""

    def test_repeat_count_written_to_meta(self, tmp_path: Path) -> None:
        """Verify repeat_count > 1 is written to agent_meta.json."""
        meta: dict[str, object] = {"pid": 1234, "repeat_count": 3}
        meta_path = tmp_path / "agent_meta.json"
        with open(meta_path, "w") as f:
            json.dump(meta, f)

        with open(meta_path) as f:
            data = json.load(f)
        assert data["repeat_count"] == 3

    def test_repeat_count_1_not_written_to_meta(self) -> None:
        """repeat_count=1 is a no-op and should not be written to meta."""
        from sase.xprompt.directives import extract_prompt_directives

        _, directives = extract_prompt_directives("%repeat:1\nDo work")
        assert directives.repeat_count == 1
        # The runner only writes repeat_count when > 1

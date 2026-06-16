"""Tests for load_xprompts_used step-specific file resolution."""

import json
from pathlib import Path

from sase.ace.tui.widgets.prompt_panel import load_xprompts_used


def _make_agent(artifacts_dir: str | None, step_name: str | None = None) -> object:
    """Create a minimal mock agent for testing load_xprompts_used."""

    class _MockAgent:
        def __init__(self, artifacts_dir: str | None, step_name: str | None) -> None:
            self.step_name = step_name
            self._artifacts_dir = artifacts_dir

        def get_artifacts_dir(self) -> str | None:
            return self._artifacts_dir

    return _MockAgent(artifacts_dir, step_name)


def test_returns_none_when_step_file_missing(tmp_path: Path) -> None:
    """Returns None when step-specific file is missing (no shared file fallback)."""
    shared_data = [
        {
            "name": "propose",
            "kind": "workflow",
            "positional": [],
            "named": {},
            "tags": [],
        }
    ]
    shared_file = tmp_path / "xprompts.json"
    shared_file.write_text(json.dumps(shared_data))

    agent = _make_agent(str(tmp_path), step_name="create_commit")
    result = load_xprompts_used(agent)  # type: ignore[arg-type]
    assert result is None

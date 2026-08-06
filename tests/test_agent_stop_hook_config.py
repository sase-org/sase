"""Static checks for active repo-local agent hook configuration."""

from __future__ import annotations

from pathlib import Path


import pytest

pytestmark = pytest.mark.contract


def test_repo_local_agent_config_does_not_reference_sase_stop_hooks() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    config_paths = [
        repo_root / ".claude" / "settings.json",
        repo_root / ".gemini" / "settings.json",
        repo_root / ".qwen" / "settings.json",
    ]
    forbidden = ("sase_commit_stop_hook", "sase_sibling_commit_stop_hook")

    for path in config_paths:
        text = path.read_text(encoding="utf-8")
        for hook_name in forbidden:
            assert hook_name not in text, f"{path} still references {hook_name}"

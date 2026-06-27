"""Tests for multi-agent prompt file persistence."""

import os
from pathlib import Path

import pytest

from sase.history.multi_agent_prompt import save_multi_agent_prompt_file

from tests.conftest import redirect_sase_home


def test_save_multi_agent_prompt_file_writes_sharded_markdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    text = "---\nmodel: test\n---\nPlan\n---\nBuild"

    result = save_multi_agent_prompt_file(
        text,
        cl_name="~/org/main",
        timestamp="260627_161500",
    )

    assert result == (
        "~/.sase/multi_prompts/202606/__org_main-multiprompt-260627_161500.md"
    )
    path = Path(os.path.expanduser(result))
    assert path.read_text(encoding="utf-8") == text

"""Phase-6 prompt panel artifact-cache acceptance tests.

The prompt panel re-globs ``*_prompt.md`` and re-reads the prompt + raw
xprompt + response artifacts every time the user selects an agent. With
the ``AgentArtifactCache`` wired through ``get_prompt_content`` and the
``Agent`` artifact accessors, repeated selection of the same agent should
not retouch the filesystem when nothing has changed.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from sase.agent.agent_artifacts_cache import get_global_cache
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import get_prompt_content


class _StubAgent:
    """Minimal Agent surface needed by ``get_prompt_content``."""

    def __init__(self, artifacts_dir: str) -> None:
        self._artifacts_dir = artifacts_dir
        self.is_workflow_child = False
        self.step_name: str | None = None

    def get_artifacts_dir(self) -> str:
        return self._artifacts_dir


def test_repeat_select_does_not_reglob_or_reread(tmp_path: Path) -> None:
    get_global_cache().clear()

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    prompt_file = artifacts_dir / "01_prompt.md"
    prompt_file.write_text("# prompt body\n", encoding="utf-8")

    agent = _StubAgent(str(artifacts_dir))

    real_listdir = os.listdir
    listdir_calls = 0

    def counting_listdir(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal listdir_calls
        listdir_calls += 1
        return real_listdir(*args, **kwargs)

    with patch(
        "sase.agent.agent_artifacts_cache.os.listdir", side_effect=counting_listdir
    ):
        first = get_prompt_content(agent)
        second = get_prompt_content(agent)
        third = get_prompt_content(agent)

    assert first == "# prompt body\n"
    assert first == second == third
    # Each call still computes a directory signature (one listdir per call)
    # but the prompt-file *selection* is cached so we don't re-sort, and
    # crucially the *content* read happens only once.
    assert listdir_calls == 3


def test_repeat_select_caches_content_read(tmp_path: Path) -> None:
    get_global_cache().clear()

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    prompt_file = artifacts_dir / "01_prompt.md"
    prompt_file.write_text("hello", encoding="utf-8")

    agent = _StubAgent(str(artifacts_dir))

    open_count = 0
    real_open = open

    def counting_open(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal open_count
        open_count += 1
        return real_open(*args, **kwargs)

    with patch("builtins.open", side_effect=counting_open):
        get_prompt_content(agent)
        baseline = open_count
        get_prompt_content(agent)
        get_prompt_content(agent)

    # Subsequent calls hit the cached file content; no new file opens for
    # reading the prompt body.
    assert open_count == baseline

"""Canonical submitted text is recorded once per human submission.

Covers phase ``canonical-text``: swarm invocations, single-slot swarms,
``%r:N`` repeats, ``launch_units`` with ``history_text``, and typed
``---`` multi-prompts all record the submitted text exactly once — never
the expanded member or slot texts.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from sase.agent.launch_types import AgentLaunchResult
from sase.agent.launcher import launch_agents_from_cwd


def _history_file(tmp_path: Path) -> Path:
    return tmp_path / "prompt_history.json"


def _load(history_file: Path) -> list:
    from sase.history.prompt_store import load_prompt_history

    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        return load_prompt_history()


def _launch_result(pid: int = 1234) -> AgentLaunchResult:
    return AgentLaunchResult(
        pid=pid,
        workspace_num=7,
        workspace_dir="/workspace/7",
        output_path="/tmp/out.txt",
        project_file="/tmp/projects/proj/proj.sase",
        project_name="proj",
        workflow_name="ace(run)-260101_120000",
        cl_name="proj",
        timestamp="260101_120000",
    )


def _isolated_successful_cwd_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock the spawn machinery so ``launch_agents_from_cwd`` succeeds."""
    from tests._workspace_provider_helpers import patch_no_workspace_metadata

    patch_no_workspace_metadata(monkeypatch)
    monkeypatch.setattr(
        "sase.main.utils.ensure_project_file_and_get_workspace_num",
        lambda create_missing=False: (None, None, None),
    )
    monkeypatch.setattr(
        "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
        lambda count, **kwargs: [f"ts-{index}" for index in range(count)],
    )
    monkeypatch.setattr("sase.agent.names.get_reserved_agent_names", lambda: set())
    execution = SimpleNamespace(results=[_launch_result()])
    monkeypatch.setattr(
        "sase.agent.launch_executor.execute_launch_plan",
        lambda *args, **kwargs: execution,
    )


def _fake_multi_launch(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Stand in for multi-prompt spawn; returns the recorded call kwargs."""
    calls: list[dict[str, Any]] = []

    def _fake(**kwargs: Any) -> list[Any]:
        calls.append(kwargs)
        return [object(), object()]

    monkeypatch.setattr(
        "sase.agent.multi_prompt_launcher.launch_multi_prompt_agents", _fake
    )
    return calls


def test_swarm_invocation_records_exactly_one_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A multi-slot swarm records its trigger, not its members."""
    from tests._macro_swarm_helpers import patch_catalog, xp

    history_file = _history_file(tmp_path)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    _isolated_successful_cwd_launch(monkeypatch)
    _fake_multi_launch(monkeypatch)
    swarm = {
        "crew": xp(
            "crew",
            "first crew task description here\n---\nsecond crew task description here",
        )
    }
    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file),
        patch_catalog(swarm),
    ):
        results = launch_agents_from_cwd("#crew", origin="typed")

    assert len(results) == 2
    (entry,) = _load(history_file)
    assert entry.text == "#crew"
    assert entry.origin == "typed"


def test_single_slot_swarm_records_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A swarm that reduces to one slot records the trigger, not the member."""
    from tests._macro_swarm_helpers import patch_catalog, xp

    history_file = _history_file(tmp_path)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    _isolated_successful_cwd_launch(monkeypatch)
    # A `---` body makes this a swarm; the empty segments drop out, so it
    # reduces to one slot whose member text must not be recorded.
    swarm = {
        "solo": xp(
            "solo",
            "---\nplease summarize these project notes for me now\n---\n",
        )
    }
    with (
        patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file),
        patch_catalog(swarm),
    ):
        results = launch_agents_from_cwd("#solo", origin="typed")

    assert len(results) == 1
    (entry,) = _load(history_file)
    assert entry.text == "#solo"
    assert entry.origin == "typed"


def test_repeat_records_parent_once_and_no_slot_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``%r:3`` records the parent once; generated slots write nothing."""
    history_file = _history_file(tmp_path)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    _isolated_successful_cwd_launch(monkeypatch)
    parent = "please review the project documentation thoroughly now %r:3"
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        results = launch_agents_from_cwd(parent, origin="typed")

    assert len(results) == 3
    (entry,) = _load(history_file)
    assert entry.text == parent
    assert entry.origin == "typed"


def test_history_text_replaces_rewritten_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit history_text wins over the rewritten launch query."""
    history_file = _history_file(tmp_path)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    _isolated_successful_cwd_launch(monkeypatch)
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        launch_agents_from_cwd(
            "remodeled member text launched here instead",
            origin="typed",
            history_text="please handle the original submission text now",
        )

    (entry,) = _load(history_file)
    assert entry.text == "please handle the original submission text now"
    assert entry.origin == "typed"


def test_launch_units_with_history_text_records_only_history_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ACE units plus history_text record one row: no members, no segments."""
    from sase.agent.launch_guard import LaunchUnitInput

    history_file = _history_file(tmp_path)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    _isolated_successful_cwd_launch(monkeypatch)
    _fake_multi_launch(monkeypatch)
    units = (
        LaunchUnitInput(prompt="first expanded member prompt text here"),
        LaunchUnitInput(prompt="second expanded member prompt text here"),
    )
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        launch_agents_from_cwd(
            "joined member text launched here",
            launch_units=units,
            origin="typed",
            history_text="#crew",
        )

    (entry,) = _load(history_file)
    assert entry.text == "#crew"
    assert entry.origin == "typed"


def test_typed_multi_prompt_records_whole_plus_segments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A user-authored ``---`` multi-prompt keeps whole-plus-segment rows."""
    history_file = _history_file(tmp_path)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    _isolated_successful_cwd_launch(monkeypatch)
    _fake_multi_launch(monkeypatch)
    text = (
        "first segment text is long enough here\n---\n"
        "second segment text is long enough here"
    )
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        launch_agents_from_cwd(text, origin="typed")

    by_text = {entry.text: entry for entry in _load(history_file)}
    assert set(by_text) == {
        text,
        "first segment text is long enough here",
        "second segment text is long enough here",
    }
    assert {entry.origin for entry in by_text.values()} == {"typed"}


def test_plain_single_launch_records_query_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without history_text (mobile and plain launches) the query records."""
    history_file = _history_file(tmp_path)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    _isolated_successful_cwd_launch(monkeypatch)
    with patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", history_file):
        launch_agents_from_cwd(
            "please summarize these project notes for me now", origin="typed"
        )

    (entry,) = _load(history_file)
    assert entry.text == "please summarize these project notes for me now"
    assert entry.origin == "typed"

"""Refreshed-pass prompt reconcile and macro-boundary replay tests."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from sase.axe.run_agent_runner_refresh import (
    RUNNER_CODE_REFRESHED_ENV,
    refresh_runner_code_after_wait,
)

if TYPE_CHECKING:
    from sase.axe.run_agent_runner_state import RunnerRunState


def _refreshed_bootstrap_state(tmp_path: Path, prompt_text: str) -> RunnerRunState:
    """Build a refreshed-pass state whose prompt file holds *prompt_text*."""
    from sase.axe.run_agent_runner_state import RunnerRunState

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text(prompt_text, encoding="utf-8")
    return RunnerRunState(
        cl_name="refresh-reconcile",
        project_file="/tmp/projects/sase/sase.sase",
        prompt_file=str(prompt_file),
        output_path=str(tmp_path / "output.log"),
        workflow_name="ace(run)-260701_010202",
        timestamp="260701_010202",
        update_target="",
        is_home_mode=False,
        workspace_dir=str(tmp_path / "workspace"),
        workspace_num=7,
        project_name="sase",
        artifacts_timestamp="20260701_010202",
        artifacts_dir=str(artifacts_dir),
    )


@pytest.mark.parametrize(
    ("live_meta", "stale_prompt", "expected_head"),
    [
        ({"name": "agent-x"}, "%auto\nDo the thing", None),
        ({"name": "agent-x"}, "%auto:plan\nDo the thing", None),
        ({"autonomy": {"selection": ""}}, "Do the thing", "%auto"),
        (
            {"autonomy": {"selection": "plan"}},
            "%auto\nDo the thing",
            "%auto:plan",
        ),
    ],
    ids=("toggle-off", "toggle-off-plan-spelling", "toggle-on", "auto-plan"),
)
def test_refreshed_pass_reconcile_keeps_wait_time_auto_toggle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    live_meta: dict[str, object],
    stale_prompt: str,
    expected_head: str | None,
) -> None:
    """An ``A`` toggle made during the wait survives the re-exec.

    The pre-exec path persists the prompt verbatim (it may not import), so
    the refreshed process must apply the live ``%auto`` reconcile before
    directive extraction; otherwise a toggle-off is undone and a toggle-on
    is lost.
    """
    import json

    from sase.axe.run_agent_runner_bootstrap import _load_submitted_prompt

    monkeypatch.setenv(RUNNER_CODE_REFRESHED_ENV, "1")
    state = _refreshed_bootstrap_state(tmp_path, stale_prompt)
    (Path(state.artifacts_dir) / "agent_meta.json").write_text(
        json.dumps(live_meta), encoding="utf-8"
    )

    _load_submitted_prompt(state)

    if expected_head is None:
        assert "%auto" not in state.prompt
    else:
        assert state.prompt.split("\n")[0].startswith(expected_head)
    assert "Do the thing" in state.prompt
    assert state.submitted_prompt == state.prompt


def test_non_refreshed_pass_leaves_prompt_unreconciled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reconcile hook is gated on the refresh marker."""
    from sase.axe.run_agent_runner_bootstrap import _load_submitted_prompt

    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    stale_prompt = "%auto\nDo the thing"
    state = _refreshed_bootstrap_state(tmp_path, stale_prompt)

    _load_submitted_prompt(state)

    assert state.prompt == stale_prompt


def test_refresh_local_macros_boundary_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First extract -> refresh -> second extract keeps local macros."""
    import json

    from sase.agent.multi_prompt_launcher import _serialize_local_macros
    from sase.axe.run_agent_directives import extract_directives_and_write_meta
    from sase.agent.multi_prompt_macros import LOCAL_MACROS_ENV
    from sase.macro.models import Macro
    from tests._agent_names_extract_fixtures import mock_provider

    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    workspace = tmp_path / "workspace"
    artifacts = tmp_path / "artifacts"
    workspace.mkdir()
    artifacts.mkdir()
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    monkeypatch.delenv(LOCAL_MACROS_ENV, raising=False)

    first_path = _serialize_local_macros(
        {"_x": Macro(name="_x", content="expanded body")}
    )
    monkeypatch.setenv(LOCAL_MACROS_ENV, first_path)

    def run_extract(prompt: str) -> object:
        with (
            patch(
                "sase.llm_provider.registry.get_default_provider_name",
                return_value="test",
            ),
            patch(
                "sase.llm_provider.registry.get_provider",
                return_value=mock_provider(),
            ),
            patch(
                "sase.llm_provider.registry.resolve_model_provider",
                return_value=("test", "test-model"),
            ),
            patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        ):
            os.environ.pop("SASE_AGENT_SESSION_ATTACH", None)
            return extract_directives_and_write_meta(
                prompt,
                str(workspace),
                str(artifacts),
            )

    first = run_extract("#_x\nplease")
    assert set(first.local_macros) == {"_x"}
    assert LOCAL_MACROS_ENV not in os.environ

    captured: dict[str, str] = {}

    def capture_exec(*_args: object) -> None:
        captured.update(os.environ)

    prompt_file = tmp_path / "prompt.md"
    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity",
            return_value="b" * 40,
        ),
        patch(
            "sase.axe.run_agent_runner_refresh.os.execv",
            side_effect=capture_exec,
        ),
    ):
        refresh_runner_code_after_wait(
            "a" * 40,
            blocking_wait_occurred=True,
            killed=False,
            prompt_file=str(prompt_file),
            submitted_prompt="#_x\nplease",
            local_macros=first.local_macros,
        )

    assert LOCAL_MACROS_ENV in captured
    with patch.dict(os.environ, captured, clear=False):
        second = run_extract("#_x\nplease")

    assert set(second.local_macros) == {"_x"}
    assert second.local_macros["_x"].content == "expanded body"
    assert json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))

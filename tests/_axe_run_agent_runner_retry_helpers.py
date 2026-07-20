"""Shared helpers for agent runner retry tests."""

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.run_agent_phases import AgentInfo
from sase.llm_provider.retry_config import ProviderRetryConfig


def make_retry_config(
    max_retries: int = 2,
    error_patterns: list[str] | None = None,
    wait_times: list[int] | None = None,
    fallback_model: str | None = None,
) -> ProviderRetryConfig:
    return ProviderRetryConfig(
        max_retries=max_retries,
        error_patterns=error_patterns or ["rate limit"],
        wait_times=wait_times or [1],
        fallback_model=fallback_model,
    )


AGENT_INFO = AgentInfo(
    name="test-agent",
    bead_id=None,
    wait_names=[],
    wait_identity_deps=[],
    wait_beads=[],
    wait_duration=None,
    wait_until=None,
    wait_runners=None,
    wait_priority=None,
    model="test-model",
    llm_provider="test-provider",
    vcs_provider=None,
    hidden=False,
    approve=False,
    plan=False,
    tribe=None,
    meta={"pid": 1},
    local_xprompts={},
)


class WorkflowResult:
    """Minimal stand-in for a workflow result object."""

    def __init__(self, response_text: str = "done") -> None:
        self.response_text = response_text


RUNNER = "sase.axe.run_agent_runner"
SETUP = "sase.axe.run_agent_runner_setup"
FINALIZE = "sase.axe.run_agent_runner_finalize"
EXEC = "sase.axe.run_agent_exec"
RETRY = "sase.axe.run_agent_exec_retry"


def base_patches(artifacts_dir: str) -> dict[str, Any]:
    """Return a dict of common mock targets and their return values."""
    # Shared mocks for names imported into both runner and exec modules.
    was_killed_mock = MagicMock(return_value=False)
    prepare_ws_mock = MagicMock(return_value=True)

    def pass_runner_slot(*_args: Any, claim: Any, **_kwargs: Any) -> str:
        return claim()

    return {
        # Runner module.
        f"{SETUP}.prepare_workspace": prepare_ws_mock,
        f"{RUNNER}.extract_directives_and_write_meta": MagicMock(
            return_value=AGENT_INFO
        ),
        f"{SETUP}.convert_timestamp_to_artifacts_format": MagicMock(
            return_value="20260316_120000"
        ),
        f"{SETUP}.create_artifacts_directory": MagicMock(return_value=artifacts_dir),
        "sase.notifications.senders.append_notification": MagicMock(),
        f"{RUNNER}.format_duration": MagicMock(return_value="1s"),
        f"{FINALIZE}.record_stop_time": MagicMock(),
        f"{RUNNER}.was_killed": was_killed_mock,
        f"{RUNNER}.all_steps_hidden": MagicMock(return_value=True),
        f"{RUNNER}.wait_for_runner_slot": MagicMock(side_effect=pass_runner_slot),
        # Exec module execution loop.
        f"{EXEC}.was_killed": was_killed_mock,
        f"{EXEC}.reset_killed": MagicMock(),
        # Retry module error/retry handler.
        f"{RETRY}.prepare_workspace": prepare_ws_mock,
        f"{RETRY}.was_killed": was_killed_mock,
        f"{EXEC}.save_chat_history": MagicMock(return_value="/tmp/history.md"),
        f"{EXEC}.format_extra_sections": MagicMock(return_value=""),
        f"{EXEC}.extract_step_output_and_diff_path": MagicMock(
            return_value=(None, None)
        ),
        # Chat history, patched at source so shell commands are skipped.
        "sase.history.chat.generate_chat_filename": MagicMock(return_value="test_chat"),
        "sase.history.chat.get_chat_file_path": MagicMock(
            return_value="/tmp/test_chat.md"
        ),
        # xprompt, patched at source.
        "sase.xprompt.resolve_xprompt_aliases": MagicMock(side_effect=lambda x: x),
        "sase.xprompt._parsing.extract_vcs_workflow_tag": MagicMock(return_value=None),
        "sase.xprompt.processor.process_xprompt_references": MagicMock(
            side_effect=lambda x: x
        ),
        "sase.xprompt.models.create_anonymous_workflow": MagicMock(),
    }


def run_main(
    patches: dict[str, Any],
    tmp_path: Path,
    *,
    update_target: str = "",
    workspace_dir: Path | None = None,
    workspace_num: str = "1",
    is_home_mode: bool = False,
    env: dict[str, str] | None = None,
) -> Path:
    """Run main() with the given patches dict. Returns the artifacts dir."""
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("test prompt")
    output_file = tmp_path / "output.txt"
    output_file.write_text("")

    artifacts_dir_mock = patches.get(f"{SETUP}.create_artifacts_directory")
    if artifacts_dir_mock:
        adir = Path(artifacts_dir_mock.return_value)
        adir.mkdir(parents=True, exist_ok=True)

    import sys

    argv = [
        "runner",
        "test-cl",
        str(tmp_path / "project.sase"),
        str(workspace_dir or tmp_path),
        str(output_file),
        workspace_num,
        "test-workflow",
        str(prompt_file),
        "20260316_120000",
        update_target,
        "test-project",
        "test-cl",
        "1" if is_home_mode else "",
    ]

    stack: list[Any] = []
    saved_env = os.environ.copy()
    if env:
        os.environ.update(env)
    with patch.object(sys, "argv", argv):
        for target, value in patches.items():
            p = patch(target, value)
            p.start()
            stack.append(p)
        try:
            from sase.axe.run_agent_runner import main

            with pytest.raises(SystemExit):
                main()
        finally:
            for p in stack:
                p.stop()
            os.environ.clear()
            os.environ.update(saved_env)
    return adir  # type: ignore[possibly-undefined]


def exec_result(artifacts_dir: str) -> SimpleNamespace:
    return SimpleNamespace(
        success=True,
        outcome="completed",
        saved_path=None,
        diff_path=None,
        markdown_pdf_paths=[],
        markdown_source_count=0,
        image_paths=[],
        video_paths=[],
        current_artifacts_dir=artifacts_dir,
        step_output=None,
    )

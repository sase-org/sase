"""Shared harness for forced agent-name-reuse ``,x`` relaunch seam tests.

Split from ``tests.test_force_reuse_launch_seam``. Every helper defined
here carries a public name so the sibling
``test_force_reuse_launch_seam_*`` modules can import it without a
``_``-private cross-module import.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agent_workflow._entry_name_prompts import (
    prepare_kill_and_edit_prompt,
)
from sase.ace.tui.actions.agent_workflow._launch_procs import LaunchProcMixin
from sase.ace.tui.actions.agent_workflow._launch_start import AgentLaunchStartMixin
from sase.ace.tui.actions.agent_workflow._types import PromptContext
from sase.ops.models import DurableOperationRequest
from sase.ops.names import RUN_LAUNCH

__all__ = [
    "SubmitHost",
    "agent_session_kill_and_edit_prompt",
    "authorized_request",
    "clan_kill_and_edit_prompt",
    "home_ctx",
    "run_authorized_launch_query",
    "submit_kill_and_edit",
]


class SubmitHost(AgentLaunchStartMixin, LaunchProcMixin):
    """ACE launch-start harness that stops at the durable-proc boundary."""

    def __init__(self) -> None:
        self._prompt_context: PromptContext | None = home_ctx()
        self.calls: list[dict[str, Any]] = []
        self.notifications: list[tuple[str, str | None]] = []

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def _unmount_prompt_bar_after_submit(self) -> None:
        pass

    def _submit_durable_proc(self, argv: list[str], **kwargs: Any) -> object:
        self.calls.append({"argv": argv, **kwargs})
        return SimpleNamespace(proc_id="p1")


def home_ctx() -> PromptContext:
    return PromptContext(
        project_name="home",
        cl_name=None,
        project_file="/tmp/home.sase",
        workspace_dir="/tmp",
        workspace_num=0,
        workflow_name="ace(run)-seed",
        timestamp="seed",
        history_sort_key="sase-op.2",
        display_name="sase-op.2",
        update_target="",
        is_home_mode=True,
    )


def submit_kill_and_edit(prompt: str) -> dict[str, Any]:
    host = SubmitHost()
    with patch(
        "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
        return_value=["forced-ts"],
    ):
        host._launch_resolved_prompt(prompt)
    assert len(host.calls) == 1
    return host.calls[0]


def clan_kill_and_edit_prompt() -> str:
    return prepare_kill_and_edit_prompt(
        "%id(2, clan=sase-op, bead=sase-op.2)\n#gh:gh_sase-org__sase\nDo work",
        "sase-op.2",
    )


def agent_session_kill_and_edit_prompt() -> str:
    return prepare_kill_and_edit_prompt(
        "Do work",
        "sase-oc.4--plan",
        agent_session_name="sase-oc.4",
        role_suffix="--plan",
        phase_bead_id="sase-oc.4",
    )


def authorized_request(prompt: str) -> DurableOperationRequest:
    return DurableOperationRequest(
        operation=RUN_LAUNCH,
        payload={"prompt": prompt, "workflow": "w", "allow_force_reuse": True},
    )


def run_authorized_launch_query(
    prompt: str,
    monkeypatch: pytest.MonkeyPatch,
    *,
    wipe_side_effect: Exception | None = None,
    expect_launch: bool = True,
) -> tuple[Any, Any, Any, Any, SystemExit]:
    from sase.main.query_handler._launch import launch_query

    monkeypatch.delenv("SASE_AGENT", raising=False)
    request = authorized_request(prompt)
    wipe_kwargs: dict[str, Any] = {}
    if wipe_side_effect is not None:
        wipe_kwargs["side_effect"] = wipe_side_effect
    launch_kwargs: dict[str, Any] = {}
    if expect_launch:
        launch_kwargs["return_value"] = []
    with (
        patch("sase.ops.cli.load_request", return_value=request),
        patch("sase.agent.prompt_inputs.missing_required_input_names", return_value=[]),
        patch(
            "sase.xprompt.unresolved.scan_query_for_unresolved_references",
            return_value=[],
        ),
        patch(
            "sase.agent.launch_validation.wipe_names_for_forced_reuse",
            **wipe_kwargs,
        ) as wipe_names,
        patch(
            "sase.main.query_handler._launch.launch_agents_from_cwd",
            **launch_kwargs,
        ) as mock_launch,
        patch("sase.history.prompt.record_failed_launch_prompt") as record_failed,
        patch("sase.ops.commands.run.emit_run_launch_result") as emit_result,
        pytest.raises(SystemExit) as excinfo,
    ):
        launch_query(prompt)
    return wipe_names, mock_launch, record_failed, emit_result, excinfo.value

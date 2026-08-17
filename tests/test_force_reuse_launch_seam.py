"""End-to-end seam tests for forced agent-name-reuse ``,x`` relaunches.

Commit 0835b38d2 ("feat(ace): migrate Patch and agent producers to durable
argv") changed ``LaunchProcMixin._submit_launch_proc()`` to submit argv-only
``python -m sase run`` through the durable proc supervisor and discard the
in-process worker body that used to rewrite ``%id(!name)`` prompts and wipe
the reserved name before relaunch. These tests pin the fix at the seam that
actually runs in production: the ``RUN_LAUNCH`` request payload ACE submits,
and how the ``sase run`` child (``launch_query()``) consumes it.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agent_workflow._launch_procs import LaunchProcMixin
from sase.ace.tui.actions.agent_workflow._launch_start import AgentLaunchStartMixin
from sase.ace.tui.actions.agent_workflow._types import PromptContext
from sase.agent.force_reuse_bead import SASE_AGENT_FORCE_REUSE_BEAD_ENV
from sase.ops.models import DurableOperationRequest
from sase.ops.names import RUN_LAUNCH


class _SubmitHost(AgentLaunchStartMixin, LaunchProcMixin):
    """ACE launch-start harness that stops at the durable-proc boundary."""

    def __init__(self) -> None:
        self._prompt_context: PromptContext | None = _home_ctx()
        self.calls: list[dict[str, Any]] = []
        self.notifications: list[tuple[str, str | None]] = []
        self._last_custom_agent_selection = None

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def _unmount_prompt_bar_after_submit(self) -> None:
        pass

    def _submit_durable_proc(self, argv: list[str], **kwargs: Any) -> object:
        self.calls.append({"argv": argv, **kwargs})
        return SimpleNamespace(proc_id="p1")


def _home_ctx() -> PromptContext:
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


def _submit_kill_and_edit(prompt: str) -> dict[str, Any]:
    host = _SubmitHost()
    with patch(
        "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
        return_value=["forced-ts"],
    ):
        host._launch_resolved_prompt(prompt)
    assert len(host.calls) == 1
    return host.calls[0]


# --- ACE submission carries the authorization + unrewritten prompt ---------


def test_kill_and_edit_submission_authorizes_forced_reuse_clan_form() -> None:
    """A clan-member ``,x`` relaunch prompt reaches the proc queue verbatim."""
    prompt = "%id(!2, clan=sase-op, bead=sase-op.2)\n#gh:gh_sase-org__sase\nDo work"

    call = _submit_kill_and_edit(prompt)

    assert call["operation"] == RUN_LAUNCH
    assert call["request"]["prompt"] == prompt
    assert call["request"]["allow_force_reuse"] is True


def test_kill_and_edit_submission_authorizes_forced_reuse_family_form() -> None:
    """A family-phase ``,x`` relaunch prompt reaches the proc queue verbatim."""
    prompt = "%id(!plan, family=sase-oc.4, bead=sase-oc.4)\nDo work"

    call = _submit_kill_and_edit(prompt)

    assert call["request"]["prompt"] == prompt
    assert call["request"]["allow_force_reuse"] is True


def test_marked_bulk_kill_and_edit_each_pane_authorizes_its_own_forced_name() -> None:
    """Each pane of a marked/bulk ``,x`` submit gets its own authorized request."""
    host = _SubmitHost()
    panes = [
        "%id(!1, clan=sase-op, bead=sase-op.1)\nFirst",
        "%id(!2, clan=sase-op, bead=sase-op.2)\nSecond",
    ]

    with patch(
        "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
        return_value=["forced-ts"],
    ):
        for pane in panes:
            host._launch_resolved_prompt(pane, keep_bar=True)

    assert len(host.calls) == 2
    for pane, call in zip(panes, host.calls, strict=True):
        assert call["request"]["prompt"] == pane
        assert call["request"]["allow_force_reuse"] is True


# --- The ``sase run`` child consumes the authorization ----------------------


def test_launch_query_consumes_authorized_payload_and_wipes_reserved_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main.query_handler._launch import launch_query

    monkeypatch.delenv("SASE_AGENT", raising=False)
    prompt = "%id(!2, clan=sase-op, bead=sase-op.2)\nDo work"
    request = DurableOperationRequest(
        operation=RUN_LAUNCH,
        payload={"prompt": prompt, "workflow": "w", "allow_force_reuse": True},
    )

    with (
        patch("sase.ops.cli.load_request", return_value=request),
        patch("sase.agent.prompt_inputs.missing_required_input_names", return_value=[]),
        patch(
            "sase.xprompt.unresolved.scan_query_for_unresolved_references",
            return_value=[],
        ),
        patch("sase.agent.launch_validation.wipe_names_for_forced_reuse") as wipe_names,
        patch(
            "sase.main.query_handler._launch.launch_agents_from_cwd",
            return_value=[],
        ) as mock_launch,
        pytest.raises(SystemExit),
    ):
        launch_query(prompt)

    wipe_names.assert_called_once_with(["sase-op.2"])
    mock_launch.assert_called_once()
    args, kwargs = mock_launch.call_args
    assert args[0] == "%id(2, clan=sase-op, bead=sase-op.2)\nDo work"
    segment_envs = kwargs["segment_extra_env"]
    assert segment_envs is not None
    assert segment_envs[0] is not None
    assert segment_envs[0][SASE_AGENT_FORCE_REUSE_BEAD_ENV] == (
        '{"bead_id":"sase-op.2","owner_name":"sase-op.2"}'
    )


def test_launch_query_fanout_contradiction_surfaces_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main.query_handler._launch import launch_query

    monkeypatch.delenv("SASE_AGENT", raising=False)
    prompt = "%id(!2, clan=sase-op)\n%{%m:claude/opus | %m:claude/sonnet}"
    request = DurableOperationRequest(
        operation=RUN_LAUNCH,
        payload={"prompt": prompt, "workflow": "w", "allow_force_reuse": True},
    )

    with (
        patch("sase.ops.cli.load_request", return_value=request),
        patch("sase.agent.prompt_inputs.missing_required_input_names", return_value=[]),
        patch(
            "sase.xprompt.unresolved.scan_query_for_unresolved_references",
            return_value=[],
        ),
        patch("sase.main.query_handler._launch.launch_agents_from_cwd") as mock_launch,
        pytest.raises(SystemExit) as excinfo,
    ):
        launch_query(prompt)

    assert excinfo.value.code == 1
    mock_launch.assert_not_called()


# --- Negative: unauthorized callers keep today's rejection ------------------


def _run_launch_query_unauthorized(
    prompt: str,
    *,
    request: DurableOperationRequest | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.launch_validation import AgentNameReuseConfirmationRequiredError
    from sase.main.query_handler._launch import launch_query

    monkeypatch.delenv("SASE_AGENT", raising=False)
    load_request_patch = (
        patch("sase.ops.cli.load_request", return_value=request)
        if request is not None
        else patch("sase.ops.cli.resolve_request_path", return_value=None)
    )
    with (
        load_request_patch,
        patch("sase.agent.prompt_inputs.missing_required_input_names", return_value=[]),
        patch(
            "sase.xprompt.unresolved.scan_query_for_unresolved_references",
            return_value=[],
        ),
        patch(
            "sase.main.query_handler._launch.launch_agents_from_cwd",
            side_effect=AgentNameReuseConfirmationRequiredError("foo"),
        ) as mock_launch,
        pytest.raises(SystemExit) as excinfo,
    ):
        launch_query(prompt)

    assert excinfo.value.code == 1
    # No authorization means no force-reuse rewrite/wipe: the untouched
    # (still-``!``) prompt reaches the same validation the child always ran.
    mock_launch.assert_called_once_with(prompt, segment_extra_env=None)


def test_plain_sase_run_without_request_sidecar_still_rejects_forced_reuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run_launch_query_unauthorized(
        "%id:!foo\nDo work", request=None, monkeypatch=monkeypatch
    )


def test_sidecar_without_authorization_still_rejects_forced_reuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = DurableOperationRequest(
        operation=RUN_LAUNCH,
        payload={"prompt": "%id:!foo\nDo work", "workflow": "w"},
    )
    _run_launch_query_unauthorized(
        "%id:!foo\nDo work", request=request, monkeypatch=monkeypatch
    )

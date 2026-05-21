"""Tests that ``_run_agent_launch_body`` routes prompts to the right dispatch.

These tests cover the routing decisions made inside the launch body:
plain single-agent launches, multi-model fanout via ``%m(...)``,
``%alt(...)`` alternative fanout, forwarding of inline ``xprompts:``
to the fanout worker, and the post-launch refresh schedule.

The non-blocking event-loop guarantees live in
``test_agent_launch_non_blocking.py``; the VCS-ref resolution paths live
in ``test_agent_launch_vcs.py``.
"""

from __future__ import annotations

import threading
from unittest.mock import patch

from tests.ace.tui._agent_launch_helpers import (
    _LaunchBodyApp,
    _run_launch_body_with_common_patches,
)


def test_run_agent_launch_body_skips_xprompt_processing_for_plain_prompt() -> None:
    app = _LaunchBodyApp()
    body_thread_id = threading.get_ident()

    with patch("sase.xprompt.processor.process_xprompt_references") as process:
        _run_launch_body_with_common_patches(app, "plain single-agent prompt")

    process.assert_not_called()
    assert len(app.launched) == 1
    assert app.launched[0]["prompt"] == "plain single-agent prompt"
    assert app.launched[0]["workspace_num"] == 100
    assert app.launched[0]["workspace_dir"] == "/tmp/ws100"
    assert app.launch_thread_ids == [body_thread_id]
    refresh_calls = [
        (fn, args)
        for fn, args in app.scheduled
        if fn == app._schedule_agents_async_refresh
    ]
    assert len(refresh_calls) == 1


def test_run_agent_launch_body_expands_possible_xprompt_for_model_dispatch() -> None:
    app = _LaunchBodyApp()

    with patch(
        "sase.xprompt.processor.process_xprompt_references",
        return_value="%m(opus,sonnet)\nReview this code",
    ) as process:
        _run_launch_body_with_common_patches(app, "Review this with #swarm")

    process.assert_called_once()
    assert app.launched == []
    multi_model_calls = [
        (fn, args) for fn, args in app.scheduled if fn == app._launch_multi_model_agents
    ]
    assert len(multi_model_calls) == 1


def test_run_agent_launch_body_dispatches_pure_alt_fanout() -> None:
    app = _LaunchBodyApp()

    _run_launch_body_with_common_patches(
        app,
        "%n:ag\n%alt(sec=security pass,perf=performance pass)\nReview",
    )

    assert app.launched == []
    fanout_calls = [
        (fn, args) for fn, args in app.scheduled if fn == app._launch_multi_model_agents
    ]
    assert len(fanout_calls) == 1
    _, args = fanout_calls[0]
    assert args[0] == [
        "%name:ag.sec\nsecurity pass\nReview",
        "%name:ag.perf\nperformance pass\nReview",
    ]
    assert args[4] == "alternatives"
    assert args[5] == {}


def test_run_agent_launch_body_forwards_local_xprompts_to_fanout_worker() -> None:
    app = _LaunchBodyApp()

    _run_launch_body_with_common_patches(
        app,
        "---\n"
        "xprompts:\n"
        '  _flash: "gemini-3-flash-preview"\n'
        "---\n"
        "%n:ag\n"
        "%m(#_flash,sonnet)\n"
        "Review",
    )

    fanout_calls = [
        (fn, args) for fn, args in app.scheduled if fn == app._launch_multi_model_agents
    ]
    assert len(fanout_calls) == 1
    _, args = fanout_calls[0]
    local_xprompts = args[5]
    assert set(local_xprompts) == {"_flash"}
    assert local_xprompts["_flash"].content == "gemini-3-flash-preview"


def test_run_agent_launch_body_multi_agent_xprompt_history_uses_input() -> None:
    app = _LaunchBodyApp()
    expanded_segments = ["Generated plan step", "Generated verify step"]

    with (
        patch(
            "sase.axe.run_agent_phases.resolve_agent_refs_in_prompt",
            side_effect=lambda p: (p, None),
        ),
        patch("sase.workspace_provider.get_ref_patterns", return_value={}),
        patch("sase.workspace_provider.get_workflow_names", return_value=set()),
        patch(
            "sase.agent.multi_agent_xprompt.expand_multi_agent_xprompts",
            return_value=expanded_segments,
        ),
        patch("sase.history.prompt.add_or_update_prompt") as save_history,
        patch(
            "sase.ace.tui.actions.agent_workflow._launch_body."
            "record_prompt_file_references"
        ) as record_file_refs,
    ):
        app._run_agent_launch_body("#!research_swarm")

    save_history.assert_called_once_with(
        "#!research_swarm",
        project_name="test",
        branch_or_workspace="",
        allow_short=True,
    )
    record_file_refs.assert_called_once_with("#!research_swarm")
    assert app.launched == []
    multi_prompt_calls = [
        (fn, args)
        for fn, args in app.scheduled
        if fn == app._launch_multi_prompt_agents
    ]
    assert len(multi_prompt_calls) == 1
    _, args = multi_prompt_calls[0]
    assert args[0].segments == expanded_segments


def test_run_agent_launch_body_direct_single_agent_refreshes_after_success() -> None:
    app = _LaunchBodyApp()

    _run_launch_body_with_common_patches(app, "plain single-agent prompt")

    assert len(app.launched) == 1
    scheduled_fns = [fn for fn, _ in app.scheduled]
    assert scheduled_fns.count(app._schedule_agents_async_refresh) == 1
    assert any(
        callable(fn) and fn != app._schedule_agents_async_refresh
        for fn in scheduled_fns
    )

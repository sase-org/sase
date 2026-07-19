"""Tests that ``_run_agent_launch_body`` routes prompts to the right dispatch.

These tests cover the routing decisions made inside the launch body:
plain single-agent launches, model fanout via ``%{...}``,
``%alt(...)`` alternative fanout, forwarding of inline ``xprompts:``
to the fanout worker, and the post-launch refresh schedule.

The non-blocking event-loop guarantees live in
``test_agent_launch_non_blocking.py``; the VCS-ref resolution paths live
under ``agent_launch_vcs/``.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import patch

from sase.xprompt.models import XPrompt
from tests.ace.tui._agent_launch_helpers import (
    _LaunchBodyApp,
    _run_launch_body_with_common_patches,
)


def test_run_agent_launch_body_skips_xprompt_processing_for_plain_prompt() -> None:
    app = _LaunchBodyApp()
    body_thread_id = threading.get_ident()

    with patch("sase.xprompt.processor.process_xprompt_references") as process:
        outcome = _run_launch_body_with_common_patches(app, "plain single-agent prompt")

    process.assert_not_called()
    assert len(app.launched) == 1
    assert app.launched[0]["prompt"] == "plain single-agent prompt"
    assert app.launched[0]["workspace_num"] == 100
    assert app.launched[0]["workspace_dir"] == "/tmp/ws100"
    assert app.launch_thread_ids == [body_thread_id]
    assert len(outcome.results) == 1
    assert app.refresh_count == 0


def test_run_agent_launch_body_expands_possible_xprompt_for_model_dispatch() -> None:
    app = _LaunchBodyApp()

    with patch(
        "sase.xprompt.processor.process_xprompt_references",
        return_value="%{%model:opus | %model:sonnet}\nReview this code",
    ) as process:
        _run_launch_body_with_common_patches(app, "Review this with #swarm")

    process.assert_called_once()
    assert app.launched == []
    multi_model_calls = [
        (fn, args) for fn, args in app.scheduled if fn == app._launch_multi_model_agents
    ]
    assert len(multi_model_calls) == 1


def test_run_agent_launch_body_xprompt_model_axis_joins_alt_fanout() -> None:
    """An xprompt-injected %model axis joins the raw %( alternatives.

    Regression for the "4 agents, all Opus" bug: a prompt that already
    contains %( directives must still expand its launch-shaping xprompt
    (#m_opus_codex -> %{%model:opus | %model:#codex}) *before* the fan-out shape is
    planned. Otherwise the raw prompt plans a 4-slot alternatives shape that
    omits the injected model dimension, and the child runner expands the
    model directive too late to fan out. With the expansion ordered first,
    the model axis composes with both %( axes into a full Cartesian product:
    2 alts x 2 alts x 2 models = 8 slots, split evenly across the raw model
    branches.
    """
    app = _LaunchBodyApp()
    catalog = {
        "codex": XPrompt(name="codex", content="gpt-5.6-sol"),
        "m_opus_codex": XPrompt(
            name="m_opus_codex",
            content="%{%model:opus | %model:#codex}",
        ),
    }

    with patch("sase.xprompt.processor.get_all_xprompts", return_value=dict(catalog)):
        _run_launch_body_with_common_patches(
            app,
            "#gh:sase Describe this repo %(briefly, in detail). "
            "%(Don't trust the documentation!) #m_opus_codex",
        )

    assert app.launched == []
    fanout_calls = [
        (fn, args) for fn, args in app.scheduled if fn == app._launch_multi_model_agents
    ]
    assert len(fanout_calls) == 1
    _, args = fanout_calls[0]
    assert args[4] == "model"
    fanout_plan = args[7]
    slot_models = [slot.model for slot in fanout_plan.slots]
    assert len(slot_models) == 8
    assert slot_models.count("opus") == 4
    assert slot_models.count("#codex") == 4


def test_run_agent_launch_body_dispatches_pure_alt_fanout() -> None:
    app = _LaunchBodyApp()

    _run_launch_body_with_common_patches(
        app,
        "%i:ag\n%alt(sec=security pass,perf=performance pass)\nReview",
    )

    assert app.launched == []
    fanout_calls = [
        (fn, args) for fn, args in app.scheduled if fn == app._launch_multi_model_agents
    ]
    assert len(fanout_calls) == 1
    _, args = fanout_calls[0]
    assert args[0] == [
        "%i:ag\n%alt(sec=security pass,perf=performance pass)\nReview",
    ]
    assert args[4] == "alternatives"
    assert args[5] == {}
    fanout_plan = args[7]
    assert [slot.prompt for slot in fanout_plan.slots] == [
        "%id:ag.sec\nsecurity pass\nReview",
        "%id:ag.perf\nperformance pass\nReview",
    ]


def test_run_agent_launch_body_forwards_local_xprompts_to_fanout_worker() -> None:
    app = _LaunchBodyApp()

    _run_launch_body_with_common_patches(
        app,
        "---\n"
        "xprompts:\n"
        '  _flash: "gemini-3-flash-preview"\n'
        "---\n"
        "%i:ag\n"
        "%{%model:#_flash | %model:sonnet}\n"
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


def test_run_agent_launch_body_xprompt_swarm_history_uses_input() -> None:
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
            "sase.agent.xprompt_swarm.expand_xprompt_swarms_with_metadata",
            return_value=[
                SimpleNamespace(prompt=segment, template_group=None)
                for segment in expanded_segments
            ],
        ),
        patch("sase.history.prompt.add_or_update_prompt") as save_history,
        patch(
            "sase.ace.tui.actions.agent_workflow._launch_body_impl."
            "record_prompt_file_references"
        ) as record_file_refs,
    ):
        app._run_agent_launch_body("#research_swarm")

    save_history.assert_called_once_with(
        "#research_swarm",
        allow_short=True,
    )
    record_file_refs.assert_called_once_with("#research_swarm")
    assert app.launched == []
    multi_prompt_calls = [
        (fn, args)
        for fn, args in app.scheduled
        if fn == app._launch_multi_prompt_agents
    ]
    assert len(multi_prompt_calls) == 1
    _, args = multi_prompt_calls[0]
    assert args[0].segments == expanded_segments


def test_run_agent_launch_body_direct_single_agent_schedules_delta_after_success() -> (
    None
):
    app = _LaunchBodyApp()

    outcome = _run_launch_body_with_common_patches(app, "plain single-agent prompt")

    assert len(app.launched) == 1
    scheduled_fns = [fn for fn, _ in app.scheduled]
    assert app._schedule_agents_async_refresh not in scheduled_fns
    assert app._handle_launch_results_delta not in scheduled_fns
    assert len(outcome.results) == 1
    app._handle_launch_results_delta(outcome.results)
    assert len(app.delta_artifact_dirs) == 1
    assert app.delta_artifact_dirs[0][0].endswith(
        "/projects/test/artifacts/ace-run/20ts"
    )
    assert app.refresh_count == 0


def test_run_agent_launch_body_carries_unresolved_reference_warning() -> None:
    app = _LaunchBodyApp()

    with (
        patch(
            "sase.xprompt.unresolved.process_xprompt_references",
            side_effect=lambda prompt, **_kwargs: prompt,
        ),
        patch("sase.xprompt.loader.get_all_prompts", return_value={}),
        patch("sase.xprompt.processor.get_all_xprompts", return_value={}),
    ):
        outcome = _run_launch_body_with_common_patches(app, "do #reviewww")

    assert outcome.warning_messages == (
        "Unknown xprompt reference(s): #reviewww - passed through as literal text",
    )


def test_run_agent_launch_body_name_validation_failure_records_failed_history() -> None:
    app = _LaunchBodyApp()

    with (
        patch(
            "sase.agent.launch_validation.validate_launch_name_requests",
            side_effect=RuntimeError("bad launch name"),
        ),
        patch("sase.history.prompt.record_failed_launch_prompt") as record_failed,
    ):
        outcome = _run_launch_body_with_common_patches(app, "bad named prompt")

    record_failed.assert_called_once_with("bad named prompt")
    assert app.launched == []
    assert outcome.message == "bad launch name"
    assert outcome.severity == "error"


def test_run_agent_launch_body_bulk_multi_prompt_rejection_records_failed_history() -> (
    None
):
    app = _LaunchBodyApp()
    app._bulk_changespecs = [SimpleNamespace()]

    with patch("sase.history.prompt.record_failed_launch_prompt") as record_failed:
        outcome = app._run_agent_launch_body("first prompt\n---\nsecond prompt")

    record_failed.assert_called_once_with("first prompt\n---\nsecond prompt")
    assert app.launched == []
    assert outcome.message == "Multi-prompt is not supported with bulk launch"
    assert outcome.severity == "error"


def test_run_agent_launch_body_spawn_failure_records_failed_history() -> None:
    app = _LaunchBodyApp()

    with (
        patch.object(
            app,
            "_launch_background_agent",
            side_effect=RuntimeError("spawn failed"),
        ),
        patch("sase.history.prompt.record_failed_launch_prompt") as record_failed,
    ):
        outcome = _run_launch_body_with_common_patches(app, "plain failed prompt")

    record_failed.assert_called_once_with("plain failed prompt")
    assert outcome.message == "Agent launch failed - see Logs in SASE Admin Center (#)"
    assert outcome.severity == "error"

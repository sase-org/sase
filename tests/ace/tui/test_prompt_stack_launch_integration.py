"""Phase 5 integration tests: the prompt stack drives the real launch paths.

The stack UI deliberately produces text that the existing launch body parses
rather than launching agents itself, so these tests pin that the joined /
single-pane text the widget hands to ``_finish_agent_launch`` flows through
``_run_agent_launch_body`` exactly like a hand-typed prompt:

- A whole-stack (joined ``\\n---\\n``) submit routes to ``_launch_multi_prompt_agents``
  and saves the *combined* prompt to history (the per-segment reusable entries
  are added by ``add_or_update_prompt`` itself).
- A multi-agent xprompt joined into the stack preserves the submitted
  invocation in history, never the generated child prompts.
- A single-pane (``keep_bar``) submit launches only that pane's text, leaving
  the mounted bar's base prompt context intact, and a launch failure records
  only that pane's text — never the panes still in the stack.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from sase.ace.tui.actions.agent_workflow._types import PromptContext

from tests.ace.tui._agent_launch_helpers import _LaunchBodyApp


def _identity_expand(
    segments: list[str], _local: object = None, **_kw: object
) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(prompt=segment, template_group=None) for segment in segments
    ]


# --- whole-stack submit routing + history ----------------------------------


def test_whole_stack_submit_routes_manual_multi_prompt_to_multi_prompt_launch() -> None:
    app = _LaunchBodyApp()
    joined = "first prompt\n---\nsecond prompt"

    with (
        patch(
            "sase.axe.run_agent_phases.resolve_agent_refs_in_prompt",
            side_effect=lambda p: (p, None),
        ),
        patch("sase.workspace_provider.get_ref_patterns", return_value={}),
        patch("sase.workspace_provider.get_workflow_names", return_value=set()),
        patch(
            "sase.agent.multi_agent_xprompt.expand_multi_agent_xprompts_with_metadata",
            side_effect=_identity_expand,
        ),
        patch("sase.history.prompt.add_or_update_prompt") as save_history,
        patch(
            "sase.ace.tui.actions.agent_workflow._launch_body."
            "record_prompt_file_references"
        ) as record_refs,
    ):
        app._run_agent_launch_body(joined)

    # The combined prompt is saved (reusable segment entries are derived inside
    # add_or_update_prompt); no agent is spawned inline.
    save_history.assert_called_once_with(joined, allow_short=True)
    record_refs.assert_called_once_with(joined)
    assert app.launched == []

    multi_calls = [
        (fn, args)
        for fn, args in app.scheduled
        if fn == app._launch_multi_prompt_agents
    ]
    assert len(multi_calls) == 1
    _, args = multi_calls[0]
    assert args[0].segments == ["first prompt", "second prompt"]
    # submitted_xprompt (the 4th positional arg) is the verbatim joined text.
    assert args[3] == joined


def test_whole_stack_submit_with_multi_agent_xprompt_preserves_invocation() -> None:
    app = _LaunchBodyApp()
    # A stack whose first pane is a multi-agent xprompt invocation joined with a
    # plain second pane. The invocation expands into child segments, but history
    # must keep the authored invocation, not the generated children.
    joined = "#research_swarm\n---\nplain follow-up pane"

    def _expand(
        segments: list[str], _local: object = None, **_kw: object
    ) -> list[SimpleNamespace]:
        out: list[SimpleNamespace] = []
        for segment in segments:
            if segment == "#research_swarm":
                out.append(
                    SimpleNamespace(prompt="generated child A", template_group=1)
                )
                out.append(
                    SimpleNamespace(prompt="generated child B", template_group=1)
                )
            else:
                out.append(SimpleNamespace(prompt=segment, template_group=None))
        return out

    with (
        patch(
            "sase.axe.run_agent_phases.resolve_agent_refs_in_prompt",
            side_effect=lambda p: (p, None),
        ),
        patch("sase.workspace_provider.get_ref_patterns", return_value={}),
        patch("sase.workspace_provider.get_workflow_names", return_value=set()),
        patch(
            "sase.agent.multi_agent_xprompt.expand_multi_agent_xprompts_with_metadata",
            side_effect=_expand,
        ),
        patch("sase.history.prompt.add_or_update_prompt") as save_history,
        patch(
            "sase.ace.tui.actions.agent_workflow._launch_body."
            "record_prompt_file_references"
        ),
    ):
        app._run_agent_launch_body(joined)

    save_history.assert_called_once_with(joined, allow_short=True)
    multi_calls = [
        (fn, args)
        for fn, args in app.scheduled
        if fn == app._launch_multi_prompt_agents
    ]
    assert len(multi_calls) == 1
    _, args = multi_calls[0]
    # The expanded child prompts drive the launch...
    assert args[0].segments == [
        "generated child A",
        "generated child B",
        "plain follow-up pane",
    ]
    # ...but the authored invocation is what was preserved as submitted_xprompt.
    assert args[3] == joined


# --- single-pane (keep_bar) submit through the real body -------------------


def _keep_bar_ctx() -> PromptContext:
    return PromptContext(
        project_name="test",
        cl_name="test",
        project_file="/tmp/test.sase",
        workspace_dir="/tmp/ws",
        workspace_num=1,
        workflow_name="ace(run)-pane",
        timestamp="pane-ts",
        history_sort_key="",
        display_name="test",
        update_target="",
        is_home_mode=False,
    )


def test_keep_bar_single_pane_launch_leaves_base_context_intact() -> None:
    app = _LaunchBodyApp()
    base = app._prompt_context

    # keep_bar threads an explicit ctx snapshot; the body must launch the pane
    # without consuming/clearing the mounted bar's base ``_prompt_context``.
    with (
        patch(
            "sase.axe.run_agent_phases.resolve_agent_refs_in_prompt",
            side_effect=lambda p: (p, None),
        ),
        patch("sase.workspace_provider.get_ref_patterns", return_value={}),
        patch("sase.workspace_provider.get_workflow_names", return_value=set()),
        patch("sase.history.prompt.add_or_update_prompt"),
        patch(
            "sase.history.file_references.extract_recordable_file_refs", return_value=[]
        ),
        patch("sase.history.file_references.record_file_references"),
        patch("sase.running_field.get_first_available_axe_workspace", return_value=100),
        patch("sase.running_field.claim_next_axe_workspace", return_value=100),
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=("/tmp/ws100", None),
        ),
    ):
        app._run_agent_launch_body("only this pane", _keep_bar_ctx())

    assert len(app.launched) == 1
    assert app.launched[0]["prompt"] == "only this pane"
    # Base context untouched: keep_bar never clears it.
    assert app._prompt_context is base


def test_keep_bar_single_pane_failure_records_only_that_pane() -> None:
    app = _LaunchBodyApp()
    base = app._prompt_context

    with (
        patch.object(
            app,
            "_launch_background_agent",
            side_effect=RuntimeError("spawn failed"),
        ),
        patch("sase.history.prompt.record_failed_launch_prompt") as record_failed,
        patch(
            "sase.axe.run_agent_phases.resolve_agent_refs_in_prompt",
            side_effect=lambda p: (p, None),
        ),
        patch("sase.workspace_provider.get_ref_patterns", return_value={}),
        patch("sase.workspace_provider.get_workflow_names", return_value=set()),
        patch("sase.history.prompt.add_or_update_prompt"),
        patch(
            "sase.history.file_references.extract_recordable_file_refs",
            return_value=[],
        ),
        patch("sase.history.file_references.record_file_references"),
        patch(
            "sase.running_field.get_first_available_axe_workspace",
            return_value=100,
        ),
        patch("sase.running_field.claim_next_axe_workspace", return_value=100),
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=("/tmp/ws100", None),
        ),
    ):
        outcome = app._run_agent_launch_body("just this pane", _keep_bar_ctx())

    # Only the submitted pane's text is recorded as failed — never the panes
    # still mounted in the stack (which never reach the launch body).
    record_failed.assert_called_once_with("just this pane")
    assert outcome.severity == "error"
    # The base context for the still-mounted stack survives the failure.
    assert app._prompt_context is base


# --- repeated single submissions drain the stack ---------------------------


def test_repeated_single_submissions_launch_each_pane_independently() -> None:
    app = _LaunchBodyApp()
    base = app._prompt_context

    for pane in ("pane one", "pane two", "pane three"):
        _run_launch_body_with_common_patches_keep_bar(app, pane)

    assert [entry["prompt"] for entry in app.launched] == [
        "pane one",
        "pane two",
        "pane three",
    ]
    assert app._prompt_context is base


def _run_launch_body_with_common_patches_keep_bar(
    app: _LaunchBodyApp, pane: str
) -> None:
    with (
        patch(
            "sase.axe.run_agent_phases.resolve_agent_refs_in_prompt",
            side_effect=lambda p: (p, None),
        ),
        patch("sase.workspace_provider.get_ref_patterns", return_value={}),
        patch("sase.workspace_provider.get_workflow_names", return_value=set()),
        patch("sase.history.prompt.add_or_update_prompt"),
        patch(
            "sase.history.file_references.extract_recordable_file_refs", return_value=[]
        ),
        patch("sase.history.file_references.record_file_references"),
        patch("sase.running_field.get_first_available_axe_workspace", return_value=100),
        patch("sase.running_field.claim_next_axe_workspace", return_value=100),
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=("/tmp/ws100", None),
        ),
    ):
        app._run_agent_launch_body(pane, _keep_bar_ctx())

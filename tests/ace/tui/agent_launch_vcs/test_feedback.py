"""VCS launch toast and unresolvable-ref behavior."""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import patch

from tests.ace.tui._agent_launch_helpers import _FakeApp, _LaunchBodyApp, _fake_context


def test_finish_agent_launch_toast_uses_cycled_vcs_ref_not_baked_name() -> None:
    """Defect A: the launch toast names the submitted ref, not the baked ctx.

    When the bar is opened for one ref (``ctx.display_name`` baked from the
    last selection) and ``<ctrl+p>`` cycles to another before submitting, the
    immediate "Launching agent for ..." toast must reflect the cycled-to ref.
    """
    app = _FakeApp()
    app._prompt_context = _fake_context()
    app._prompt_context.display_name = "sase"  # baked from a prior selection

    app._finish_agent_launch("#git:foo do work")

    launching = [m for m, _ in app.notifications if m.startswith("Launching agent")]
    assert launching == ["Launching agent for foo..."]


def test_finish_agent_launch_toast_falls_back_to_display_name_without_tag() -> None:
    """Defect A: a plain prompt (no VCS tag) still labels off the baked name."""
    app = _FakeApp()
    app._prompt_context = _fake_context()
    app._prompt_context.display_name = "sase"

    app._finish_agent_launch("do work without a tag")

    launching = [m for m, _ in app.notifications if m.startswith("Launching agent")]
    assert launching == ["Launching agent for sase..."]


def test_run_agent_launch_body_aborts_unresolvable_home_mode_vcs_tag() -> None:
    """Defect B: a cycled-to VCS tag that resolves to nothing aborts loudly.

    It must NOT fall through to a home-mode launch under the baked identity
    (wrong workspace) nor silently skip the replay/MRU updates.
    """
    app = _LaunchBodyApp()
    ctx = _fake_context()  # is_home_mode=True
    ctx.display_name = "sase"
    ctx.project_name = "sase"
    app._prompt_context = ctx
    previous_selection = object()
    app._last_custom_agent_selection = previous_selection  # type: ignore[assignment]

    # Resolution fails for the cycled ref.
    app._resolve_vcs_from_prompt = (  # type: ignore[method-assign]
        lambda prompt, wf_name, skip_workspace=False: None
    )

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.axe.run_agent_phases.resolve_agent_refs_in_prompt",
                side_effect=lambda p: (p, None),
            )
        )
        stack.enter_context(
            patch("sase.workspace_provider.get_workflow_names", return_value={"git"})
        )
        stack.enter_context(
            patch(
                "sase.agent.launcher.resolve_known_project_vcs_launch_ref",
                return_value=None,
            )
        )
        record_failed = stack.enter_context(
            patch("sase.history.prompt.record_failed_launch_prompt")
        )
        stack.enter_context(
            patch(
                "sase.history.file_references.extract_recordable_file_refs",
                return_value=[],
            )
        )
        stack.enter_context(
            patch("sase.history.file_references.record_file_references")
        )
        save = stack.enter_context(
            patch("sase.ace.last_agent_selection._save_last_agent_selection")
        )
        record_mru = stack.enter_context(
            patch("sase.history.vcs_xprompt_mru.record_vcs_xprompt_usage")
        )

        outcome = app._run_agent_launch_body("#git:stale do work")

    # Nothing launched; context cleared; replay selection + MRU untouched.
    assert app.launched == []
    assert app._prompt_context is None
    assert app._last_custom_agent_selection is previous_selection
    save.assert_not_called()
    record_mru.assert_not_called()

    record_failed.assert_called_once_with("#git:stale do work")

    # The error outcome names the cycled ref, not the baked project.
    assert outcome.message == "Cannot resolve #git:stale; not launching"
    assert outcome.severity == "error"


def test_run_agent_launch_body_records_short_unresolvable_home_mode_vcs_tag() -> None:
    """A single-token unresolved VCS tag is saved as failed cancelled history."""
    app = _LaunchBodyApp()
    ctx = _fake_context()  # is_home_mode=True
    ctx.display_name = "sase"
    ctx.project_name = "sase"
    app._prompt_context = ctx
    app._resolve_vcs_from_prompt = (  # type: ignore[method-assign]
        lambda prompt, wf_name, skip_workspace=False: None
    )

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.axe.run_agent_phases.resolve_agent_refs_in_prompt",
                side_effect=lambda p: (p, None),
            )
        )
        stack.enter_context(
            patch("sase.workspace_provider.get_workflow_names", return_value={"git"})
        )
        stack.enter_context(
            patch(
                "sase.agent.launcher.resolve_known_project_vcs_launch_ref",
                return_value=None,
            )
        )
        record_failed = stack.enter_context(
            patch("sase.history.prompt.record_failed_launch_prompt")
        )

        outcome = app._run_agent_launch_body("#git:stale")

    assert app.launched == []
    record_failed.assert_called_once_with("#git:stale")
    assert outcome.message == "Cannot resolve #git:stale; not launching"
    assert outcome.severity == "error"

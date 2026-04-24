"""Regression tests for ``_try_execute_workflow`` + simple xprompt + VCS ref.

Launching ``#hg:ilar #launch/free:445408805,SS_ILAR_TOGGLE`` from the TUI
used to fail because ``_try_execute_workflow`` eagerly Jinja-rendered the
``launch/free`` simple xprompt using ``parse_workflow_reference``'s
colon-arg parsing, which (unlike ``process_xprompt_references``) does
**not** split on commas.  The second template variable was therefore
never bound, ``StrictUndefined`` raised, and the caller caught it as a
generic "Agent launch failed".

The rendered value was going to be discarded anyway (the simple-xprompt
inline-expansion branch only applies when ``vcs_ref is None``), so the
fix is to skip the render when a VCS ref is present and let
``process_xprompt_references`` handle expansion downstream.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.agent_workflow._workflow_exec import WorkflowExecMixin
from sase.xprompt.models import InputArg, InputType
from sase.xprompt.workflow_models import Workflow, WorkflowStep


class _FakeApp(WorkflowExecMixin):
    def __init__(self) -> None:
        self._prompt_context = None

    def call_later(self, fn: Any, *args: Any, **kwargs: Any) -> None:
        del fn, args, kwargs

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        del msg, severity


def _launch_free_xprompt() -> Workflow:
    """Fake simple xprompt mirroring sase-google's ``launch/free``.

    The template references both ``bug_id`` and ``feature`` — under
    ``StrictUndefined`` this fails to render unless *both* are bound.
    So if the SUT renders it with only one positional arg
    (``"445408805,SS_ILAR_TOGGLE"`` mapped to ``bug_id``), the render
    raises and the test observes that.
    """
    return Workflow(
        name="launch/free",
        inputs=[
            InputArg(name="bug_id", type=InputType.INT),
            InputArg(name="feature", type=InputType.WORD),
        ],
        steps=[
            WorkflowStep(
                name="main",
                prompt_part="bug={{ bug_id }} feature={{ feature }}",
            )
        ],
    )


def test_simple_xprompt_with_vcs_ref_defers_to_downstream_expansion() -> None:
    """When the caller has a VCS ref, don't eagerly render — return False.

    ``process_xprompt_references`` downstream correctly splits
    ``"445408805,SS_ILAR_TOGGLE"`` on the comma; rendering here with the
    parser's single-arg interpretation would crash under
    ``StrictUndefined`` and the result would be discarded anyway.
    """
    app = _FakeApp()
    xprompt = _launch_free_xprompt()

    with patch(
        "sase.xprompt.get_all_prompts",
        return_value={"launch/free": xprompt},
    ):
        result = app._try_execute_workflow(
            "#launch/free:445408805,SS_ILAR_TOGGLE",
            has_vcs_ref=True,
        )

    assert result is False


def test_simple_xprompt_without_vcs_ref_still_renders_inline() -> None:
    """Guard the existing inline-expansion path: no VCS ref → render.

    Use the parenthesis syntax so both inputs get bound — this is the
    path that still returns the rendered string for the caller to use
    as the outgoing prompt.
    """
    app = _FakeApp()
    xprompt = _launch_free_xprompt()

    with patch(
        "sase.xprompt.get_all_prompts",
        return_value={"launch/free": xprompt},
    ):
        result = app._try_execute_workflow(
            "#launch/free(445408805, SS_ILAR_TOGGLE)",
            has_vcs_ref=False,
        )

    assert result == "bug=445408805 feature=SS_ILAR_TOGGLE"

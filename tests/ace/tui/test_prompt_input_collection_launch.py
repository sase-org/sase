"""Launch-wiring tests for prompt frontmatter input collection (sase-4r.5).

Pins the contract that ``_finish_agent_launch`` gates on declared frontmatter
``input:`` arguments: required inputs open the Input Collection Modal (and launch
nothing until the user confirms), optional-only inputs substitute their defaults
without a modal, and a prompt with no declared inputs launches unchanged. The
collected values are rendered into every segment before the launch worker runs.
"""

from __future__ import annotations

from sase.ace.tui.modals.input_collection_modal import InputCollectionModal
from sase.agent.prompt_placeholder_inputs import PromptInputValues

from tests.ace.tui._agent_launch_helpers import _FakeApp

_REQUIRED_PROMPT = "---\ninput:\n  service: word\n---\nRefactor {{ service }}"
_OPTIONAL_PROMPT = "---\ninput:\n  dry_run:\n    type: bool\n    default: false\n---\nrun={{ dry_run }}"


def test_prompt_without_inputs_launches_directly() -> None:
    app = _FakeApp()

    app._finish_agent_launch("plain prompt")

    assert app.pushed_screens == []  # no modal
    assert len(app.launch_tasks) == 1
    app.launch_tasks[0]["task_callable"]()
    assert app.body_calls == ["plain prompt"]


def test_optional_only_prompt_substitutes_defaults_without_modal() -> None:
    app = _FakeApp()

    app._finish_agent_launch(_OPTIONAL_PROMPT)

    assert app.pushed_screens == []  # all defaulted -> no modal
    assert len(app.launch_tasks) == 1
    app.launch_tasks[0]["task_callable"]()
    assert app.body_calls == ["run=False"]


def test_required_input_opens_modal_then_launches_substituted() -> None:
    app = _FakeApp()

    app._finish_agent_launch(_REQUIRED_PROMPT)

    # The modal is shown and nothing launches until the user confirms.
    assert len(app.pushed_screens) == 1
    screen, callback = app.pushed_screens[0]
    assert isinstance(screen, InputCollectionModal)
    assert app.launch_tasks == []

    # Confirming with values renders them into the segment and launches.
    callback(
        PromptInputValues(
            placeholders={},
            declared={"service": "billing"},
        )
    )
    assert len(app.launch_tasks) == 1
    app.launch_tasks[0]["task_callable"]()
    assert app.body_calls == ["Refactor billing"]


def test_required_input_modal_cancel_launches_nothing() -> None:
    app = _FakeApp()

    app._finish_agent_launch(_REQUIRED_PROMPT)
    _screen, callback = app.pushed_screens[0]
    callback(None)  # user cancelled the modal

    assert app.launch_tasks == []
    assert ("Input collection cancelled", None) in app.notifications


def test_invalid_collected_value_does_not_launch() -> None:
    app = _FakeApp()

    prompt = "---\ninput:\n  retries: int\n---\n{{ retries }}"
    app._finish_agent_launch(prompt)
    _screen, callback = app.pushed_screens[0]
    callback(
        PromptInputValues(
            placeholders={},
            declared={"retries": "three"},
        )
    )  # fails int validation in render

    assert app.launch_tasks == []
    assert any(sev == "error" for _msg, sev in app.notifications)

"""Launch-wiring tests for prompt input collection (sase-4r.5, sase-9q.5).

Pins the contract that ``_finish_agent_launch`` gates on everything the prompt
needs collected: raw ``<placeholder>`` tags written in the body plus declared
frontmatter ``input:`` arguments. Either kind opens the Prompt Inputs panel (and
launches nothing until the user confirms), optional-only declared inputs
substitute their defaults without a panel, and a prompt with nothing to collect
launches unchanged. The collected values are substituted into every segment
before the launch worker runs.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

import sase.agent.prompt_placeholder_inputs as plan_module
import sase.history.prompt_placeholders as placeholder_store
from sase.ace.tui.modals.input_collection_modal import InputCollectionModal
from sase.agent.prompt_placeholder_inputs import PromptInputValues

from tests.ace.tui._agent_launch_helpers import _FakeApp

_REQUIRED_PROMPT = "---\ninput:\n  service: word\n---\nRefactor {{ service }}"
_OPTIONAL_PROMPT = "---\ninput:\n  dry_run:\n    type: bool\n    default: false\n---\nrun={{ dry_run }}"


@pytest.fixture(autouse=True)
def recorded_placeholder_texts(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[list[str]]:
    """Capture common-placeholder recording instead of touching ``~/.sase``."""
    recorded: list[str] = []
    monkeypatch.setattr(
        placeholder_store, "record_prompt_placeholders", recorded.append
    )
    yield recorded


def _disable_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn off ``ace.prompt_inputs.collect_raw_placeholders``."""
    monkeypatch.setattr(
        plan_module,
        "load_merged_config",
        lambda: {"ace": {"prompt_inputs": {"collect_raw_placeholders": False}}},
    )


def test_prompt_without_inputs_launches_directly() -> None:
    app = _FakeApp()

    app._finish_agent_launch("plain prompt")

    assert app.pushed_screens == []  # no modal
    assert len(app.launch_tasks) == 1
    app.launch_tasks[0]["proc_callable"]()
    assert app.body_calls == ["plain prompt"]


def test_optional_only_prompt_substitutes_defaults_without_modal() -> None:
    app = _FakeApp()

    app._finish_agent_launch(_OPTIONAL_PROMPT)

    assert app.pushed_screens == []  # all defaulted -> no modal
    assert len(app.launch_tasks) == 1
    app.launch_tasks[0]["proc_callable"]()
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
    app.launch_tasks[0]["proc_callable"]()
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


def test_raw_placeholder_opens_panel_then_launches_substituted(
    recorded_placeholder_texts: list[str],
) -> None:
    app = _FakeApp()

    app._finish_agent_launch("Refactor <the plan> and report back")

    assert len(app.pushed_screens) == 1
    screen, callback = app.pushed_screens[0]
    assert isinstance(screen, InputCollectionModal)
    assert app.launch_tasks == []
    assert recorded_placeholder_texts == []  # nothing learned until confirm

    callback(PromptInputValues(placeholders={"the plan": "sase-9q"}, declared={}))
    assert len(app.launch_tasks) == 1
    app.launch_tasks[0]["proc_callable"]()
    assert app.body_calls == ["Refactor sase-9q and report back"]
    # D7: the tags are learned from the pre-substitution body.
    assert recorded_placeholder_texts == ["Refactor <the plan> and report back"]


def test_raw_placeholder_panel_cancel_leaves_bar_and_launches_nothing(
    recorded_placeholder_texts: list[str],
) -> None:
    app = _FakeApp()

    app._finish_agent_launch("Refactor <the plan>", keep_bar=True)
    _screen, callback = app.pushed_screens[0]
    callback(None)

    assert app.launch_tasks == []
    assert app.unmount_calls == []  # prompt bar stays mounted with the draft
    assert recorded_placeholder_texts == []
    assert ("Input collection cancelled", None) in app.notifications


def test_literal_marked_placeholder_survives_into_the_launched_prompt() -> None:
    app = _FakeApp()

    app._finish_agent_launch("Refactor <the plan> now")
    _screen, callback = app.pushed_screens[0]
    callback(PromptInputValues(placeholders={}, declared={}))

    app.launch_tasks[0]["proc_callable"]()
    assert app.body_calls == ["Refactor <the plan> now"]


def test_backticked_placeholder_only_prompt_launches_immediately() -> None:
    app = _FakeApp()

    app._finish_agent_launch("keep `<div>` literal")

    assert app.pushed_screens == []
    app.launch_tasks[0]["proc_callable"]()
    assert app.body_calls == ["keep `<div>` literal"]


def test_placeholder_and_declared_input_collected_on_one_page() -> None:
    app = _FakeApp()
    prompt = "---\ninput:\n  service: word\n---\nRefactor {{ service }} in <the file>"

    app._finish_agent_launch(prompt)

    screen, callback = app.pushed_screens[0]
    assert isinstance(screen, InputCollectionModal)
    callback(
        PromptInputValues(
            placeholders={"the file": "app.py"},
            declared={"service": "billing"},
        )
    )
    app.launch_tasks[0]["proc_callable"]()
    assert app.body_calls == ["Refactor billing in app.py"]


def test_multi_segment_placeholder_is_collected_once_and_applied_to_both() -> None:
    app = _FakeApp()

    app._finish_agent_launch("fix <target>\n---\ntest <target>")

    screen, callback = app.pushed_screens[0]
    assert isinstance(screen, InputCollectionModal)
    callback(PromptInputValues(placeholders={"target": "parser"}, declared={}))
    app.launch_tasks[0]["proc_callable"]()
    assert app.body_calls == ["fix parser\n---\ntest parser"]


def test_collect_raw_placeholders_disabled_launches_without_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_collection(monkeypatch)
    app = _FakeApp()

    app._finish_agent_launch("Refactor <the plan> and report back")

    assert app.pushed_screens == []
    app.launch_tasks[0]["proc_callable"]()
    assert app.body_calls == ["Refactor <the plan> and report back"]


def test_collect_raw_placeholders_disabled_still_collects_declared_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_collection(monkeypatch)
    app = _FakeApp()

    app._finish_agent_launch(_REQUIRED_PROMPT)

    screen, callback = app.pushed_screens[0]
    assert isinstance(screen, InputCollectionModal)
    assert screen._placeholders == []
    callback(PromptInputValues(placeholders={}, declared={"service": "billing"}))
    app.launch_tasks[0]["proc_callable"]()
    assert app.body_calls == ["Refactor billing"]

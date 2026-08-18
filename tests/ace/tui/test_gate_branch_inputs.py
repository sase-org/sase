"""Interaction coverage for declared and raw inputs in GateBranchControls."""

from __future__ import annotations

from typing import Any

from textual.app import App, ComposeResult
from textual.widgets import Button, Static

from sase.ace.tui.modals.gate_branch_controls import GateBranchControls, GateBranchData
from sase.ace.tui.modals.gate_input_panel import GateInputPanel
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.vim_text_area import VimTextArea
from sase.notification_gates.models import GateGroup, GateOption


def _option(
    option_id: str,
    *,
    label: str | None = None,
    inputs: list[dict[str, Any]] | None = None,
    input_schema: dict[str, Any] | None = None,
    default_selected: bool = True,
    feedback: str = "disabled",
) -> GateOption:
    payload: dict[str, Any] = {
        "id": option_id,
        "label": label or option_id.title(),
        "default_selected": default_selected,
        "feedback": feedback,
        "command": {"argv": [f"commands/{option_id}"]},
    }
    if inputs is not None:
        payload["inputs"] = inputs
    if input_schema is not None:
        payload["input_schema"] = input_schema
    return GateOption.from_mapping(payload, 0)


def _controls(
    *,
    options: tuple[GateOption, ...],
    branches: tuple[tuple[str, ...], ...],
    groups: tuple[GateGroup, ...] = (),
) -> GateBranchControls:
    data = GateBranchData(
        query="test query",
        options=options,
        branches=branches,
        groups=groups,
        primary_branch=branches[0],
    )
    return GateBranchControls(data)


class _ControlsApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, controls: GateBranchControls) -> None:
        super().__init__()
        self._controls = controls
        self.resolved: list[GateBranchControls.Resolved] = []
        self.pushed: list[object] = []

    def compose(self) -> ComposeResult:
        yield self._controls

    def push_screen(self, screen: object, *args: object, **kwargs: object) -> object:
        self.pushed.append(screen)
        return super().push_screen(screen, *args, **kwargs)  # type: ignore[misc]

    def on_gate_branch_controls_resolved(
        self, event: GateBranchControls.Resolved
    ) -> None:
        self.resolved.append(event)


def _panel(app: _ControlsApp) -> GateInputPanel:
    screen = app.screen
    assert isinstance(screen, GateInputPanel)
    return screen


def _plain(widget: object) -> str:
    rendered = widget.render()  # type: ignore[attr-defined]
    return rendered.plain if hasattr(rendered, "plain") else str(rendered)


async def test_branch_without_declared_inputs_renders_no_container() -> None:
    controls = _controls(options=(_option("proceed"),), branches=(("proceed",),))
    app = _ControlsApp(controls)

    async with app.run_test(size=(100, 34)) as pilot:
        await pilot.pause()
        assert not controls.query("#gate-inputs-0")
        assert not controls.query(".gate-review-section-title")
        assert not controls.query("#gate-feedback-input")


async def test_no_input_branch_submits_immediately_without_opening_the_panel() -> None:
    controls = _controls(options=(_option("proceed"),), branches=(("proceed",),))
    app = _ControlsApp(controls)

    async with app.run_test(size=(100, 34)) as pilot:
        await pilot.pause()
        controls.query_one("#gate-singleton-0", Button).press()
        await pilot.pause()

    assert not any(isinstance(screen, GateInputPanel) for screen in app.pushed)
    [event] = app.resolved
    assert event.selected_option_ids == ("proceed",)
    assert event.feedback is None
    assert event.option_inputs == {}


async def test_toggling_and_member_does_not_open_the_panel() -> None:
    build = _option(
        "build",
        inputs=[
            {"id": "profile", "label": "Profile", "type": "word", "required": True}
        ],
    )
    publish = _option(
        "publish",
        inputs=[
            {"id": "channel", "label": "Channel", "type": "word", "required": True}
        ],
        default_selected=False,
    )
    controls = _controls(
        options=(build, publish),
        branches=(("build", "publish"),),
        groups=(GateGroup(("build", "publish")),),
    )
    app = _ControlsApp(controls)

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        controls.toggle_option(0, 1)
        await pilot.pause()
        assert not any(isinstance(screen, GateInputPanel) for screen in app.pushed)
        assert controls.selected_option_ids(0) == ("build", "publish")
        assert not controls.query(".gate-input-section")


async def test_group_submit_opens_panel_for_selected_options_only() -> None:
    build = _option(
        "build",
        inputs=[
            {"id": "profile", "label": "Profile", "type": "word", "required": True}
        ],
        default_selected=False,
    )
    publish = _option(
        "publish",
        inputs=[
            {"id": "channel", "label": "Channel", "type": "word", "required": True}
        ],
    )
    controls = _controls(
        options=(build, publish),
        branches=(("build", "publish"),),
        groups=(GateGroup(("build", "publish"), "Ship"),),
    )
    app = _ControlsApp(controls)

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        controls.query_one("#gate-group-submit-0", Button).press()
        await pilot.pause()
        panel = _panel(app)
        assert panel.query("#gate-input-section-publish")
        assert not panel.query("#gate-input-section-build")
        titles = [_plain(widget) for widget in panel.query(".gate-input-section-title")]
        assert any("Publish" in title for title in titles)
        assert all("Build" not in title for title in titles)


async def test_required_field_does_not_disable_the_control_that_opens_the_panel() -> (
    None
):
    solo = _option(
        "solo",
        inputs=[
            {"id": "target_env", "label": "Target", "type": "line", "required": True}
        ],
    )
    build = _option(
        "build",
        inputs=[
            {"id": "profile", "label": "Profile", "type": "word", "required": True}
        ],
    )
    publish = _option("publish")
    controls = _controls(
        options=(solo, build, publish),
        branches=(("solo",), ("build", "publish")),
        groups=(GateGroup(("build", "publish")),),
    )
    app = _ControlsApp(controls)

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        singleton = controls.query_one("#gate-singleton-0", Button)
        group_submit = controls.query_one("#gate-group-submit-1", Button)
        assert singleton.disabled is False
        assert group_submit.disabled is False

        singleton.press()
        await pilot.pause()
        panel = _panel(app)
        assert panel.query_one("#gate-input-submit", Button).disabled is True
        panel.action_cancel()
        await pilot.pause()
        assert app.resolved == []


async def test_and_members_each_receive_only_their_own_declared_fields() -> None:
    build = _option(
        "build",
        inputs=[
            {"id": "profile", "label": "Profile", "type": "word", "required": True},
            {"id": "shared_note", "label": "Note", "type": "line"},
        ],
    )
    publish = _option(
        "publish",
        inputs=[
            {"id": "channel", "label": "Channel", "type": "word", "required": True},
            {"id": "shared_note", "label": "Note", "type": "line"},
        ],
    )
    controls = _controls(
        options=(build, publish),
        branches=(("build", "publish"),),
        groups=(GateGroup(("build", "publish")),),
    )
    app = _ControlsApp(controls)

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        controls.query_one("#gate-group-submit-0", Button).press()
        await pilot.pause()
        panel = _panel(app)
        panel.query_one(
            "#gate-input-build-input-0", SingleLineVimTextArea
        ).text = "release"
        panel.query_one("#gate-input-build-input-1", SingleLineVimTextArea).text = "hi"
        panel.query_one(
            "#gate-input-publish-input-0", SingleLineVimTextArea
        ).text = "beta"
        await pilot.pause()
        panel.action_submit()
        await pilot.pause()

    [event] = app.resolved
    assert event.option_inputs == {
        "build": {"profile": "release", "shared_note": "hi"},
        "publish": {"channel": "beta", "shared_note": "hi"},
    }


async def test_conflicting_declared_field_types_notify_and_do_not_open_panel() -> None:
    build = _option(
        "build",
        inputs=[{"id": "value", "label": "Value", "type": "word", "required": True}],
    )
    publish = _option(
        "publish",
        inputs=[{"id": "value", "label": "Value", "type": "int", "required": True}],
    )
    controls = _controls(
        options=(build, publish),
        branches=(("build", "publish"),),
        groups=(GateGroup(("build", "publish")),),
    )
    app = _ControlsApp(controls)

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        assert controls.query_one("#gate-group-submit-0", Button).disabled is False
        controls._resolve_branch(0)
        await pilot.pause()

    assert app.resolved == []
    assert not any(isinstance(screen, GateInputPanel) for screen in app.pushed)


async def test_raw_input_schema_opens_panel_validates_and_delivers() -> None:
    option = _option(
        "rotate",
        input_schema={
            "type": "object",
            "properties": {"reason": {"type": "string", "minLength": 1}},
            "required": ["reason"],
            "additionalProperties": False,
        },
    )
    controls = _controls(options=(option,), branches=(("rotate",),))
    app = _ControlsApp(controls)

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        controls.query_one("#gate-singleton-0", Button).press()
        await pilot.pause()
        panel = _panel(app)
        editor = panel.query_one("#gate-input-rotate-raw", VimTextArea)

        editor.text = "reason: 5\n"  # schema requires a string
        await pilot.pause()
        assert panel.query_one("#gate-input-submit", Button).disabled is True
        error = panel.query_one("#gate-input-rotate-raw-error", Static)
        assert error.display is True

        editor.text = "reason: rotate quarterly\n"
        await pilot.pause()
        assert panel.query_one("#gate-input-submit", Button).disabled is False
        panel.action_submit()
        await pilot.pause()

    [event] = app.resolved
    assert event.option_inputs == {"rotate": {"reason": "rotate quarterly"}}


async def test_raw_schema_with_only_host_collected_property_submits_immediately() -> (
    None
):
    option = _option(
        "accept",
        input_schema={
            "type": "object",
            "properties": {"feedback": {"type": "string"}},
            "additionalProperties": False,
        },
    )
    controls = _controls(options=(option,), branches=(("accept",),))
    app = _ControlsApp(controls)

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        assert not controls.query("#gate-inputs-0")
        controls.query_one("#gate-singleton-0", Button).press()
        await pilot.pause()

    assert not any(isinstance(screen, GateInputPanel) for screen in app.pushed)
    [event] = app.resolved
    assert event.selected_option_ids == ("accept",)
    assert event.option_inputs == {}


async def test_raw_schema_with_no_properties_submits_immediately() -> None:
    option = _option(
        "log", input_schema={"type": "object", "additionalProperties": False}
    )
    controls = _controls(options=(option,), branches=(("log",),))
    app = _ControlsApp(controls)

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        assert not controls.query("#gate-inputs-0")
        controls.query_one("#gate-singleton-0", Button).press()
        await pilot.pause()

    assert not any(isinstance(screen, GateInputPanel) for screen in app.pushed)
    [event] = app.resolved
    assert event.selected_option_ids == ("log",)


async def test_cancelling_the_panel_restores_typed_values_on_reopen() -> None:
    option = _option(
        "deploy",
        inputs=[
            {"id": "target_env", "label": "Target", "type": "line", "required": True}
        ],
    )
    controls = _controls(options=(option,), branches=(("deploy",),))
    app = _ControlsApp(controls)

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        controls.query_one("#gate-singleton-0", Button).press()
        await pilot.pause()
        first = _panel(app)
        first.query_one(
            "#gate-input-deploy-input-0", SingleLineVimTextArea
        ).text = "staging"
        first.action_cancel()
        await pilot.pause()
        assert app.resolved == []

        controls.query_one("#gate-singleton-0", Button).press()
        await pilot.pause()
        second = _panel(app)
        assert (
            second.query_one("#gate-input-deploy-input-0", SingleLineVimTextArea).text
            == "staging"
        )
        second.action_submit()
        await pilot.pause()

    [event] = app.resolved
    assert event.option_inputs == {"deploy": {"target_env": "staging"}}

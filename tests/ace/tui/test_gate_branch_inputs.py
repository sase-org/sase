"""Interaction coverage for declared and raw inputs in GateBranchControls."""

from __future__ import annotations

from typing import Any

from textual.app import App, ComposeResult
from textual.widgets import Button, Static, TextArea

from sase.ace.tui.modals.gate_branch_controls import GateBranchControls, GateBranchData
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.notification_gates.models import GateGroup, GateOption


def _option(
    option_id: str,
    *,
    label: str | None = None,
    inputs: list[dict[str, Any]] | None = None,
    input_schema: dict[str, Any] | None = None,
    default_selected: bool = True,
) -> GateOption:
    payload: dict[str, Any] = {
        "id": option_id,
        "label": label or option_id.title(),
        "default_selected": default_selected,
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
        groups=groups,
        branches=branches,
        primary_branch=branches[0],
    )
    return GateBranchControls(data)


class _ControlsApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, controls: GateBranchControls) -> None:
        super().__init__()
        self._controls = controls
        self.resolved: list[GateBranchControls.Resolved] = []

    def compose(self) -> ComposeResult:
        yield self._controls

    def on_gate_branch_controls_resolved(
        self, event: GateBranchControls.Resolved
    ) -> None:
        self.resolved.append(event)


async def test_branch_without_declared_inputs_renders_no_container() -> None:
    controls = _controls(options=(_option("proceed"),), branches=(("proceed",),))
    app = _ControlsApp(controls)

    async with app.run_test(size=(100, 34)) as pilot:
        await pilot.pause()
        assert not controls.query("#gate-inputs-0")
        assert not controls.query(".gate-review-section-title")


async def test_toggling_and_member_reveals_and_hides_exactly_its_fields() -> None:
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
        profile_block = controls.query_one("#gate-branch-0-field-block-0")
        channel_block = controls.query_one("#gate-branch-0-field-block-1")
        assert profile_block.display is True  # build is selected by default
        assert channel_block.display is False  # publish is not

        controls.toggle_option(0, 1)  # select publish
        await pilot.pause()
        assert profile_block.display is True
        assert channel_block.display is True

        controls.toggle_option(0, 0)  # deselect build
        await pilot.pause()
        assert profile_block.display is False
        assert channel_block.display is True


async def test_required_field_blocks_singleton_and_group_submit_until_filled() -> None:
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
        assert singleton.disabled is True
        assert group_submit.disabled is True

        solo_editor = controls.query_one(
            "#gate-branch-0-field-input-0", SingleLineVimTextArea
        )
        solo_editor.text = "staging"
        await pilot.pause()
        assert singleton.disabled is False
        assert group_submit.disabled is True  # build's required field still empty

        build_editor = controls.query_one(
            "#gate-branch-1-field-input-0", SingleLineVimTextArea
        )
        build_editor.text = "release"
        await pilot.pause()
        assert group_submit.disabled is False


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
        controls.query_one(
            "#gate-branch-0-field-input-0", SingleLineVimTextArea
        ).text = "release"
        controls.query_one(
            "#gate-branch-0-field-input-1", SingleLineVimTextArea
        ).text = "hi"
        controls.query_one(
            "#gate-branch-0-field-input-2", SingleLineVimTextArea
        ).text = "beta"
        await pilot.pause()

        controls.query_one("#gate-group-submit-0", Button).press()
        await pilot.pause()

    [event] = app.resolved
    assert event.option_inputs == {
        "build": {"profile": "release", "shared_note": "hi"},
        "publish": {"channel": "beta", "shared_note": "hi"},
    }


async def test_conflicting_declared_field_types_render_message_and_block_submit() -> (
    None
):
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
        message = controls.query_one(".gate-input-conflict", Static)
        assert "value" in message.render().plain
        assert controls.query_one("#gate-group-submit-0", Button).disabled is True

        controls._resolve_branch(0)
        await pilot.pause()

    assert app.resolved == []


async def test_raw_input_schema_renders_yaml_editor_validates_and_delivers() -> None:
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
        editor = controls.query_one("#gate-branch-0-raw-rotate", TextArea)

        editor.text = "reason: 5\n"  # schema requires a string
        await pilot.pause()
        assert controls._branch_inputs_valid(0) is False
        error = controls.query_one("#gate-branch-0-raw-rotate-error", Static)
        assert error.display is True

        editor.text = "reason: rotate quarterly\n"
        await pilot.pause()
        assert controls._branch_inputs_valid(0) is True

        controls._resolve_branch(0)
        await pilot.pause()

    [event] = app.resolved
    assert event.option_inputs == {"rotate": {"reason": "rotate quarterly"}}


async def test_raw_schema_with_only_host_collected_property_renders_nothing() -> None:
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


async def test_raw_schema_with_no_properties_renders_nothing() -> None:
    option = _option(
        "log", input_schema={"type": "object", "additionalProperties": False}
    )
    controls = _controls(options=(option,), branches=(("log",),))
    app = _ControlsApp(controls)

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        assert not controls.query("#gate-inputs-0")

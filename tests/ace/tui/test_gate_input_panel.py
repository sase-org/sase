"""Direct coverage for the gate input panel and its pure request model."""

from __future__ import annotations

from typing import Any

from textual.app import App
from textual.widgets import Button, Static

from sase.ace.tui.modals.gate_input_panel import GateInputPanel, GateInputPanelResult
from sase.ace.tui.modals.gate_input_panel_model import (
    GateInputDraft,
    build_gate_input_request,
    collect_option_inputs,
)
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.vim_text_area import VimTextArea
from sase.notification_gates.models import GateOption


class _PanelApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self) -> None:
        super().__init__()
        self.results: list[GateInputPanelResult | None] = []


def _option(
    option_id: str,
    *,
    label: str | None = None,
    icon: str | None = None,
    inputs: list[dict[str, Any]] | None = None,
    input_schema: dict[str, Any] | None = None,
    feedback: str | None = None,
) -> GateOption:
    payload: dict[str, Any] = {
        "id": option_id,
        "label": label or option_id.title(),
        "command": {"argv": [f"commands/{option_id}"]},
    }
    if icon is not None:
        payload["icon"] = icon
    if inputs is not None:
        payload["inputs"] = inputs
    if input_schema is not None:
        payload["input_schema"] = input_schema
    if feedback is not None:
        payload["feedback"] = feedback
    return GateOption.from_mapping(payload, 0)


def _request(
    *options: GateOption,
    selected: tuple[str, ...] | None = None,
    branch_label: str = "Deploy",
    feedback_mode: str = "disabled",
    draft: GateInputDraft | None = None,
):
    chosen = (
        selected if selected is not None else tuple(option.id for option in options)
    )
    return build_gate_input_request(
        options,
        chosen,
        branch_index=0,
        branch_label=branch_label,
        feedback_mode=feedback_mode,  # type: ignore[arg-type]
        draft=draft,
    )


def _plain(widget: object) -> str:
    rendered = widget.render()  # type: ignore[attr-defined]
    return rendered.plain if hasattr(rendered, "plain") else str(rendered)


# -- pure model ---------------------------------------------------------------


def test_requires_panel_and_is_empty_follow_the_open_table() -> None:
    declared = _option(
        "deploy",
        inputs=[{"id": "env", "label": "Env", "type": "line", "required": True}],
    )
    optional_field = _option(
        "tag",
        inputs=[{"id": "note", "label": "Note", "type": "line"}],
    )
    raw = _option(
        "rotate",
        input_schema={
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    )
    host_only = _option(
        "accept",
        input_schema={
            "type": "object",
            "properties": {"feedback": {"type": "string"}},
        },
    )
    bare = _option("proceed")

    required_field = _request(declared)
    assert required_field.requires_panel is True
    assert required_field.is_empty is False

    optional_declared = _request(optional_field)
    assert optional_declared.requires_panel is True
    assert optional_declared.is_empty is False

    raw_schema = _request(raw)
    assert raw_schema.requires_panel is True
    assert raw_schema.is_empty is False

    required_note = _request(bare, feedback_mode="required")
    assert required_note.requires_panel is True
    assert required_note.is_empty is False

    optional_note = _request(bare, feedback_mode="optional")
    assert optional_note.requires_panel is False
    assert optional_note.is_empty is False

    nothing = _request(bare)
    assert nothing.requires_panel is False
    assert nothing.is_empty is True

    hidden_host = _request(host_only)
    assert hidden_host.requires_panel is False
    assert hidden_host.is_empty is True


def test_collect_option_inputs_parses_raw_yaml() -> None:
    option = _option(
        "rotate",
        input_schema={
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    )
    request = _request(option)
    assert collect_option_inputs(
        request, {}, {"rotate": "reason: rotate quarterly\n"}
    ) == {"rotate": {"reason": "rotate quarterly"}}


# -- panel interactions -------------------------------------------------------


async def test_one_section_per_selected_option_uses_icon_and_label() -> None:
    deploy = _option(
        "deploy",
        label="Deploy signed build",
        icon="🚀",
        inputs=[{"id": "env", "label": "Target", "type": "line", "required": True}],
    )
    publish = _option(
        "publish",
        label="Publish notes",
        icon="📝",
        inputs=[
            {"id": "channel", "label": "Channel", "type": "word", "required": True}
        ],
    )
    request = _request(deploy, publish, branch_label="Ship it")
    app = _PanelApp()
    panel = GateInputPanel(request)

    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(panel, app.results.append)
        await pilot.pause()
        titles = [_plain(widget) for widget in panel.query(".gate-input-section-title")]
        assert any("🚀" in title and "Deploy signed build" in title for title in titles)
        assert any("📝" in title and "Publish notes" in title for title in titles)
        assert panel.query("#gate-input-section-deploy")
        assert panel.query("#gate-input-section-publish")


async def test_shared_compatible_field_renders_once_and_lands_in_both() -> None:
    build = _option(
        "build",
        label="Build",
        inputs=[
            {"id": "profile", "label": "Profile", "type": "word", "required": True},
            {"id": "shared_note", "label": "Shared", "type": "line"},
        ],
    )
    publish = _option(
        "publish",
        label="Publish",
        inputs=[
            {"id": "channel", "label": "Channel", "type": "word", "required": True},
            {"id": "shared_note", "label": "Shared", "type": "line"},
        ],
    )
    request = _request(build, publish)
    app = _PanelApp()
    panel = GateInputPanel(request)

    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(panel, app.results.append)
        await pilot.pause()
        assert panel.query("#gate-input-build-input-0")
        assert panel.query("#gate-input-build-input-1")
        assert panel.query("#gate-input-publish-input-0")
        assert not panel.query("#gate-input-publish-input-1")
        guidance = " ".join(_plain(widget) for widget in panel.query(".field-desc"))
        assert "also sent to Publish" in guidance

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

    [result] = app.results
    assert result is not None
    assert result.option_inputs == {
        "build": {"profile": "release", "shared_note": "hi"},
        "publish": {"channel": "beta", "shared_note": "hi"},
    }


async def test_incompatible_shared_field_shows_conflict_and_blocks_submit() -> None:
    build = _option(
        "build",
        inputs=[{"id": "value", "label": "Value", "type": "word", "required": True}],
    )
    publish = _option(
        "publish",
        inputs=[{"id": "value", "label": "Value", "type": "int", "required": True}],
    )
    request = _request(build, publish)
    assert request.conflict is not None
    app = _PanelApp()
    panel = GateInputPanel(request)

    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(panel, app.results.append)
        await pilot.pause()
        message = panel.query_one(".gate-input-conflict", Static)
        assert "value" in _plain(message)
        assert not panel.query("#gate-input-submit")
        panel.action_submit()
        await pilot.pause()

    assert app.results == []


async def test_tab_and_shift_tab_walk_editors_enum_and_buttons() -> None:
    option = _option(
        "deploy",
        inputs=[
            {"id": "env", "label": "Env", "type": "line", "required": True},
            {
                "id": "mode",
                "label": "Mode",
                "type": "enum",
                "choices": ["full", "quick"],
            },
        ],
        feedback="optional",
    )
    request = _request(option, feedback_mode="optional")
    app = _PanelApp()
    panel = GateInputPanel(request)

    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(panel, app.results.append)
        await pilot.pause()
        panel.query_one(
            "#gate-input-deploy-input-0", SingleLineVimTextArea
        ).text = "production"
        await pilot.pause()
        expected = [
            "gate-input-deploy-input-0",
            "gate-input-deploy-input-1",
            "gate-input-note",
            "gate-input-submit",
            "gate-input-cancel",
        ]
        panel.query_one(f"#{expected[0]}").focus()
        await pilot.pause()
        assert panel.focused is not None
        assert panel.focused.id == expected[0]
        seen = [panel.focused.id]
        for _ in expected[1:]:
            await pilot.press("tab")
            await pilot.pause()
            assert panel.focused is not None
            seen.append(panel.focused.id)
        assert seen == expected
        await pilot.press("tab")
        await pilot.pause()
        assert panel.focused is not None
        assert panel.focused.id == expected[0]
        await pilot.press("shift+tab")
        await pilot.pause()
        assert panel.focused is not None
        assert panel.focused.id == expected[-1]


async def test_enter_on_last_field_advances_section_then_submits() -> None:
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
    )
    request = _request(build, publish)
    app = _PanelApp()
    panel = GateInputPanel(request)

    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(panel, app.results.append)
        await pilot.pause()
        first = panel.query_one("#gate-input-build-input-0", SingleLineVimTextArea)
        second = panel.query_one("#gate-input-publish-input-0", SingleLineVimTextArea)
        first.text = "release"
        first.focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert second.has_focus

        second.text = "beta"
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    [result] = app.results
    assert result is not None
    assert result.option_inputs == {
        "build": {"profile": "release"},
        "publish": {"channel": "beta"},
    }


async def test_required_field_blocks_submit_and_refocuses() -> None:
    option = _option(
        "deploy",
        inputs=[{"id": "env", "label": "Env", "type": "line", "required": True}],
    )
    request = _request(option)
    app = _PanelApp()
    panel = GateInputPanel(request)

    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(panel, app.results.append)
        await pilot.pause()
        submit = panel.query_one("#gate-input-submit", Button)
        assert submit.disabled is True
        panel.action_submit()
        await pilot.pause()
        editor = panel.query_one("#gate-input-deploy-input-0", SingleLineVimTextArea)
        assert editor.has_focus
        assert app.results == []

        editor.text = "production"
        await pilot.pause()
        assert submit.disabled is False
        panel.action_submit()
        await pilot.pause()

    [result] = app.results
    assert result is not None
    assert result.option_inputs == {"deploy": {"env": "production"}}


async def test_raw_schema_option_round_trips_yaml() -> None:
    option = _option(
        "rotate",
        input_schema={
            "type": "object",
            "properties": {"reason": {"type": "string", "minLength": 1}},
            "required": ["reason"],
            "additionalProperties": False,
        },
    )
    request = _request(option)
    app = _PanelApp()
    panel = GateInputPanel(request)

    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(panel, app.results.append)
        await pilot.pause()
        editor = panel.query_one("#gate-input-rotate-raw", VimTextArea)
        editor.text = "reason: rotate quarterly\n"
        await pilot.pause()
        panel.action_submit()
        await pilot.pause()

    [result] = app.results
    assert result is not None
    assert result.option_inputs == {"rotate": {"reason": "rotate quarterly"}}


async def test_note_section_and_declared_feedback_field() -> None:
    with_note = _option("accept", feedback="required")
    request = _request(with_note, feedback_mode="required")
    app = _PanelApp()
    panel = GateInputPanel(request)

    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(panel, app.results.append)
        await pilot.pause()
        assert panel.query("#gate-input-note")
        panel.query_one("#gate-input-note", VimTextArea).text = "looks good"
        await pilot.pause()
        panel.action_submit()
        await pilot.pause()

    [result] = app.results
    assert result is not None
    assert result.feedback == "looks good"

    declared = _option(
        "reject",
        inputs=[
            {
                "id": "feedback",
                "label": "Reason",
                "type": "line",
                "required": True,
            }
        ],
        feedback="required",
    )
    owned = _request(declared, feedback_mode="required")
    assert owned.feedback_field_owner == "reject"
    app = _PanelApp()
    panel = GateInputPanel(owned)

    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(panel, app.results.append)
        await pilot.pause()
        assert not panel.query("#gate-input-note")
        panel.query_one(
            "#gate-input-reject-input-0", SingleLineVimTextArea
        ).text = "not ready"
        await pilot.pause()
        panel.action_submit()
        await pilot.pause()

    [owned_result] = app.results
    assert owned_result is not None
    assert owned_result.feedback == "not ready"
    assert owned_result.option_inputs == {"reject": {"feedback": "not ready"}}


async def test_cancel_dismisses_none_and_draft_restores_values() -> None:
    option = _option(
        "deploy",
        inputs=[{"id": "env", "label": "Env", "type": "line", "required": True}],
        feedback="optional",
    )
    request = _request(option, feedback_mode="optional")
    app = _PanelApp()
    panel = GateInputPanel(request)

    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(panel, app.results.append)
        await pilot.pause()
        panel.query_one(
            "#gate-input-deploy-input-0", SingleLineVimTextArea
        ).text = "staging"
        panel.query_one("#gate-input-note", VimTextArea).text = "hold for qa"
        await pilot.pause()
        panel.action_cancel()
        await pilot.pause()

    assert app.results == [None]
    draft = panel.draft
    assert draft.values["env"] == "staging"
    assert draft.feedback == "hold for qa"

    restored = _request(option, feedback_mode="optional", draft=draft)
    app = _PanelApp()
    panel = GateInputPanel(restored)
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(panel)
        await pilot.pause()
        assert (
            panel.query_one("#gate-input-deploy-input-0", SingleLineVimTextArea).text
            == "staging"
        )
        assert panel.query_one("#gate-input-note", VimTextArea).text == "hold for qa"

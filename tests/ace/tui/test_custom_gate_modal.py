"""Interaction coverage for the shared branch-driven gate modal."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from rich.markup import escape
from rich.text import Text
from textual.app import App
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Button, Static

from sase.ace.testing import wait_for
from sase.ace.tui.keymaps import (
    GateModalKeymaps,
    build_gate_numbered_branch_bindings,
)
from sase.ace.tui.modals.custom_gate_modal import (
    CustomGateModal,
    CustomGateModalData,
    CustomGateModalResult,
)
from sase.ace.tui.modals.gate_branch_controls import (
    GateBranchControls,
    GateBranchData,
)
from sase.ace.tui.modals.gate_input_panel import GateInputPanel
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.vim_text_area import VimTextArea
from sase.bead._task_gate_spec import build_task_triage_gate_spec
from sase.notification_gates.models import GateGroup, GateOption
from sase.notification_gates.presentation import GateChip


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self) -> None:
        super().__init__()
        self.recorded_notifications: list[tuple[str, str]] = []

    def notify(
        self,
        message: str,
        *_args: object,
        severity: str = "information",
        **_kwargs: object,
    ) -> None:
        self.recorded_notifications.append((message, severity))


_ROOT = Path(__file__).resolve().parents[3]


class _StyledTestApp(_TestApp):
    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"


def _option(
    option_id: str,
    *,
    label: str | None = None,
    icon: str | None = None,
    selected: bool = True,
    feedback: str = "disabled",
    inputs: list[dict[str, Any]] | None = None,
) -> GateOption:
    payload: dict[str, Any] = {
        "id": option_id,
        "label": label or option_id.title(),
        "icon": icon,
        "default_selected": selected,
        "feedback": feedback,
        "command": {"argv": [f"commands/{option_id}"]},
    }
    if inputs is not None:
        payload["inputs"] = inputs
    return GateOption.from_mapping(payload, 0)


def _data(
    *,
    options: tuple[GateOption, ...],
    branches: tuple[tuple[str, ...], ...],
    groups: tuple[GateGroup, ...] = (),
    primary_branch: tuple[str, ...] | None = None,
    preview_name: str | None = None,
    preview_text: str | None = None,
    title: str = "Custom Gate",
    origin_agent: str | None = None,
    notes: tuple[str, ...] | None = None,
    gate_title: str | None = None,
    chip: GateChip | None = None,
) -> CustomGateModalData:
    return CustomGateModalData(
        request_id="custom-ace",
        title=title,
        sender="review-agent",
        icon="🛡️",
        notes=notes or ("Review guarded work.",),
        attachments=(),
        preview_name=preview_name,
        preview_text=preview_text,
        gate=GateBranchData(
            query="test query",
            options=options,
            groups=groups,
            branches=branches,
            primary_branch=primary_branch or branches[0],
        ),
        origin_agent=origin_agent,
        gate_title=gate_title,
        chip=chip,
    )


def _open_panel(app: App[None]) -> GateInputPanel:
    screen = app.screen
    assert isinstance(screen, GateInputPanel)
    return screen


def _task_triage_data() -> CustomGateModalData:
    spec = build_task_triage_gate_spec(
        request_id="task-triage-ace-modal",
        bead_id="sase-task.1",
        project="sase",
        title="Review follow-up",
        description="Preserve the compatibility path.",
        notes="Raised by the land agent.",
        created_by="claude_coder",
        created_at="2026-01-01T00:00:00Z",
    )
    presentation = spec["presentation"]
    preview = next(
        resource["content"]
        for resource in spec["resources"]
        if resource["path"] == "task.md"
    )
    options = tuple(
        GateOption.from_mapping(option, index)
        for index, option in enumerate(spec["options"])
    )
    return CustomGateModalData(
        request_id=str(spec["request_id"]),
        title="Task Triage",
        sender=str(presentation["sender"]),
        icon=str(presentation["icon"]),
        notes=tuple(str(note) for note in presentation["notes"]),
        attachments=("task.md",),
        preview_name="task.md",
        preview_text=str(preview),
        gate=GateBranchData(
            query=str(spec["query"]),
            options=options,
            groups=(),
            branches=(("launch",), ("close",), ("snooze",)),
            primary_branch=("launch",),
        ),
        origin_agent=str(presentation["origin_agent"]),
        gate_title=str(presentation["title"]),
    )


async def test_singleton_button_resolves_its_option() -> None:
    results: list[CustomGateModalResult | None] = []
    modal = CustomGateModal(
        _data(
            options=(_option("proceed", icon="✅"), _option("cancel", icon="❌")),
            branches=(("proceed",), ("cancel",)),
        )
    )

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.click("#gate-singleton-0")
        await pilot.pause()

    assert results == [CustomGateModalResult(("proceed",), None)]


async def test_group_renders_defaults_toggles_and_configured_submit() -> None:
    results: list[CustomGateModalResult | None] = []
    group = GateGroup(
        options=("approve", "audit"),
        label="Approve guarded work",
        icon="✅",
    )
    modal = CustomGateModal(
        _data(
            options=(
                _option("approve", icon="✅"),
                _option("audit", icon="📝", selected=False),
                _option("reject", icon="❌"),
            ),
            branches=(("approve", "audit"), ("reject",)),
            groups=(group,),
        )
    )

    async with _TestApp().run_test(size=(100, 36)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        controls = modal.query_one(GateBranchControls)
        assert controls.selected_option_ids(0) == ("approve",)
        group_expand_label = str(modal.query_one("#gate-group-expand-0", Button).label)
        group_submit_label = str(modal.query_one("#gate-group-submit-0", Button).label)
        toggle_label = str(modal.query_one("#gate-option-0-1", Button).label)
        assert group_expand_label.startswith("1 ")
        assert group_submit_label.startswith("1 ")
        assert toggle_label.startswith("⬜")
        assert str(modal.query_one("#gate-singleton-1", Button).label).startswith("2 ")
        assert str(modal.query_one("#custom-gate-cancel", Button).label) == "Cancel"
        assert "Approve guarded work" in group_submit_label

        modal.query_one("#gate-option-0-1", Button).press()
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause()

    assert results == [CustomGateModalResult(("approve", "audit"), None)]


async def test_declared_input_value_reaches_resolved_option_inputs() -> None:
    results: list[CustomGateModalResult | None] = []
    option = GateOption.from_mapping(
        {
            "id": "deploy",
            "label": "Deploy",
            "icon": "🚀",
            "default_selected": True,
            "feedback": "disabled",
            "command": {"argv": ["commands/deploy"]},
            "inputs": [
                {
                    "id": "target_env",
                    "label": "Target environment",
                    "type": "line",
                    "required": True,
                }
            ],
        },
        0,
    )
    modal = CustomGateModal(_data(options=(option,), branches=(("deploy",),)))

    async with _TestApp().run_test(size=(100, 40)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("1")
        await wait_for(pilot, lambda: isinstance(pilot.app.screen, GateInputPanel))
        panel = _open_panel(pilot.app)
        field = panel.query_one("#gate-input-deploy-input-0", SingleLineVimTextArea)
        field.text = "staging"
        await pilot.pause()
        await pilot.press("ctrl+s")
        await wait_for(pilot, lambda: bool(results))

    assert results == [
        CustomGateModalResult(
            ("deploy",),
            None,
            option_inputs={"deploy": {"target_env": "staging"}},
        )
    ]


async def test_numbered_shortcut_focuses_required_enum_then_submits() -> None:
    results: list[CustomGateModalResult | None] = []
    modal = CustomGateModal(
        _data(
            options=(
                _option("approve", icon="✅"),
                _option("close", icon="✅"),
                _option(
                    "snooze",
                    icon="💤",
                    inputs=[
                        {
                            "id": "wake_after",
                            "label": "Wake after",
                            "type": "enum",
                            "required": True,
                            "choices": [
                                {"value": "tomorrow", "label": "Tomorrow"},
                                {"value": "next_week", "label": "Next week"},
                            ],
                        },
                        {
                            "id": "note",
                            "label": "Note",
                            "type": "line",
                            "required": False,
                        },
                    ],
                ),
            ),
            branches=(("approve",), ("close",), ("snooze",)),
            preview_name="triage.md",
            preview_text="# Task triage\n",
            notes=tuple(f"Context line {index}" for index in range(16)),
        )
    )
    app = _StyledTestApp()

    async with app.run_test(size=(120, 24)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("j")
        assert modal.query_one("#gate-singleton-1", Button).has_focus

        await pilot.press("3")
        await wait_for(pilot, lambda: isinstance(pilot.app.screen, GateInputPanel))
        panel = _open_panel(app)
        wake_after = panel.query_one("#gate-input-snooze-input-0", Button)

        assert results == []
        assert wake_after.has_focus
        assert (
            "Fix the highlighted inputs before submitting",
            "warning",
        ) not in app.recorded_notifications

        wake_after.press()
        await pilot.pause()
        await pilot.press("ctrl+s")
        await wait_for(pilot, lambda: bool(results))

    assert results == [
        CustomGateModalResult(
            ("snooze",),
            None,
            option_inputs={"snooze": {"wake_after": "tomorrow"}},
        )
    ]


async def test_task_triage_shortcut_focuses_duration_line_then_submits() -> None:
    results: list[CustomGateModalResult | None] = []
    modal = CustomGateModal(_task_triage_data())
    app = _StyledTestApp()

    async with app.run_test(size=(120, 24)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()

        await pilot.press("3")
        await wait_for(pilot, lambda: isinstance(pilot.app.screen, GateInputPanel))
        panel = _open_panel(app)
        duration = panel.query_one("#gate-input-snooze-input-0", SingleLineVimTextArea)
        await wait_for(pilot, lambda: duration.has_focus)

        assert results == []
        assert (
            "Fix the highlighted inputs before submitting",
            "warning",
        ) not in app.recorded_notifications

        duration.text = "3d +2"
        await pilot.press("ctrl+s")
        await wait_for(pilot, lambda: bool(results))

    assert results == [
        CustomGateModalResult(
            ("snooze",),
            None,
            option_inputs={"snooze": {"duration": "3d +2"}},
        )
    ]


@pytest.mark.parametrize(
    ("key", "expected_option_id"),
    [("1", "first"), ("2", "second"), ("3", "third")],
)
async def test_numbered_shortcuts_dispatch_canonical_branch_independent_of_focus(
    key: str,
    expected_option_id: str,
) -> None:
    results: list[CustomGateModalResult | None] = []
    modal = CustomGateModal(
        _data(
            options=tuple(
                _option(option_id) for option_id in ("first", "second", "third")
            ),
            branches=(("first",), ("second",), ("third",)),
        )
    )

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("j")
        assert modal.query_one("#gate-singleton-1", Button).has_focus
        await pilot.press(key)
        await pilot.pause()

    assert results == [CustomGateModalResult((expected_option_id,), None)]


async def test_required_feedback_blocks_until_entered() -> None:
    results: list[CustomGateModalResult | None] = []
    modal = CustomGateModal(
        _data(
            options=(_option("revise", feedback="required", icon="💬"),),
            branches=(("revise",),),
        )
    )

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("1")
        await wait_for(pilot, lambda: isinstance(pilot.app.screen, GateInputPanel))
        panel = _open_panel(pilot.app)
        assert results == []
        feedback = panel.query_one("#gate-input-note", VimTextArea)
        assert feedback.has_focus
        feedback.text = "123 Please revise the rollout."
        await pilot.press("ctrl+s")
        await wait_for(pilot, lambda: bool(results))

    assert results == [
        CustomGateModalResult(("revise",), "123 Please revise the rollout.")
    ]


async def test_enter_submits_declared_primary_even_when_focus_is_elsewhere() -> None:
    results: list[CustomGateModalResult | None] = []
    modal = CustomGateModal(
        _data(
            options=(_option("cancel", icon="❌"), _option("proceed", icon="✅")),
            branches=(("cancel",), ("proceed",)),
            primary_branch=("proceed",),
        )
    )

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        assert modal.query_one("#gate-singleton-0", Button).has_focus
        await pilot.press("enter")
        await pilot.pause()

    assert results == [CustomGateModalResult(("proceed",), None)]


async def test_remapped_primary_key_matches_footer_and_dispatch() -> None:
    results: list[CustomGateModalResult | None] = []
    modal = CustomGateModal(
        _data(
            options=(_option("cancel", icon="❌"), _option("proceed", icon="✅")),
            branches=(("cancel",), ("proceed",)),
            primary_branch=("proceed",),
        ),
        gate_keymaps=GateModalKeymaps(submit_primary="a"),
    )

    assert "a=Proceed" in modal._footer_text().plain

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()

    assert results == [CustomGateModalResult(("proceed",), None)]


async def test_ctrl_s_still_submits_the_active_non_primary_branch() -> None:
    results: list[CustomGateModalResult | None] = []
    modal = CustomGateModal(
        _data(
            options=(_option("proceed", icon="✅"), _option("cancel", icon="❌")),
            branches=(("proceed",), ("cancel",)),
        )
    )

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("j")
        await pilot.press("ctrl+s")
        await pilot.pause()

    assert results == [CustomGateModalResult(("cancel",), None)]


async def test_multiple_groups_expand_primary_and_switch_one_at_a_time() -> None:
    options = tuple(_option(option_id) for option_id in ("a", "b", "c", "d"))
    modal = CustomGateModal(
        _data(
            options=options,
            branches=(("a", "b"), ("c", "d")),
            groups=(
                GateGroup(("a", "b"), "First", "1️⃣"),
                GateGroup(("c", "d"), "Second", "2️⃣"),
            ),
        )
    )

    async with _TestApp().run_test(size=(100, 36)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        assert not modal.query_one("#gate-group-details-0").has_class("hidden")
        assert modal.query_one("#gate-group-details-1").has_class("hidden")

        await pilot.click("#gate-group-expand-1")
        await pilot.pause()
        assert modal.query_one("#gate-group-details-0").has_class("hidden")
        assert not modal.query_one("#gate-group-details-1").has_class("hidden")


async def test_unassigned_digit_is_harmless_and_q_still_cancels() -> None:
    results: list[CustomGateModalResult | None] = []
    modal = CustomGateModal(
        _data(options=(_option("proceed"),), branches=(("proceed",),))
    )

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("9")
        await pilot.pause()
        assert results == []
        await pilot.press("q")
        await pilot.pause()

    assert results == [None]


async def test_preview_composes_two_pane_shell_with_document_border_title() -> None:
    modal = CustomGateModal(
        _data(
            options=(_option("proceed"),),
            branches=(("proceed",),),
            preview_name="change.md",
            preview_text="# Change\n",
        )
    )

    async with _TestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert modal.query_one(".gate-review-body")
        assert modal.query_one(".gate-review-actions")
        scroll = modal.query_one("#custom-gate-review-scroll", VerticalScroll)
        assert scroll.has_class("gate-review-document")
        assert scroll.border_title == "change.md"
        assert not modal.query_one("#custom-gate-container").has_class(
            "gate-review-shell--compact"
        )
        assert modal.has_class("-gate-review-wide")


async def test_preview_uses_narrow_breakpoint_below_threshold() -> None:
    modal = CustomGateModal(
        _data(
            options=(_option("proceed"),),
            branches=(("proceed",),),
            preview_name="change.md",
            preview_text="# Change\n",
        )
    )

    async with _TestApp().run_test(size=(90, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert modal.has_class("-gate-review-narrow")
        assert not modal.has_class("-gate-review-wide")


async def test_previewless_gate_composes_compact_actions_only() -> None:
    modal = CustomGateModal(
        _data(options=(_option("proceed"),), branches=(("proceed",),))
    )

    async with _TestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        shell = modal.query_one("#custom-gate-container")
        assert shell.has_class("gate-review-shell--compact")
        assert not modal.query(".gate-review-body")
        assert not modal.query(".gate-review-document")
        actions = modal.query_one("#custom-gate-review-scroll", VerticalScroll)
        assert actions.has_class("gate-review-actions--compact")


def test_title_omits_chip_when_absent() -> None:
    modal = CustomGateModal(
        _data(options=(_option("proceed"),), branches=(("proceed",),))
    )

    assert modal._title() == (
        "[bold cyan]🛡️ Custom Gate[/bold cyan]  "
        "[dim]Custom Gate[/dim]  "
        "[bold]review-agent[/bold]  "
        "[dim]custom-ace[/dim]"
    )


def test_title_renders_chip_between_headline_and_kind() -> None:
    modal = CustomGateModal(
        _data(
            options=(_option("proceed"),),
            branches=(("proceed",),),
            title="Task Triage",
            gate_title="Review follow-up",
            chip=GateChip("≈", "flake", "#AF87FF"),
        )
    )

    assert modal._title() == (
        "[bold cyan]🛡️ Review follow-up[/bold cyan]  "
        "[bold #AF87FF]≈ flake[/]  "
        "[dim]Task Triage[/dim]  "
        "[bold]review-agent[/bold]  "
        "[dim]custom-ace[/dim]"
    )


def test_title_degrades_malformed_chip_color() -> None:
    modal = CustomGateModal(
        _data(
            options=(_option("proceed"),),
            branches=(("proceed",),),
            chip=GateChip("≈", "flake", "not-a-color"),
        )
    )
    title = modal._title()

    assert "[bold]≈ flake[/]" in title
    assert "not-a-color" not in title


def test_title_escapes_markup_in_chip_glyph_and_label() -> None:
    modal = CustomGateModal(
        _data(
            options=(_option("proceed"),),
            branches=(("proceed",),),
            chip=GateChip("[", "x[/]y"),
        )
    )
    title = modal._title()

    assert f"[bold]{escape('[')} {escape('x[/]y')}[/]" in title
    assert "[ x[/]y" in Text.from_markup(title).plain


async def test_header_uses_adapter_title_and_omits_absent_filer() -> None:
    modal = CustomGateModal(
        _data(
            options=(_option("proceed"),),
            branches=(("proceed",),),
            title="Task Triage",
        )
    )

    async with _TestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        rendered = modal.query_one("#custom-gate-title", Static).render().plain
        assert "Task Triage" in rendered
        assert "Custom Gate" not in rendered
        assert not modal.query("#custom-gate-origin")


async def test_declared_origin_agent_renders_filed_by_above_context() -> None:
    modal = CustomGateModal(
        _data(
            options=(_option("proceed"),),
            branches=(("proceed",),),
            origin_agent="claude_coder",
        )
    )

    async with _TestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        origin = modal.query_one("#custom-gate-origin", Static)
        assert origin.render().plain == "Filed by @claude_coder"
        assert origin.has_class("gate-review-origin")

        siblings = list(modal.query_one("#custom-gate-review-scroll").children)
        context_index = next(
            index
            for index, widget in enumerate(siblings)
            if isinstance(widget, Static) and widget.render().plain == "Context"
        )
        assert siblings.index(origin) < context_index


def test_bindings_match_shared_branch_actions() -> None:
    actions = {
        binding.action if isinstance(binding, Binding) else binding[1]
        for binding in CustomGateModal.BINDINGS
    }
    assert {"next_control", "previous_control", "toggle_option"} <= actions
    assert {"submit_primary", "submit_branch", "open_inputs"} <= actions
    assert {f"submit_numbered_branch({index})" for index in range(9)} <= actions
    assert "next_choice" not in actions

    numbered = build_gate_numbered_branch_bindings()
    assert [binding.key for binding in numbered] == [
        str(index) for index in range(1, 10)
    ]
    assert all(not binding.show and not binding.priority for binding in numbered)


def test_footer_omits_open_inputs_when_gate_has_no_inputs_or_note() -> None:
    modal = CustomGateModal(
        _data(
            options=(_option("proceed", icon="✅"),),
            branches=(("proceed",),),
        )
    )

    footer = modal._footer_text().plain
    assert "note/inputs" not in footer
    assert "^t complete path" not in footer


async def test_remapped_open_inputs_opens_panel_and_appears_in_footer() -> None:
    modal = CustomGateModal(
        _data(
            options=(_option("proceed", icon="✅", feedback="optional"),),
            branches=(("proceed",),),
        ),
        gate_keymaps=GateModalKeymaps(open_inputs="o"),
    )

    footer = modal._footer_text().plain
    assert "o note/inputs" in footer
    assert "i note/inputs" not in footer
    assert "^t complete path" not in footer

    async with _TestApp().run_test(size=(100, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.press("o")
        await wait_for(pilot, lambda: isinstance(pilot.app.screen, GateInputPanel))
        assert _open_panel(pilot.app).query("#gate-input-note")

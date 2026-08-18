"""Interaction coverage for the Actions section of the gate modals.

The properties under test are the ones that make an action feel repeatable
rather than destructive: the modal is never torn down, the reviewer's branch
selection and feedback survive, an unaccepted draft is visible and blocks
submission, and a display action leaves the gate answerable.
"""

from __future__ import annotations

from collections.abc import Callable

from textual.app import App
from textual.widgets import Button, Static

from sase.ace.tui.keymaps import GateModalKeymaps
from sase.ace.tui.modals.custom_gate_modal import (
    CustomGateModal,
    CustomGateModalData,
    CustomGateModalResult,
)
from sase.ace.tui.modals.gate_action_controls import (
    GateActionControls,
    GateActionsData,
    resolve_gate_action_keys,
)
from sase.ace.tui.modals.gate_action_output_modal import GateActionOutputModal
from sase.ace.tui.modals.gate_action_runner import (
    GateCommandOutcome,
    GateEditOutcome,
    gate_modal_taken_keys,
)
from sase.ace.tui.modals.gate_branch_controls import GateBranchControls, GateBranchData
from sase.notification_gates.model_operations import GateOperation
from sase.notification_gates.models import GateGroup, GateOption


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False


class _StubRunner:
    """A runner that records calls and returns the outcomes a test dictates."""

    def __init__(
        self,
        *,
        edit: GateEditOutcome | None = None,
        discard: GateEditOutcome | None = None,
        command: GateCommandOutcome | None = None,
    ) -> None:
        self.edit_outcome = edit or GateEditOutcome(accepted=True)
        self.discard_outcome = discard or GateEditOutcome(accepted=True)
        self.command_outcome = command
        self.edited: list[str] = []
        self.discarded: list[str] = []
        self.ran: list[str] = []

    def run_edit(self, operation_id: str) -> GateEditOutcome:
        self.edited.append(operation_id)
        return self.edit_outcome

    def discard_draft(self, operation_id: str) -> GateEditOutcome:
        self.discarded.append(operation_id)
        return self.discard_outcome

    def run_command(
        self, operation_id: str, on_done: Callable[[GateCommandOutcome], None]
    ) -> bool:
        self.ran.append(operation_id)
        if self.command_outcome is None:
            return False
        on_done(self.command_outcome)
        return True

    def reviewed_content(self) -> str | None:
        return self.edit_outcome.content


def _option(option_id: str, *, feedback: str = "disabled") -> GateOption:
    return GateOption.from_mapping(
        {
            "id": option_id,
            "label": option_id.title(),
            "feedback": feedback,
            "command": {"argv": [f"commands/{option_id}"]},
        },
        0,
    )


def _edit_operation(**overrides: object) -> GateOperation:
    return GateOperation.from_mapping(
        {
            "id": "edit_plan",
            "kind": "edit_file",
            "target": "plan.md",
            "edit_target": "origin",
            "label": "Edit plan",
            "icon": "✏️",
            "key": "e",
            "description": "Accepted only when `sase plan validate` passes.",
            **overrides,
        },
        0,
    )


def _run_operation(**overrides: object) -> GateOperation:
    return GateOperation.from_mapping(
        {
            "id": "show_diff",
            "kind": "run_command",
            "command": {"argv": ["commands/show_diff"]},
            "label": "Show diff",
            "key": "x",
            "display": "markdown",
            **overrides,
        },
        1,
    )


_NO_ACTIONS = GateActionsData()


def _preview_text(modal: CustomGateModal) -> str:
    """Read the syntax-highlighted preview pane back as plain source text."""
    syntax = modal.query_one("#custom-gate-preview", Static).render()._renderable
    return str(syntax.code)


def _modal(
    *,
    options: tuple[GateOption, ...],
    branches: tuple[tuple[str, ...], ...],
    groups: tuple[GateGroup, ...] = (),
    actions: GateActionsData = _NO_ACTIONS,
    runner: _StubRunner | None = None,
    preview_text: str | None = None,
) -> CustomGateModal:
    data = CustomGateModalData(
        request_id="gate-actions",
        title="Custom Gate",
        sender="review-agent",
        icon="🛡️",
        notes=("Review guarded work.",),
        attachments=(),
        preview_name="plan.md" if preview_text else None,
        preview_text=preview_text,
        gate=GateBranchData(
            query="test query",
            options=options,
            groups=groups,
            branches=branches,
            primary_branch=branches[0],
        ),
        actions=actions,
    )
    return CustomGateModal(data, action_runner=runner)


async def test_gate_without_actions_renders_no_actions_section() -> None:
    modal = _modal(options=(_option("proceed"),), branches=(("proceed",),))

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        assert not modal.query(GateActionControls)
        assert modal.query_one("#gate-singleton-0", Button).has_focus


async def test_actions_render_bound_keys_and_join_focus_traversal() -> None:
    modal = _modal(
        options=(_option("proceed"), _option("reject")),
        branches=(("proceed",), ("reject",)),
        actions=GateActionsData(operations=(_edit_operation(), _run_operation())),
        runner=_StubRunner(),
    )

    async with _TestApp().run_test(size=(100, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        assert str(modal.query_one("#gate-action-0", Button).label) == "e ✏️ Edit plan"
        assert str(modal.query_one("#gate-action-1", Button).label) == "x Show diff"
        assert (
            "Accepted only when"
            in modal.query_one("#gate-action-description-0", Static).render().plain
        )

        # Actions come first in the ring, then the Decision controls.
        assert modal.query_one("#gate-action-0", Button).has_focus
        await pilot.press("j")
        assert modal.query_one("#gate-action-1", Button).has_focus
        await pilot.press("j")
        assert modal.query_one("#gate-singleton-0", Button).has_focus
        await pilot.press("k")
        assert modal.query_one("#gate-action-1", Button).has_focus


async def test_configured_keymap_collision_reassigns_and_renders_the_bound_key() -> (
    None
):
    # The reviewer rebound toggle to "e", which creation could not have known.
    keymaps = GateModalKeymaps(toggle_option="e")
    data = CustomGateModalData(
        request_id="gate-actions",
        title="Custom Gate",
        sender="review-agent",
        icon="🛡️",
        notes=(),
        attachments=(),
        preview_name=None,
        preview_text=None,
        gate=GateBranchData(
            query="q",
            options=(_option("proceed"),),
            groups=(),
            branches=(("proceed",),),
            primary_branch=("proceed",),
        ),
        actions=GateActionsData(operations=(_edit_operation(),)),
    )
    runner = _StubRunner()
    modal = CustomGateModal(data, gate_keymaps=keymaps, action_runner=runner)

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        label = str(modal.query_one("#gate-action-0", Button).label)
        bound = label.split(" ", 1)[0]
        assert bound != "e"
        assert label == f"{bound} ✏️ Edit plan"
        await pilot.press(bound)
        await pilot.pause()

    assert runner.edited == ["edit_plan"]


def test_declared_key_wins_when_free_and_falls_back_when_taken() -> None:
    operations = (_edit_operation(), _run_operation())
    assert resolve_gate_action_keys(operations, taken=set()) == {
        "edit_plan": "e",
        "show_diff": "x",
    }
    reassigned = resolve_gate_action_keys(operations, taken={"e", "x"})
    assert reassigned["edit_plan"] not in {"e", "x"}
    assert reassigned["show_diff"] not in {"e", "x", reassigned["edit_plan"]}


def test_open_inputs_key_is_withheld_from_declared_gate_action_keys() -> None:
    taken = gate_modal_taken_keys((), GateModalKeymaps())
    assert "i" in taken
    resolved = resolve_gate_action_keys((_edit_operation(key="i"),), taken=taken)
    assert resolved["edit_plan"] != "i"

    remapped = gate_modal_taken_keys((), GateModalKeymaps(open_inputs="o"))
    assert "i" not in remapped
    assert "o" in remapped
    assert (
        resolve_gate_action_keys((_edit_operation(key="i"),), taken=remapped)[
            "edit_plan"
        ]
        == "i"
    )


async def test_accepted_edit_keeps_the_modal_and_the_reviewers_work() -> None:
    runner = _StubRunner(
        edit=GateEditOutcome(accepted=True, content="# Revised plan\n")
    )
    group = GateGroup(options=("approve", "commit"), label="Approve", icon="✅")
    results: list[CustomGateModalResult | None] = []
    modal = _modal(
        options=(_option("approve", feedback="optional"), _option("commit")),
        branches=(("approve", "commit"),),
        groups=(group,),
        actions=GateActionsData(operations=(_edit_operation(),)),
        runner=runner,
        preview_text="# Plan\n",
    )

    async with _TestApp().run_test(size=(120, 44)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        controls = modal.query_one(GateBranchControls)
        # Deselect one AND member so the surviving selection is not the default.
        controls.toggle_option(0, 1)
        await pilot.pause()
        assert controls.selected_option_ids(0) == ("approve",)
        await pilot.pause()

        await pilot.press("e")
        await pilot.pause()

        # The modal is still the active screen and nothing was reset.
        assert runner.edited == ["edit_plan"]
        assert pilot.app.screen is modal
        assert controls.selected_option_ids(0) == ("approve",)
        assert "Revised plan" in _preview_text(modal)
        assert results == []


async def test_unaccepted_draft_shows_the_banner_and_blocks_every_submit() -> None:
    runner = _StubRunner(
        edit=GateEditOutcome(
            accepted=False,
            message="plan validate failed",
            draft=True,
            draft_path="~/.sase/plans/202608/foo.md",
        )
    )
    results: list[CustomGateModalResult | None] = []
    modal = _modal(
        options=(_option("approve"), _option("reject")),
        branches=(("approve",), ("reject",)),
        actions=GateActionsData(operations=(_edit_operation(),)),
        runner=runner,
    )

    async with _TestApp().run_test(size=(110, 40)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()

        banner = modal.query_one("#gate-draft-banner", Static)
        assert not banner.has_class("hidden")
        rendered = banner.render().plain
        assert "Draft not accepted" in rendered
        assert "~/.sase/plans/202608/foo.md" in rendered
        assert modal.query_one("#gate-singleton-0", Button).disabled
        assert modal.query_one("#gate-singleton-1", Button).disabled

        # Rejecting is blocked too: a submit would overwrite the draft.
        await pilot.press("2")
        await pilot.pause()
        assert results == []


async def test_a_draft_found_on_open_blocks_submission_immediately() -> None:
    """A draft left by an earlier session — or another editor — blocks on open."""
    results: list[CustomGateModalResult | None] = []
    modal = _modal(
        options=(_option("approve"), _option("reject")),
        branches=(("approve",), ("reject",)),
        actions=GateActionsData(
            operations=(_edit_operation(),),
            draft_operation_id="edit_plan",
            draft_path="~/.sase/plans/202608/foo.md",
        ),
        runner=_StubRunner(),
    )

    async with _TestApp().run_test(size=(110, 40)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()

        assert not modal.query_one("#gate-draft-banner", Static).has_class("hidden")
        assert modal.query_one("#gate-singleton-0", Button).disabled
        await pilot.press("1")
        await pilot.pause()

    assert results == []


async def test_draft_clears_once_a_later_edit_is_accepted() -> None:
    runner = _StubRunner(
        edit=GateEditOutcome(accepted=False, message="invalid", draft=True)
    )
    modal = _modal(
        options=(_option("approve"),),
        branches=(("approve",),),
        actions=GateActionsData(operations=(_edit_operation(),)),
        runner=runner,
    )

    async with _TestApp().run_test(size=(110, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        assert modal.query_one("#gate-singleton-0", Button).disabled

        runner.edit_outcome = GateEditOutcome(accepted=True, content="fixed")
        await pilot.press("e")
        await pilot.pause()
        assert modal.query_one("#gate-draft-banner", Static).has_class("hidden")
        assert not modal.query_one("#gate-singleton-0", Button).disabled


async def test_discard_draft_confirms_before_restoring_the_reviewed_copy() -> None:
    runner = _StubRunner(
        edit=GateEditOutcome(accepted=False, message="invalid", draft=True),
        discard=GateEditOutcome(accepted=True, content="# Reviewed\n"),
    )
    modal = _modal(
        options=(_option("approve"),),
        branches=(("approve",),),
        actions=GateActionsData(
            operations=(_edit_operation(),), draft_path="~/.sase/plans/foo.md"
        ),
        runner=runner,
        preview_text="# Draft\n",
    )

    async with _TestApp().run_test(size=(110, 44)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()

        await pilot.press("D")
        await pilot.pause()
        assert runner.discarded == []
        await pilot.press("y")
        await pilot.pause()

        assert runner.discarded == ["edit_plan"]
        assert modal.query_one("#gate-draft-banner", Static).has_class("hidden")
        assert not modal.query_one("#gate-singleton-0", Button).disabled


async def test_run_command_shows_output_and_leaves_the_gate_answerable() -> None:
    runner = _StubRunner(
        command=GateCommandOutcome(
            success=True,
            summary="3 files changed",
            body="```diff\n+one\n```",
            display_format="markdown",
        )
    )
    results: list[CustomGateModalResult | None] = []
    modal = _modal(
        options=(_option("approve"),),
        branches=(("approve",),),
        actions=GateActionsData(operations=(_run_operation(),)),
        runner=runner,
    )

    async with _TestApp().run_test(size=(110, 40)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("x")
        await pilot.pause()

        assert runner.ran == ["show_diff"]
        assert isinstance(pilot.app.screen, GateActionOutputModal)
        await pilot.press("q")
        await pilot.pause()

        # The gate is still open and still answerable.
        assert pilot.app.screen is modal
        assert results == []
        await pilot.press("1")
        await pilot.pause()

    assert results == [CustomGateModalResult(("approve",), None)]


async def test_refreshing_action_reloads_the_reviewed_document() -> None:
    runner = _StubRunner(
        edit=GateEditOutcome(accepted=True, content="# Regenerated\n"),
        command=GateCommandOutcome(success=True, summary="regenerated", refresh=True),
    )
    modal = _modal(
        options=(_option("approve"),),
        branches=(("approve",),),
        actions=GateActionsData(operations=(_run_operation(),)),
        runner=runner,
        preview_text="# Original\n",
    )

    async with _TestApp().run_test(size=(110, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.press("x")
        await pilot.pause()
        assert "Regenerated" in _preview_text(modal)

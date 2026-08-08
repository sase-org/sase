"""Host contract and modal wiring for repeatable gate actions.

The modals render actions and react to their results; they never touch a
bundle themselves. Everything that needs a bundle path — running the editor,
accepting an edited origin, executing a ``run_command`` action — lives behind
:class:`GateActionRunner`, which the notification layer implements and the
tests replace with a stub.

The point of running an action *through* the open modal rather than by
dismissing it is that a reviewer's work survives: branch selection, toggled
AND members, typed feedback, and scroll position are all still there when the
editor exits, which is what makes an action feel repeatable instead of
destructive.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from typing import Protocol

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widget import Widget

from sase.notification_gates.model_operations import GateOperation

from .gate_action_controls import (
    GateActionControls,
    GateActionsData,
    resolve_gate_action_keys,
)
from .gate_branch_controls import GateBranchControls


@dataclass(frozen=True)
class GateEditOutcome:
    """What one ``edit_file`` round trip did to the reviewed content."""

    accepted: bool
    content: str | None = None
    message: str | None = None
    draft: bool = False
    draft_path: str | None = None


@dataclass(frozen=True)
class GateCommandOutcome:
    """The display projection of one ``run_command`` action run."""

    success: bool
    summary: str | None = None
    body: str | None = None
    display_format: str = "text"
    refresh: bool = False
    message: str | None = None


class GateActionRunner(Protocol):
    """What a gate modal needs from its host to run declared actions."""

    def run_edit(self, operation_id: str) -> GateEditOutcome:
        """Open the editor for one action and accept the result, or reject it."""
        ...

    def discard_draft(self, operation_id: str) -> GateEditOutcome:
        """Restore the origin file from the reviewed copy."""
        ...

    def run_command(
        self, operation_id: str, on_done: Callable[[GateCommandOutcome], None]
    ) -> bool:
        """Run one ``run_command`` action, reporting its outcome when it ends."""
        ...

    def reviewed_content(self) -> str | None:
        """Re-verify the bundle and return its reviewed document text."""
        ...


def gate_modal_taken_keys(
    static_bindings: Sequence[tuple[str, str, str]], keymaps: object
) -> set[str]:
    """Return every single-character key a gate modal already owns.

    Creation-time validation cannot see the reviewer's configured keymap, so
    this is the render-time half of the same rule: whatever the modal binds
    for itself is unavailable to a declared action key.
    """
    taken = {GateActionControls.DISCARD_DRAFT_KEY}
    taken.update(key for key, _action, _description in static_bindings)
    taken.update(
        value
        for value in vars(keymaps).values()
        if isinstance(value, str) and len(value) == 1
    )
    return taken


class GateActionsMixin:
    """Compose, bind, and drive the Actions section of a gate modal.

    The mixin owns nothing a modal already owns: it reads the branch controls
    for submit blocking and calls back into the modal to re-render its own
    document pane, so plan and custom gates share one implementation without
    sharing a layout.
    """

    _gate_actions: GateActionsData
    _gate_action_runner: GateActionRunner | None

    def _init_gate_actions(
        self,
        actions: GateActionsData | None,
        runner: GateActionRunner | None,
        *,
        taken_keys: Collection[str],
    ) -> None:
        self._gate_actions = actions or GateActionsData()
        self._gate_action_runner = runner
        self._gate_action_taken_keys = tuple(taken_keys)
        self._gate_action_controls: GateActionControls | None = None

    def gate_action_hints(self, *, separator: str = " ") -> Text:
        """Render footer hints for the keys the actions were actually bound to.

        The key shown is the one the modal bound, not the one the gate
        declared, so a reviewer whose keymap forced a reassignment reads the
        key that will actually work.
        """
        text = Text()
        controls = self._mounted_action_controls()
        keys = (
            controls.keys
            if controls is not None
            else resolve_gate_action_keys(
                self._gate_actions.operations, taken=self._gate_action_taken_keys
            )
        )
        for operation in self._gate_actions.operations:
            key = keys.get(operation.id)
            if key is not None:
                text.append(key, style="blue")
                text.append(f"{separator}{operation.label}  ")
        return text

    def _gate_action_bindings(self) -> list[Binding]:
        """Return the modal-scoped bindings for the resolved action keys."""
        if not self._gate_actions.operations:
            return []
        resolved = resolve_gate_action_keys(
            self._gate_actions.operations, taken=self._gate_action_taken_keys
        )
        bindings = [
            Binding(
                key,
                f"run_gate_action('{operation_id}')",
                f"Run {operation_id}",
                show=False,
                priority=True,
            )
            for operation_id, key in resolved.items()
            if key is not None
        ]
        bindings.append(
            Binding(
                GateActionControls.DISCARD_DRAFT_KEY,
                "discard_gate_draft",
                "Discard draft",
                show=False,
                priority=True,
            )
        )
        return bindings

    def _compose_gate_actions(self) -> ComposeResult:
        """Yield the Actions section, or nothing when the gate declares none."""
        if not self._gate_actions.operations:
            return
        from textual.widgets import Static

        yield Static("Actions", classes="gate-review-section-title")
        controls = GateActionControls(
            self._gate_actions,
            taken_keys=self._gate_action_taken_keys,
            id="gate-actions",
        )
        self._gate_action_controls = controls
        yield controls

    # -- traversal ---------------------------------------------------------

    def _gate_control_ids(self) -> list[str]:
        controls = self._mounted_action_controls()
        action_ids = [] if controls is None else controls.control_ids()
        branch = self._branch_controls()
        return action_ids + (
            [] if branch is None else branch.visible_control_ids()  # type: ignore[union-attr]
        )

    def focus_gate_control(self, delta: int) -> None:
        """Move focus across the Actions and Decision controls as one ring."""
        control_ids = self._gate_control_ids()
        if not control_ids:
            return
        focused = self.screen.focused  # type: ignore[attr-defined]
        focused_id = focused.id if isinstance(focused, Widget) else None
        try:
            current = control_ids.index(focused_id or "")
        except ValueError:
            current = -1 if delta > 0 else 0
        target = control_ids[(current + delta) % len(control_ids)]
        self.query_one(f"#{target}", Widget).focus(scroll_visible=False)  # type: ignore[attr-defined]

    # -- action dispatch ---------------------------------------------------

    def action_run_gate_action(self, operation_id: str) -> None:
        """Run one declared action without dismissing the modal."""
        self._run_gate_action(operation_id)

    def action_discard_gate_draft(self) -> None:
        """Ask, with confirmation, to throw away an unaccepted origin draft."""
        controls = self._mounted_action_controls()
        if controls is not None:
            controls.request_discard_draft()

    def on_gate_action_controls_triggered(
        self, event: GateActionControls.Triggered
    ) -> None:
        event.stop()
        self._run_gate_action(event.operation_id)

    def on_gate_action_controls_discard_draft_requested(
        self, event: GateActionControls.DiscardDraftRequested
    ) -> None:
        event.stop()
        self._confirm_discard_draft(event.operation_id)

    def _run_gate_action(self, operation_id: str) -> None:
        runner = self._gate_action_runner
        operation = self._gate_operation(operation_id)
        if operation is None:
            return
        if runner is None:
            self.notify(  # type: ignore[attr-defined]
                "Gate actions are unavailable for this gate", severity="warning"
            )
            return
        if operation.kind == "edit_file":
            self._apply_edit_outcome(operation_id, runner.run_edit(operation_id))
            return
        if not runner.run_command(operation_id, self._apply_command_outcome):
            self.notify(  # type: ignore[attr-defined]
                f"Could not run action: {operation.label}", severity="error"
            )

    def _confirm_discard_draft(self, operation_id: str) -> None:
        from .confirm_dialog import ConfirmDialog, ConfirmKind

        def on_confirmed(confirmed: bool | None) -> None:
            runner = self._gate_action_runner
            if not confirmed or runner is None:
                return
            self._apply_edit_outcome(operation_id, runner.discard_draft(operation_id))

        self.app.push_screen(  # type: ignore[attr-defined]
            ConfirmDialog(
                "Discard draft",
                "Restore the edited file from the reviewed copy?",
                subject=self._gate_actions.draft_path,
                kind=ConfirmKind.DANGER,
                confirm_label="Discard",
                cancel_label="Keep",
            ),
            on_confirmed,
        )

    # -- outcome application ----------------------------------------------

    def _apply_edit_outcome(self, operation_id: str, outcome: GateEditOutcome) -> None:
        if outcome.content is not None:
            self.render_reviewed_content(outcome.content)
        controls = self._mounted_action_controls()
        if controls is not None:
            controls.set_draft(
                operation_id if outcome.draft else None, outcome.draft_path
            )
        self._sync_submission_block()
        if outcome.message is None:
            return
        if outcome.accepted:
            self.notify(outcome.message)  # type: ignore[attr-defined]
            return
        # A rejection carries validation diagnostics worth reading, so it gets
        # a long timeout rather than the default few seconds.
        self.notify(  # type: ignore[attr-defined]
            outcome.message,
            title="Edit rejected",
            severity="error",
            timeout=15,
        )

    def _apply_command_outcome(self, outcome: GateCommandOutcome) -> None:
        if outcome.refresh:
            runner = self._gate_action_runner
            content = None if runner is None else runner.reviewed_content()
            if content is not None:
                self.render_reviewed_content(content)
        if outcome.summary:
            self.notify(  # type: ignore[attr-defined]
                outcome.summary,
                severity="information" if outcome.success else "error",
            )
        elif outcome.message:
            self.notify(  # type: ignore[attr-defined]
                outcome.message,
                severity="information" if outcome.success else "error",
            )
        if not outcome.body:
            return
        from .gate_action_output_modal import GateActionOutputModal

        self.app.push_screen(  # type: ignore[attr-defined]
            GateActionOutputModal(
                title=outcome.summary or "Action output",
                body=outcome.body,
                display_format=outcome.display_format,
            )
        )

    def _sync_submission_block(self) -> None:
        """Disable every submit control while an unaccepted draft exists."""
        branch = self._branch_controls()
        controls = self._mounted_action_controls()
        if branch is None:
            return
        blocked = controls is not None and controls.draft_operation_id is not None
        branch.block_submission(  # type: ignore[union-attr]
            "Accept or discard your draft before submitting" if blocked else None
        )

    # -- modal hooks -------------------------------------------------------

    def render_reviewed_content(self, content: str) -> None:
        """Re-render the modal's document pane with newly accepted content."""

    def _branch_controls(self) -> GateBranchControls | None:
        try:
            return self.query_one(GateBranchControls)  # type: ignore[attr-defined,no-any-return]
        except Exception:
            return None

    def _mounted_action_controls(self) -> GateActionControls | None:
        controls = self._gate_action_controls
        return controls if controls is not None and controls.is_mounted else None

    def _gate_operation(self, operation_id: str) -> GateOperation | None:
        for operation in self._gate_actions.operations:
            if operation.id == operation_id:
                return operation
        return None


__all__ = [
    "GateActionRunner",
    "gate_modal_taken_keys",
    "GateActionsMixin",
    "GateCommandOutcome",
    "GateEditOutcome",
]

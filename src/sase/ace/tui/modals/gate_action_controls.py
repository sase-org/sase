"""Shared **Actions** section for ACE notification-gate modals.

A gate action is repeatable and never answers the gate, so it is rendered as
its own section above **Decision** rather than as another way to submit. The
section is omitted entirely when a gate declares no actions, which is what
keeps every gate written before actions existed looking exactly as it did.

A declared key is rejected at creation when it collides with a static modal
binding, but a collision with a *user-configured* keymap cannot be known then.
This module resolves those at render time by reassigning from the shared
fallback pool and rendering the key it actually bound, so what the reviewer
reads is always what the modal will run.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Button, Static

from sase.notification_gates.action_keys import GATE_ACTION_FALLBACK_KEYS
from sase.notification_gates.model_operations import GateOperation


@dataclass(frozen=True)
class GateActionsData:
    """Declared actions plus the draft state a surface must warn about."""

    operations: tuple[GateOperation, ...] = ()
    draft_operation_id: str | None = None
    draft_path: str | None = None


class _GateActionButton(Button):
    """Button carrying the action id it runs."""

    def __init__(self, *args: object, operation_id: str, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.operation_id = operation_id


def resolve_gate_action_keys(
    operations: Sequence[GateOperation], *, taken: Collection[str]
) -> dict[str, str | None]:
    """Map each action id to the key a modal can actually bind for it.

    A declared key wins unless the reviewer's own keymap already owns it, in
    which case the action falls back to the first free key in the shared pool.
    An action that cannot be given any key is still rendered and focusable —
    it just has no shortcut.
    """
    unavailable = {key for key in taken if len(key) == 1}
    resolved: dict[str, str | None] = {}
    for operation in operations:
        declared = operation.key
        if declared is not None and declared not in unavailable:
            resolved[operation.id] = declared
            unavailable.add(declared)
            continue
        fallback = next(
            (key for key in GATE_ACTION_FALLBACK_KEYS if key not in unavailable), None
        )
        resolved[operation.id] = fallback
        if fallback is not None:
            unavailable.add(fallback)
    return resolved


class GateActionControls(Vertical):
    """Render the declared non-terminal actions and the unaccepted-draft banner."""

    class Triggered(Message):
        """The reviewer asked to run one declared action."""

        def __init__(self, operation_id: str) -> None:
            super().__init__()
            self.operation_id = operation_id

    class DiscardDraftRequested(Message):
        """The reviewer asked to throw away an unaccepted origin draft."""

        def __init__(self, operation_id: str) -> None:
            super().__init__()
            self.operation_id = operation_id

    DISCARD_DRAFT_KEY = "D"

    def __init__(
        self,
        data: GateActionsData,
        *,
        taken_keys: Collection[str] = (),
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.data = data
        self.keys = resolve_gate_action_keys(data.operations, taken=taken_keys)
        self._draft_operation_id = data.draft_operation_id
        self._draft_path = data.draft_path

    def compose(self) -> ComposeResult:
        for index, operation in enumerate(self.data.operations):
            yield _GateActionButton(
                self._action_label(operation),
                operation_id=operation.id,
                id=f"gate-action-{index}",
                classes="gate-action",
            )
            if operation.description:
                yield Static(
                    Text(operation.description, style="dim"),
                    id=f"gate-action-description-{index}",
                    classes="gate-action-description",
                )
        yield Static(
            self._banner_text(),
            id="gate-draft-banner",
            classes=(
                "gate-draft-banner"
                if self._draft_operation_id
                else "gate-draft-banner hidden"
            ),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button = event.button
        if not isinstance(button, _GateActionButton):
            return
        event.stop()
        self.post_message(self.Triggered(button.operation_id))

    def control_ids(self) -> list[str]:
        """Return the focusable action control ids, in render order."""
        return [f"gate-action-{index}" for index in range(len(self.data.operations))]

    def request_discard_draft(self) -> bool:
        """Ask to discard the pending draft; ``False`` when there is none."""
        if self._draft_operation_id is None:
            return False
        self.post_message(self.DiscardDraftRequested(self._draft_operation_id))
        return True

    @property
    def draft_operation_id(self) -> str | None:
        return self._draft_operation_id

    def set_draft(
        self, operation_id: str | None, draft_path: str | None = None
    ) -> None:
        """Show or clear the unaccepted-draft banner."""
        self._draft_operation_id = operation_id
        if draft_path is not None:
            self._draft_path = draft_path
        if not self.is_mounted:
            return
        banner = self.query_one("#gate-draft-banner", Static)
        banner.update(self._banner_text())
        if operation_id is None:
            banner.add_class("hidden")
        else:
            banner.remove_class("hidden")

    def _banner_text(self) -> Text:
        if self._draft_operation_id is None:
            return Text()
        key = self.keys.get(self._draft_operation_id) or "the edit action"
        path = self._draft_path or "the edited file"
        text = Text()
        text.append("⚠ Draft not accepted", style="bold yellow")
        text.append(f" — {path} differs from the reviewed content.\n", style="yellow")
        text.append(
            f"Press {key} to fix it, or {self.DISCARD_DRAFT_KEY} to discard your draft.",
            style="dim",
        )
        return text

    def _action_label(self, operation: GateOperation) -> str:
        key = self.keys.get(operation.id)
        parts = [part for part in (key, operation.icon, operation.label) if part]
        return " ".join(parts)


__all__ = [
    "GateActionControls",
    "GateActionsData",
    "resolve_gate_action_keys",
]

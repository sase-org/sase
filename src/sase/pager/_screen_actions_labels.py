"""Label-key handling and pending-action arming for ``PagerScreen``.

Owns the jump-hint label dispatch (``_handle_label_key``/``_activate_label``)
and the ``y``/``E``/``ctrl+w`` pending-action arms. Section dispatch,
copy/edit/follow targets, and resolve logic live in the sibling
``_screen_actions_*`` modules; this module never imports them.
"""

from __future__ import annotations

from typing import Any, Literal

from textual.events import Key

from sase.pager.jump_hints import (
    JumpHintMatchOutcome,
    match_jump_hint,
    normalize_jump_key,
)
from sase.pager._labels import PagerLabel, PagerLabelLayer
from sase.pager.link_scan import LinkSpanKind
from sase.pager.app import ViewPendingAction

__all__ = ["PagerActionLabelsMixin"]

# Attribute declarations mirror PagerBodyMixin so the combined view keeps
# one consistent type for each shared slot.

#: The key that arms each non-follow pending action, so a second press of
#: that same key can be recognized as the doubled ``yy``/``EE``/``ctrl+w
#: ctrl+w`` form (design doc section D8) instead of an invalid label key.
_PENDING_ACTION_KEYS: dict[ViewPendingAction, str] = {
    "copy": "y",
    "edit": "E",
    "other": "ctrl+w",
}


class PagerActionLabelsMixin:
    """Handle link labels and arm copy/edit/other-pane actions."""

    _label_layer: PagerLabelLayer | None
    _last_activated_label: PagerLabel | None
    _pending_action: ViewPendingAction

    def _handle_label_key(self: Any, event: Key) -> bool:
        layer = self._label_layer
        hint_to_label_index = layer.hint_to_label_index if layer is not None else {}
        armed = self._pending_action != "follow"
        if not hint_to_label_index and not armed:
            return False

        key = normalize_jump_key(event.key, event.character)
        if (
            armed
            and not self._label_pending_prefix
            and key == _PENDING_ACTION_KEYS[self._pending_action]
        ):
            # A second `y`/`E` press is the doubled form (D8) - fall through
            # to the binding that armed this prefix so it can recognize the
            # double-press itself, rather than swallowing it as invalid here.
            return False

        match = match_jump_hint(
            hint_to_label_index,
            self._label_pending_prefix,
            key,
        )
        if match.outcome is JumpHintMatchOutcome.PENDING:
            self._label_pending_prefix = match.prefix
            self._repaint_label_state()
            return True
        if match.outcome is JumpHintMatchOutcome.COMPLETE:
            label_index = match.target
            if label_index is None or layer is None:
                return False
            self._label_pending_prefix = ""
            self._activate_label(layer.labels[label_index])
            self._repaint_label_state()
            return True
        if self._label_pending_prefix or armed:
            self._label_pending_prefix = ""
            self._pending_action = "follow"
            try:
                self.pager_host._clear_other_preview()
            except Exception:
                pass
            self._repaint_label_state()
            self.notify("No link label matches that key.", severity="information")
            return True
        return False

    def action_arm_copy(self: Any) -> None:
        self._arm_pending_action("copy")

    def action_arm_edit(self: Any) -> None:
        self._arm_pending_action("edit")

    def action_arm_other(self: Any) -> None:
        """Arm an other-pane follow (``ctrl+w``).

        Arming captures the most recently focused other pane and lifts its
        frame to preview strength until the label lands or the arm is
        canceled. A doubled ``ctrl+w`` (pressed while already armed, with
        no label prefix pending) focuses the captured pane instead — with
        two panes this equals ``ctrl+f`` — and is a no-op when single.
        Either way the arm clears.
        """
        if self._pending_action == "other":
            self._pending_action = "follow"
            self._label_pending_prefix = ""
            self._repaint_label_state()
            try:
                self.pager_host.focus_other_view(self)
            except Exception:
                pass
            return
        self._pending_action = "other"
        self._label_pending_prefix = ""
        try:
            self.pager_host._arm_other_preview(self)
        except Exception:
            pass
        self._repaint_label_state()

    def _arm_pending_action(self: Any, action: Literal["copy", "edit"]) -> None:
        if self._pending_action == action:
            # Doubled (``yy``/``EE``): act on the current section itself,
            # per design doc section D8, rather than waiting on a label.
            self._pending_action = "follow"
            self._label_pending_prefix = ""
            self._dispatch_section_action(action)
            self._repaint_label_state()
            return
        self._pending_action = action
        self._label_pending_prefix = ""
        self._repaint_label_state()

    def _activate_label(self: Any, label: PagerLabel) -> None:
        self._last_activated_label = label
        action = self._pending_action
        self._pending_action = "follow"
        other_pane = action == "other"
        target = label.target
        context = self._link_context_for_section_index(label.section_index)

        handler = self._attached_handlers.get(target.kind)
        if handler is not None:
            # The internal ``"other"`` arm never reaches attached handlers;
            # they see the public ``"follow"`` contract value instead.
            handler(target, action if action != "other" else "follow")
            return

        origin = self._origin_for_section_index(label.section_index)
        if target.kind == LinkSpanKind.URL.value or action == "copy":
            self._copy_target(target, context=context, origin=origin)
            return
        if action == "edit":
            self._edit_target(target, context=context, origin=origin)
            return
        self._follow_target(
            target, context=context, origin=origin, other_pane=other_pane
        )

    def _repaint_label_state(self: Any) -> None:
        self._invalidate_body_paint()
        self._update_footer()

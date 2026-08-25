"""Compatibility stubs for retired Glossary panel write actions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
else:
    _MixinBase = object

_RETIRED_WRITE_MESSAGE = (
    "Glossary writes now use the Memory panel's glossary web controls."
)


class GlossaryPanelActionsMixin(_MixinBase):
    """Add-form and delete-confirmation actions for :class:`GlossaryPanel`."""

    if TYPE_CHECKING:
        _loading: bool
        _write_busy: bool
        is_mounted: bool
        app: Any

    def action_add_term(self) -> None:
        if self._loading or self._write_busy:
            return
        self.app.notify(_RETIRED_WRITE_MESSAGE, severity="warning")

    def action_delete_term(self) -> None:
        if self._loading or self._write_busy:
            return
        self.app.notify(_RETIRED_WRITE_MESSAGE, severity="warning")


__all__ = ["GlossaryPanelActionsMixin"]

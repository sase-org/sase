"""PromptTextArea mixin that warms the app-level bead-store directory."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase

    from sase.ace.tui.models.bead_preview import BeadStoreDirectory
else:
    _MixinBase = object


class PromptBeadMentionMixin(_MixinBase):
    """Warm the bead-store directory when the prompt mounts.

    Overlay styling of bead IDs is a later phase; this mixin only keeps the
    directory warm so K can take the synchronous non-bead fast path.
    """

    def _prompt_mount_hook(self) -> None:
        super_hook = getattr(super(), "_prompt_mount_hook", None)
        if callable(super_hook):
            super_hook()
        directory = self._bead_store_directory_for_action(schedule=True)
        del directory

    def _bead_store_directory_for_action(
        self,
        *,
        schedule: bool = False,
    ) -> BeadStoreDirectory | None:
        app = self._active_app()
        if app is None:
            return None
        getter = getattr(app, "get_bead_store_directory", None)
        if not callable(getter):
            return None
        try:
            value = getter(schedule=schedule)
        except Exception:
            return None
        return value

    def _active_app(self) -> Any | None:
        try:
            return self.app
        except Exception:
            return None


__all__ = ["PromptBeadMentionMixin"]

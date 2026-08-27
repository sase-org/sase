"""Standalone Textual host for the reusable pager screen."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from textual.app import App

from sase.pager.document import PagerDocument, PagerTargetSpan
from sase.pager.resolve import LinkTarget

PendingAction = Literal["follow", "copy", "edit"]

#: A caller-registered handler for one non-scanned `AttachedTarget` kind
#: (design doc section D3: "the scanner cannot recover ... objects, not
#: substrings"). Takes over a label press entirely; `resolve_ref` is never
#: consulted for a kind that has a handler, since there is no ref string to
#: resolve.
AttachedTargetHandler = Callable[[PagerTargetSpan, PendingAction], None]
ResolveRef = Callable[[str], LinkTarget | None]


@dataclass(frozen=True, slots=True)
class PagerExit:
    """The result of a finished ``SasePager`` run.

    ``trail_exhausted`` lets a host resume its own history when a pager-owned
    trail has already been fully walked back.
    """

    trail_exhausted: bool = False


class SasePager(App[PagerExit]):
    """Standalone app wrapper that hosts ``PagerScreen`` for CLI entry points."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self,
        document: PagerDocument,
        *,
        links_enabled: bool = True,
        attached_handlers: Mapping[str, AttachedTargetHandler] | None = None,
        resolve_ref_fn: ResolveRef | None = None,
    ) -> None:
        super().__init__()
        self.document = document
        self.links_enabled = links_enabled
        self._attached_handlers: Mapping[str, AttachedTargetHandler] = (
            {} if attached_handlers is None else attached_handlers
        )
        self._resolve_ref_fn = resolve_ref_fn

    def on_mount(self) -> None:
        from sase.pager.screen import PagerScreen

        self.push_screen(
            PagerScreen(
                self.document,
                links_enabled=self.links_enabled,
                attached_handlers=self._attached_handlers,
                resolve_ref_fn=self._resolve_ref_fn,
            ),
            callback=self.exit,
        )


__all__ = [
    "AttachedTargetHandler",
    "PagerExit",
    "PendingAction",
    "ResolveRef",
    "SasePager",
]

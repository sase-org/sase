"""PromptTextArea mixin that previews the bead under the cursor on K."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from sase.ace.tui.models.bead_preview import (
    BeadRouteAmbiguous,
    BeadRouteFound,
    BeadRouteMissing,
    BeadRouteNotBead,
    BeadRouteUnavailable,
    BeadStoreDirectory,
    load_bead_store_directory,
    route_bead_mention,
)
from sase.ace.tui.widgets._prompt_preview import PreviewFallbackSnapshot
from sase.bead.mentions import bead_mention_at

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


class PromptBeadPreviewMixin(_MixinBase):
    """Insert the bead step into the prompt K chain."""

    if TYPE_CHECKING:
        _prompt_preview_request_id: int

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _bead_store_directory_for_action(
            self,
            *,
            schedule: bool = False,
        ) -> BeadStoreDirectory | None: ...
        def _macro_arg_assist_project_from_text(self) -> str | None: ...
        def _resume_preview_fallback(
            self,
            snapshot: PreviewFallbackSnapshot,
            *,
            bead_miss: str | None = None,
        ) -> None: ...

    def _preview_bead_under_cursor(self, fallback: PreviewFallbackSnapshot) -> bool:
        """Preview the bead under the cursor, or return ``False`` to continue.

        The only synchronous work is mention detection and a memory-only
        prefix-ownership check against a warm directory. Routing and loads
        run off-thread.
        """
        offset = self._absolute_offset(self.cursor_location)
        mention = bead_mention_at(self.text, offset)
        if mention is None:
            return False

        directory = self._bead_store_directory_for_action(schedule=False)
        if directory is not None and not directory.owns_prefix(mention.prefix):
            if mention.form == "bare":
                return False
            self.notify(
                f"No enabled project owns bead prefix '{mention.prefix}'",
                severity="warning",
            )
            return True

        self._prompt_preview_request_id += 1
        request_id = self._prompt_preview_request_id
        cursor = self.cursor_location
        project_ref = self._project_ref_for_bead_route()
        self.run_worker(
            self._resolve_bead_preview_async(
                mention.bead_id,
                mention.form,
                mention.prefix,
                fallback,
                project_ref=project_ref,
                request_id=request_id,
                cursor=cursor,
            ),
            name=f"prompt-bead-preview:{request_id}",
        )
        return True

    async def _resolve_bead_preview_async(
        self,
        bead_id: str,
        form: str,
        prefix: str,
        fallback: PreviewFallbackSnapshot,
        *,
        project_ref: str | None,
        request_id: int,
        cursor: tuple[int, int],
    ) -> None:
        directory, generation = await asyncio.to_thread(
            self._load_directory_for_preview,
        )
        if not self._bead_preview_request_is_current(request_id, cursor):
            return
        if directory is None:
            return

        if generation is not None:
            self._publish_loaded_directory(directory, generation)

        if form == "ref" and not directory.owns_prefix(prefix):
            self.notify(
                f"No enabled project owns bead prefix '{prefix}'",
                severity="warning",
            )
            return

        route = await asyncio.to_thread(
            route_bead_mention,
            bead_id,
            directory,
            project_ref=project_ref,
        )
        if not self._bead_preview_request_is_current(request_id, cursor):
            return

        if isinstance(route, BeadRouteNotBead):
            if form == "ref":
                self.notify(
                    f"No enabled project owns bead prefix '{prefix}'",
                    severity="warning",
                )
                return
            self._resume_preview_fallback(fallback)
            return
        if isinstance(route, BeadRouteFound):
            from sase.ace.tui.modals.bead_preview_modal import BeadPreviewModal

            self.app.push_screen(BeadPreviewModal(route.store, route.bead_id))
            return
        if isinstance(route, BeadRouteMissing):
            miss = _missing_bead_message(route.bead_id, route.project_labels)
            if form == "ref":
                self.notify(miss, severity="information")
                return
            self._resume_preview_fallback(fallback, bead_miss=miss)
            return
        if isinstance(route, BeadRouteAmbiguous):
            labels = ", ".join(route.project_labels)
            self.notify(
                f"Bead '{route.bead_id}' matches multiple projects ({labels}); "
                "add a +project tag",
                severity="warning",
            )
            return
        if isinstance(route, BeadRouteUnavailable):
            self.notify(
                f"{route.project_label} beads are unavailable: {route.reason}",
                severity="warning",
            )

    def _load_directory_for_preview(
        self,
    ) -> tuple[BeadStoreDirectory | None, int | None]:
        directory = self._bead_store_directory_for_action(schedule=False)
        if directory is not None:
            return directory, None
        app = getattr(self, "_active_app", lambda: None)()
        generation = (
            int(getattr(app, "_bead_store_directory_generation", 0))
            if app is not None
            else 0
        )
        return load_bead_store_directory(), generation

    def _publish_loaded_directory(
        self,
        directory: BeadStoreDirectory,
        generation: int,
    ) -> None:
        app = getattr(self, "_active_app", lambda: None)()
        if app is None:
            return
        publisher = getattr(app, "publish_bead_store_directory", None)
        if callable(publisher):
            publisher(directory, generation=generation)

    def _project_ref_for_bead_route(self) -> str | None:
        getter = getattr(self, "_macro_arg_assist_project_from_text", None)
        if not callable(getter):
            return None
        try:
            value = getter()
        except Exception:
            return None
        return value if isinstance(value, str) and value else None

    def _bead_preview_request_is_current(
        self,
        request_id: int,
        cursor: tuple[int, int],
    ) -> bool:
        if request_id != self._prompt_preview_request_id or not self.is_mounted:
            return False
        return self.cursor_location == cursor


def _missing_bead_message(bead_id: str, project_labels: tuple[str, ...]) -> str:
    if not project_labels:
        return f"No bead '{bead_id}'"
    return f"No bead '{bead_id}' in {project_labels[0]}"


__all__ = ["PromptBeadPreviewMixin"]

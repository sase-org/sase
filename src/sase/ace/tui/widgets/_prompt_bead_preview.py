"""PromptTextArea mixin that previews the bead under the cursor on K."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from sase.ace.tui.models.bead_preview import (
    BeadRoute,
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
from sase.pager.beads import bead_detail_link_resolution
from sase.pager.link_context import LinkAnchor, LinkResolutionContext
from sase.pager.targets import LinkResolution

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase

    from sase.ace.tui.widgets._prompt_jump_target import JumpToken
else:
    _MixinBase = object


class PromptBeadPreviewMixin(_MixinBase):
    """Insert the bead step into the prompt K chain."""

    if TYPE_CHECKING:
        _prompt_preview_request_id: int
        _prompt_jump_request_id: int

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _active_app(self) -> Any | None: ...
        def _bead_store_directory_for_action(
            self,
            *,
            schedule: bool = False,
        ) -> BeadStoreDirectory | None: ...
        def _macro_arg_assist_project_from_text(self) -> str | None: ...
        def _bead_mention_context_key(self) -> str | None: ...
        def _preview_context(self) -> tuple[str | None, str]: ...
        def _resolve_jump_async(
            self,
            token: JumpToken,
            *,
            project: str | None,
            base_dir: str,
            request_id: int,
            prefer_load: bool = False,
            is_current: Callable[[], bool] | None = None,
        ) -> Any: ...
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
        context_key = self._bead_mention_context_key()
        text_snapshot = self.text
        selection_snapshot = getattr(self, "selection", None)
        context_snapshot = self._bead_prompt_context_snapshot()
        directory_generation = self._bead_store_directory_generation()
        self.run_worker(
            self._resolve_bead_preview_async(
                mention.bead_id,
                mention.form,
                mention.prefix,
                fallback,
                project_ref=project_ref,
                context_key=context_key,
                request_id=request_id,
                cursor=cursor,
                text_snapshot=text_snapshot,
                selection_snapshot=selection_snapshot,
                context_snapshot=context_snapshot,
                directory_generation=directory_generation,
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
        context_key: str | None,
        request_id: int,
        cursor: tuple[int, int],
        text_snapshot: str,
        selection_snapshot: object,
        context_snapshot: tuple[object, ...],
        directory_generation: int,
    ) -> None:
        try:
            directory, generation = await asyncio.to_thread(
                self._load_directory_for_preview,
                directory_generation,
            )
        except Exception as exc:
            if self._bead_preview_request_is_current(
                request_id,
                cursor,
                text_snapshot,
                selection_snapshot,
                context_snapshot,
                directory_generation,
            ):
                self.notify(
                    f"Could not load bead stores: {exc}",
                    severity="warning",
                )
            return
        if not self._bead_preview_request_is_current(
            request_id,
            cursor,
            text_snapshot,
            selection_snapshot,
            context_snapshot,
            directory_generation,
        ):
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

        try:
            route = await asyncio.to_thread(
                route_bead_mention,
                bead_id,
                directory,
                project_ref=project_ref,
            )
        except Exception as exc:
            if self._bead_preview_request_is_current(
                request_id,
                cursor,
                text_snapshot,
                selection_snapshot,
                context_snapshot,
                directory_generation,
            ):
                self.notify(
                    f"Could not resolve bead '{bead_id}': {exc}",
                    severity="warning",
                )
            return
        if not self._bead_preview_request_is_current(
            request_id,
            cursor,
            text_snapshot,
            selection_snapshot,
            context_snapshot,
            directory_generation,
        ):
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
            self._note_bead_mention_resolved(
                route.bead_id,
                project_ref=project_ref,
                context_key=context_key,
            )
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

    def _jump_to_bead_under_cursor(self) -> bool:
        """Open the full bead detail for the ID under the cursor, if any."""
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

        self._prompt_jump_request_id += 1
        request_id = self._prompt_jump_request_id
        cursor = self.cursor_location
        project_ref = self._project_ref_for_bead_route()
        context_key = self._bead_mention_context_key()
        text_snapshot = self.text
        selection_snapshot = getattr(self, "selection", None)
        context_snapshot = self._bead_prompt_context_snapshot()
        directory_generation = self._bead_store_directory_generation()
        self.run_worker(
            self._resolve_bead_jump_async(
                mention.bead_id,
                mention.form,
                mention.prefix,
                offset,
                project_ref=project_ref,
                context_key=context_key,
                request_id=request_id,
                cursor=cursor,
                text_snapshot=text_snapshot,
                selection_snapshot=selection_snapshot,
                context_snapshot=context_snapshot,
                directory_generation=directory_generation,
            ),
            name=f"prompt-bead-jump:{request_id}",
        )
        return True

    async def _resolve_bead_jump_async(
        self,
        bead_id: str,
        form: str,
        prefix: str,
        offset: int,
        *,
        project_ref: str | None,
        context_key: str | None,
        request_id: int,
        cursor: tuple[int, int],
        text_snapshot: str,
        selection_snapshot: object,
        context_snapshot: tuple[object, ...],
        directory_generation: int,
    ) -> None:
        try:
            directory, generation = await asyncio.to_thread(
                self._load_directory_for_preview,
                directory_generation,
            )
        except Exception as exc:
            if self._bead_jump_request_is_current(
                request_id,
                cursor,
                text_snapshot,
                selection_snapshot,
                context_snapshot,
                directory_generation,
            ):
                self.notify(
                    f"Could not load bead stores: {exc}",
                    severity="warning",
                )
            return
        if not self._bead_jump_request_is_current(
            request_id,
            cursor,
            text_snapshot,
            selection_snapshot,
            context_snapshot,
            directory_generation,
        ):
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

        try:
            route, resolution = await asyncio.to_thread(
                _route_and_resolve_bead_detail,
                bead_id,
                directory,
                project_ref,
            )
        except Exception as exc:
            if self._bead_jump_request_is_current(
                request_id,
                cursor,
                text_snapshot,
                selection_snapshot,
                context_snapshot,
                directory_generation,
            ):
                self.notify(
                    f"Could not resolve bead '{bead_id}': {exc}",
                    severity="warning",
                )
            return
        if not self._bead_jump_request_is_current(
            request_id,
            cursor,
            text_snapshot,
            selection_snapshot,
            context_snapshot,
            directory_generation,
        ):
            return

        if isinstance(route, BeadRouteNotBead):
            if form == "ref":
                self.notify(
                    f"No enabled project owns bead prefix '{prefix}'",
                    severity="warning",
                )
                return
            self._resume_jump_after_non_bead(
                offset,
                request_id,
                cursor=cursor,
                text_snapshot=text_snapshot,
                selection_snapshot=selection_snapshot,
                context_snapshot=context_snapshot,
                directory_generation=directory_generation,
            )
            return
        if isinstance(route, BeadRouteFound):
            if resolution is None:
                self.notify(
                    f"bead:{route.bead_id} could not be resolved",
                    severity="warning",
                )
                return
            self._present_bead_detail(resolution, bead_id=route.bead_id)
            self._note_bead_mention_resolved(
                route.bead_id,
                project_ref=project_ref,
                context_key=context_key,
            )
            return
        if isinstance(route, BeadRouteMissing):
            self.notify(
                _missing_bead_message(route.bead_id, route.project_labels),
                severity="information",
            )
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

    def _resume_jump_after_non_bead(
        self,
        offset: int,
        request_id: int,
        *,
        cursor: tuple[int, int],
        text_snapshot: str,
        selection_snapshot: object,
        context_snapshot: tuple[object, ...],
        directory_generation: int,
    ) -> None:
        from sase.ace.tui.widgets._prompt_jump_target import (
            detect_shorthand_argument_owner_jump_target,
        )

        token = detect_shorthand_argument_owner_jump_target(self.text, offset)
        if token is None:
            self.notify(
                "Move the cursor onto a macro, skill, file path, glossary term, "
                "repo name, or bead ID to jump to its definition",
                severity="warning",
            )
            return
        project, base_dir = self._preview_context()
        self.run_worker(
            self._resolve_jump_async(
                token,
                project=project,
                base_dir=base_dir,
                request_id=request_id,
                is_current=lambda: self._bead_jump_request_is_current(
                    request_id,
                    cursor,
                    text_snapshot,
                    selection_snapshot,
                    context_snapshot,
                    directory_generation,
                ),
            ),
            name=f"prompt-jump:{request_id}",
        )

    def _present_bead_detail(self, resolution: LinkResolution, *, bead_id: str) -> None:
        document = resolution.target.document if resolution.target is not None else None
        if document is None:
            message = resolution.unresolved_message or (
                f"bead:{bead_id} could not be resolved"
            )
            self.notify(message, severity="warning")
            return
        from sase.pager.screen import PagerScreen

        self.app.push_screen(PagerScreen(document, links_enabled=True))

    def _load_directory_for_preview(
        self,
        expected_generation: int,
    ) -> tuple[BeadStoreDirectory | None, int | None]:
        app = getattr(self, "_active_app", lambda: None)()
        generation = (
            int(getattr(app, "_bead_store_directory_generation", 0))
            if app is not None
            else 0
        )
        if generation != expected_generation:
            return None, generation
        directory = self._bead_store_directory_for_action(schedule=False)
        if directory is not None:
            return directory, generation
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

    def _note_bead_mention_resolved(
        self,
        bead_id: str,
        *,
        project_ref: str | None,
        context_key: str | None,
    ) -> None:
        """Seed the mention index after a K/Ctrl+] resolution (memory only)."""
        try:
            app = self._active_app()
        except Exception:
            return
        if app is None:
            return
        requester = getattr(app, "request_bead_mention_resolution", None)
        if not callable(requester):
            return
        try:
            requester(
                (bead_id,),
                project_ref=project_ref,
                context_key=context_key,
            )
        except Exception:
            pass

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
        text_snapshot: str,
        selection_snapshot: object,
        context_snapshot: tuple[object, ...],
        directory_generation: int,
    ) -> bool:
        return self._bead_request_is_current(
            self._prompt_preview_request_id,
            request_id,
            cursor,
            text_snapshot,
            selection_snapshot,
            context_snapshot,
            directory_generation,
        )

    def _bead_jump_request_is_current(
        self,
        request_id: int,
        cursor: tuple[int, int],
        text_snapshot: str,
        selection_snapshot: object,
        context_snapshot: tuple[object, ...],
        directory_generation: int,
    ) -> bool:
        return self._bead_request_is_current(
            self._prompt_jump_request_id,
            request_id,
            cursor,
            text_snapshot,
            selection_snapshot,
            context_snapshot,
            directory_generation,
        )

    def _bead_request_is_current(
        self,
        current_request_id: int,
        request_id: int,
        cursor: tuple[int, int],
        text_snapshot: str,
        selection_snapshot: object,
        context_snapshot: tuple[object, ...],
        directory_generation: int,
    ) -> bool:
        if request_id != current_request_id or not self.is_mounted:
            return False
        if self.cursor_location != cursor or self.text != text_snapshot:
            return False
        if getattr(self, "selection", None) != selection_snapshot:
            return False
        if self._bead_prompt_context_snapshot() != context_snapshot:
            return False
        return self._bead_store_directory_generation() == directory_generation

    def _bead_prompt_context_snapshot(self) -> tuple[object, ...]:
        app = self._active_app()
        context = getattr(app, "_prompt_context", None) if app is not None else None
        return (
            getattr(context, "project_name", None),
            getattr(context, "workspace_dir", None),
            bool(getattr(context, "is_home_mode", False)),
        )

    def _bead_store_directory_generation(self) -> int:
        app = self._active_app()
        return int(getattr(app, "_bead_store_directory_generation", 0))


def _route_and_resolve_bead_detail(
    bead_id: str,
    directory: BeadStoreDirectory,
    project_ref: str | None,
) -> tuple[BeadRoute, LinkResolution | None]:
    route = route_bead_mention(bead_id, directory, project_ref=project_ref)
    if not isinstance(route, BeadRouteFound):
        return route, None
    resolution = bead_detail_link_resolution(
        route.bead_id,
        project_ref=route.store.project_key or None,
        context=LinkResolutionContext(
            anchors=(LinkAnchor(route.store.primary_workspace),)
        ),
    )
    return route, resolution


def _missing_bead_message(bead_id: str, project_labels: tuple[str, ...]) -> str:
    if not project_labels:
        return f"No bead '{bead_id}'"
    return f"No bead '{bead_id}' in {project_labels[0]}"


__all__ = ["PromptBeadPreviewMixin"]

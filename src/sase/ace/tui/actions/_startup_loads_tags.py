"""Startup project-tag catalog warm helpers for sase's TUI."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class StartupLoadsTagsMixin:
    """Mixin warming the project-tag catalog after first paint."""

    def _warm_project_tag_catalog_at_startup(self: Any) -> None:
        """Warm the tag snapshot off-thread so first paints tagify (D5).

        Agent panels, history, and query accents render ``#`` while the
        snapshot is cold because the catalog previously warmed only when
        a prompt bar mounted. The build runs in a pump-free task, never
        before first paint; the warmed message refreshes cold surfaces.
        """
        if getattr(self, "_project_tag_catalog_startup_warm_scheduled", False):
            return
        self._project_tag_catalog_startup_warm_scheduled = True
        from ..project_tag_messages import ProjectTagCatalogWarmed
        from ..util.pump_tasks import spawn_pump_free_task

        async def _warm_and_announce() -> None:
            import asyncio

            try:
                from sase.project_tags import load_project_tag_catalog

                await asyncio.to_thread(load_project_tag_catalog)
            except Exception:  # noqa: BLE001 - surfaces keep cold rendering.
                log.debug("Startup project-tag catalog warm failed", exc_info=True)
                return
            try:
                self.post_message(ProjectTagCatalogWarmed())
            except Exception:  # noqa: BLE001 - teardown races degrade silently.
                log.debug("Startup project-tag warmed announce failed", exc_info=True)

        coro = _warm_and_announce()
        try:
            task = spawn_pump_free_task(
                self,
                coro,
                name="project-tag-catalog-warm",
                registry_attr="_project_tag_catalog_warm_tasks",
            )
        except Exception:
            coro.close()
            self._project_tag_catalog_startup_warm_scheduled = False
            log.exception("Failed to schedule startup project-tag catalog warm")
            return
        if task is None:
            coro.close()
            self._project_tag_catalog_startup_warm_scheduled = False
            log.debug("No running event loop for project-tag catalog warm")

    def on_project_tag_catalog_warmed(self: Any, message: object) -> None:
        """Rebuild tag surfaces that rendered while the catalog was cold.

        Render and highlight caches already key on the catalog signature,
        so one rebuild per fresh snapshot is enough; repeat announcements
        for an unchanged snapshot are ignored. ``App.refresh()`` alone
        only repaints the Screen: the agent detail is prebuilt ``Text``
        set through ``update_display``, so it stays ``#`` until the
        selection or data changes without an explicit rebuild.
        """
        del message
        try:
            from sase.project_tags import peek_project_tag_catalog_signature

            signature = peek_project_tag_catalog_signature()
        except Exception:  # noqa: BLE001 - cold catalog still repaints once.
            signature = None
        if signature is not None and (
            getattr(self, "_project_tag_warm_refresh_signature", None) == signature
        ):
            return
        self._project_tag_warm_refresh_signature = signature
        try:
            refresh_detail = getattr(self, "_refresh_agent_focus_detail", None)
            if callable(refresh_detail):
                refresh_detail(render_immediate=False)
        except Exception:  # noqa: BLE001 - teardown races degrade silently.
            log.debug("Project-tag warmed detail rebuild failed", exc_info=True)
        try:
            self._refresh_warmed_tag_modals()
        except Exception:  # noqa: BLE001 - teardown races degrade silently.
            log.debug("Project-tag warmed modal refresh failed", exc_info=True)
        try:
            self.refresh()
        except Exception:  # noqa: BLE001 - teardown races degrade silently.
            log.debug("Project-tag warmed refresh failed", exc_info=True)

    def _refresh_warmed_tag_modals(self: Any) -> None:
        """Rebuild open history/stash modals that cached cold tag text."""
        screens: list[Any] = []
        try:
            stack = getattr(self, "screen_stack", None)
            if stack:
                screens.extend(list(stack))
        except Exception:
            pass
        try:
            current = getattr(self, "screen", None)
            if current is not None and current not in screens:
                screens.append(current)
        except Exception:
            pass
        for screen in screens:
            try:
                self._refresh_one_warmed_tag_modal(screen)
            except Exception:  # noqa: BLE001 - one modal never blocks others.
                continue

    def _refresh_one_warmed_tag_modal(self: Any, screen: Any) -> None:
        """Re-humanize and repaint one open modal, if it shows tag text."""
        # Prompt history caches humanized display text per row at page
        # append time; cold rows stay ``#`` until re-humanized.
        items = getattr(screen, "_all_items", None)
        if isinstance(items, list) and items:
            try:
                from sase.project_display_names import humanize_vcs_refs_in_text

                for index, item in enumerate(items):
                    try:
                        entry = getattr(item, "entry", None)
                        text = getattr(entry, "text", None)
                        if not isinstance(text, str):
                            continue
                        display = humanize_vcs_refs_in_text(text)
                        try:
                            data = dict(getattr(item, "__dict__", {}))
                            data["display_text"] = display
                            # Summaries cache the cold preview; drop it so
                            # the next label rebuild summarizes warm text.
                            if "summary" in data:
                                data["summary"] = None
                            items[index] = type(item)(**data)
                        except Exception:
                            # Frozen dataclass or NamedTuple shapes vary;
                            # fall back to attribute assignment.
                            try:
                                item.display_text = display
                            except Exception:
                                continue
                            try:
                                item.summary = None
                            except Exception:
                                pass
                    except Exception:
                        continue
            except Exception:
                pass
            refresh_options = getattr(screen, "_refresh_options", None)
            if callable(refresh_options):
                try:
                    refresh_options(preserve_highlight=True)
                except TypeError:
                    try:
                        refresh_options()
                    except Exception:
                        pass
                except Exception:
                    pass
                return
        refresh_rows = getattr(screen, "_refresh_rows", None)
        if callable(refresh_rows):
            try:
                refresh_rows()
            except Exception:
                pass

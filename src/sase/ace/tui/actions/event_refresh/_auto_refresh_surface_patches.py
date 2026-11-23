"""Patch surface work for TUI auto-refresh."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class EventAutoRefreshPatchSurfaceMixin:
    """Refresh the visible Patch surface during an auto-refresh pass."""

    async def _refresh_auto_refresh_patch_surface(
        self: Any,
        current_tokens: Any,
        *,
        refresh_counters: dict[str, Any] | None,
        reloaded: list[str],
        should_refresh: Callable[[str, str], bool],
    ) -> None:
        """Refresh Patches when visible and dirty, or request Artifacts."""
        from sase.ace.tui.actions.patch._relation_index import patches_pane_is_visible

        if patches_pane_is_visible(self) and should_refresh(
            "_dirty_patches", "patches"
        ):
            run_patches_refresh = getattr(
                self,
                "_run_patches_async_refresh",
                None,
            )
            if callable(run_patches_refresh):
                if not getattr(self, "_patches_loading", False) and not getattr(
                    self,
                    "_patches_refresh_scheduled",
                    False,
                ):
                    await run_patches_refresh()
                    if refresh_counters is not None:
                        refresh_counters["surface_outcomes"]["patches"] = (
                            "applied_changed"
                        )
                    self._dirty_patches = False
                    self._accept_surface_token("patches", current_tokens)
                    reloaded.append("patches")
            else:
                # Narrow EventAutoRefreshMixin test doubles do not include the
                # Patch loader mixin; production uses its overlap guard.
                await self._reload_and_reposition_async()  # type: ignore[attr-defined]
                self._dirty_patches = False
                self._accept_surface_token("patches", current_tokens)
                reloaded.append("patches")
        else:
            if refresh_counters is not None:
                refresh_counters["surface_outcomes"]["patches"] = "skipped"
            if getattr(self, "current_tab", None) == "artifacts" and not (
                patches_pane_is_visible(self)
            ):
                self._request_active_artifacts_refresh()  # type: ignore[attr-defined]
                reloaded.append("artifacts")

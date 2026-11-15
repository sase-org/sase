"""App-level warm bead-store directory for prompt K previews."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from sase.ace.tui.models.bead_preview import BeadStoreDirectory

log = logging.getLogger(__name__)


class StartupPromptBeadDirectoryMixin:
    """Mixin for the app-wide warm bead-store directory used by prompt K."""

    _bead_store_directory: BeadStoreDirectory | None
    _bead_store_directory_generation: int
    _bead_store_directory_warming: bool

    def get_bead_store_directory(
        self: Any,
        *,
        schedule: bool = True,
    ) -> BeadStoreDirectory | None:
        """Return the memory-only bead-store directory, or ``None`` if cold."""
        if self._bead_store_directory is not None:
            return self._bead_store_directory
        if schedule:
            self.warm_bead_store_directory()
        return None

    def warm_bead_store_directory(self: Any) -> None:
        """Schedule one in-flight off-thread directory warm."""
        if self._bead_store_directory is not None:
            return
        if self._bead_store_directory_warming:
            return
        self._bead_store_directory_warming = True
        generation = self._bead_store_directory_generation

        async def run_warm() -> None:
            await self._run_bead_store_directory_warm(generation)

        try:
            self.run_worker(
                cast(Any, run_warm),
                name=f"prompt-bead-directory:{generation}",
                group="prompt-bead-directory",
                exclusive=False,
            )
        except Exception:
            self._bead_store_directory_warming = False
            log.exception("Failed to schedule prompt bead-store directory warm")

    async def _run_bead_store_directory_warm(
        self: Any,
        generation: int,
    ) -> None:
        """Load the directory off-thread and publish it if still current."""
        import asyncio

        from sase.ace.tui.models.bead_preview import load_bead_store_directory

        try:
            directory = await asyncio.to_thread(load_bead_store_directory)
        except Exception:
            log.exception("Prompt bead-store directory warm failed")
            return
        finally:
            if generation == self._bead_store_directory_generation:
                self._bead_store_directory_warming = False

        if generation != self._bead_store_directory_generation:
            return
        self.publish_bead_store_directory(directory, generation=generation)

    def publish_bead_store_directory(
        self: Any,
        directory: BeadStoreDirectory,
        *,
        generation: int | None = None,
    ) -> None:
        """Publish a directory loaded inline by a K worker while the cache was cold."""
        if (
            generation is not None
            and generation != self._bead_store_directory_generation
        ):
            return
        self._bead_store_directory = directory
        self._bead_store_directory_warming = False

    def _invalidate_bead_store_directory(self: Any, *, reason: str) -> None:
        """Drop the warm directory after config/project source changes."""
        del reason
        self._bead_store_directory_generation += 1
        self._bead_store_directory = None
        self._bead_store_directory_warming = False


__all__ = ["StartupPromptBeadDirectoryMixin"]

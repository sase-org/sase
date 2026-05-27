"""Stderr progress reporter for ``sase memory episodes build``."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
import time
from types import TracebackType
from typing import Any

from rich.console import Console


class BuildProgress:
    """Emit phase progress to stderr while ``episodes build`` runs.

    Each phase is wrapped in :meth:`phase` and (optionally) followed by a
    :meth:`summary` call that records the per-phase outcome and elapsed time.
    Passing ``enabled=False`` turns every method into a no-op, so call sites
    do not need to branch for ``--json`` or ``--quiet``.
    """

    def __init__(self, *, enabled: bool) -> None:
        self._enabled = enabled
        self._console: Console | None = Console(stderr=True) if enabled else None
        self._phase_start: float | None = None
        self._status: Any | None = None

    def __enter__(self) -> BuildProgress:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._status is not None:
            self._status.__exit__(exc_type, exc_val, tb)
            self._status = None

    @contextmanager
    def phase(self, label: str) -> Generator[None, None, None]:
        if not self._enabled or self._console is None:
            yield
            return
        self._phase_start = time.monotonic()
        if self._console.is_terminal:
            self._status = self._console.status(f"{label}…", spinner="dots")
            self._status.__enter__()
            try:
                yield
            finally:
                if self._status is not None:
                    self._status.__exit__(None, None, None)
                    self._status = None
        else:
            self._console.print(f"  [cyan]▶[/cyan] {label}…")
            yield

    def summary(self, message: str) -> None:
        if not self._enabled or self._console is None or self._phase_start is None:
            return
        elapsed = time.monotonic() - self._phase_start
        self._console.print(
            f"  [green]✔[/green] {message}  [dim]({elapsed:.1f}s)[/dim]"
        )
        self._phase_start = None


__all__ = ["BuildProgress"]

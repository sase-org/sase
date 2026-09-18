"""Stable executable resolution for long-lived service hosts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable


@dataclass(frozen=True)
class StableExecutable:
    """Resolved long-lived ``sase`` executable and its drift diagnostics."""

    path: Path | None
    diagnostics: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return self.path is not None


def resolve_stable_sase_executable(
    *,
    resolver: Callable[[], str | None] | None = None,
) -> StableExecutable:
    """Resolve the stable ``sase`` executable used by platform service units."""
    if resolver is not None:
        resolved = resolver()
    else:
        resolved = _canonical_axe_start_command()
    if not resolved:
        return StableExecutable(
            path=None,
            diagnostics=(
                "could not find a stable non-ephemeral `sase` executable; "
                "install SASE into a durable environment before running `sase service init`",
            ),
        )
    path = Path(str(resolved)).expanduser()
    if not path.exists():
        return StableExecutable(
            path=None,
            diagnostics=(f"stable `sase` executable is missing: {path}",),
        )
    return StableExecutable(path=path.resolve(strict=False))


def _canonical_axe_start_command() -> str | None:
    """Use the existing AXE canonical-start resolver as the shared source."""
    try:
        from sase.axe.process import canonical_axe_start_command

        return canonical_axe_start_command()
    except Exception:
        return None


__all__ = [
    "StableExecutable",
    "resolve_stable_sase_executable",
]

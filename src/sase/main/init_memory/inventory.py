"""Memory reference discovery and validation helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
import sys

from sase.memory.inventory import (
    memory_parent_blockers_for_init,
    unreferenced_memory_files_for_init,
)

from .constants import COMMAND_LABEL
from .models import MemoryRootResult


def unreferenced_memory_files(
    root: Path,
    *,
    overlay: Mapping[Path, str] | None = None,
    source_memory_root: Path | None = None,
    ignored_paths: Iterable[Path] = (),
) -> tuple[Path, ...]:
    return unreferenced_memory_files_for_init(
        root,
        overlay=overlay,
        source_memory_root=source_memory_root,
        ignored_paths=ignored_paths,
    )


def memory_parent_blockers(
    root: Path,
    *,
    overlay: Mapping[Path, str] | None = None,
    source_memory_root: Path | None = None,
    ignored_paths: Iterable[Path] = (),
) -> tuple[str, ...]:
    return memory_parent_blockers_for_init(
        root,
        overlay=overlay,
        source_memory_root=source_memory_root,
        ignored_paths=ignored_paths,
    )


def print_validation_errors(results: tuple[MemoryRootResult, ...]) -> None:
    printed = False
    for result in results:
        if not result.unreferenced:
            continue
        if not printed:
            print(
                f"{COMMAND_LABEL}: unreferenced memory files were found",
                file=sys.stderr,
            )
            printed = True
        print(f"  {result.root}:", file=sys.stderr)
        for path in result.unreferenced:
            try:
                display = path.relative_to(result.root.resolve(strict=False))
            except ValueError:
                display = path
            print(f"    - {display}", file=sys.stderr)

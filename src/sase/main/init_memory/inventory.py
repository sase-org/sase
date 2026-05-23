"""Memory reference discovery and validation helpers."""

from __future__ import annotations

from pathlib import Path
import sys

from sase.memory.inventory import (
    unreferenced_memory_files_for_init,
)

from .constants import COMMAND_LABEL
from .models import MemoryRootResult


def unreferenced_memory_files(root: Path) -> tuple[Path, ...]:
    return unreferenced_memory_files_for_init(root)


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

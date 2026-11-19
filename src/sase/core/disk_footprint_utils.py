"""Shared filesystem and formatting helpers for disk-footprint code."""

from __future__ import annotations

import os
import stat
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

DISK_SIZE_MEASURED = "measured"
DISK_SIZE_LOWER_BOUND = "lower_bound"
DISK_SIZE_UNMEASURED = "unmeasured"


@dataclass(frozen=True)
class TreeSizeMeasurement:
    """One tree-size observation: exact, a floor, or unknown."""

    size_bytes: int
    state: str = DISK_SIZE_MEASURED
    diagnostics: tuple[str, ...] = ()


type TreeSizeFn = Callable[[Path], int | TreeSizeMeasurement]


class _MeasuredRowFields(TypedDict):
    size_bytes: int
    size_state: str
    coverage: str
    diagnostics: tuple[str, ...]


def _coerce_tree_size(value: int | TreeSizeMeasurement) -> TreeSizeMeasurement:
    """Treat a plain int from ``tree_size_fn`` as a complete measurement."""

    if isinstance(value, TreeSizeMeasurement):
        return value
    return TreeSizeMeasurement(size_bytes=int(value), state=DISK_SIZE_MEASURED)


def measured_row_fields(
    tree_size_fn: TreeSizeFn,
    path: Path,
    *,
    coverage: str = "complete",
    diagnostics: tuple[str, ...] = (),
) -> _MeasuredRowFields:
    """Size *path* and force partial coverage on any non-measured result."""

    measurement = _coerce_tree_size(tree_size_fn(path))
    merged = list(diagnostics)
    merged.extend(measurement.diagnostics)
    if measurement.state != DISK_SIZE_MEASURED:
        coverage = "partial"
        if not merged:
            merged.append(f"{path}: size {measurement.state}")
    return {
        "size_bytes": measurement.size_bytes,
        "size_state": measurement.state,
        "coverage": coverage,
        "diagnostics": tuple(merged),
    }


@dataclass
class InventoryScanBudget:
    """One budget shared by a whole disk-inventory collection pass."""

    max_nodes: int = 50_000
    max_seconds: float = 5.0
    started_at: float = field(default_factory=time.monotonic)
    visited_nodes: int = 0
    truncated: bool = False
    diagnostics: list[str] = field(default_factory=list)

    def remaining_seconds(self, cap: float | None = None) -> float:
        remaining = self.started_at + self.max_seconds - time.monotonic()
        if cap is not None:
            remaining = min(remaining, cap)
        return max(0.0, remaining)

    def consume_node(self) -> bool:
        if self.exhausted:
            self.truncated = True
            return False
        self.visited_nodes += 1
        if self.visited_nodes > self.max_nodes:
            self.truncated = True
            return False
        return True

    @property
    def exhausted(self) -> bool:
        return (
            self.truncated
            or self.visited_nodes >= self.max_nodes
            or self.remaining_seconds() <= 0
        )

    def record_diagnostic(self, message: str) -> None:
        self.diagnostics.append(message)


@dataclass(frozen=True)
class _ChildListing:
    """Bounded child listing result that preserves partial-read evidence."""

    children: tuple[Path, ...]
    complete: bool
    error: str | None = None


def iter_children(directory: Path) -> list[Path]:
    try:
        return list(directory.iterdir())
    except OSError:
        return []


def iter_children_bounded(
    directory: Path,
    budget: InventoryScanBudget,
) -> _ChildListing:
    children: list[Path] = []
    if not budget.consume_node():
        return _ChildListing(
            tuple(children),
            False,
            "scan budget exhausted before listing directory",
        )
    try:
        iterator = directory.iterdir()
        for child in iterator:
            if not budget.consume_node():
                return _ChildListing(
                    tuple(children),
                    False,
                    "scan budget exhausted while listing directory",
                )
            children.append(child)
    except OSError as exc:
        return _ChildListing(tuple(children), False, f"{type(exc).__name__}: {exc}")
    return _ChildListing(tuple(children), True)


def tree_size(path: Path) -> int:
    measured = du_size(path)
    if measured is not None:
        return measured
    return tree_size_walk(path)


@dataclass
class BoundedTreeSizer:
    """Measure trees without letting fallback walks hang inventory."""

    max_nodes: int = 50_000
    max_seconds: float = 5.0
    budget: InventoryScanBudget | None = None

    def __post_init__(self) -> None:
        if self.budget is None:
            self.budget = InventoryScanBudget(
                max_nodes=self.max_nodes,
                max_seconds=self.max_seconds,
            )

    @property
    def diagnostics(self) -> list[str]:
        return self._budget.diagnostics

    @property
    def _budget(self) -> InventoryScanBudget:
        budget = self.budget
        if budget is None:
            budget = InventoryScanBudget(
                max_nodes=self.max_nodes,
                max_seconds=self.max_seconds,
            )
            self.budget = budget
        return budget

    def size(self, path: Path) -> TreeSizeMeasurement:
        budget = self._budget
        if budget.exhausted:
            budget.truncated = True
            diagnostic = f"{path}: skipped; shared scan budget exhausted"
            budget.record_diagnostic(diagnostic)
            return TreeSizeMeasurement(
                size_bytes=0,
                state=DISK_SIZE_UNMEASURED,
                diagnostics=(diagnostic,),
            )
        measured = du_size(path, timeout=budget.remaining_seconds(5.0))
        if measured is not None:
            return TreeSizeMeasurement(
                size_bytes=measured,
                state=DISK_SIZE_MEASURED,
            )
        size, visited, truncated = _tree_size_walk_bounded(
            path,
            max_nodes=self.max_nodes,
            max_seconds=self.max_seconds,
            budget=budget,
        )
        reason = "truncated" if truncated else "du unavailable"
        diagnostic = f"{path}: fallback walk {reason}; visited={visited}; bytes={size}"
        budget.record_diagnostic(diagnostic)
        if truncated:
            return TreeSizeMeasurement(
                size_bytes=size,
                state=DISK_SIZE_LOWER_BOUND,
                diagnostics=(diagnostic,),
            )
        return TreeSizeMeasurement(
            size_bytes=size,
            state=DISK_SIZE_MEASURED,
            diagnostics=(diagnostic,),
        )


def du_size(path: Path, *, timeout: float = 5.0) -> int | None:
    if not path.exists():
        return 0
    if timeout <= 0:
        return None
    try:
        result = subprocess.run(
            ["du", "-skx", "--", str(path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=max(0.001, timeout),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    first = result.stdout.split(None, 1)[0] if result.stdout.strip() else ""
    try:
        return int(first) * 1024
    except ValueError:
        return None


def tree_size_walk(path: Path) -> int:
    try:
        entry_stat = path.stat(follow_symlinks=False)
    except OSError:
        return 0
    if stat.S_ISLNK(entry_stat.st_mode):
        return 0
    if stat.S_ISREG(entry_stat.st_mode):
        return int(entry_stat.st_size)
    if not stat.S_ISDIR(entry_stat.st_mode):
        return 0
    return sum(tree_size_walk(child) for child in iter_children(path))


def _tree_size_walk_bounded(
    path: Path,
    *,
    max_nodes: int,
    max_seconds: float,
    budget: InventoryScanBudget | None = None,
) -> tuple[int, int, bool]:
    local_budget = budget or InventoryScanBudget(
        max_nodes=max_nodes,
        max_seconds=max_seconds,
    )
    total = 0
    visited = 0
    truncated = False
    stack = [path]
    while stack:
        if not local_budget.consume_node():
            truncated = True
            break
        current = stack.pop()
        visited += 1
        try:
            entry_stat = current.stat(follow_symlinks=False)
        except OSError:
            continue
        if stat.S_ISLNK(entry_stat.st_mode):
            continue
        if stat.S_ISREG(entry_stat.st_mode):
            total += int(entry_stat.st_size)
            continue
        if not stat.S_ISDIR(entry_stat.st_mode):
            continue
        listing = iter_children_bounded(current, local_budget)
        if not listing.complete:
            truncated = True
        stack.extend(listing.children)
    return total, visited, truncated


def normalize_path_no_follow(path: Path) -> Path:
    """Return an absolute, lexical path without resolving symlinks."""

    return Path(os.path.abspath(os.path.normpath(os.fspath(path.expanduser()))))


def format_horizon_seconds(seconds: float) -> str:
    if seconds % 86_400 == 0:
        return f"{int(seconds // 86_400)}d"
    if seconds % 3_600 == 0:
        return f"{int(seconds // 3_600)}h"
    return f"{int(seconds)}s"


def format_bytes(value: int) -> str:
    """Format bytes for compact CLI rows."""

    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{int(amount)} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value} B"


def format_measured_bytes(size_bytes: int, size_state: str) -> str:
    """Render a size with its measurement state, never as a fake exact zero."""

    if size_state == DISK_SIZE_UNMEASURED:
        return "unmeasured"
    formatted = format_bytes(size_bytes)
    if size_state == DISK_SIZE_LOWER_BOUND:
        return f"≥{formatted}"
    return formatted


def resolve_soft(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def is_relative_to(path: Path, base: Path) -> bool:
    try:
        return os.path.commonpath((os.fspath(path), os.fspath(base))) == os.fspath(base)
    except ValueError:
        return False


__all__ = [
    "BoundedTreeSizer",
    "DISK_SIZE_LOWER_BOUND",
    "DISK_SIZE_MEASURED",
    "DISK_SIZE_UNMEASURED",
    "TreeSizeFn",
    "du_size",
    "format_bytes",
    "format_horizon_seconds",
    "format_measured_bytes",
    "is_relative_to",
    "iter_children",
    "iter_children_bounded",
    "InventoryScanBudget",
    "measured_row_fields",
    "normalize_path_no_follow",
    "resolve_soft",
    "tree_size",
    "tree_size_walk",
]

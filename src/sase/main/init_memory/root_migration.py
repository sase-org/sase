"""Legacy memory-tree migration planning for memory root initialization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sase.memory.paths import memory_layout

from .models import MemoryExpectedFile


@dataclass(frozen=True)
class _MemoryMigrationPlan:
    source_memory_root: Path
    expected_files: tuple[MemoryExpectedFile, ...] = ()
    delete_paths: tuple[Path, ...] = ()
    blockers: tuple[str, ...] = ()


def _tree_files(root: Path) -> tuple[Path, ...]:
    if not root.is_dir():
        return ()
    return tuple(
        sorted(
            (path for path in root.rglob("*") if path.is_file()),
            key=lambda path: path.as_posix(),
        )
    )


def _tree_symlinks(root: Path) -> tuple[Path, ...]:
    if not root.is_dir():
        return ()
    return tuple(
        sorted(
            (path for path in root.rglob("*") if path.is_symlink()),
            key=lambda path: path.as_posix(),
        )
    )


def _relative_file_map(root: Path) -> dict[Path, Path]:
    return {path.relative_to(root): path for path in _tree_files(root)}


def _identical_memory_trees(canonical: Path, legacy: Path) -> bool:
    canonical_files = _relative_file_map(canonical)
    legacy_files = _relative_file_map(legacy)
    if canonical_files.keys() != legacy_files.keys():
        return False
    try:
        return all(
            canonical_files[relative].read_bytes()
            == legacy_files[relative].read_bytes()
            for relative in canonical_files
        )
    except OSError:
        return False


def memory_migration_plan(root: Path) -> _MemoryMigrationPlan:
    compatible = memory_layout(root)
    canonical = compatible.canonical.path
    legacy = compatible.legacy[0].path
    canonical_exists = canonical.exists()
    legacy_exists = legacy.exists()

    if canonical_exists and not canonical.is_dir():
        return _MemoryMigrationPlan(
            source_memory_root=canonical,
            blockers=(f"{canonical}: canonical memory path is not a directory",),
        )
    if legacy_exists and not legacy.is_dir():
        return _MemoryMigrationPlan(
            source_memory_root=canonical,
            blockers=(f"{legacy}: legacy memory path is not a directory",),
        )
    if not legacy_exists:
        return _MemoryMigrationPlan(source_memory_root=canonical)

    legacy_symlinks = _tree_symlinks(legacy)
    if legacy_symlinks:
        rendered = ", ".join(str(path) for path in legacy_symlinks)
        return _MemoryMigrationPlan(
            source_memory_root=legacy,
            blockers=(
                "legacy memory tree contains symlinks that cannot be migrated "
                f"safely: {rendered}",
            ),
        )

    legacy_files = _tree_files(legacy)
    delete_paths = tuple(reversed(legacy_files))
    if canonical_exists:
        if not _identical_memory_trees(canonical, legacy):
            return _MemoryMigrationPlan(
                source_memory_root=canonical,
                blockers=(
                    f"memory exists in non-identical canonical and legacy trees: "
                    f"{canonical}, {legacy}; reconcile them before running init",
                ),
            )
        return _MemoryMigrationPlan(
            source_memory_root=canonical,
            delete_paths=delete_paths,
        )

    expected: list[MemoryExpectedFile] = []
    blockers: list[str] = []
    for source in legacy_files:
        relative = source.relative_to(legacy)
        try:
            content = source.read_bytes()
        except OSError as exc:
            blockers.append(f"{source}: failed to read legacy memory file: {exc}")
            continue
        expected.append(
            MemoryExpectedFile(
                path=canonical / relative,
                content=content,
                detail="migrate legacy memory file",
            )
        )
    return _MemoryMigrationPlan(
        source_memory_root=legacy,
        expected_files=tuple(expected),
        delete_paths=delete_paths,
        blockers=tuple(blockers),
    )

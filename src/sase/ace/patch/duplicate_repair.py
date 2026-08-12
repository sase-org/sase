"""Locked repair driver for duplicate ProjectSpec Patch blocks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sase.ace.patch.duplicate_blocks import (
    DuplicateBlockScan,
    dedupe_patch_blocks,
    scan_duplicate_patch_blocks,
)
from sase.ace.patch.locking import LockTimeoutError, patch_lock, write_patch_atomic
from sase.ace.patch.project_spec_path import preferred_project_spec_path
from sase.core.paths import is_valid_sase_project_name
from sase.project_display_names import load_project_display_snapshot


@dataclass(frozen=True)
class DuplicateBlockPreview:
    project_key: str
    project_label: str
    active_file: str
    archive_file: str
    active_scan: DuplicateBlockScan
    archive_scan: DuplicateBlockScan


@dataclass(frozen=True)
class _DuplicateBlockFileRepairResult:
    file_path: str
    dropped_blocks: int
    reclaimable_bytes: int
    changed: bool


@dataclass(frozen=True)
class DuplicateBlockRepairResult:
    project_key: str
    project_label: str
    active_file: str
    archive_file: str
    active_result: _DuplicateBlockFileRepairResult | None
    archive_result: _DuplicateBlockFileRepairResult | None
    error: str | None = None

    @property
    def dropped_blocks(self) -> int:
        return sum(
            result.dropped_blocks
            for result in (self.active_result, self.archive_result)
            if result is not None
        )

    @property
    def reclaimable_bytes(self) -> int:
        return sum(
            result.reclaimable_bytes
            for result in (self.active_result, self.archive_result)
            if result is not None
        )


def plan_duplicate_block_repairs(
    *,
    projects_root: Path,
) -> tuple[DuplicateBlockPreview, ...]:
    """Find project specs with duplicate raw Patch blocks."""
    display_snapshot = load_project_display_snapshot(projects_root)
    previews: list[DuplicateBlockPreview] = []

    for project_dir in sorted(projects_root.iterdir(), key=lambda path: path.name):
        if not project_dir.is_dir():
            continue
        project_key = project_dir.name
        if not is_valid_sase_project_name(project_key):
            continue

        active_file = Path(preferred_project_spec_path(str(project_dir), project_key))
        archive_file = Path(
            preferred_project_spec_path(str(project_dir), project_key, archive=True)
        )
        active_scan = _scan_file(active_file)
        archive_scan = _scan_file(archive_file)
        if active_scan.dropped_blocks == 0 and archive_scan.dropped_blocks == 0:
            continue
        previews.append(
            DuplicateBlockPreview(
                project_key=project_key,
                project_label=display_snapshot.label_for(project_key),
                active_file=str(active_file),
                archive_file=str(archive_file),
                active_scan=active_scan,
                archive_scan=archive_scan,
            )
        )

    return tuple(previews)


def apply_duplicate_block_repairs(
    previews: tuple[DuplicateBlockPreview, ...],
) -> tuple[DuplicateBlockRepairResult, ...]:
    """Apply duplicate-block repairs, recording per-project failures."""
    results: list[DuplicateBlockRepairResult] = []
    for preview in previews:
        active_file = preview.active_file
        archive_file = preview.archive_file
        try:
            with patch_lock(active_file):
                with patch_lock(archive_file):
                    active_result = _repair_file(Path(active_file))
                    archive_result = _repair_file(Path(archive_file))
            results.append(
                DuplicateBlockRepairResult(
                    project_key=preview.project_key,
                    project_label=preview.project_label,
                    active_file=active_file,
                    archive_file=archive_file,
                    active_result=active_result,
                    archive_result=archive_result,
                )
            )
        except (LockTimeoutError, OSError) as exc:
            results.append(
                DuplicateBlockRepairResult(
                    project_key=preview.project_key,
                    project_label=preview.project_label,
                    active_file=active_file,
                    archive_file=archive_file,
                    active_result=None,
                    archive_result=None,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    return tuple(results)


def _scan_file(path: Path) -> DuplicateBlockScan:
    if not path.exists():
        return _empty_scan()
    return scan_duplicate_patch_blocks(path.read_text(encoding="utf-8"))


def _repair_file(path: Path) -> _DuplicateBlockFileRepairResult:
    if not path.exists():
        return _DuplicateBlockFileRepairResult(
            file_path=str(path),
            dropped_blocks=0,
            reclaimable_bytes=0,
            changed=False,
        )

    text = path.read_text(encoding="utf-8")
    deduped, scan = dedupe_patch_blocks(text)
    changed = deduped != text
    if changed:
        write_patch_atomic(str(path), deduped, "Repair duplicate Patch blocks")
    return _DuplicateBlockFileRepairResult(
        file_path=str(path),
        dropped_blocks=scan.dropped_blocks,
        reclaimable_bytes=scan.reclaimable_bytes,
        changed=changed,
    )


def _empty_scan() -> DuplicateBlockScan:
    return DuplicateBlockScan(
        total_blocks=0,
        unique_names=0,
        duplicate_names=(),
        dropped_blocks=0,
        reclaimable_bytes=0,
    )


__all__ = [
    "DuplicateBlockPreview",
    "DuplicateBlockRepairResult",
    "apply_duplicate_block_repairs",
    "plan_duplicate_block_repairs",
]

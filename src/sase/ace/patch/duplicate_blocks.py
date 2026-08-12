"""Raw ProjectSpec Patch block de-duplication helpers."""

from __future__ import annotations

from dataclasses import dataclass

from .storage import is_patch_heading


@dataclass(frozen=True)
class DuplicateBlockScan:
    total_blocks: int
    unique_names: int
    duplicate_names: tuple[str, ...]
    dropped_blocks: int
    reclaimable_bytes: int


def split_patch_blocks(text: str) -> tuple[str, tuple[tuple[str, str], ...]]:
    """Split *text* into a preamble and raw Patch blocks keyed by ``NAME``.

    This deliberately avoids the ProjectSpec parser because it is used to find
    records that old parser versions could not see.
    """
    lines = text.splitlines(keepends=True)
    anchors = [idx for idx, line in enumerate(lines) if line.startswith("NAME: ")]
    if not anchors:
        return text, ()

    line_offsets: list[int] = []
    offset = 0
    for line in lines:
        line_offsets.append(offset)
        offset += len(line)

    block_starts = tuple(_block_start_for_anchor(lines, anchor) for anchor in anchors)
    preamble = text[: line_offsets[block_starts[0]]]
    blocks: list[tuple[str, str]] = []
    for idx, anchor in enumerate(anchors):
        start = line_offsets[block_starts[idx]]
        end = (
            line_offsets[block_starts[idx + 1]]
            if idx + 1 < len(block_starts)
            else len(text)
        )
        blocks.append((_name_from_anchor(lines[anchor]), text[start:end]))

    return preamble, tuple(blocks)


def scan_duplicate_patch_blocks(text: str) -> DuplicateBlockScan:
    """Return duplicate-name statistics for raw ProjectSpec Patch blocks."""
    _, blocks = split_patch_blocks(text)
    keep = _kept_block_indexes(blocks)
    duplicate_names = _duplicate_names(blocks)
    reclaimable_bytes = sum(
        len(block) for idx, (_name, block) in enumerate(blocks) if idx not in keep
    )
    keyed_names = {name for name, _block in blocks if name}
    return DuplicateBlockScan(
        total_blocks=len(blocks),
        unique_names=len(keyed_names),
        duplicate_names=duplicate_names,
        dropped_blocks=len(blocks) - len(keep),
        reclaimable_bytes=reclaimable_bytes,
    )


def dedupe_patch_blocks(text: str) -> tuple[str, DuplicateBlockScan]:
    """Drop duplicate raw Patch blocks, keeping the last block for each name."""
    preamble, blocks = split_patch_blocks(text)
    keep = _kept_block_indexes(blocks)
    scan = scan_duplicate_patch_blocks(text)
    if scan.dropped_blocks == 0:
        return text, scan
    deduped = preamble + "".join(
        block for idx, (_name, block) in enumerate(blocks) if idx in keep
    )
    return deduped, scan


def _block_start_for_anchor(lines: list[str], anchor: int) -> int:
    block_start = anchor
    idx = anchor - 1
    while idx >= 0 and lines[idx].strip() == "":
        idx -= 1
    if idx < anchor - 1:
        block_start = idx + 1
    if idx >= 0 and is_patch_heading(lines[idx]):
        block_start = idx
        while block_start > 0 and lines[block_start - 1].strip() == "":
            block_start -= 1
    return block_start


def _name_from_anchor(line: str) -> str:
    return line[6:].strip()


def _duplicate_names(blocks: tuple[tuple[str, str], ...]) -> tuple[str, ...]:
    counts: dict[str, int] = {}
    for name, _block in blocks:
        if name:
            counts[name] = counts.get(name, 0) + 1
    return tuple(sorted(name for name, count in counts.items() if count > 1))


def _kept_block_indexes(blocks: tuple[tuple[str, str], ...]) -> set[int]:
    last_by_name: dict[str, int] = {}
    for idx, (name, _block) in enumerate(blocks):
        if name:
            last_by_name[name] = idx

    keep: set[int] = set()
    for idx, (name, _block) in enumerate(blocks):
        if not name or last_by_name[name] == idx:
            keep.add(idx)
    return keep


__all__ = [
    "DuplicateBlockScan",
    "dedupe_patch_blocks",
    "scan_duplicate_patch_blocks",
    "split_patch_blocks",
]

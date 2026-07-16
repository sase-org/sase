"""Failure artifact serialization for ACE PNG visual tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tests.ace.tui.visual._png_diff_comparison import PngDiffSummary
from tests.ace.tui.visual._png_diff_tolerance import PngDiffTolerance


@dataclass(frozen=True)
class FailureArtifacts:
    """Paths written to describe a failed PNG assertion."""

    actual_path: Path
    expected_path: Path | None
    diff_path: Path | None
    source_svg_path: Path | None
    summary_path: Path
    failure_json_path: Path


def snapshot_path(snapshot_root: Path, name: str) -> Path:
    """Return the committed PNG golden path for *name*."""
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"invalid snapshot name: {name!r}")
    if path.suffix != ".png":
        path = path.with_suffix(".png")
    return snapshot_root / path


def write_failure_artifacts(
    *,
    name: str,
    artifact_root: Path,
    node_id: str,
    actual: bytes,
    expected: bytes | None,
    source_svg: str | None,
    kind: str,
    expected_repo_path: str,
    test_file: str | None = None,
    test_line: int | None = None,
    repo_root: Path | None = None,
    diff: bytes | None = None,
    summary: PngDiffSummary | None = None,
    tolerance: PngDiffTolerance | None = None,
) -> FailureArtifacts:
    """Write all diagnostic files for a missing or mismatched snapshot."""
    failure_dir = artifact_root / _slug(node_id) / _slug(name)
    actual_path = failure_dir / "actual.png"
    expected_path = failure_dir / "expected.png"
    diff_path = failure_dir / "diff.png"
    source_svg_path = failure_dir / "actual.svg"
    summary_path = failure_dir / "summary.txt"
    failure_json_path = failure_dir / "failure.json"

    write_bytes(actual_path, actual)
    if expected is not None:
        write_bytes(expected_path, expected)
    if diff is not None:
        write_bytes(diff_path, diff)
    if source_svg is not None:
        _write_text(source_svg_path, source_svg)
    _write_text(summary_path, _summary_text(summary, tolerance))

    record: dict[str, Any] = {
        "node_id": node_id,
        "snapshot": name,
        "kind": kind,
        "expected_repo_path": expected_repo_path,
        "actual_path": repo_relative(actual_path, repo_root),
        "summary_path": repo_relative(summary_path, repo_root),
        "test_file": test_file,
        "test_line": test_line,
    }
    if expected is not None:
        record["expected_path"] = repo_relative(expected_path, repo_root)
    if diff is not None:
        record["diff_path"] = repo_relative(diff_path, repo_root)
    if source_svg is not None:
        record["source_svg_path"] = repo_relative(source_svg_path, repo_root)
    if summary is not None:
        record["expected_size"] = list(summary.expected_size)
        record["actual_size"] = list(summary.actual_size)
        record["changed_pixels"] = summary.changed_pixels
        record["total_pixels"] = summary.total_pixels
        record["changed_ratio"] = summary.changed_ratio
        record["material_diff_pixels"] = summary.material_diff_pixels
        record["material_diff_ratio"] = summary.material_diff_ratio
        record["material_diff_threshold"] = summary.material_diff_threshold
    if tolerance is not None:
        record["max_diff_pixels"] = tolerance.max_diff_pixels
        record["max_diff_ratio"] = tolerance.max_diff_ratio
        record["max_material_diff_pixels"] = tolerance.max_material_diff_pixels
        record["tolerance_source"] = tolerance.source

    _write_text(failure_json_path, json.dumps(record, indent=2, sort_keys=True) + "\n")

    return FailureArtifacts(
        actual_path=actual_path,
        expected_path=expected_path if expected is not None else None,
        diff_path=diff_path if diff is not None else None,
        source_svg_path=source_svg_path if source_svg is not None else None,
        summary_path=summary_path,
        failure_json_path=failure_json_path,
    )


def repo_relative(path: Path, repo_root: Path | None) -> str:
    """Return *path* as a repo-relative POSIX string when possible."""
    if repo_root is None:
        return path.as_posix()
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def write_bytes(path: Path, value: bytes) -> None:
    """Write bytes after creating the destination's parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def _summary_text(
    summary: PngDiffSummary | None,
    tolerance: PngDiffTolerance | None,
) -> str:
    if summary is None:
        return "expected PNG golden is missing\n"
    text = (
        f"expected_size: {summary.expected_size[0]}x{summary.expected_size[1]}\n"
        f"actual_size: {summary.actual_size[0]}x{summary.actual_size[1]}\n"
        f"changed_pixels: {summary.changed_pixels}\n"
        f"total_pixels: {summary.total_pixels}\n"
        f"changed_ratio: {summary.changed_ratio:.12f}\n"
        f"material_diff_pixels: {summary.material_diff_pixels}\n"
        f"material_diff_ratio: {summary.material_diff_ratio:.12f}\n"
        f"material_diff_threshold: {summary.material_diff_threshold}\n"
    )
    if tolerance is None:
        return text
    return text + (
        f"max_diff_pixels: {_optional_limit(tolerance.max_diff_pixels)}\n"
        f"max_diff_ratio: {_optional_limit(tolerance.max_diff_ratio)}\n"
        "max_material_diff_pixels: "
        f"{_optional_limit(tolerance.max_material_diff_pixels)}\n"
        f"tolerance_source: {tolerance.source}\n"
    )


def _optional_limit(value: int | float | None) -> str:
    return "none" if value is None else str(value)


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


def _slug(value: str) -> str:
    chars = [char if char.isalnum() or char in "._-" else "_" for char in value]
    slug = "".join(chars).strip("._-")
    return slug or "snapshot"

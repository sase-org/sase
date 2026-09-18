"""Exact pixel comparison and change classification for screenshot maintenance."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from tests.ace.tui.visual._visual_capture import (
    CaptureRecord,
    InventoryReport,
    png_dimensions,
    sha256_bytes,
)
from tests.ace.tui.visual._visual_maintenance_types import (
    KIND_CREATED,
    KIND_STALE,
    KIND_UNCHANGED,
    KIND_UPDATED,
    ChangeRecord,
    GoldenBaseline,
    GoldenFileState,
    MaintenanceError,
)


def classify_captures(
    inventory: InventoryReport,
    *,
    baseline: GoldenBaseline,
    repo_root: Path,
    capture_dir: Path,
) -> tuple[ChangeRecord, ...]:
    """Compare captures to the run-start baseline using exact pixel equality.

    Encoding-only differences are ``unchanged``. Dimension changes are
    ``updated`` even when a padded canvas reports zero changed pixels. Stale
    goldens are reported only when the inventory proves a full run.
    """
    if inventory.errors:
        raise MaintenanceError(
            "capture inventory has protocol errors: " + "; ".join(inventory.errors)
        )
    changes: list[ChangeRecord] = []
    captured_paths: set[str] = set()
    for record in inventory.captures:
        captured_paths.add(record.canonical_golden_path)
        changes.append(
            _classify_record(
                record,
                baseline=baseline,
                repo_root=repo_root,
                capture_dir=capture_dir,
            )
        )
    if inventory.pruning_allowed:
        for relative, state in sorted(baseline.files.items()):
            if relative in captured_paths:
                continue
            changes.append(_stale_record(state, repo_root=repo_root))
    return tuple(
        sorted(changes, key=lambda item: (item.kind, item.path, item.node_id or ""))
    )


def preserve_expected_bytes(
    run_dir: Path,
    changes: Sequence[ChangeRecord],
    repo_root: Path,
) -> None:
    """Copy pre-update golden bytes for updated and stale paths into *run_dir*."""
    from tests.ace.tui.visual._visual_capture_paths import atomic_write_bytes

    for change in changes:
        if change.kind not in {KIND_UPDATED, KIND_STALE, KIND_UNCHANGED}:
            continue
        source = repo_root / change.path
        if not source.is_file():
            continue
        target = run_dir / "baseline" / change.path
        atomic_write_bytes(target, source.read_bytes())


def compare_verification_captures(
    first: InventoryReport,
    second: InventoryReport,
    node_ids: Sequence[str],
) -> tuple[str, ...]:
    """Return mismatch reasons between two captures of the same node set."""
    wanted = set(node_ids)
    first_caps = [item for item in first.captures if item.node_id in wanted]
    second_caps = [item for item in second.captures if item.node_id in wanted]
    reasons: list[str] = []
    first_keys = {
        (item.node_id, item.canonical_golden_path, item.root_identity)
        for item in first_caps
    }
    second_keys = {
        (item.node_id, item.canonical_golden_path, item.root_identity)
        for item in second_caps
    }
    if first_keys != second_keys:
        missing = sorted(first_keys - second_keys)
        extra = sorted(second_keys - first_keys)
        if missing:
            reasons.append("verify_missing_keys:" + ",".join(map(str, missing)))
        if extra:
            reasons.append("verify_extra_keys:" + ",".join(map(str, extra)))
    first_by_path = {item.canonical_golden_path: item for item in first_caps}
    for item in second_caps:
        original = first_by_path.get(item.canonical_golden_path)
        if original is None:
            continue
        if original.candidate_sha256 != item.candidate_sha256:
            reasons.append(f"verify_hash_mismatch:{item.canonical_golden_path}")
        if original.node_id != item.node_id:
            reasons.append(f"verify_owner_mismatch:{item.canonical_golden_path}")
    return tuple(reasons)


def _classify_record(
    record: CaptureRecord,
    *,
    baseline: GoldenBaseline,
    repo_root: Path,
    capture_dir: Path,
) -> ChangeRecord:
    candidate_path = capture_dir / record.candidate_png_relpath
    if not candidate_path.is_file():
        raise MaintenanceError(
            f"missing candidate PNG for {record.canonical_golden_path}: "
            f"{record.candidate_png_relpath}"
        )
    candidate = candidate_path.read_bytes()
    candidate_sha = sha256_bytes(candidate)
    if candidate_sha != record.candidate_sha256:
        raise MaintenanceError(
            f"candidate hash mismatch for {record.canonical_golden_path}"
        )
    golden_state = baseline.files.get(record.canonical_golden_path)
    golden_path = repo_root / record.canonical_golden_path
    golden = golden_path.read_bytes() if golden_path.is_file() else None
    if golden is None or golden_state is None:
        return _change_from_record(
            record,
            kind=KIND_CREATED,
            baseline_sha256=None,
            baseline_width=None,
            baseline_height=None,
            candidate=candidate,
            byte_equal=False,
            encoding_only=False,
            dimension_mismatch=False,
            changed_pixels=None,
            total_pixels=record.png_width * record.png_height,
            material_diff_pixels=None,
        )
    if golden == candidate:
        width, height = _header_dims(golden)
        return _change_from_record(
            record,
            kind=KIND_UNCHANGED,
            baseline_sha256=golden_state.sha256,
            baseline_width=width,
            baseline_height=height,
            candidate=candidate,
            byte_equal=True,
            encoding_only=False,
            dimension_mismatch=False,
            changed_pixels=0,
            total_pixels=width * height,
            material_diff_pixels=0,
        )
    comparison = _pixel_comparison(golden, candidate)
    if comparison.pixel_equal and not comparison.dimension_mismatch:
        width, height = comparison.expected_size
        return _change_from_record(
            record,
            kind=KIND_UNCHANGED,
            baseline_sha256=golden_state.sha256,
            baseline_width=width,
            baseline_height=height,
            candidate=candidate,
            byte_equal=False,
            encoding_only=True,
            dimension_mismatch=False,
            changed_pixels=0,
            total_pixels=width * height,
            material_diff_pixels=0,
        )
    return _change_from_record(
        record,
        kind=KIND_UPDATED,
        baseline_sha256=golden_state.sha256,
        baseline_width=comparison.expected_size[0],
        baseline_height=comparison.expected_size[1],
        candidate=candidate,
        byte_equal=False,
        encoding_only=False,
        dimension_mismatch=comparison.dimension_mismatch,
        changed_pixels=comparison.changed_pixels,
        total_pixels=comparison.total_pixels,
        material_diff_pixels=comparison.material_diff_pixels,
    )


def _stale_record(state: GoldenFileState, *, repo_root: Path) -> ChangeRecord:
    path = repo_root / state.relative_path
    width = height = None
    if path.is_file():
        try:
            width, height = png_dimensions(path.read_bytes())
        except ValueError:
            width = height = None
    return ChangeRecord(
        kind=KIND_STALE,
        path=state.relative_path,
        root_identity=state.root_identity,
        node_id=None,
        snapshot_name=None,
        baseline_sha256=state.sha256,
        candidate_sha256=None,
        baseline_width=width,
        baseline_height=height,
        candidate_width=None,
        candidate_height=None,
        changed_pixels=None,
        total_pixels=(width * height) if width and height else None,
        material_diff_pixels=None,
        byte_equal=False,
        encoding_only=False,
        dimension_mismatch=False,
        candidate_png_relpath=None,
        candidate_svg_relpath=None,
        artifact_id=None,
    )


def _change_from_record(
    record: CaptureRecord,
    *,
    kind: str,
    baseline_sha256: str | None,
    baseline_width: int | None,
    baseline_height: int | None,
    candidate: bytes,
    byte_equal: bool,
    encoding_only: bool,
    dimension_mismatch: bool,
    changed_pixels: int | None,
    total_pixels: int | None,
    material_diff_pixels: int | None,
) -> ChangeRecord:
    return ChangeRecord(
        kind=kind,
        path=record.canonical_golden_path,
        root_identity=record.root_identity,
        node_id=record.node_id,
        snapshot_name=record.snapshot_name,
        baseline_sha256=baseline_sha256,
        candidate_sha256=record.candidate_sha256,
        baseline_width=baseline_width,
        baseline_height=baseline_height,
        candidate_width=record.png_width,
        candidate_height=record.png_height,
        changed_pixels=changed_pixels,
        total_pixels=total_pixels,
        material_diff_pixels=material_diff_pixels,
        byte_equal=byte_equal,
        encoding_only=encoding_only,
        dimension_mismatch=dimension_mismatch,
        candidate_png_relpath=record.candidate_png_relpath,
        candidate_svg_relpath=record.candidate_svg_relpath,
        artifact_id=record.artifact_id,
        test_file=record.test_file,
        test_line=record.test_line,
        source_file=record.source_file,
        source_line=record.source_line,
    )


class _PixelComparison:
    __slots__ = (
        "pixel_equal",
        "dimension_mismatch",
        "expected_size",
        "actual_size",
        "changed_pixels",
        "total_pixels",
        "material_diff_pixels",
    )

    def __init__(
        self,
        *,
        pixel_equal: bool,
        dimension_mismatch: bool,
        expected_size: tuple[int, int],
        actual_size: tuple[int, int],
        changed_pixels: int,
        total_pixels: int,
        material_diff_pixels: int,
    ) -> None:
        self.pixel_equal = pixel_equal
        self.dimension_mismatch = dimension_mismatch
        self.expected_size = expected_size
        self.actual_size = actual_size
        self.changed_pixels = changed_pixels
        self.total_pixels = total_pixels
        self.material_diff_pixels = material_diff_pixels


def _pixel_comparison(expected: bytes, actual: bytes) -> _PixelComparison:
    expected_id = _decoded_rgba(expected)
    actual_id = _decoded_rgba(actual)
    if expected_id is None or actual_id is None:
        expected_size = _header_size(expected)
        actual_size = _header_size(actual)
        return _PixelComparison(
            pixel_equal=False,
            dimension_mismatch=expected_size != actual_size,
            expected_size=expected_size,
            actual_size=actual_size,
            changed_pixels=1,
            total_pixels=max(expected_size[0] * expected_size[1], 1),
            material_diff_pixels=1,
        )
    expected_size = (expected_id[0], expected_id[1])
    actual_size = (actual_id[0], actual_id[1])
    dimension_mismatch = expected_size != actual_size
    pixel_equal = (not dimension_mismatch) and expected_id[2] == actual_id[2]
    changed_pixels = 0
    total_pixels = actual_size[0] * actual_size[1]
    material_diff_pixels = 0
    if not pixel_equal or dimension_mismatch:
        stats = _diff_stats(expected, actual)
        if stats is not None:
            changed_pixels, total_pixels, material_diff_pixels = stats
        elif dimension_mismatch:
            changed_pixels = 1
            material_diff_pixels = 1
            total_pixels = max(
                expected_size[0] * expected_size[1],
                actual_size[0] * actual_size[1],
            )
        else:
            changed_pixels = _count_changed_pixels(expected_id[2], actual_id[2])
            material_diff_pixels = changed_pixels
            total_pixels = expected_size[0] * expected_size[1]
    return _PixelComparison(
        pixel_equal=pixel_equal,
        dimension_mismatch=dimension_mismatch,
        expected_size=expected_size,
        actual_size=actual_size,
        changed_pixels=changed_pixels,
        total_pixels=total_pixels,
        material_diff_pixels=material_diff_pixels,
    )


def _decoded_rgba(png_bytes: bytes) -> tuple[int, int, bytes] | None:
    try:
        from io import BytesIO

        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(BytesIO(png_bytes)) as image:
            rgba = image.convert("RGBA")
            return rgba.width, rgba.height, rgba.tobytes()
    except Exception:
        return None


def _diff_stats(expected: bytes, actual: bytes) -> tuple[int, int, int] | None:
    try:
        from tests.ace.tui.visual._png_diff_comparison import diff_pngs
    except ImportError:
        return None
    try:
        summary, _diff = diff_pngs(expected, actual)
    except Exception:
        return None
    return summary.changed_pixels, summary.total_pixels, summary.material_diff_pixels


def _count_changed_pixels(left: bytes, right: bytes) -> int:
    if left == right:
        return 0
    stride = 4
    limit = min(len(left), len(right))
    changed = 0
    for offset in range(0, limit, stride):
        if left[offset : offset + stride] != right[offset : offset + stride]:
            changed += 1
    extra = abs(len(left) - len(right)) // stride
    return changed + extra


def _header_dims(png: bytes) -> tuple[int, int]:
    try:
        return png_dimensions(png)
    except ValueError:
        decoded = _decoded_rgba(png)
        if decoded is not None:
            return decoded[0], decoded[1]
        return 0, 0


def _header_size(png: bytes) -> tuple[int, int]:
    try:
        return png_dimensions(png)
    except ValueError:
        return (0, 0)

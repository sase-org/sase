"""PNG pixel assertions for ACE visual tests."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol

from PIL import Image, ImageChops

PNG_MAX_DIFF_RATIO_ENV = "SASE_VISUAL_PNG_MAX_DIFF_RATIO"
PNG_MATERIAL_DIFF_THRESHOLD_ENV = "SASE_VISUAL_PNG_MATERIAL_DIFF_THRESHOLD"
PNG_MAX_MATERIAL_DIFF_PIXELS_ENV = "SASE_VISUAL_PNG_MAX_MATERIAL_DIFF_PIXELS"

# Known macOS/Linux resvg drift stays within eight visible channel levels after
# alpha-aware compositing. Differences above this ceiling are product-visible,
# even when their total area is small enough for the cross-host ratio allowance.
DEFAULT_MATERIAL_DIFF_THRESHOLD = 8
DEFAULT_MAX_MATERIAL_DIFF_PIXELS = 0
_FONTS_DIR = Path(__file__).parent / "fonts"


class SvgExporter(Protocol):
    """Object that can export its current state as SVG."""

    def export_svg(
        self,
        title: str | None = None,
        simplify: bool = True,
    ) -> str: ...


@dataclass(frozen=True)
class PngDiffSummary:
    """Exact pixel comparison summary for two PNG images."""

    expected_size: tuple[int, int]
    actual_size: tuple[int, int]
    changed_pixels: int
    total_pixels: int
    material_diff_pixels: int
    material_diff_threshold: int

    @property
    def changed_ratio(self) -> float:
        return self.changed_pixels / self.total_pixels if self.total_pixels else 0.0

    @property
    def material_diff_ratio(self) -> float:
        return (
            self.material_diff_pixels / self.total_pixels if self.total_pixels else 0.0
        )

    def is_within(
        self,
        *,
        max_diff_pixels: int | None,
        max_diff_ratio: float | None,
        max_material_diff_pixels: int | None,
    ) -> bool:
        if max_diff_pixels is not None and self.changed_pixels > max_diff_pixels:
            return False
        if max_diff_ratio is not None and self.changed_ratio > max_diff_ratio:
            return False
        if (
            max_material_diff_pixels is not None
            and self.material_diff_pixels > max_material_diff_pixels
        ):
            return False
        return True


@dataclass(frozen=True)
class _PngDiffTolerance:
    max_diff_pixels: int | None
    max_diff_ratio: float | None
    material_diff_threshold: int
    max_material_diff_pixels: int | None
    source: str

    def is_within(self, summary: PngDiffSummary) -> bool:
        return summary.is_within(
            max_diff_pixels=self.max_diff_pixels,
            max_diff_ratio=self.max_diff_ratio,
            max_material_diff_pixels=self.max_material_diff_pixels,
        )

    def describe(self) -> str:
        pixels = (
            "no pixel cap"
            if self.max_diff_pixels is None
            else f"{self.max_diff_pixels} pixels"
        )
        ratio = (
            "no ratio cap"
            if self.max_diff_ratio is None
            else f"{self.max_diff_ratio:.6%}"
        )
        material = (
            "no material-pixel cap"
            if self.max_material_diff_pixels is None
            else f"{self.max_material_diff_pixels} material pixels"
        )
        return (
            f"{pixels}, {ratio}, and {material} above alpha-aware color "
            f"distance {self.material_diff_threshold} ({self.source})"
        )


@dataclass(frozen=True)
class AcePngSnapshotFixture:
    """Assert ACE PNG captures against committed golden snapshots."""

    snapshot_root: Path
    artifact_root: Path
    update: bool
    node_id: str
    test_file: str | None = None
    test_line: int | None = None
    repo_root: Path | None = None

    def assert_page_png(
        self,
        page: SvgExporter,
        name: str,
        *,
        title: str | None = None,
        simplify: bool = True,
        max_diff_pixels: int | None = None,
        max_diff_ratio: float | None = None,
        material_diff_threshold: int | None = None,
        max_material_diff_pixels: int | None = None,
    ) -> None:
        """Capture *page* as PNG and assert that it matches the golden.

        Direct helper calls default to exact equality. The repository's visual
        commands configure a bounded cross-host allowance: setting
        ``SASE_VISUAL_PNG_MAX_DIFF_RATIO`` or passing tolerance kwargs relaxes
        the exact area comparison, while the material-difference limit still
        rejects small high-contrast changes. Both limits have explicit
        overrides for renderer investigations.
        """
        svg = page.export_svg(title=title, simplify=simplify)
        png_bytes = render_svg_to_png(svg)
        self.assert_png(
            name,
            png_bytes,
            source_svg=svg,
            max_diff_pixels=max_diff_pixels,
            max_diff_ratio=max_diff_ratio,
            material_diff_threshold=material_diff_threshold,
            max_material_diff_pixels=max_material_diff_pixels,
        )

    def assert_png(
        self,
        name: str,
        png_bytes: bytes,
        *,
        source_svg: str | None = None,
        max_diff_pixels: int | None = None,
        max_diff_ratio: float | None = None,
        material_diff_threshold: int | None = None,
        max_material_diff_pixels: int | None = None,
    ) -> None:
        """Assert that *png_bytes* matches the named golden."""
        assert_png_matches(
            name,
            png_bytes,
            snapshot_root=self.snapshot_root,
            artifact_root=self.artifact_root,
            update=self.update,
            node_id=self.node_id,
            source_svg=source_svg,
            max_diff_pixels=max_diff_pixels,
            max_diff_ratio=max_diff_ratio,
            material_diff_threshold=material_diff_threshold,
            max_material_diff_pixels=max_material_diff_pixels,
            test_file=self.test_file,
            test_line=self.test_line,
            repo_root=self.repo_root,
        )


def render_svg_to_png(svg: str) -> bytes:
    """Render SVG text to PNG bytes using the pinned hermetic renderer.

    Rendering goes through resvg (a pure-Rust SVG rasterizer with its own font
    database) restricted to the bundled Fira Code. ``skip_system_fonts`` keeps
    every platform text and graphics stack out of the render. The remaining
    cross-host edge-rasterization drift is bounded by the comparison contract.
    """
    try:
        import resvg_py
    except ImportError as exc:
        raise RuntimeError(
            "ACE PNG visual snapshots require the visual test extra. "
            "Install it with `uv pip install -e '.[dev,visual]'` or an "
            "equivalent environment setup."
        ) from exc

    return bytes(
        resvg_py.svg_to_bytes(
            svg_string=svg,
            skip_system_fonts=True,
            font_dirs=[str(_FONTS_DIR)],
            font_family="Fira Code",
            monospace_family="Fira Code",
            sans_serif_family="Fira Code",
            serif_family="Fira Code",
        )
    )


def assert_png_matches(
    name: str,
    png_bytes: bytes,
    *,
    snapshot_root: Path,
    artifact_root: Path,
    update: bool,
    node_id: str,
    source_svg: str | None = None,
    max_diff_pixels: int | None = None,
    max_diff_ratio: float | None = None,
    material_diff_threshold: int | None = None,
    max_material_diff_pixels: int | None = None,
    test_file: str | None = None,
    test_line: int | None = None,
    repo_root: Path | None = None,
) -> None:
    """Assert PNG bytes against a committed golden and write diff artifacts."""
    expected_path = snapshot_path(snapshot_root, name)
    expected_repo_path = _repo_relative(expected_path, repo_root)

    if update:
        _write_bytes(expected_path, png_bytes)
        return

    if not expected_path.exists():
        artifacts = _write_failure_artifacts(
            name=name,
            artifact_root=artifact_root,
            node_id=node_id,
            actual=png_bytes,
            expected=None,
            source_svg=source_svg,
            kind="missing_golden",
            expected_repo_path=expected_repo_path,
            test_file=test_file,
            test_line=test_line,
            repo_root=repo_root,
        )
        raise AssertionError(
            "Missing ACE PNG snapshot golden: "
            f"{expected_path}\n"
            f"Actual PNG written to: {artifacts.actual_path}\n"
            f"Summary written to: {artifacts.summary_path}\n"
            "Re-run with --sase-update-visual-snapshots to accept this "
            "snapshot intentionally."
        )

    tolerance = _resolve_png_diff_tolerance(
        max_diff_pixels=max_diff_pixels,
        max_diff_ratio=max_diff_ratio,
        material_diff_threshold=material_diff_threshold,
        max_material_diff_pixels=max_material_diff_pixels,
    )
    expected = expected_path.read_bytes()
    summary, diff_png = diff_pngs(
        expected,
        png_bytes,
        material_diff_threshold=tolerance.material_diff_threshold,
    )
    if tolerance.is_within(summary):
        return

    artifacts = _write_failure_artifacts(
        name=name,
        artifact_root=artifact_root,
        node_id=node_id,
        actual=png_bytes,
        expected=expected,
        diff=diff_png,
        source_svg=source_svg,
        summary=summary,
        tolerance=tolerance,
        kind="mismatch",
        expected_repo_path=expected_repo_path,
        test_file=test_file,
        test_line=test_line,
        repo_root=repo_root,
    )
    raise AssertionError(
        "ACE PNG snapshot mismatch: "
        f"{expected_path}\n"
        f"Changed pixels: {summary.changed_pixels}/{summary.total_pixels} "
        f"({summary.changed_ratio:.6%}); materially changed pixels: "
        f"{summary.material_diff_pixels}/{summary.total_pixels} "
        f"({summary.material_diff_ratio:.6%}, alpha-aware color distance "
        f"> {summary.material_diff_threshold}); "
        f"allowed: {tolerance.describe()}\n"
        f"Expected PNG written to: {artifacts.expected_path}\n"
        f"Actual PNG written to: {artifacts.actual_path}\n"
        f"Diff PNG written to: {artifacts.diff_path}\n"
        f"Summary written to: {artifacts.summary_path}\n"
        "Inspect the artifacts, then re-run with "
        "--sase-update-visual-snapshots only for intentional changes."
    )


def _resolve_png_diff_tolerance(
    *,
    max_diff_pixels: int | None,
    max_diff_ratio: float | None,
    material_diff_threshold: int | None,
    max_material_diff_pixels: int | None,
) -> _PngDiffTolerance:
    if any(
        value is not None
        for value in (
            max_diff_pixels,
            max_diff_ratio,
            material_diff_threshold,
            max_material_diff_pixels,
        )
    ):
        return _PngDiffTolerance(
            max_diff_pixels=_validate_optional_non_negative_int(
                max_diff_pixels,
                name="max_diff_pixels",
            ),
            max_diff_ratio=_validate_optional_non_negative_float(
                max_diff_ratio,
                name="max_diff_ratio",
            ),
            material_diff_threshold=_validate_material_diff_threshold(
                DEFAULT_MATERIAL_DIFF_THRESHOLD
                if material_diff_threshold is None
                else material_diff_threshold,
                name="material_diff_threshold",
            ),
            max_material_diff_pixels=_validate_optional_non_negative_int(
                DEFAULT_MAX_MATERIAL_DIFF_PIXELS
                if max_material_diff_pixels is None
                else max_material_diff_pixels,
                name="max_material_diff_pixels",
            ),
            source="explicit",
        )
    if env_tolerance := _resolve_env_png_diff_tolerance():
        return env_tolerance
    return _PngDiffTolerance(
        max_diff_pixels=0,
        max_diff_ratio=0.0,
        material_diff_threshold=DEFAULT_MATERIAL_DIFF_THRESHOLD,
        max_material_diff_pixels=DEFAULT_MAX_MATERIAL_DIFF_PIXELS,
        source="default",
    )


def _resolve_env_png_diff_tolerance() -> _PngDiffTolerance | None:
    raw_ratio = os.environ.get(PNG_MAX_DIFF_RATIO_ENV)
    raw_material_threshold = os.environ.get(PNG_MATERIAL_DIFF_THRESHOLD_ENV)
    raw_max_material_pixels = os.environ.get(PNG_MAX_MATERIAL_DIFF_PIXELS_ENV)
    configured = {
        name: value
        for name, value in (
            (PNG_MAX_DIFF_RATIO_ENV, raw_ratio),
            (PNG_MATERIAL_DIFF_THRESHOLD_ENV, raw_material_threshold),
            (PNG_MAX_MATERIAL_DIFF_PIXELS_ENV, raw_max_material_pixels),
        )
        if value is not None
    }
    if not configured:
        return None

    max_diff_ratio = (
        0.0
        if raw_ratio is None
        else _parse_env_non_negative_float(PNG_MAX_DIFF_RATIO_ENV, raw_ratio)
    )
    material_diff_threshold = (
        DEFAULT_MATERIAL_DIFF_THRESHOLD
        if raw_material_threshold is None
        else _parse_env_material_diff_threshold(
            PNG_MATERIAL_DIFF_THRESHOLD_ENV,
            raw_material_threshold,
        )
    )
    max_material_diff_pixels = (
        DEFAULT_MAX_MATERIAL_DIFF_PIXELS
        if raw_max_material_pixels is None
        else _parse_env_non_negative_int(
            PNG_MAX_MATERIAL_DIFF_PIXELS_ENV,
            raw_max_material_pixels,
        )
    )

    return _PngDiffTolerance(
        max_diff_pixels=None,
        max_diff_ratio=max_diff_ratio,
        material_diff_threshold=material_diff_threshold,
        max_material_diff_pixels=max_material_diff_pixels,
        source=", ".join(f"${name}" for name in configured),
    )


def _parse_env_non_negative_float(name: str, raw_value: str) -> float:
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(
            f"{name} must be a finite non-negative float, got {raw_value!r}"
        ) from exc
    validated = _validate_optional_non_negative_float(value, name=name)
    assert validated is not None
    return validated


def _parse_env_non_negative_int(name: str, raw_value: str) -> int:
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(
            f"{name} must be a non-negative integer, got {raw_value!r}"
        ) from exc
    validated = _validate_optional_non_negative_int(value, name=name)
    assert validated is not None
    return validated


def _parse_env_material_diff_threshold(name: str, raw_value: str) -> int:
    value = _parse_env_non_negative_int(name, raw_value)
    return _validate_material_diff_threshold(value, name=name)


def _validate_optional_non_negative_float(
    value: float | None,
    *,
    name: str,
) -> float | None:
    if value is not None and (not math.isfinite(value) or value < 0):
        raise ValueError(f"{name} must be a finite non-negative float, got {value!r}")
    return value


def _validate_optional_non_negative_int(
    value: int | None,
    *,
    name: str,
) -> int | None:
    if value is not None and (not isinstance(value, int) or value < 0):
        raise ValueError(f"{name} must be a non-negative integer, got {value!r}")
    return value


def _validate_material_diff_threshold(value: int, *, name: str) -> int:
    validated = _validate_optional_non_negative_int(value, name=name)
    assert validated is not None
    if validated > 255:
        raise ValueError(f"{name} must be between 0 and 255, got {value!r}")
    return validated


def snapshot_path(snapshot_root: Path, name: str) -> Path:
    """Return the committed PNG golden path for *name*."""
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"invalid snapshot name: {name!r}")
    if path.suffix != ".png":
        path = path.with_suffix(".png")
    return snapshot_root / path


def diff_pngs(
    expected_png: bytes,
    actual_png: bytes,
    *,
    material_diff_threshold: int = DEFAULT_MATERIAL_DIFF_THRESHOLD,
) -> tuple[PngDiffSummary, bytes]:
    """Compare two PNG byte strings and return a red-pixel diff image."""
    material_diff_threshold = _validate_material_diff_threshold(
        material_diff_threshold,
        name="material_diff_threshold",
    )
    expected = _load_png(expected_png)
    actual = _load_png(actual_png)
    size = (
        max(expected.width, actual.width),
        max(expected.height, actual.height),
    )
    expected_canvas = _place_on_canvas(expected, size)
    actual_canvas = _place_on_canvas(actual, size)

    exact_distance = _max_channel(ImageChops.difference(expected_canvas, actual_canvas))
    changed_mask = exact_distance.point([0, *([255] * 255)])
    changed_pixels = sum(exact_distance.histogram()[1:])

    material_distance = _alpha_aware_color_distance(
        expected_canvas,
        actual_canvas,
    )
    material_diff_pixels = sum(
        material_distance.histogram()[material_diff_threshold + 1 :]
    )

    diff = Image.new("RGBA", size, (255, 0, 0, 0))
    diff.putalpha(changed_mask)

    return (
        PngDiffSummary(
            expected_size=expected.size,
            actual_size=actual.size,
            changed_pixels=changed_pixels,
            total_pixels=size[0] * size[1],
            material_diff_pixels=material_diff_pixels,
            material_diff_threshold=material_diff_threshold,
        ),
        _to_png_bytes(diff),
    )


@dataclass(frozen=True)
class _FailureArtifacts:
    actual_path: Path
    expected_path: Path | None
    diff_path: Path | None
    source_svg_path: Path | None
    summary_path: Path
    failure_json_path: Path


def _write_failure_artifacts(
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
    tolerance: _PngDiffTolerance | None = None,
) -> _FailureArtifacts:
    failure_dir = artifact_root / _slug(node_id) / _slug(name)
    actual_path = failure_dir / "actual.png"
    expected_path = failure_dir / "expected.png"
    diff_path = failure_dir / "diff.png"
    source_svg_path = failure_dir / "actual.svg"
    summary_path = failure_dir / "summary.txt"
    failure_json_path = failure_dir / "failure.json"

    _write_bytes(actual_path, actual)
    if expected is not None:
        _write_bytes(expected_path, expected)
    if diff is not None:
        _write_bytes(diff_path, diff)
    if source_svg is not None:
        _write_text(source_svg_path, source_svg)
    _write_text(summary_path, _summary_text(summary, tolerance))

    record: dict[str, Any] = {
        "node_id": node_id,
        "snapshot": name,
        "kind": kind,
        "expected_repo_path": expected_repo_path,
        "actual_path": _repo_relative(actual_path, repo_root),
        "summary_path": _repo_relative(summary_path, repo_root),
        "test_file": test_file,
        "test_line": test_line,
    }
    if expected is not None:
        record["expected_path"] = _repo_relative(expected_path, repo_root)
    if diff is not None:
        record["diff_path"] = _repo_relative(diff_path, repo_root)
    if source_svg is not None:
        record["source_svg_path"] = _repo_relative(source_svg_path, repo_root)
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

    return _FailureArtifacts(
        actual_path=actual_path,
        expected_path=expected_path if expected is not None else None,
        diff_path=diff_path if diff is not None else None,
        source_svg_path=source_svg_path if source_svg is not None else None,
        summary_path=summary_path,
        failure_json_path=failure_json_path,
    )


def _repo_relative(path: Path, repo_root: Path | None) -> str:
    """Return *path* as a repo-relative POSIX string when possible."""
    if repo_root is None:
        return path.as_posix()
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _summary_text(
    summary: PngDiffSummary | None,
    tolerance: _PngDiffTolerance | None,
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


def _load_png(value: bytes) -> Image.Image:
    with Image.open(BytesIO(value)) as image:
        return image.convert("RGBA")


def _place_on_canvas(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    canvas.paste(image, (0, 0))
    return canvas


def _max_channel(image: Image.Image) -> Image.Image:
    channels = image.split()
    maximum = channels[0]
    for channel in channels[1:]:
        maximum = ImageChops.lighter(maximum, channel)
    return maximum


def _alpha_aware_color_distance(
    expected: Image.Image,
    actual: Image.Image,
) -> Image.Image:
    """Return maximum visible channel distance over black and white canvases."""
    distance_channels: list[Image.Image] = []
    for background_color in ((0, 0, 0, 255), (255, 255, 255, 255)):
        background = Image.new("RGBA", expected.size, background_color)
        expected_composite = Image.alpha_composite(background, expected).convert("RGB")
        actual_composite = Image.alpha_composite(background, actual).convert("RGB")
        distance_channels.extend(
            ImageChops.difference(expected_composite, actual_composite).split()
        )

    maximum = distance_channels[0]
    for channel in distance_channels[1:]:
        maximum = ImageChops.lighter(maximum, channel)
    return maximum


def _optional_limit(value: int | float | None) -> str:
    return "none" if value is None else str(value)


def _to_png_bytes(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


def _slug(value: str) -> str:
    chars = [char if char.isalnum() or char in "._-" else "_" for char in value]
    slug = "".join(chars).strip("._-")
    return slug or "snapshot"

"""PNG pixel assertions for ACE visual tests."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Protocol

from PIL import Image


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

    @property
    def changed_ratio(self) -> float:
        return self.changed_pixels / self.total_pixels if self.total_pixels else 0.0

    def is_within(
        self,
        *,
        max_diff_pixels: int,
        max_diff_ratio: float,
    ) -> bool:
        return (
            self.changed_pixels <= max_diff_pixels
            and self.changed_ratio <= max_diff_ratio
        )


@dataclass(frozen=True)
class AcePngSnapshotFixture:
    """Assert ACE PNG captures against committed golden snapshots."""

    snapshot_root: Path
    artifact_root: Path
    update: bool
    node_id: str

    def assert_page_png(
        self,
        page: SvgExporter,
        name: str,
        *,
        title: str | None = None,
        simplify: bool = True,
        max_diff_pixels: int = 0,
        max_diff_ratio: float = 0.0,
    ) -> None:
        """Capture *page* as PNG and assert that it matches the golden."""
        svg = page.export_svg(title=title, simplify=simplify)
        png_bytes = render_svg_to_png(svg)
        self.assert_png(
            name,
            png_bytes,
            source_svg=svg,
            max_diff_pixels=max_diff_pixels,
            max_diff_ratio=max_diff_ratio,
        )

    def assert_png(
        self,
        name: str,
        png_bytes: bytes,
        *,
        source_svg: str | None = None,
        max_diff_pixels: int = 0,
        max_diff_ratio: float = 0.0,
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
        )


def render_svg_to_png(svg: str) -> bytes:
    """Render SVG text to PNG bytes using the opt-in visual renderer."""
    try:
        import cairosvg
    except ImportError as exc:
        raise RuntimeError(
            "ACE PNG visual snapshots require the visual test extra. "
            "Install it with `uv pip install -e '.[dev,visual]'` or an "
            "equivalent environment setup."
        ) from exc

    return cairosvg.svg2png(bytestring=svg.encode("utf-8"))


def assert_png_matches(
    name: str,
    png_bytes: bytes,
    *,
    snapshot_root: Path,
    artifact_root: Path,
    update: bool,
    node_id: str,
    source_svg: str | None = None,
    max_diff_pixels: int = 0,
    max_diff_ratio: float = 0.0,
) -> None:
    """Assert PNG bytes against a committed golden and write diff artifacts."""
    expected_path = snapshot_path(snapshot_root, name)

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
        )
        raise AssertionError(
            "Missing ACE PNG snapshot golden: "
            f"{expected_path}\n"
            f"Actual PNG written to: {artifacts.actual_path}\n"
            f"Summary written to: {artifacts.summary_path}\n"
            "Re-run with --sase-update-visual-snapshots to accept this "
            "snapshot intentionally."
        )

    expected = expected_path.read_bytes()
    summary, diff_png = diff_pngs(expected, png_bytes)
    if summary.is_within(
        max_diff_pixels=max_diff_pixels,
        max_diff_ratio=max_diff_ratio,
    ):
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
    )
    raise AssertionError(
        "ACE PNG snapshot mismatch: "
        f"{expected_path}\n"
        f"Changed pixels: {summary.changed_pixels}/{summary.total_pixels} "
        f"({summary.changed_ratio:.6%}); "
        f"allowed <= {max_diff_pixels} pixels and <= {max_diff_ratio:.6%}\n"
        f"Expected PNG written to: {artifacts.expected_path}\n"
        f"Actual PNG written to: {artifacts.actual_path}\n"
        f"Diff PNG written to: {artifacts.diff_path}\n"
        f"Summary written to: {artifacts.summary_path}\n"
        "Inspect the artifacts, then re-run with "
        "--sase-update-visual-snapshots only for intentional changes."
    )


def snapshot_path(snapshot_root: Path, name: str) -> Path:
    """Return the committed PNG golden path for *name*."""
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"invalid snapshot name: {name!r}")
    if path.suffix != ".png":
        path = path.with_suffix(".png")
    return snapshot_root / path


def diff_pngs(expected_png: bytes, actual_png: bytes) -> tuple[PngDiffSummary, bytes]:
    """Compare two PNG byte strings and return a red-pixel diff image."""
    expected = _load_png(expected_png)
    actual = _load_png(actual_png)
    size = (
        max(expected.width, actual.width),
        max(expected.height, actual.height),
    )
    expected_canvas = _place_on_canvas(expected, size)
    actual_canvas = _place_on_canvas(actual, size)

    expected_pixels = _image_pixels(expected_canvas)
    actual_pixels = _image_pixels(actual_canvas)
    changed = [
        left != right
        for left, right in zip(expected_pixels, actual_pixels, strict=True)
    ]

    diff = Image.new("RGBA", size, (0, 0, 0, 0))
    diff.putdata(
        [(255, 0, 0, 255) if is_changed else (0, 0, 0, 0) for is_changed in changed]
    )

    return (
        PngDiffSummary(
            expected_size=expected.size,
            actual_size=actual.size,
            changed_pixels=sum(changed),
            total_pixels=size[0] * size[1],
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


def _write_failure_artifacts(
    *,
    name: str,
    artifact_root: Path,
    node_id: str,
    actual: bytes,
    expected: bytes | None,
    source_svg: str | None,
    diff: bytes | None = None,
    summary: PngDiffSummary | None = None,
) -> _FailureArtifacts:
    failure_dir = artifact_root / _slug(node_id) / _slug(name)
    actual_path = failure_dir / "actual.png"
    expected_path = failure_dir / "expected.png"
    diff_path = failure_dir / "diff.png"
    source_svg_path = failure_dir / "actual.svg"
    summary_path = failure_dir / "summary.txt"

    _write_bytes(actual_path, actual)
    if expected is not None:
        _write_bytes(expected_path, expected)
    if diff is not None:
        _write_bytes(diff_path, diff)
    if source_svg is not None:
        _write_text(source_svg_path, source_svg)
    _write_text(summary_path, _summary_text(summary))

    return _FailureArtifacts(
        actual_path=actual_path,
        expected_path=expected_path if expected is not None else None,
        diff_path=diff_path if diff is not None else None,
        source_svg_path=source_svg_path if source_svg is not None else None,
        summary_path=summary_path,
    )


def _summary_text(summary: PngDiffSummary | None) -> str:
    if summary is None:
        return "expected PNG golden is missing\n"
    return (
        f"expected_size: {summary.expected_size[0]}x{summary.expected_size[1]}\n"
        f"actual_size: {summary.actual_size[0]}x{summary.actual_size[1]}\n"
        f"changed_pixels: {summary.changed_pixels}\n"
        f"total_pixels: {summary.total_pixels}\n"
        f"changed_ratio: {summary.changed_ratio:.12f}\n"
    )


def _load_png(value: bytes) -> Image.Image:
    with Image.open(BytesIO(value)) as image:
        return image.convert("RGBA")


def _place_on_canvas(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    canvas.paste(image, (0, 0))
    return canvas


def _image_pixels(image: Image.Image) -> list[tuple[int, int, int, int]]:
    get_flattened_data = getattr(image, "get_flattened_data", None)
    if get_flattened_data is not None:
        return list(get_flattened_data())
    return list(image.getdata())


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

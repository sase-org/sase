"""PNG pixel assertions for ACE visual tests."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol

from PIL import Image

GITHUB_ACTIONS_MAX_DIFF_RATIO = 0.01


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
        max_diff_pixels: int | None,
        max_diff_ratio: float | None,
    ) -> bool:
        if max_diff_pixels is not None and self.changed_pixels > max_diff_pixels:
            return False
        if max_diff_ratio is not None and self.changed_ratio > max_diff_ratio:
            return False
        return True


@dataclass(frozen=True)
class _PngDiffTolerance:
    max_diff_pixels: int | None
    max_diff_ratio: float | None
    source: str

    def is_within(self, summary: PngDiffSummary) -> bool:
        return summary.is_within(
            max_diff_pixels=self.max_diff_pixels,
            max_diff_ratio=self.max_diff_ratio,
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
        return f"{pixels} and {ratio} ({self.source})"


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
    ) -> None:
        """Capture *page* as PNG and assert that it matches the golden.

        Local runs default to exact pixel equality. GitHub Actions workflow
        runs default to a small ratio-only tolerance to absorb renderer drift.
        Explicit ``max_diff_pixels`` or ``max_diff_ratio`` kwargs take
        precedence over those environment-derived defaults.
        """
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
        max_diff_pixels: int | None = None,
        max_diff_ratio: float | None = None,
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
            test_file=self.test_file,
            test_line=self.test_line,
            repo_root=self.repo_root,
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
    max_diff_pixels: int | None = None,
    max_diff_ratio: float | None = None,
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

    expected = expected_path.read_bytes()
    summary, diff_png = diff_pngs(expected, png_bytes)
    tolerance = _resolve_png_diff_tolerance(
        max_diff_pixels=max_diff_pixels,
        max_diff_ratio=max_diff_ratio,
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
        f"({summary.changed_ratio:.6%}); "
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
) -> _PngDiffTolerance:
    if max_diff_pixels is not None or max_diff_ratio is not None:
        return _PngDiffTolerance(
            max_diff_pixels=max_diff_pixels,
            max_diff_ratio=max_diff_ratio,
            source="explicit",
        )
    if _running_in_github_actions_workflow():
        return _PngDiffTolerance(
            max_diff_pixels=None,
            max_diff_ratio=GITHUB_ACTIONS_MAX_DIFF_RATIO,
            source="GitHub Actions default",
        )
    return _PngDiffTolerance(
        max_diff_pixels=0,
        max_diff_ratio=0.0,
        source="local default",
    )


def _running_in_github_actions_workflow() -> bool:
    """Return true for GitHub Actions workflow execution, not generic CI."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return False
    return bool(os.environ.get("GITHUB_WORKFLOW") or os.environ.get("GITHUB_RUN_ID"))


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
    _write_text(summary_path, _summary_text(summary))

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

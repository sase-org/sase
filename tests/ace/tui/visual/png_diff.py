"""PNG pixel assertions for ACE visual tests.

This module is the public façade for the visual snapshot helper. Pixel
comparison, tolerance resolution, and failure artifact serialization live in
focused sibling modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sase.ace.testing import AcePage
from tests.ace.tui.visual._png_diff_artifacts import (
    repo_relative,
    snapshot_path,
    write_bytes,
    write_failure_artifacts,
)
from tests.ace.tui.visual._png_diff_comparison import (
    DEFAULT_MATERIAL_DIFF_THRESHOLD,
    PngDiffSummary,
    diff_pngs,
)
from tests.ace.tui.visual._png_diff_tolerance import (
    DEFAULT_MAX_MATERIAL_DIFF_PIXELS,
    PNG_MATERIAL_DIFF_THRESHOLD_ENV,
    PNG_MAX_DIFF_RATIO_ENV,
    PNG_MAX_MATERIAL_DIFF_PIXELS_ENV,
    resolve_png_diff_tolerance,
)

_FONTS_DIR = Path(__file__).parent / "fonts"

__all__ = [
    "DEFAULT_MATERIAL_DIFF_THRESHOLD",
    "DEFAULT_MAX_MATERIAL_DIFF_PIXELS",
    "PNG_MATERIAL_DIFF_THRESHOLD_ENV",
    "PNG_MAX_DIFF_RATIO_ENV",
    "PNG_MAX_MATERIAL_DIFF_PIXELS_ENV",
    "AcePngSnapshotFixture",
    "PngDiffSummary",
    "SvgExporter",
    "assert_png_matches",
    "diff_pngs",
    "render_svg_to_png",
    "snapshot_path",
]


class SvgExporter(Protocol):
    """Object that can export its current state as SVG."""

    def export_svg(
        self,
        title: str | None = None,
        simplify: bool = True,
    ) -> str: ...


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

        Direct helper calls and the repository's visual commands default to
        exact equality. Setting ``SASE_VISUAL_PNG_MAX_DIFF_RATIO`` or passing
        tolerance kwargs relaxes the exact area comparison, while the
        material-difference limit still rejects small high-contrast changes.
        Both limits have explicit overrides for renderer investigations.
        """
        if isinstance(page, AcePage):
            # ``assert_page_png`` must stay synchronous across the verified
            # canonical export and this titled export. That makes the
            # rasterized frame exactly the one whose convergence was proved,
            # even when an earlier await allowed Textual to repaint.
            from tests.ace.tui.visual._ace_png_snapshot_waits import (
                assert_visual_frame_converged,
            )

            assert_visual_frame_converged(page)
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
    database) restricted to the fonts bundled in ``fonts/``.
    ``skip_system_fonts`` keeps every platform text and graphics stack out of
    the render. Naming Fira Code for every generic family gives it every glyph
    it carries; resvg falls back within the bundled database only for a
    codepoint Fira Code lacks, which is how symbol marks such as the
    notification tab icons rasterize as themselves instead of ``.notdef``
    boxes. ``font_files`` lists those faces explicitly because some
    ``resvg-py`` wheels never scan ``font_dirs``. Explicit tolerance
    overrides remain available when investigating cross-host
    edge-rasterization drift.
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
            # Some resvg-py wheels ignore font_dirs (CPython 3.14 manylinux).
            # Listing faces makes Noto Emoji / DejaVu load on every wheel.
            font_files=_bundled_font_files(),
            font_family="Fira Code",
            monospace_family="Fira Code",
            sans_serif_family="Fira Code",
            serif_family="Fira Code",
        )
    )


def _bundled_font_files() -> list[str]:
    """Return paths to every bundled snapshot face."""
    return sorted(
        str(path)
        for path in _FONTS_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in {".otf", ".ttf"}
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
    expected_repo_path = repo_relative(expected_path, repo_root)

    if update:
        write_bytes(expected_path, png_bytes)
        return

    if not expected_path.exists():
        artifacts = write_failure_artifacts(
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

    tolerance = resolve_png_diff_tolerance(
        max_diff_pixels=max_diff_pixels,
        max_diff_ratio=max_diff_ratio,
        material_diff_threshold=material_diff_threshold,
        max_material_diff_pixels=max_material_diff_pixels,
    )
    expected = expected_path.read_bytes()
    # The pinned local renderer emits deterministic PNG bytes. Avoid decoding,
    # compositing, diffing, and re-encoding the overwhelmingly common exact
    # passing case. Byte differences still take the normal pixel-comparison
    # path, so equivalent encodings and every failure artifact behave exactly
    # as before.
    if expected == png_bytes:
        return
    summary, diff_png = diff_pngs(
        expected,
        png_bytes,
        material_diff_threshold=tolerance.material_diff_threshold,
    )
    if tolerance.is_within(summary):
        return

    artifacts = write_failure_artifacts(
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

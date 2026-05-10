"""SVG snapshot assertions for ACE visual tests."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Protocol


class SvgExporter(Protocol):
    """Object that can export its current state as SVG."""

    def export_svg(
        self,
        title: str | None = None,
        simplify: bool = True,
    ) -> str: ...


@dataclass(frozen=True)
class AceSvgSnapshotFixture:
    """Assert ACE SVG captures against committed golden snapshots."""

    snapshot_root: Path
    artifact_root: Path
    update: bool
    node_id: str

    def assert_svg(
        self,
        page: SvgExporter,
        name: str,
        *,
        title: str | None = None,
        simplify: bool = True,
    ) -> None:
        """Assert that *page*'s SVG matches the named golden."""
        actual = page.export_svg(title=title, simplify=simplify)
        expected_path = self.snapshot_path(name)

        if self.update:
            self._write_text(expected_path, actual)
            return

        if not expected_path.exists():
            artifacts = self._write_failure_artifacts(
                name=name,
                actual=actual,
                expected=None,
            )
            raise AssertionError(
                "Missing ACE SVG snapshot golden: "
                f"{expected_path}\n"
                f"Actual SVG written to: {artifacts.actual_path}\n"
                f"HTML report written to: {artifacts.report_path}\n"
                "Re-run with --sase-update-visual-snapshots to accept this "
                "snapshot intentionally."
            )

        expected = expected_path.read_text()
        if actual == expected:
            return

        artifacts = self._write_failure_artifacts(
            name=name,
            actual=actual,
            expected=expected,
        )
        raise AssertionError(
            "ACE SVG snapshot mismatch: "
            f"{expected_path}\n"
            f"Expected SVG written to: {artifacts.expected_path}\n"
            f"Actual SVG written to: {artifacts.actual_path}\n"
            f"HTML report written to: {artifacts.report_path}\n"
            "Inspect the artifacts, then re-run with "
            "--sase-update-visual-snapshots only for intentional changes."
        )

    def snapshot_path(self, name: str) -> Path:
        """Return the committed golden path for *name*."""
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"invalid snapshot name: {name!r}")
        if path.suffix != ".svg":
            path = path.with_suffix(".svg")
        return self.snapshot_root / path

    def _write_failure_artifacts(
        self,
        *,
        name: str,
        actual: str,
        expected: str | None,
    ) -> _FailureArtifacts:
        failure_dir = self.artifact_root / _slug(self.node_id) / _slug(name)
        actual_path = failure_dir / "actual.svg"
        expected_path = failure_dir / "expected.svg"
        report_path = failure_dir / "report.html"

        self._write_text(actual_path, actual)
        if expected is not None:
            self._write_text(expected_path, expected)
        self._write_text(
            report_path,
            _html_report(
                name=name,
                expected_exists=expected is not None,
                expected_path=expected_path,
                actual_path=actual_path,
            ),
        )
        return _FailureArtifacts(
            actual_path=actual_path,
            expected_path=expected_path if expected is not None else None,
            report_path=report_path,
        )

    @staticmethod
    def _write_text(path: Path, value: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)


@dataclass(frozen=True)
class _FailureArtifacts:
    actual_path: Path
    expected_path: Path | None
    report_path: Path


def _slug(value: str) -> str:
    chars = [char if char.isalnum() or char in "._-" else "_" for char in value]
    slug = "".join(chars).strip("._-")
    return slug or "snapshot"


def _html_report(
    *,
    name: str,
    expected_exists: bool,
    expected_path: Path,
    actual_path: Path,
) -> str:
    expected_panel = (
        f'<iframe title="expected" src="{escape(expected_path.name)}"></iframe>'
        if expected_exists
        else "<p>No expected SVG golden exists.</p>"
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>ACE SVG Snapshot: {escape(name)}</title>
  <style>
    body {{ font-family: sans-serif; margin: 16px; }}
    main {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    iframe {{ width: 100%; height: 80vh; border: 1px solid #999; }}
    h1 {{ font-size: 18px; }}
    h2 {{ font-size: 14px; }}
  </style>
</head>
<body>
  <h1>{escape(name)}</h1>
  <main>
    <section>
      <h2>Expected</h2>
      {expected_panel}
    </section>
    <section>
      <h2>Actual</h2>
      <iframe title="actual" src="{escape(actual_path.name)}"></iframe>
    </section>
  </main>
</body>
</html>
"""

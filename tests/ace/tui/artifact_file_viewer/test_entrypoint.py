from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from sase.ace.tui.graphics.viewer import (
    ArtifactFileViewerResult,
    ArtifactFileViewSpec,
    main as viewer_main,
)


def test_viewer_module_entrypoint_delegates_to_view_artifact_files(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    artifact = tmp_path / "artifact.png"
    artifact.write_bytes(b"png")
    calls: list[tuple[ArtifactFileViewSpec, ...]] = []

    def fake_viewer(artifacts) -> ArtifactFileViewerResult:
        calls.append(tuple(artifacts))
        return ArtifactFileViewerResult(True)

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.view_artifact_files", fake_viewer)

    code = viewer_main(["--kind", "image", str(artifact)])

    assert code == 0
    assert calls == [(ArtifactFileViewSpec(str(artifact), "image"),)]
    assert capsys.readouterr().err == ""


def test_viewer_module_entrypoint_accepts_multiple_paths_and_kinds(
    tmp_path: Path,
    monkeypatch,
) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.md"
    calls: list[tuple[ArtifactFileViewSpec, ...]] = []

    def fake_viewer(artifacts) -> ArtifactFileViewerResult:
        calls.append(tuple(artifacts))
        return ArtifactFileViewerResult(True)

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.view_artifact_files", fake_viewer)

    code = viewer_main(
        ["--kind", "image", "--kind", "markdown", str(first), str(second)]
    )

    assert code == 0
    assert calls == [
        (
            ArtifactFileViewSpec(str(first), "image"),
            ArtifactFileViewSpec(str(second), "markdown"),
        )
    ]


def test_viewer_module_entrypoint_prints_warning_and_returns_nonzero(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    artifact = tmp_path / "artifact.png"
    artifact.write_bytes(b"png")

    def fake_viewer(artifacts) -> ArtifactFileViewerResult:
        del artifacts
        return ArtifactFileViewerResult(False, warning="missing dependency")

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.view_artifact_files", fake_viewer)

    code = viewer_main([str(artifact)])

    assert code == 1
    assert capsys.readouterr().err == "missing dependency\n"


def test_viewer_module_entrypoint_help_does_not_emit_runpy_warning() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-Wdefault",
            "-m",
            "sase.ace.tui.graphics.viewer",
            "--help",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "RuntimeWarning" not in result.stderr
    assert "found in sys.modules" not in result.stderr

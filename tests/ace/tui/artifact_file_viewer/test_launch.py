from __future__ import annotations

import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from sase.ace.tui.graphics._viewer_launch import _artifact_file_view_spec
from sase.ace.tui.graphics._viewer_loop import (
    _PageLoopResult,
    run_artifact_sequence_loop,
)
from sase.ace.tui.graphics.viewer import (
    ArtifactFileImageArea,
    ArtifactRenderResult,
    ArtifactFileViewSpec,
    view_registered_artifact_files,
    view_registered_artifact_files_in_tmux_pane,
)


@dataclass(frozen=True)
class _Artifact:
    path: str
    kind: str
    source_path: str | None = None
    workspace_dir: str | None = None


def test_artifact_file_view_spec_rerenders_markdown_pdf_source(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "artifacts" / "markdown_pdfs" / "report.pdf"
    source = tmp_path / "workspace" / "docs" / "report.md"
    pdf.parent.mkdir(parents=True)
    source.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF")
    source.write_text("# Report\n", encoding="utf-8")

    spec = _artifact_file_view_spec(
        _Artifact(path=str(pdf), kind="pdf", source_path=str(source))
    )

    assert spec == ArtifactFileViewSpec(source, "markdown")


def test_artifact_file_view_spec_keeps_pdf_when_source_is_unusable(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "artifacts" / "markdown_pdfs" / "report.pdf"
    text_source = tmp_path / "workspace" / "docs" / "report.txt"
    missing_source = tmp_path / "workspace" / "docs" / "missing.md"
    pdf.parent.mkdir(parents=True)
    text_source.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF")
    text_source.write_text("Report\n", encoding="utf-8")

    assert _artifact_file_view_spec(_Artifact(path=str(pdf), kind="pdf")) == (
        ArtifactFileViewSpec(str(pdf), "pdf")
    )
    assert _artifact_file_view_spec(
        _Artifact(path=str(pdf), kind="pdf", source_path=str(text_source))
    ) == ArtifactFileViewSpec(str(pdf), "pdf")
    assert _artifact_file_view_spec(
        _Artifact(path=str(pdf), kind="pdf", source_path=str(missing_source))
    ) == ArtifactFileViewSpec(str(pdf), "pdf")


def test_view_registered_artifact_files_passes_normalized_specs_to_viewer_loop(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pdf = tmp_path / "artifacts" / "markdown_pdfs" / "report.pdf"
    source = tmp_path / "workspace" / "docs" / "report.md"
    image = tmp_path / "image.png"
    pdf.parent.mkdir(parents=True)
    source.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF")
    source.write_text("# Report\n", encoding="utf-8")
    image.write_bytes(b"png")
    calls: list[tuple[ArtifactFileViewSpec, ...]] = []

    def fake_loop(artifacts, **_kwargs) -> _PageLoopResult:
        calls.append(tuple(artifacts))
        return _PageLoopResult()

    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_launch.run_artifact_sequence_loop",
        fake_loop,
    )

    result = view_registered_artifact_files(
        (
            _Artifact(path=str(pdf), kind="pdf", source_path=str(source)),
            _Artifact(path=str(image), kind="image"),
        )
    )

    assert result.ok is True
    assert calls == [
        (
            ArtifactFileViewSpec(source, "markdown"),
            ArtifactFileViewSpec(str(image), "image"),
        )
    ]


def test_view_registered_artifact_files_tmux_pane_uses_normalized_module_command(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pdf = tmp_path / "artifacts" / "markdown_pdfs" / "report.pdf"
    source = tmp_path / "workspace" / "docs" / "report.md"
    pdf.parent.mkdir(parents=True)
    source.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF")
    source.write_text("# Report\n", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setenv("TMUX", "/tmp/tmux")
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.shutil.which",
        lambda tool: f"/usr/bin/{tool}" if tool == "tmux" else None,
    )

    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "%7\n", "")

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.subprocess.run", fake_run)

    result = view_registered_artifact_files_in_tmux_pane(
        (_Artifact(path=str(pdf), kind="pdf", source_path=str(source)),)
    )

    assert result.ok is True
    assert shlex.split(calls[0][6]) == [
        sys.executable,
        "-m",
        "sase.ace.tui.graphics.viewer",
        "--kind",
        "markdown",
        str(source),
    ]


def test_normalized_markdown_pdf_reaches_renderer_with_image_area(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pdf = tmp_path / "artifacts" / "markdown_pdfs" / "report.pdf"
    source = tmp_path / "workspace" / "docs" / "report.md"
    page = tmp_path / "page-1.png"
    pdf.parent.mkdir(parents=True)
    source.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF")
    source.write_text("# Report\n", encoding="utf-8")
    page.write_bytes(b"png")
    image_area = ArtifactFileImageArea(columns=90, rows=24)
    render_calls: list[tuple[Path, str | None, Path, ArtifactFileImageArea | None]] = []

    def fake_render_artifact_pages(path, *, kind=None, cache_dir=None, image_area=None):
        render_calls.append((Path(path), kind, Path(cache_dir), image_area))
        return ArtifactRenderResult((page,))

    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_loop.render_artifact_file_pages",
        fake_render_artifact_pages,
    )

    def fake_run(cmd):
        return subprocess.CompletedProcess(cmd, 0)

    spec = _artifact_file_view_spec(
        _Artifact(path=str(pdf), kind="pdf", source_path=str(source))
    )
    result = run_artifact_sequence_loop(
        (spec,),
        cache_root=tmp_path / "cache",
        read_key=lambda: "q",
        run_command=fake_run,
        image_area=image_area,
    )

    assert result.returncode == 0
    assert render_calls == [
        (source, "markdown", tmp_path / "cache" / "artifact-0", image_area)
    ]

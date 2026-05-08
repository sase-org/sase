from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

from sase.ace.tui.graphics.viewer import (
    ArtifactViewerResult,
    artifact_view_mode,
    convert_pdf_to_png_pages,
    is_tmux_session,
    main as viewer_main,
    page_index_after_key,
    render_artifact_pages,
    run_artifact_page_loop,
    validate_artifact_viewer_dependencies,
    view_artifact_file,
    view_artifact_file_in_tmux_pane,
)


def test_convert_pdf_to_png_pages_uses_pdftoppm_and_numeric_order(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pdf = tmp_path / "artifact.pdf"
    pdf.write_bytes(b"%PDF")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        prefix = Path(cmd[-1])
        (prefix.parent / f"{prefix.name}-10.png").write_bytes(b"10")
        (prefix.parent / f"{prefix.name}-2.png").write_bytes(b"2")
        (prefix.parent / f"{prefix.name}-1.png").write_bytes(b"1")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.subprocess.run", fake_run)

    result = convert_pdf_to_png_pages(pdf, tmp_path / "pages")

    assert calls == [["pdftoppm", "-png", str(pdf), str(tmp_path / "pages" / "page")]]
    assert [path.name for path in result.pages] == [
        "page-1.png",
        "page-2.png",
        "page-10.png",
    ]
    assert result.warnings == ()


def test_convert_pdf_to_png_pages_reports_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pdf = tmp_path / "artifact.pdf"
    pdf.write_bytes(b"%PDF")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 2, "", "bad pdf")

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.subprocess.run", fake_run)

    result = convert_pdf_to_png_pages(pdf, tmp_path / "pages")

    assert result.pages == ()
    assert result.warnings[0].code == "pdftoppm_failed"
    assert "bad pdf" in result.warnings[0].message


def test_artifact_page_index_state_machine() -> None:
    assert page_index_after_key(0, "n", 3) == 1
    assert page_index_after_key(2, "n", 3) == 2
    assert page_index_after_key(2, "p", 3) == 1
    assert page_index_after_key(0, "p", 3) == 0
    assert page_index_after_key(1, "x", 3) == 1
    assert page_index_after_key(0, "q", 3) is None
    assert page_index_after_key(0, "n", 1) == 0


def test_run_artifact_page_loop_redraws_and_tracks_keys(tmp_path: Path) -> None:
    pages = [tmp_path / "page-1.png", tmp_path / "page-2.png"]
    for page in pages:
        page.write_bytes(b"png")
    commands: list[list[str]] = []
    keys = iter(["n", "p", "q"])

    def fake_run(cmd):
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    result = run_artifact_page_loop(
        pages,
        read_key=lambda: next(keys),
        run_command=fake_run,
    )

    assert result.returncode == 0
    assert commands == [
        ["clear"],
        ["kitten", "icat", str(pages[0])],
        ["clear"],
        ["kitten", "icat", str(pages[1])],
        ["clear"],
        ["kitten", "icat", str(pages[0])],
        ["clear"],
    ]


def test_validate_artifact_viewer_dependencies_reports_missing_tools(
    monkeypatch,
) -> None:
    monkeypatch.setattr("sase.ace.tui.graphics.viewer.shutil.which", lambda _tool: None)

    warnings = validate_artifact_viewer_dependencies("markdown")

    assert [warning.code for warning in warnings] == [
        "missing_kitten",
        "missing_pdftoppm",
        "missing_pandoc",
        "missing_pdf_engine",
    ]


def test_render_markdown_artifact_uses_transient_pdf_and_pdf_pages(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "chat.md"
    source.write_text("# Chat\n", encoding="utf-8")
    rendered_pdf_paths: list[Path] = []
    pdftoppm_calls: list[list[str]] = []

    def fake_which(tool: str) -> str:
        return f"/usr/bin/{tool}"

    def fake_render_markdown_pdf(src: Path, dest: Path) -> Path:
        assert src == source
        rendered_pdf_paths.append(dest)
        dest.write_bytes(b"%PDF")
        return dest

    def fake_run(cmd, **kwargs):
        pdftoppm_calls.append(cmd)
        prefix = Path(cmd[-1])
        (prefix.parent / f"{prefix.name}-1.png").write_bytes(b"png")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.shutil.which", fake_which)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.render_markdown_pdf",
        fake_render_markdown_pdf,
    )
    monkeypatch.setattr("sase.ace.tui.graphics.viewer.subprocess.run", fake_run)

    result = render_artifact_pages(source, kind="chat", cache_dir=tmp_path / "cache")

    assert result.warnings == ()
    assert [path.name for path in rendered_pdf_paths] == ["chat.pdf"]
    assert pdftoppm_calls == [
        [
            "pdftoppm",
            "-png",
            str(tmp_path / "cache" / "chat.pdf"),
            str(tmp_path / "cache" / "markdown_pages" / "page"),
        ]
    ]
    assert [path.name for path in result.pages] == ["page-1.png"]


def test_render_artifact_pages_reports_unsupported_kind(tmp_path: Path) -> None:
    artifact = tmp_path / "data.json"
    artifact.write_text("{}", encoding="utf-8")

    result = render_artifact_pages(artifact, kind="file", cache_dir=tmp_path / "cache")

    assert result.pages == ()
    assert result.warnings[0].code == "unsupported_artifact_kind"


def test_view_artifact_file_returns_first_structured_warning(
    tmp_path: Path,
    monkeypatch,
) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(b"png")
    monkeypatch.setattr("sase.ace.tui.graphics.viewer.shutil.which", lambda _tool: None)

    result = view_artifact_file(image, kind="image")

    assert result.ok is False
    assert result.warning == "kitten executable not found"
    assert result.warnings[0].code == "missing_kitten"


def test_tmux_detection_returns_false_outside_tmux(monkeypatch) -> None:
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)

    assert is_tmux_session() is False


def test_tmux_pane_launch_warns_when_tmux_is_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("TMUX_PANE", "%1")
    monkeypatch.setattr("sase.ace.tui.graphics.viewer.shutil.which", lambda _tool: None)

    result = view_artifact_file_in_tmux_pane(tmp_path / "artifact.png", kind="image")

    assert result.ok is False
    assert result.warning == "tmux executable not found"
    assert result.warnings[0].code == "missing_tmux"


def test_tmux_pane_launch_invokes_split_window_with_module_entrypoint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifact = tmp_path / "artifact.png"
    artifact.write_bytes(b"png")
    calls: list[list[str]] = []
    monkeypatch.setenv("TMUX", "/tmp/tmux")
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.shutil.which",
        lambda tool: f"/usr/bin/{tool}" if tool == "tmux" else None,
    )

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.subprocess.run", fake_run)

    result = view_artifact_file_in_tmux_pane(artifact, kind="image")

    assert result.ok is True
    assert len(calls) == 1
    assert calls[0][:3] == ["tmux", "split-window", "-h"]
    assert shlex.split(calls[0][3]) == [
        sys.executable,
        "-m",
        "sase.ace.tui.graphics.viewer",
        "--kind",
        "image",
        str(artifact),
    ]


def test_viewer_module_entrypoint_delegates_to_view_artifact_file(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    artifact = tmp_path / "artifact.png"
    artifact.write_bytes(b"png")
    calls: list[tuple[str, str | None]] = []

    def fake_viewer(path: str, *, kind: str | None = None) -> ArtifactViewerResult:
        calls.append((path, kind))
        return ArtifactViewerResult(True)

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.view_artifact_file", fake_viewer)

    code = viewer_main(["--kind", "image", str(artifact)])

    assert code == 0
    assert calls == [(str(artifact), "image")]
    assert capsys.readouterr().err == ""


def test_viewer_module_entrypoint_prints_warning_and_returns_nonzero(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    artifact = tmp_path / "artifact.png"
    artifact.write_bytes(b"png")

    def fake_viewer(path: str, *, kind: str | None = None) -> ArtifactViewerResult:
        del path, kind
        return ArtifactViewerResult(False, warning="missing dependency")

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.view_artifact_file", fake_viewer)

    code = viewer_main([str(artifact)])

    assert code == 1
    assert capsys.readouterr().err == "missing dependency\n"


def test_artifact_view_mode_treats_chat_markdown_as_markdown(tmp_path: Path) -> None:
    assert artifact_view_mode(tmp_path / "chat.md", kind="chat") == "markdown"
    assert artifact_view_mode(tmp_path / "plan.markdown", kind="plan") == "markdown"
    assert artifact_view_mode(tmp_path / "report.pdf", kind="file") == "pdf"
    assert artifact_view_mode(tmp_path / "image.png", kind="file") == "image"

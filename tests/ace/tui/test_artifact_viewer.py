from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

from rich.console import Console

from sase.ace.tui.graphics.viewer import (
    ArtifactRenderResult,
    ArtifactViewSpec,
    ArtifactViewerResult,
    _artifact_header_panel,
    _format_artifact_header_path,
    _print_page_prompt,
    artifact_tmux_pane_exists,
    artifact_view_mode,
    close_artifact_tmux_pane,
    convert_pdf_to_png_pages,
    is_tmux_session,
    main as viewer_main,
    page_index_after_key,
    page_loop_available_keys,
    render_artifact_pages,
    run_artifact_sequence_loop,
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
    assert page_index_after_key(2, "n", 3) == 0
    assert page_index_after_key(2, "p", 3) == 1
    assert page_index_after_key(0, "p", 3) == 2
    assert page_index_after_key(1, "r", 3) == 1
    assert page_index_after_key(1, "x", 3) == 1
    assert page_index_after_key(0, "q", 3) is None
    assert page_index_after_key(0, "n", 1) == 0
    assert page_index_after_key(0, "p", 1) == 0


def test_artifact_page_loop_available_keys_and_prompts(capsys) -> None:
    assert page_loop_available_keys(0, 1) == ("r", "q")
    assert page_loop_available_keys(0, 3) == ("n", "p", "r", "q")
    assert page_loop_available_keys(1, 3) == ("n", "p", "r", "q")
    assert page_loop_available_keys(2, 3) == ("n", "p", "r", "q")
    assert page_loop_available_keys(0, 1, artifact_index=0, artifact_count=3) == (
        "N",
        "r",
        "q",
    )
    assert page_loop_available_keys(0, 1, artifact_index=1, artifact_count=3) == (
        "N",
        "P",
        "r",
        "q",
    )
    assert page_loop_available_keys(0, 1, artifact_index=2, artifact_count=3) == (
        "P",
        "r",
        "q",
    )

    _print_page_prompt(index=0, page_count=1)
    assert capsys.readouterr().out == "\nPage 1/1  r: refresh  q: quit"

    _print_page_prompt(index=0, page_count=3)
    assert (
        capsys.readouterr().out
        == "\nPage 1/3  n: next page  p: previous page  r: refresh  q: quit"
    )

    _print_page_prompt(index=1, page_count=3)
    assert (
        capsys.readouterr().out
        == "\nPage 2/3  n: next page  p: previous page  r: refresh  q: quit"
    )

    _print_page_prompt(index=2, page_count=3)
    assert (
        capsys.readouterr().out
        == "\nPage 3/3  n: next page  p: previous page  r: refresh  q: quit"
    )

    _print_page_prompt(
        index=0,
        page_count=1,
        artifact_index=0,
        artifact_count=2,
    )
    assert (
        capsys.readouterr().out
        == "\nArtifact 1/2  Page 1/1  N: next artifact  r: refresh  q: quit"
    )


def test_artifact_header_panel_includes_path_and_positions(tmp_path: Path) -> None:
    artifact = tmp_path / "missing artifact.png"
    spec = ArtifactViewSpec(artifact, "image")
    console = Console(record=True, width=100, color_system=None)

    console.print(
        _artifact_header_panel(
            spec,
            page_index=2,
            page_count=7,
            artifact_index=1,
            artifact_count=4,
        )
    )
    output = console.export_text()

    assert "Viewing artifact" in output
    assert "Artifact 2/4" in output
    assert "Page 3/7" in output
    assert str(artifact.resolve(strict=False)) in output
    assert _format_artifact_header_path(artifact) == str(artifact.resolve(strict=False))


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


def test_run_artifact_page_loop_refreshes_current_page(tmp_path: Path) -> None:
    pages = [tmp_path / "page-1.png", tmp_path / "page-2.png"]
    for page in pages:
        page.write_bytes(b"png")
    commands: list[list[str]] = []
    keys = iter(["r", "q"])

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
        ["kitten", "icat", str(pages[0])],
        ["clear"],
    ]


def test_run_artifact_page_loop_wraps_boundary_keys(
    tmp_path: Path,
) -> None:
    pages = [tmp_path / "page-1.png", tmp_path / "page-2.png"]
    for page in pages:
        page.write_bytes(b"png")
    commands: list[list[str]] = []
    keys = iter(["p", "n", "q"])

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


def test_run_artifact_sequence_loop_navigates_pages_and_artifacts(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    first_pages = [tmp_path / "first-1.png", tmp_path / "first-2.png"]
    second_pages = [tmp_path / "second-1.png"]
    for page in [*first_pages, *second_pages]:
        page.write_bytes(b"png")
    specs = (
        ArtifactViewSpec(tmp_path / "first.md", "markdown"),
        ArtifactViewSpec(tmp_path / "second.png", "image"),
    )
    render_calls: list[tuple[Path, str | None, Path]] = []

    def fake_render_result(path, *, kind=None, cache_dir=None):
        render_calls.append((Path(path), kind, Path(cache_dir)))
        pages = tuple(first_pages if kind == "markdown" else second_pages)
        return ArtifactRenderResult(pages)

    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.render_artifact_pages",
        fake_render_result,
    )
    commands: list[list[str]] = []
    keys = iter(["p", "n", "N", "P", "q"])

    def fake_run(cmd):
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    result = run_artifact_sequence_loop(
        specs,
        cache_root=tmp_path / "cache",
        read_key=lambda: next(keys),
        run_command=fake_run,
    )

    assert result.returncode == 0
    assert [call[:2] for call in render_calls] == [
        (tmp_path / "first.md", "markdown"),
        (tmp_path / "second.png", "image"),
    ]
    assert commands == [
        ["clear"],
        ["kitten", "icat", str(first_pages[0])],
        ["clear"],
        ["kitten", "icat", str(first_pages[1])],
        ["clear"],
        ["kitten", "icat", str(first_pages[0])],
        ["clear"],
        ["kitten", "icat", str(second_pages[0])],
        ["clear"],
        ["kitten", "icat", str(first_pages[0])],
        ["clear"],
    ]
    output = capsys.readouterr().out
    assert "Viewing artifact" in output
    assert "Artifact 1/2" in output
    assert "Artifact 2/2" in output
    assert "Page 2/2" in output
    assert "first.md" in output
    assert "second.png" in output


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
        return subprocess.CompletedProcess(cmd, 0, "%7\n", "")

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.subprocess.run", fake_run)

    result = view_artifact_file_in_tmux_pane(artifact, kind="image")

    assert result.ok is True
    assert result.pane_id == "%7"
    assert len(calls) == 1
    assert calls[0][:6] == [
        "tmux",
        "split-window",
        "-h",
        "-P",
        "-F",
        "#{pane_id}",
    ]
    assert shlex.split(calls[0][6]) == [
        sys.executable,
        "-m",
        "sase.ace.tui.graphics.viewer",
        "--kind",
        "image",
        str(artifact),
    ]


def test_tmux_pane_launch_invokes_multi_artifact_entrypoint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifacts = (
        ArtifactViewSpec(tmp_path / "first.png", "image"),
        ArtifactViewSpec(tmp_path / "second.md", "markdown"),
    )
    calls: list[list[str]] = []
    monkeypatch.setenv("TMUX", "/tmp/tmux")
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.shutil.which",
        lambda tool: f"/usr/bin/{tool}" if tool == "tmux" else None,
    )

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "%7\n", "")

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.subprocess.run", fake_run)

    result = view_artifact_file_in_tmux_pane(artifacts[0].path, kind=artifacts[0].kind)
    assert result.ok is True
    assert result.pane_id == "%7"

    calls.clear()
    from sase.ace.tui.graphics.viewer import view_artifact_files_in_tmux_pane

    result = view_artifact_files_in_tmux_pane(artifacts)

    assert result.ok is True
    assert result.pane_id == "%7"
    assert shlex.split(calls[0][6]) == [
        sys.executable,
        "-m",
        "sase.ace.tui.graphics.viewer",
        "--kind",
        "image",
        "--kind",
        "markdown",
        str(artifacts[0].path),
        str(artifacts[1].path),
    ]


def test_tmux_pane_helpers_check_and_kill_tracked_pane(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setenv("TMUX_PANE", "%1")
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.shutil.which",
        lambda tool: f"/usr/bin/{tool}" if tool == "tmux" else None,
    )

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if cmd[:2] == ["tmux", "display-message"]:
            return subprocess.CompletedProcess(cmd, 0, "%7\n", "")
        if cmd[:2] == ["tmux", "kill-pane"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(cmd)

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.subprocess.run", fake_run)

    assert artifact_tmux_pane_exists("%7") is True
    result = close_artifact_tmux_pane("%7")

    assert result.ok is True
    assert calls == [
        ["tmux", "display-message", "-p", "-t", "%7", "#{pane_id}"],
        ["tmux", "kill-pane", "-t", "%7"],
    ]


def test_tmux_pane_close_refuses_current_pane(monkeypatch) -> None:
    kill = MagicMock()
    monkeypatch.setenv("TMUX_PANE", "%1")
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.shutil.which",
        lambda tool: f"/usr/bin/{tool}" if tool == "tmux" else None,
    )
    monkeypatch.setattr("sase.ace.tui.graphics.viewer.subprocess.run", kill)

    result = close_artifact_tmux_pane("%1")

    assert result.ok is False
    assert result.warning == "Refusing to close the current tmux pane"
    kill.assert_not_called()


def test_viewer_module_entrypoint_delegates_to_view_artifact_files(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    artifact = tmp_path / "artifact.png"
    artifact.write_bytes(b"png")
    calls: list[tuple[ArtifactViewSpec, ...]] = []

    def fake_viewer(artifacts) -> ArtifactViewerResult:
        calls.append(tuple(artifacts))
        return ArtifactViewerResult(True)

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.view_artifact_files", fake_viewer)

    code = viewer_main(["--kind", "image", str(artifact)])

    assert code == 0
    assert calls == [(ArtifactViewSpec(str(artifact), "image"),)]
    assert capsys.readouterr().err == ""


def test_viewer_module_entrypoint_accepts_multiple_paths_and_kinds(
    tmp_path: Path,
    monkeypatch,
) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.md"
    calls: list[tuple[ArtifactViewSpec, ...]] = []

    def fake_viewer(artifacts) -> ArtifactViewerResult:
        calls.append(tuple(artifacts))
        return ArtifactViewerResult(True)

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.view_artifact_files", fake_viewer)

    code = viewer_main(
        ["--kind", "image", "--kind", "markdown", str(first), str(second)]
    )

    assert code == 0
    assert calls == [
        (
            ArtifactViewSpec(str(first), "image"),
            ArtifactViewSpec(str(second), "markdown"),
        )
    ]


def test_viewer_module_entrypoint_prints_warning_and_returns_nonzero(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    artifact = tmp_path / "artifact.png"
    artifact.write_bytes(b"png")

    def fake_viewer(artifacts) -> ArtifactViewerResult:
        del artifacts
        return ArtifactViewerResult(False, warning="missing dependency")

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.view_artifact_files", fake_viewer)

    code = viewer_main([str(artifact)])

    assert code == 1
    assert capsys.readouterr().err == "missing dependency\n"


def test_artifact_view_mode_treats_chat_markdown_as_markdown(tmp_path: Path) -> None:
    assert artifact_view_mode(tmp_path / "chat.md", kind="chat") == "markdown"
    assert artifact_view_mode(tmp_path / "plan.markdown", kind="plan") == "markdown"
    assert artifact_view_mode(tmp_path / "report.pdf", kind="file") == "pdf"
    assert artifact_view_mode(tmp_path / "image.png", kind="file") == "image"

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from rich.console import Console

from sase.ace.tui.graphics import _viewer_render
from sase.ace.tui.graphics.viewer import (
    ArtifactFileImageArea,
    ArtifactVideoPlaybackConfig,
    ArtifactFileViewSpec,
    _artifact_header_panel,
    _format_artifact_header_path,
    artifact_image_area,
    artifact_markdown_pdf_profile_for_image_area,
    artifact_text_viewer_command,
    artifact_video_player_command,
    artifact_file_view_mode,
    convert_pdf_to_png_pages,
    is_supported_video_path,
    kitten_icat_command,
    render_artifact_file_pages,
    run_artifact_text_viewer,
    SUPPORTED_VIDEO_EXTENSIONS,
    validate_artifact_file_viewer_dependencies,
    view_artifact_file,
)


def _inch_value(value: str) -> float:
    assert value.endswith("in")
    return float(value.removesuffix("in"))


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


def test_artifact_header_panel_includes_path_and_positions() -> None:
    artifact = Path("/tmp/sase-artifact-header-missing.png")
    spec = ArtifactFileViewSpec(artifact, "image")
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


def test_artifact_image_area_reserves_viewer_rows() -> None:
    assert artifact_image_area((100, 40)) == ArtifactFileImageArea(
        columns=98,
        rows=33,
        top=5,
    )
    assert artifact_image_area((10, 8)) == ArtifactFileImageArea(
        columns=20,
        rows=5,
        top=3,
    )
    assert artifact_image_area((100, 40), reserved_rows=2, top_rows=0) == (
        ArtifactFileImageArea(columns=98, rows=38)
    )
    assert artifact_image_area((100, 40), reserved_columns=0) == (
        ArtifactFileImageArea(columns=100, rows=33, top=5)
    )


def test_kitten_icat_command_targets_image_area(tmp_path: Path) -> None:
    page = tmp_path / "page.png"

    assert kitten_icat_command(page, ArtifactFileImageArea(100, 33)) == [
        "kitten",
        "icat",
        "--scale-up",
        "--align",
        "left",
        "--place",
        "100x33@0x0",
        str(page),
    ]


def test_artifact_video_player_command_targets_image_area(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"

    assert artifact_video_player_command(video, ArtifactFileImageArea(100, 33)) == [
        "mpv",
        "--no-config",
        "--vo=kitty",
        "--keep-open=yes",
        "--vo-kitty-alt-screen=no",
        "--vo-kitty-config-clear=no",
        "--vo-kitty-left=0",
        "--vo-kitty-top=0",
        "--vo-kitty-cols=100",
        "--vo-kitty-rows=33",
        "--mute=yes",
        "--",
        str(video.resolve(strict=False)),
    ]


def test_artifact_video_player_command_honors_config(tmp_path: Path) -> None:
    video = tmp_path / "clip.webm"
    config = ArtifactVideoPlaybackConfig(
        audio=True,
        loop=True,
        vo="tct",
        extra_mpv_args=("--profile=low-latency", "--keep-open=no"),
    )

    command = artifact_video_player_command(
        video,
        ArtifactFileImageArea(100, 33),
        config,
    )

    assert command == [
        "mpv",
        "--no-config",
        "--vo=tct",
        "--keep-open=yes",
        "--loop-file=inf",
        "--profile=low-latency",
        "--keep-open=no",
        "--",
        str(video.resolve(strict=False)),
    ]
    assert "--mute=yes" not in command
    assert not any(arg.startswith("--vo-kitty-") for arg in command)


def test_artifact_markdown_pdf_profile_uses_image_area_aspect() -> None:
    profile = artifact_markdown_pdf_profile_for_image_area(
        ArtifactFileImageArea(columns=100, rows=33)
    )

    assert profile is not None
    assert profile.page_width == "8.50in"
    assert profile.page_height == "5.61in"
    assert profile.margin == "0.18in"
    assert profile.css_font_size == "16px"
    assert profile.latex_font_size == "12pt"


def test_artifact_markdown_pdf_profile_tracks_cell_adjusted_pane_aspect() -> None:
    profile = artifact_markdown_pdf_profile_for_image_area(
        ArtifactFileImageArea(columns=100, rows=33),
        cell_pixel_aspect=0.45,
    )

    assert profile is not None
    assert profile.page_width == "8.50in"
    assert profile.page_height == "6.23in"
    assert (
        round(_inch_value(profile.page_width) / _inch_value(profile.page_height), 2)
        == 1.36
    )


def test_artifact_markdown_pdf_profile_keeps_width_capped_for_wide_pane() -> None:
    profile = artifact_markdown_pdf_profile_for_image_area(
        ArtifactFileImageArea(columns=90, rows=24)
    )

    assert profile is not None
    assert profile.page_width == "8.50in"
    assert profile.page_height == "4.53in"


def test_artifact_markdown_pdf_profile_rejects_missing_or_invalid_area() -> None:
    assert artifact_markdown_pdf_profile_for_image_area(None) is None
    assert (
        artifact_markdown_pdf_profile_for_image_area(
            ArtifactFileImageArea(columns=0, rows=24)
        )
        is None
    )
    assert (
        artifact_markdown_pdf_profile_for_image_area(
            ArtifactFileImageArea(columns=90, rows=0)
        )
        is None
    )


def test_terminal_cell_pixel_aspect_uses_runtime_pixels_when_available() -> None:
    assert (
        _viewer_render._terminal_cell_pixel_aspect(
            winsize=(40, 100, 1000, 800),
        )
        == 0.5
    )


def test_terminal_cell_pixel_aspect_falls_back_for_missing_pixels() -> None:
    assert (
        _viewer_render._terminal_cell_pixel_aspect(
            winsize=(40, 100, 0, 0),
        )
        == 0.5
    )


def test_validate_artifact_file_viewer_dependencies_reports_missing_tools(
    monkeypatch,
) -> None:
    monkeypatch.setattr("sase.ace.tui.graphics.viewer.shutil.which", lambda _tool: None)

    warnings = validate_artifact_file_viewer_dependencies("markdown")

    assert [warning.code for warning in warnings] == [
        "missing_kitten",
        "missing_pdftoppm",
        "missing_pandoc",
        "missing_pdf_engine",
    ]


def test_validate_artifact_file_viewer_dependencies_reports_missing_mpv(
    monkeypatch,
) -> None:
    monkeypatch.setattr("sase.ace.tui.graphics.viewer.shutil.which", lambda _tool: None)

    warnings = validate_artifact_file_viewer_dependencies("video")

    assert [warning.code for warning in warnings] == ["missing_mpv"]
    assert warnings[0].message == "mpv executable not found"
    assert warnings[0].tool == "mpv"


def test_render_markdown_artifact_uses_transient_pdf_and_pdf_pages(
    tmp_path: Path,
    monkeypatch,
    capsys,
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

    result = render_artifact_file_pages(
        source, kind="chat", cache_dir=tmp_path / "cache"
    )

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
    output = capsys.readouterr().out
    assert "Rendering Markdown as PDF..." in output
    assert "Converting PDF pages..." in output


def test_render_markdown_artifact_passes_pane_aware_profile(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "chat.md"
    source.write_text("# Chat\n", encoding="utf-8")
    profiles = []

    def fake_which(tool: str) -> str:
        return f"/usr/bin/{tool}"

    def fake_render_markdown_pdf(src: Path, dest: Path, *, profile) -> Path:
        assert src == source
        profiles.append(profile)
        dest.write_bytes(b"%PDF")
        return dest

    def fake_run(cmd, **kwargs):
        prefix = Path(cmd[-1])
        (prefix.parent / f"{prefix.name}-1.png").write_bytes(b"png")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.shutil.which", fake_which)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.render_markdown_pdf",
        fake_render_markdown_pdf,
    )
    monkeypatch.setattr("sase.ace.tui.graphics.viewer.subprocess.run", fake_run)

    result = render_artifact_file_pages(
        source,
        kind="chat",
        cache_dir=tmp_path / "cache",
        image_area=ArtifactFileImageArea(columns=90, rows=24),
    )

    assert result.warnings == ()
    assert len(profiles) == 1
    assert profiles[0].page_width == "8.50in"
    assert profiles[0].page_height == "4.53in"
    assert profiles[0].margin == "0.18in"


def test_unknown_file_artifact_uses_text_mode_without_render_warnings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifact = tmp_path / "data.json"
    artifact.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("sase.ace.tui.graphics.viewer.shutil.which", lambda _tool: None)

    result = render_artifact_file_pages(
        artifact, kind="file", cache_dir=tmp_path / "cache"
    )

    assert result.pages == ()
    assert result.warnings == ()
    assert artifact_file_view_mode(artifact, kind="file") == "text"
    assert artifact_file_view_mode(artifact, kind="json") == "text"
    assert validate_artifact_file_viewer_dependencies("text") == ()


def test_video_file_artifact_uses_video_mode_without_render_pages(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifact = tmp_path / "demo.mp4"
    artifact.write_bytes(b"video")
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.shutil.which",
        lambda tool: f"/usr/bin/{tool}" if tool == "mpv" else None,
    )

    result = render_artifact_file_pages(
        artifact, kind="file", cache_dir=tmp_path / "cache"
    )

    assert result.pages == ()
    assert result.warnings == ()
    assert artifact_file_view_mode(artifact, kind="file") == "video"
    assert artifact_file_view_mode(artifact, kind=None) == "video"
    assert (
        artifact_file_view_mode(artifact.with_suffix(".webm"), kind="video") == "video"
    )


def test_video_suffix_helper_matches_axe_attachment_constant() -> None:
    from sase.axe.image_attachments import (
        SUPPORTED_VIDEO_EXTENSIONS as AXE_VIDEO_EXTENSIONS,
    )

    assert SUPPORTED_VIDEO_EXTENSIONS == AXE_VIDEO_EXTENSIONS
    assert is_supported_video_path("render.MOV")
    assert not is_supported_video_path("render.gif")


def test_artifact_text_viewer_command_uses_sase_pager(tmp_path: Path) -> None:
    artifact = tmp_path / "data.json"
    artifact.write_text("{}", encoding="utf-8")

    assert artifact_text_viewer_command(artifact) == [
        sys.executable,
        "-m",
        "sase",
        "pager",
        "--",
        str(artifact.resolve(strict=False)),
    ]


def test_artifact_text_viewer_command_preserves_safe_path(tmp_path: Path) -> None:
    artifact = tmp_path / "-leading name.json"
    artifact.write_text("{}", encoding="utf-8")

    assert artifact_text_viewer_command(artifact) == [
        sys.executable,
        "-m",
        "sase",
        "pager",
        "--",
        str(artifact.resolve(strict=False)),
    ]


def test_artifact_text_viewer_does_not_wait_for_extra_quit_key(
    tmp_path: Path,
    capsys,
) -> None:
    artifact = tmp_path / "data.json"
    artifact.write_text("{}", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_run(cmd):
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    result = run_artifact_text_viewer(
        ArtifactFileViewSpec(artifact, "file"),
        run_command=fake_run,
    )

    assert result.returncode == 0
    assert commands == [
        ["clear"],
        [
            sys.executable,
            "-m",
            "sase",
            "pager",
            "--",
            str(artifact.resolve(strict=False)),
        ],
    ]
    assert "q: quit" not in capsys.readouterr().out


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


def test_artifact_view_mode_treats_chat_markdown_as_markdown(tmp_path: Path) -> None:
    assert artifact_file_view_mode(tmp_path / "chat.md", kind="chat") == "markdown"
    assert (
        artifact_file_view_mode(tmp_path / "plan.markdown", kind="plan") == "markdown"
    )
    assert artifact_file_view_mode(tmp_path / "report.pdf", kind="file") == "pdf"
    assert artifact_file_view_mode(tmp_path / "image.png", kind="file") == "image"

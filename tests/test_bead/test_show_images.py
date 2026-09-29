"""show_images: mode matrix, previews, pager targets, open, artifact refs."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.feature_flags import override_flags
from sase.main.parser import create_parser

PNG_HEAD = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

_HANDLERS = {
    "show": bead_cli.handle_bead_show,
    "read": bead_cli.handle_bead_read,
    "attachment": bead_cli.handle_bead_attachment,
    "note": bead_cli.handle_bead_note,
    "attach": bead_cli.handle_bead_attach,
}


def _run(argv: list[str]) -> tuple[str, str, int]:
    args = create_parser().parse_args(["bead", *argv])
    handler = _HANDLERS[args.bead_subcommand]
    out, err, code = io.StringIO(), io.StringIO(), 0
    try:
        with redirect_stdout(out), redirect_stderr(err):
            handler(args)
    except SystemExit as exc:
        code = int(exc.code or 0)
    return out.getvalue(), err.getvalue(), code


def _attach(
    project_dir: Path, filename: str, data: bytes, note: str = "see"
) -> tuple[str, str]:
    (project_dir / filename).write_bytes(data)
    with BeadProject(project_dir) as project:
        issue_id = project.create("Show images target", IssueType.PLAN).id
    with override_flags(bead_note_attachments=True):
        out, err, code = _run(
            ["note", issue_id, "-a", "amy", note, f"@./{filename}", "here"]
        )
    assert code == 0, err
    with BeadProject(project_dir) as project:
        sha = project.show(issue_id).notes[0].attachments[0].sha256
    return issue_id, sha


def test_mode_matrix_tty_pipe_no_color_agent_tmux_kitty() -> None:
    from sase.bead.show_images import resolve_images_mode

    kitty_env = {"KITTY_WINDOW_ID": "1", "TERM": "xterm-kitty"}
    assert resolve_images_mode(None, is_tty=False, env={})[0] == "never"
    assert resolve_images_mode("cells", is_tty=False, env=kitty_env)[0] == "never"
    assert resolve_images_mode(None, is_tty=True, env={"NO_COLOR": "1"})[0] == "never"
    assert resolve_images_mode(None, is_tty=True, env={"SASE_AGENT": "1"})[0] == "never"
    mode, _ = resolve_images_mode(None, is_tty=True, env=kitty_env)
    assert mode == "kitty"
    mode, _ = resolve_images_mode(None, is_tty=True, env={**kitty_env, "TMUX": "x"})
    assert mode == "cells"
    mode, hint = resolve_images_mode("kitty", is_tty=True, env={"TERM": "dumb"})
    assert mode == "cells" and hint is not None and "kitty" in hint.lower()
    assert resolve_images_mode("never", is_tty=True, env=kitty_env)[0] == "never"
    assert resolve_images_mode("cells", is_tty=True, env=kitty_env)[0] == "cells"
    assert resolve_images_mode("bogus", is_tty=True, env=kitty_env)[0] == "kitty"


def test_config_accessor_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    from sase.bead.config import get_show_images_default

    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"bead": {"show": {"images": "kitty"}}},
    )
    assert get_show_images_default() == "kitty"
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"bead": {"show": {"images": "bogus"}}},
    )
    assert get_show_images_default() == "auto"
    monkeypatch.setattr("sase.config.load_merged_config", lambda: {"bead": None})
    assert get_show_images_default() == "auto"


def test_thumbnail_dimensions_and_limits() -> None:
    from sase.bead.show_images import MAX_PREVIEW_ROWS, thumbnail_size

    columns, rows = thumbnail_size(800, 400, 80)
    assert rows <= MAX_PREVIEW_ROWS and columns > 0
    wide_columns, wide_rows = thumbnail_size(1600, 100, 80)
    assert wide_rows <= MAX_PREVIEW_ROWS
    assert thumbnail_size(0, 0, 80)[1] <= MAX_PREVIEW_ROWS


def test_cell_rendering_and_decode_failure(tmp_path: Path) -> None:
    from sase.bead.show_images import render_cell_thumbnail

    pytest.importorskip("PIL.Image")
    from PIL import Image

    good = tmp_path / "good.png"
    Image.new("RGB", (32, 16), (200, 30, 30)).save(good)
    rendered = render_cell_thumbnail(str(good), columns=20, rows=6)
    assert rendered is not None and rendered.strip()
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image at all")
    assert render_cell_thumbnail(str(bad), columns=20, rows=6) is None
    assert (
        render_cell_thumbnail(str(tmp_path / "missing.png"), columns=20, rows=6) is None
    )


def test_kitty_framing_chunking() -> None:
    from sase.bead.show_images import kitty_escape_for_png

    payload = bytes(range(256)) * 200
    escape = kitty_escape_for_png(payload)
    assert escape.startswith("\x1b_Ga=T,f=100,m=")
    assert escape.endswith("\x1b\\")
    assert "\x1b_Ga=T,f=100,m=1;" in escape
    assert "\x1b_Ga=T,f=100,m=0;" in escape
    single = kitty_escape_for_png(b"hi")
    assert single.count("\x1b_G") == 1
    assert single.startswith("\x1b_Ga=T,f=100,m=0;")


def test_text_sanitization_and_size_cap(
    project_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.show_images import preview_text_attachment, sanitize_text_line

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.chdir(project_dir)
    assert "\x1b" not in sanitize_text_line("\x1b[31mhi\x1b[0m")
    assert sanitize_text_line("a\u202eb") == "ab"
    big = project_dir / "big.txt"
    big.write_bytes(b"x" * ((1 << 20) + 10))
    assert preview_text_attachment(str(big)) is None
    small = project_dir / "small.txt"
    small.write_text("one\n\ntwo \x1b[1m\nthree\nfour\nfive\nsix\n", encoding="utf-8")
    previewed = preview_text_attachment(str(small))
    assert previewed is not None and len(previewed) <= 5
    assert all("\x1b" not in line for line in previewed)
    binary = project_dir / "binary.bin"
    binary.write_bytes(b"hi\x00there")
    assert preview_text_attachment(str(binary)) is None


def test_svg_never_decodes_for_previews() -> None:
    from sase.bead.show_images import is_previewable_raster

    assert is_previewable_raster("shot.png", "image/png") is True
    assert is_previewable_raster("vector.svg", "image/svg+xml") is False
    assert is_previewable_raster("fig.eps", "application/postscript") is False


def test_pager_targets_and_media_order(
    project_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("PIL.Image")
    from PIL import Image

    from sase.bead.show_images import attachment_targets_for_body

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.chdir(project_dir)
    first = project_dir / "first.png"
    second = project_dir / "second.png"
    Image.new("RGB", (16, 16), (10, 200, 10)).save(first)
    Image.new("RGB", (16, 16), (10, 10, 200)).save(second)
    with BeadProject(project_dir) as project:
        issue_id = project.create("Pager targets", IssueType.PLAN).id
    with override_flags(bead_note_attachments=True):
        assert _run(["note", issue_id, "-a", "amy", "see", "@./first.png"])[2] == 0
        (project_dir / "second.png").write_bytes(second.read_bytes())
        from sase.bead.cli_attach import handle_bead_attach

        args = create_parser().parse_args(
            ["bead", "attach", issue_id, "./second.png", "-a", "amy"]
        )
        out, err = io.StringIO(), io.StringIO()
        from contextlib import redirect_stderr as _re, redirect_stdout as _ro

        with _ro(out), _re(err):
            try:
                handle_bead_attach(args)
            except SystemExit as exc:
                assert int(exc.code or 0) == 0, err.getvalue()
    with BeadProject(project_dir) as project:
        issue = project.show(issue_id)
    body = "see [first.png] and [second.png]\n       first.png · image\n       second.png · image\n"
    targets = attachment_targets_for_body(issue_id, body, ["first.png", "second.png"])
    assert len(targets) == 4
    assert all(item.kind == "artifact_ref" for item in targets)
    refs = [str(item.target) for item in targets]
    assert f"attachment:{issue_id}/first.png" in refs
    assert f"attachment:{issue_id}/second.png" in refs

    from sase.bead.attachment_resolve import viewable_media_specs

    specs = viewable_media_specs(issue, "second.png")
    assert len(specs) >= 2
    assert "second.png" in str(specs[0].path)


def test_pager_resolution_per_file_class(
    project_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("PIL.Image")
    from PIL import Image

    from sase.pager.resolve import resolve_link

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.chdir(project_dir)
    Image.new("RGB", (16, 16), (200, 10, 10)).save(project_dir / "pic.png")
    (project_dir / "note.txt").write_text("hello\nworld\n", encoding="utf-8")
    (project_dir / "blob.bin").write_bytes(bytes(range(256)) * 4)
    with BeadProject(project_dir) as project:
        issue_id = project.create("Resolve classes", IssueType.PLAN).id
    with override_flags(bead_note_attachments=True):
        assert _run(["note", issue_id, "-a", "amy", "img", "@./pic.png"])[2] == 0
        assert _run(["note", issue_id, "-a", "amy", "txt", "@./note.txt"])[2] == 0
        assert _run(["note", issue_id, "-a", "amy", "bin", "@./blob.bin"])[2] == 0
    image_resolution = resolve_link(f"attachment:{issue_id}/pic.png")
    assert image_resolution.target is not None
    assert image_resolution.target.kind.value == "media"
    assert len(image_resolution.target.media_specs) >= 1
    text_resolution = resolve_link(f"attachment:{issue_id}/note.txt")
    assert text_resolution.target is not None
    assert text_resolution.target.kind.value == "document"
    binary_resolution = resolve_link(f"attachment:{issue_id}/blob.bin")
    assert binary_resolution.target is not None
    missing = resolve_link(f"attachment:{issue_id}/nope.png")
    assert missing.target is None and missing.unresolved_message
    unavailable = resolve_link("attachment:sase-missing-bead/x.png")
    assert unavailable.target is None and unavailable.unresolved_message


def test_cli_open_and_artifact_refs(
    project_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("PIL.Image")
    from PIL import Image

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.chdir(project_dir)
    Image.new("RGB", (16, 16), (30, 30, 200)).save(project_dir / "shot.png")
    (project_dir / "log.txt").write_text("line one\nline two\n", encoding="utf-8")
    with BeadProject(project_dir) as project:
        issue_id = project.create("Open target", IssueType.PLAN).id
    with override_flags(bead_note_attachments=True):
        assert _run(["note", issue_id, "-a", "amy", "see", "@./shot.png"])[2] == 0
        assert _run(["note", issue_id, "-a", "amy", "log", "@./log.txt"])[2] == 0

    seen: list[object] = []
    import sase.ace.tui.graphics as _graphics

    class _Ok:
        ok = True
        warnings: tuple[object, ...] = ()

    monkeypatch.setattr(
        _graphics,
        "view_artifact_files",
        lambda specs: seen.append(tuple(specs)) or _Ok(),
    )

    out, err, code = _run(["attachment", "open", issue_id, "shot.png"])
    assert code == 0, err
    assert seen and "shot.png" in str(seen[-1][0].path)

    out, err, code = _run(["attachment", "open", issue_id, "missing.png"])
    assert code != 0

    from sase.artifact_cli.references import resolve_cli_reference

    text_result = resolve_cli_reference(f"attachment:{issue_id}/log.txt")
    assert text_result.resolution.status == "exact"
    assert text_result.resolution.resolved_path is not None
    assert str(text_result.resolution.resolved_path).endswith("log.txt")
    missing_result = resolve_cli_reference(f"attachment:{issue_id}/nope.txt")
    assert missing_result.resolution.status == "missing"

    from sase.artifact_cli.path import handle_path as _handle_path
    from sase.artifact_cli.read import handle_read as _handle_read

    args = create_parser().parse_args(
        ["artifact", "path", f"attachment:{issue_id}/log.txt"]
    )
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = _handle_path(args)
        except SystemExit as exc:
            code = int(exc.code or 0)
    assert code == 0
    assert out.getvalue().strip().endswith("log.txt")

    args = create_parser().parse_args(
        ["artifact", "read", f"attachment:{issue_id}/log.txt", "Need it"]
    )
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = _handle_read(args)
        except SystemExit as exc:
            code = int(exc.code or 0)
    assert code == 0
    assert "line one" in out.getvalue()

    args = create_parser().parse_args(
        ["artifact", "read", f"attachment:{issue_id}/shot.png", "Need it"]
    )
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = _handle_read(args)
        except SystemExit as exc:
            code = int(exc.code or 0)
    assert code == 0
    assert "sase artifact open" in out.getvalue()


def test_no_escapes_or_bytes_in_read_json_piped(
    project_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.chdir(project_dir)
    issue_id, _sha = _attach(project_dir, "shot.png", PNG_HEAD + b"pixels")

    out, err, code = _run(
        ["show", issue_id, "--no-links", "--pager", "never", "--color", "never"]
    )
    assert code == 0, err
    assert "\x1b" not in out and "pixels" not in out

    out, err, code = _run(
        ["show", issue_id, "--format", "json", "--no-links", "--pager", "never"]
    )
    assert code == 0, err
    assert "\x1b" not in out and "pixels" not in out
    payload = json.loads(out)
    assert payload["issue"]["notes"][0]["attachments"][0]["name"] == "shot.png"

    out, err, code = _run(
        [
            "read",
            issue_id,
            "--no-links",
            "--pager",
            "never",
            "--color",
            "never",
            "-r",
            "Need it",
        ]
    )
    assert code == 0, err
    assert "\x1b" not in out and "pixels" not in out


def test_rendering_identical_across_beta_flag(
    project_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.chdir(project_dir)
    issue_id, _sha = _attach(project_dir, "shot.png", PNG_HEAD + b"flag-pixels")
    with override_flags(bead_note_attachments=True):
        on_out, _, on_code = _run(
            ["show", issue_id, "--no-links", "--pager", "never", "--color", "never"]
        )
    with override_flags(bead_note_attachments=False):
        off_out, _, off_code = _run(
            ["show", issue_id, "--no-links", "--pager", "never", "--color", "never"]
        )
    assert on_code == 0 and off_code == 0
    assert on_out == off_out


def test_parser_help_covers_images_and_open() -> None:
    from tests.main.parser_help_helpers import flat_help, parser_for

    show_help = flat_help(parser_for(("sase", "bead", "show")).format_help())
    assert "-i, --images" in show_help
    read_help = flat_help(parser_for(("sase", "bead", "read")).format_help())
    assert "--images" not in read_help
    open_help = flat_help(
        parser_for(("sase", "bead", "attachment", "open")).format_help()
    )
    assert "viewer" in open_help

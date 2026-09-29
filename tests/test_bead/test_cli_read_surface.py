"""Phase read_surface: text chips, ATTACHMENTS block, list/path, history, docs."""

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
    "list": bead_cli.handle_bead_list,
    "search": bead_cli.handle_bead_search,
    "history": bead_cli.handle_bead_history,
    "attachment": bead_cli.handle_bead_attachment,
    "note": bead_cli.handle_bead_note,
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


def _create_plan(project_dir: Path) -> str:
    with BeadProject(project_dir) as project:
        return project.create("Read surface target", IssueType.PLAN).id


def _attach_note(project_dir: Path, work_dir: Path) -> tuple[str, bytes, str]:
    data = PNG_HEAD + b"read-surface-pixels"
    (work_dir / "shot.png").write_bytes(data)
    issue_id = _create_plan(project_dir)
    with override_flags(bead_note_attachments=True):
        out, err, code = _run(
            ["note", issue_id, "-a", "amy", "see", "@./shot.png", "here"]
        )
    assert code == 0, err
    with BeadProject(project_dir) as project:
        note = project.show(issue_id).notes[0]
    assert note.text == "see @attachment:shot.png here"
    return issue_id, data, note.attachments[0].sha256


def test_read_show_json_contain_chips_descriptor_view(
    project_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.chdir(project_dir)
    work_dir = project_dir
    issue_id, data, sha = _attach_note(project_dir, work_dir)

    out, err, code = _run(
        ["show", issue_id, "--no-links", "--pager", "never", "--color", "never"]
    )
    assert code == 0, err
    assert "[shot.png]" in out
    assert "@attachment:shot.png" not in out
    assert "ATTACHMENTS" in out
    assert "shot.png" in out and "image/png" in out
    assert f"sha256:{sha[:12]}" in out
    assert "views" in out and "shot.png" in out
    assert "\x1b" not in out
    assert "read-surface-pixels" not in out
    assert "\U0001f4ce 1" in out

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
    assert "[shot.png]" in out
    assert f"sha256:{sha[:12]}" in out
    assert "\x1b" not in out
    assert "read-surface-pixels" not in out

    out, err, code = _run(
        ["show", issue_id, "--format", "json", "--no-links", "--pager", "never"]
    )
    assert code == 0, err
    payload = json.loads(out)
    attachments = payload["issue"]["notes"][0]["attachments"]
    assert attachments[0]["name"] == "shot.png"
    assert attachments[0]["availability"] == "cached"
    assert "local_path" in attachments[0]
    assert attachments[0]["local_path"].endswith("shot.png")
    assert "\x1b" not in out
    assert "read-surface-pixels" not in out


def test_missing_object_renders_unavailable_exits_zero(
    project_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.chdir(project_dir)
    issue_id, _data, sha = _attach_note(project_dir, project_dir)
    from sase.bead.attachments.store import LocalAttachmentStore

    assert LocalAttachmentStore().remove(sha) is True

    out, err, code = _run(
        ["show", issue_id, "--no-links", "--pager", "never", "--color", "never"]
    )
    assert code == 0, err
    assert "[shot.png]" in out
    assert "\u2715 unavailable offline" in out

    out, err, code = _run(
        ["show", issue_id, "--format", "json", "--no-links", "--pager", "never"]
    )
    assert code == 0, err
    attachments = json.loads(out)["issue"]["notes"][0]["attachments"]
    assert attachments[0]["availability"] == "unavailable"
    assert "local_path" not in attachments[0]


def test_no_attachments_output_has_no_badges(
    project_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.chdir(project_dir)
    issue_id = _create_plan(project_dir)
    with override_flags(bead_note_attachments=True):
        assert _run(["note", issue_id, "-a", "amy", "plain note"])[2] == 0

    out, _, code = _run(
        ["show", issue_id, "--no-links", "--pager", "never", "--color", "never"]
    )
    assert code == 0
    assert "\U0001f4ce" not in out
    assert "ATTACHMENTS" not in out

    out, _, code = _run(["list", "--color", "never"])
    assert code == 0
    assert "\U0001f4ce" not in out


def test_compact_suffix_and_rendering_identical_flag_off(
    project_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.chdir(project_dir)
    issue_id, _data, _sha = _attach_note(project_dir, project_dir)

    out, _, code = _run(["list", "--color", "never"])
    assert code == 0
    assert "\U0001f4ce1" in out

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


def test_attachment_list_and_path_work_flag_off(
    project_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.chdir(project_dir)
    issue_id, _data, sha = _attach_note(project_dir, project_dir)

    with override_flags(bead_note_attachments=False):
        out, err, code = _run(["attachment", "list", issue_id])
    assert code == 0, err
    assert "shot.png" in out and f"sha256:{sha[:12]}" in out

    with override_flags(bead_note_attachments=False):
        out, err, code = _run(["attachment", "list", issue_id, "--json"])
    assert code == 0, err
    payload = json.loads(out)
    assert payload["attachments"][0]["availability"] == "cached"

    with override_flags(bead_note_attachments=False):
        out, err, code = _run(["attachment", "path", issue_id, "shot.png"])
    assert code == 0, err
    assert out.strip().endswith("shot.png")
    assert Path(out.strip()).is_symlink() or Path(out.strip()).exists()


def test_history_full_names_attachment(
    project_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.chdir(project_dir)
    issue_id, _data, _sha = _attach_note(project_dir, project_dir)

    out, err, code = _run(["history", issue_id, "--format", "full"])
    assert code == 0, err
    assert "attachment:" in out
    assert "shot.png" in out


def test_help_covers_new_commands() -> None:
    from tests.main.parser_help_helpers import flat_help, parser_for

    bead_help = flat_help(parser_for(("sase", "bead")).format_help())
    assert "attach" in bead_help
    assert "attachment" in bead_help
    attach_help = flat_help(parser_for(("sase", "bead", "attach")).format_help())
    assert "bead_note_attachments beta flag" in attach_help
    attachment_help = flat_help(
        parser_for(("sase", "bead", "attachment")).format_help()
    )
    assert "attachment list" in attachment_help
    list_help = flat_help(
        parser_for(("sase", "bead", "attachment", "list")).format_help()
    )
    assert "--json" in list_help
    path_help = flat_help(
        parser_for(("sase", "bead", "attachment", "path")).format_help()
    )
    assert "absolute" in path_help

    args = create_parser().parse_args(["bead", "attachment"])
    assert args.attachment_action == "list"

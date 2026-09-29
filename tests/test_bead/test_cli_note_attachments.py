"""Phase note_authoring: beta flag, authoring service, and the note verb.

Both flag states run against a temporary bead store. The flag-on tests
cover inline, quoted, reused, and ``@@`` references, the failure modes that
must leave the store unchanged, edit reuse/replace/detach, whole-argument
``@file`` reads, and the fast-path rule. The flag-off tests pin today's
behavior.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import BeadNote, IssueType
from sase.bead.note_codec import notes_from_dicts, notes_to_dicts
from sase.bead.project import BeadProject
from sase.cli_file_values import CliFileValueError, read_note_text_value
from sase.feature_flags import override_flags
from sase.main.parser import create_parser

PNG_HEAD = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture()
def work_dir(
    project_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Isolate the CAS home and resolve ``@./`` refs inside the project."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.chdir(project_dir)
    return project_dir


def _create_issue(project_dir: Path) -> str:
    with BeadProject(project_dir) as project:
        issue = project.create("Attachment target", IssueType.PLAN)
    return issue.id


def _run_note(argv: list[str]) -> tuple[str, str, int]:
    """Run ``sase bead note`` argv, returning (stdout, stderr, exit code)."""
    import io
    from contextlib import redirect_stderr, redirect_stdout

    args = create_parser().parse_args(["bead", "note", *argv])
    out, err, code = io.StringIO(), io.StringIO(), 0
    try:
        with redirect_stdout(out), redirect_stderr(err):
            bead_cli.handle_bead_note(args)
    except SystemExit as exc:
        code = int(exc.code or 0)
    return out.getvalue(), err.getvalue(), code


def _notes(project_dir: Path, issue_id: str) -> list[BeadNote]:
    with BeadProject(project_dir) as project:
        return list(project.show(issue_id).notes)


def test_inline_reference_attaches_and_round_trips(
    project_dir: Path, work_dir: Path
) -> None:
    data = PNG_HEAD + b"pixels"
    (work_dir / "shot.png").write_bytes(data)
    issue_id = _create_issue(project_dir)

    with override_flags(bead_note_attachments=True):
        out, err, code = _run_note(
            [issue_id, "-a", "amy", "see", "@./shot.png", "here"]
        )

    assert code == 0
    assert f"Noted: {issue_id}" in out
    assert "attached shot.png" in err
    assert "local" in err
    notes = _notes(project_dir, issue_id)
    assert notes[0].text == "see @attachment:shot.png here"
    assert "@./shot.png" not in notes[0].text
    (name, manifest) = (notes[0].attachments[0].name, notes[0].attachments)
    assert name == "shot.png"
    assert manifest[0].sha256 == hashlib.sha256(data).hexdigest()
    assert manifest[0].size_bytes == len(data)
    assert manifest[0].mime_type == "image/png"


def test_quoted_reference_with_spaces(project_dir: Path, work_dir: Path) -> None:
    (work_dir / "name with spaces.png").write_text("fake png bytes\n")
    issue_id = _create_issue(project_dir)

    with override_flags(bead_note_attachments=True):
        _, _, code = _run_note(
            [issue_id, "-a", "amy", 'see @"name with spaces.png" ok']
        )

    assert code == 0
    notes = _notes(project_dir, issue_id)
    assert notes[0].text == "see @attachment:name_with_spaces.png ok"
    assert notes[0].attachments[0].name == "name_with_spaces.png"


def test_escape_and_non_references_stay_literal(
    project_dir: Path, work_dir: Path
) -> None:
    issue_id = _create_issue(project_dir)
    text = "literal @@./x.png, me@host, @large, see @research:cite for it"

    with override_flags(bead_note_attachments=True):
        _, err, code = _run_note([issue_id, "-a", "amy", text])

    assert code == 0
    assert err == ""
    notes = _notes(project_dir, issue_id)
    assert notes[0].text == (
        "literal @./x.png, me@host, @large, see @research:cite for it"
    )
    assert notes[0].attachments == ()


def test_reused_roster_token_round_trips(project_dir: Path, work_dir: Path) -> None:
    (work_dir / "shot.png").write_bytes(PNG_HEAD)
    issue_id = _create_issue(project_dir)

    with override_flags(bead_note_attachments=True):
        assert _run_note([issue_id, "-a", "amy", "first", "@./shot.png"])[2] == 0
        _, _, code = _run_note(
            [issue_id, "-a", "amy", "again", "@attachment:shot.png", "kept"]
        )

    assert code == 0
    notes = _notes(project_dir, issue_id)
    assert notes[1].text == "again @attachment:shot.png kept"
    assert [a.name for a in notes[1].attachments] == ["shot.png"]
    assert notes[1].attachments[0].sha256 == notes[0].attachments[0].sha256


def test_missing_path_writes_nothing(project_dir: Path, work_dir: Path) -> None:
    issue_id = _create_issue(project_dir)

    with override_flags(bead_note_attachments=True):
        _, err, code = _run_note([issue_id, "-a", "amy", "see", "@./gone.png"])

    assert code == 1
    assert "file not found" in err
    assert "Write @@… for literal text, or fix the path." in err
    assert "nothing was written" in err
    assert _notes(project_dir, issue_id) == []


def test_directory_writes_nothing(project_dir: Path, work_dir: Path) -> None:
    (work_dir / "subdir").mkdir()
    issue_id = _create_issue(project_dir)

    with override_flags(bead_note_attachments=True):
        _, err, code = _run_note([issue_id, "-a", "amy", "see", "@./subdir"])

    assert code == 1
    assert "tar czf" in err
    assert _notes(project_dir, issue_id) == []


def test_sensitive_path_requires_allow_sensitive(
    project_dir: Path, work_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = work_dir / "home"
    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(parents=True)
    (ssh_dir / "id_rsa").write_text("private-key-bytes\n")
    monkeypatch.setenv("HOME", str(home))
    issue_id = _create_issue(project_dir)

    with override_flags(bead_note_attachments=True):
        _, err, code = _run_note([issue_id, "-a", "amy", "key", "@~/.ssh/id_rsa"])
    assert code == 1
    assert "--allow-sensitive" in err
    assert _notes(project_dir, issue_id) == []

    with override_flags(bead_note_attachments=True):
        _, err, code = _run_note([issue_id, "-S", "-a", "amy", "key", "@~/.ssh/id_rsa"])
    assert code == 0
    assert "attached id_rsa" in err
    assert _notes(project_dir, issue_id)[0].attachments[0].name == "id_rsa"


def test_scanner_diagnostic_writes_nothing(project_dir: Path, work_dir: Path) -> None:
    issue_id = _create_issue(project_dir)

    with override_flags(bead_note_attachments=True):
        _, err, code = _run_note([issue_id, "-a", "amy", 'see @"oops'])

    assert code == 1
    assert "1 attachment problem in note text — nothing was written." in err
    assert _notes(project_dir, issue_id) == []


def test_source_deletable_after_successful_note(
    project_dir: Path, work_dir: Path
) -> None:
    src = work_dir / "trace.json"
    src.write_text('{"ok": true}\n')
    issue_id = _create_issue(project_dir)

    with override_flags(bead_note_attachments=True):
        assert _run_note([issue_id, "-a", "amy", "log", "@./trace.json"])[2] == 0
    src.unlink()

    notes = _notes(project_dir, issue_id)
    assert notes[0].text == "log @attachment:trace.json"
    assert notes[0].attachments[0].mime_type == "application/json"


def test_edit_reuses_replaces_and_detaches(project_dir: Path, work_dir: Path) -> None:
    (work_dir / "a.png").write_bytes(PNG_HEAD + b"v1")
    issue_id = _create_issue(project_dir)

    with override_flags(bead_note_attachments=True):
        assert _run_note([issue_id, "-a", "amy", "first", "@./a.png"])[2] == 0
        # Reuse the roster token: the manifest is kept.
        _, _, code = _run_note(
            [issue_id, "-a", "amy", "-e", "1", "first", "@attachment:a.png", "kept"]
        )
        assert code == 0
        notes = _notes(project_dir, issue_id)
        assert notes[0].text == "first @attachment:a.png kept"
        assert [a.name for a in notes[0].attachments] == ["a.png"]
        # A changed digest uniquifies and echoes the new name.
        (work_dir / "a.png").write_bytes(PNG_HEAD + b"v2-changed")
        _, err, code = _run_note([issue_id, "-a", "amy", "second", "@./a.png"])
        assert code == 0
        assert "stored as a-2.png" in err
        notes = _notes(project_dir, issue_id)
        assert notes[1].text == "second @attachment:a-2.png"
        # Dropping the token detaches the manifest.
        _, err, code = _run_note([issue_id, "-a", "amy", "-e", "1", "first"])
        assert code == 0
        assert "detached a.png" in err
        assert _notes(project_dir, issue_id)[0].attachments == ()


def test_whole_argument_file_loads_text_and_attaches_when_on(
    project_dir: Path, work_dir: Path
) -> None:
    (work_dir / "inner.png").write_bytes(PNG_HEAD)
    (work_dir / "body.txt").write_text("from file @./inner.png\n")
    issue_id = _create_issue(project_dir)

    with override_flags(bead_note_attachments=True):
        _, _, code = _run_note([issue_id, "-a", "amy", "@body.txt"])

    assert code == 0
    notes = _notes(project_dir, issue_id)
    assert notes[0].text == "from file @attachment:inner.png"
    assert [a.name for a in notes[0].attachments] == ["inner.png"]


def test_whole_argument_file_loads_text_without_attaching_when_off(
    project_dir: Path, work_dir: Path
) -> None:
    (work_dir / "inner.png").write_bytes(PNG_HEAD)
    (work_dir / "body.txt").write_text("from file @./inner.png\n")
    issue_id = _create_issue(project_dir)

    with override_flags(bead_note_attachments=False):
        _, err, code = _run_note([issue_id, "-a", "amy", "@body.txt"])

    assert code == 0
    assert err == ""
    notes = _notes(project_dir, issue_id)
    assert notes[0].text == "from file @./inner.png"
    assert notes[0].attachments == ()


def test_flag_off_stores_inline_reference_as_literal(
    project_dir: Path, work_dir: Path
) -> None:
    (work_dir / "shot.png").write_bytes(PNG_HEAD)
    issue_id = _create_issue(project_dir)

    with override_flags(bead_note_attachments=False):
        _, err, code = _run_note([issue_id, "-a", "amy", "see", "@./shot.png"])

    assert code == 0
    assert err == ""
    notes = _notes(project_dir, issue_id)
    assert notes[0].text == "see @./shot.png"
    assert notes[0].attachments == ()


def test_fast_path_note_with_embedded_at_stays_in_python_when_on() -> None:
    from sase.main import bead_fast_path

    argv = ["note", "sase-1", "see", "@./shot.png", "here"]
    with (
        override_flags(bead_note_attachments=True),
        patch.object(bead_fast_path, "execute_bead_cli") as execute,
    ):
        assert bead_fast_path.try_handle_bead_fast_path(argv) is None
        execute.assert_not_called()


def test_fast_path_note_with_embedded_at_keeps_fast_path_when_off() -> None:
    from sase.main import bead_fast_path

    argv = ["note", "sase-1", "see", "me@host"]
    with (
        override_flags(bead_note_attachments=False),
        patch.object(bead_fast_path, "execute_bead_cli", return_value=7) as execute,
    ):
        assert bead_fast_path.try_handle_bead_fast_path(argv) == 7
        execute.assert_called_once()


def test_notes_to_dicts_omits_empty_attachments() -> None:
    plain = BeadNote(id="e1", timestamp="2026-01-01T00:00:00Z", author="amy", text="hi")
    assert notes_to_dicts([plain]) == [
        {
            "id": "e1",
            "timestamp": "2026-01-01T00:00:00Z",
            "author": "amy",
            "text": "hi",
        }
    ]

    wire = {
        "name": "shot.png",
        "sha256": "ab" * 32,
        "size_bytes": 12,
        "mime_type": "image/png",
        "image": {"width": 4, "height": 2},
        "origin": "athena",
    }
    restored = notes_from_dicts(
        [
            {
                "id": "e2",
                "timestamp": "2026-01-01T00:00:00Z",
                "author": "amy",
                "text": "see @attachment:shot.png",
                "attachments": [wire],
            }
        ]
    )
    assert notes_to_dicts(restored) == [
        {
            "id": "e2",
            "timestamp": "2026-01-01T00:00:00Z",
            "author": "amy",
            "text": "see @attachment:shot.png",
            "attachments": [wire],
        }
    ]
    assert restored[0].attachments[0].image == (4, 2)


def test_read_note_text_value_flag_off_delegates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "note.md"
    target.write_text("loaded\n")
    monkeypatch.chdir(tmp_path)

    with override_flags(bead_note_attachments=False):
        assert (
            read_note_text_value(f"@{target}", target="note text", bead_id="sase-1")
            == "loaded\n"
        )
        assert (
            read_note_text_value("@@./x", target="note text", bead_id="sase-1")
            == "@./x"
        )


def test_read_note_text_value_flag_on() -> None:
    with override_flags(bead_note_attachments=True):
        assert (
            read_note_text_value("plain", target="note text", bead_id="sase-1")
            == "plain"
        )
        assert read_note_text_value("@@./x", target="note text", bead_id="sase-1") == (
            "@@./x"
        )
        assert read_note_text_value("@", target="note text", bead_id="sase-1") == "@"


def test_read_note_text_value_rejects_binary_and_oversized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    binary = tmp_path / "blob.bin"
    binary.write_bytes(bytes(range(256)))
    big = tmp_path / "big.txt"
    big.write_bytes(b"x" * (262144 + 1))

    with override_flags(bead_note_attachments=True):
        with pytest.raises(CliFileValueError, match="sase bead attach"):
            read_note_text_value("@blob.bin", target="note text", bead_id="sase-9")
        with pytest.raises(CliFileValueError, match="256 KiB"):
            read_note_text_value("@big.txt", target="note text", bead_id="sase-9")


def test_attachment_sensitive_patterns_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead import config as bead_config

    def _boom() -> object:
        raise RuntimeError("config unavailable")

    monkeypatch.setattr(bead_config, "load_merged_config", _boom)
    assert bead_config.get_attachment_sensitive_patterns() == []
    monkeypatch.setattr(
        bead_config, "load_merged_config", lambda: {"bead": {"attachments": "nope"}}
    )
    assert bead_config.get_attachment_sensitive_patterns() == []
    monkeypatch.setattr(
        bead_config,
        "load_merged_config",
        lambda: {"bead": {"attachments": {"sensitive_patterns": ["*.key", 7]}}},
    )
    assert bead_config.get_attachment_sensitive_patterns() == ["*.key"]

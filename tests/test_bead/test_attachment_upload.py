"""Phase upload: placement, pre-publication upload, and outbox (phase upload).

Both flag states run against a temporary bead store. The flag-on tests use a
local bare remote behind the hidden ``attachments-private`` clone; no network
and no GitHub.
"""

from __future__ import annotations

import io
import subprocess
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
    "note": bead_cli.handle_bead_note,
    "attach": bead_cli.handle_bead_attach,
    "attachment": bead_cli.handle_bead_attachment,
}

_GIT_TIMEOUT = 60.0


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
    )


@pytest.fixture()
def work_dir(
    project_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Isolate the CAS home and resolve ``@./`` refs inside the project."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.chdir(project_dir)
    return project_dir


def _create_plan(project_dir: Path) -> str:
    with BeadProject(project_dir) as project:
        issue = project.create("Attachment target", IssueType.PLAN)
    return issue.id


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


def _show(project_dir: Path, issue_id: str):
    with BeadProject(project_dir) as project:
        return project.show(issue_id)


def _outbox_entries() -> list:
    from sase.bead.attachments.outbox import read_outbox

    try:
        return read_outbox("test-project")
    except ValueError:
        return []


def _plant_hidden_clone(tmp_path: Path, remote: Path) -> Path:
    from sase.core.paths import sase_projects_dir

    clone = sase_projects_dir() / "test-project" / "repos" / "attachments-private"
    clone.parent.mkdir(parents=True, exist_ok=True)
    _git(
        tmp_path,
        "clone",
        "--bare",
        "--filter=blob:none",
        f"file://{remote}",
        str(clone),
    )
    return clone


@pytest.fixture()
def remote(tmp_path: Path) -> Path:
    path = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", "-b", "main", path.name)
    _git(path, "config", "uploadpack.allowFilter", "true")
    _git(path, "config", "uploadpack.allowAnySHA1InWant", "true")
    return path


def test_flag_off_keeps_text_writes_no_outbox(
    project_dir: Path, work_dir: Path
) -> None:
    (work_dir / "shot.png").write_bytes(PNG_HEAD)
    issue_id = _create_plan(project_dir)
    with override_flags(bead_note_attachments=False):
        out, err, code = _run(["note", issue_id, "see @./shot.png"])
    assert code == 0
    assert "Noted" in out
    assert _show(project_dir, issue_id).notes[0].text == "see @./shot.png"
    assert _outbox_entries() == []


def test_no_store_echo_stays_local(project_dir: Path, work_dir: Path) -> None:
    (work_dir / "shot.png").write_bytes(PNG_HEAD + b"pixels")
    issue_id = _create_plan(project_dir)
    with override_flags(bead_note_attachments=True):
        out, err, code = _run(["note", issue_id, "see @./shot.png"])
    assert code == 0
    assert "stayed local on this machine" in err
    assert "(private)" not in err
    assert _outbox_entries() == []
    assert _show(project_dir, issue_id).notes[0].attachments


def test_oversize_fails_without_local_only(
    project_dir: Path,
    work_dir: Path,
    remote: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    _plant_hidden_clone(tmp_path, remote)
    (work_dir / "big.bin").write_bytes(b"x" * 64)
    issue_id = _create_plan(project_dir)
    monkeypatch.setattr("sase.bead.config.get_attachment_git_max_bytes", lambda: 10)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with override_flags(bead_note_attachments=True):
        _out, err, code = _run(["note", issue_id, "see @./big.bin"])
    assert code != 0
    assert "-L" in err
    assert list(_show(project_dir, issue_id).notes) == []


def test_oversize_local_only_writes_without_queue(
    project_dir: Path,
    work_dir: Path,
    remote: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _plant_hidden_clone(tmp_path, remote)
    (work_dir / "big.bin").write_bytes(b"x" * 64)
    issue_id = _create_plan(project_dir)
    monkeypatch.setattr("sase.bead.config.get_attachment_git_max_bytes", lambda: 10)
    with override_flags(bead_note_attachments=True):
        out, err, code = _run(["note", issue_id, "-L", "see @./big.bin"])
    assert code == 0
    assert "stayed local on this machine" in err
    assert _outbox_entries() == []
    assert _show(project_dir, issue_id).notes[0].attachments


def test_failed_put_queues_then_push_drains(
    project_dir: Path,
    work_dir: Path,
    remote: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.attachments.git_store import GitAttachmentStore
    from sase.bead.attachments.blob_store import BlobStoreError

    _plant_hidden_clone(tmp_path, remote)
    (work_dir / "shot.png").write_bytes(PNG_HEAD + b"queued")
    issue_id = _create_plan(project_dir)
    calls = {"count": 0}
    real_put = GitAttachmentStore.put

    def flaky_put(self, sha256, src, size_bytes, progress=None):
        calls["count"] += 1
        if calls["count"] == 1:
            raise BlobStoreError("boom", transient=True)
        return real_put(self, sha256, src, size_bytes, progress)

    monkeypatch.setattr(GitAttachmentStore, "put", flaky_put)
    with override_flags(bead_note_attachments=True):
        out, err, code = _run(["note", issue_id, "see @./shot.png"])
    assert code == 0
    assert "pending upload" in err
    assert _show(project_dir, issue_id).notes[0].attachments
    assert len(_outbox_entries()) == 1
    with override_flags(bead_note_attachments=True):
        out, err, code = _run(["attachment", "push", issue_id])
    assert code == 0
    assert "Pushed 1" in out
    assert _outbox_entries() == []


def test_require_upload_failure_writes_nothing(
    project_dir: Path,
    work_dir: Path,
    remote: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.attachments.git_store import GitAttachmentStore
    from sase.bead.attachments.blob_store import BlobStoreError

    _plant_hidden_clone(tmp_path, remote)
    (work_dir / "shot.png").write_bytes(PNG_HEAD + b"strict")
    issue_id = _create_plan(project_dir)
    monkeypatch.setattr("sase.bead.config.get_attachment_require_upload", lambda: True)

    def always_fail(self, sha256, src, size_bytes, progress=None):
        raise BlobStoreError("boom", transient=True)

    monkeypatch.setattr(GitAttachmentStore, "put", always_fail)
    with override_flags(bead_note_attachments=True):
        _out, _err, code = _run(["note", issue_id, "see @./shot.png"])
    assert code != 0
    assert list(_show(project_dir, issue_id).notes) == []
    assert _outbox_entries() == []

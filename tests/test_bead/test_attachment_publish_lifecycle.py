"""Publish lifecycle: gate-aware publish, unpublish narrowing, doctor rescans.

Synthetic inputs only; no network and no real GitHub repositories. Store
interactions use local bare remotes (``file://``) or stub stores.
"""

from __future__ import annotations

import argparse
import io
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest


def _publish_args(bead_id: str, name: str, *, yes: bool = True) -> argparse.Namespace:
    return argparse.Namespace(id=bead_id, name=name, yes=yes)


def _unpublish_args(bead_id: str, name: str, *, yes: bool = True) -> argparse.Namespace:
    return argparse.Namespace(id=bead_id, name=name, yes=yes)


def test_gate_marker_allows_agent_publish_past_human_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead import cli_attachment_publish as _publish

    assert _publish.is_gate_option_command({"SASE_GATE_COMMAND": "1"}) is True
    assert _publish.is_gate_option_command({}) is False
    # An agent run without the marker is refused before any bead work.
    monkeypatch.setenv("SASE_AGENT_NAME", "test.agent")
    monkeypatch.delenv("SASE_GATE_COMMAND", raising=False)
    out, err, code = io.StringIO(), io.StringIO(), 0
    try:
        with redirect_stdout(out), redirect_stderr(err):
            _publish.handle_bead_attachment_publish(_publish_args("sase-x", "a.bin"))
    except SystemExit as exc:
        code = int(exc.code or 0)
    assert code == 1
    assert "human-only" in err.getvalue()
    # The same agent run with the gate marker reaches bead resolution.
    monkeypatch.setenv("SASE_GATE_COMMAND", "1")

    def _boom(_ids: list[str]) -> object:
        raise SystemExit(99)

    monkeypatch.setattr(
        "sase.bead.cli_attachment_publish.resolve_bead_operation_context", _boom
    )
    out, err, code = io.StringIO(), io.StringIO(), 0
    try:
        with redirect_stdout(out), redirect_stderr(err):
            _publish.handle_bead_attachment_publish(_publish_args("sase-x", "a.bin"))
    except SystemExit as exc:
        code = int(exc.code or 0)
    assert code == 99


def test_metadata_and_size_refusals_are_non_widenable() -> None:
    from sase.bead import cli_attachment_publish as _publish

    assert (
        _publish._metadata_refuses_publish(
            {"rule": "sensitive_path", "reason": "under ~/.ssh"}
        )
        is not None
    )
    assert (
        _publish._metadata_refuses_publish(
            {"rule": "scan_hit", "reason": "known value match"}
        )
        is not None
    )
    assert (
        _publish._metadata_refuses_publish(
            {"rule": "scan_hit", "reason": "credential pattern"}
        )
        is None
    )
    assert _publish._metadata_refuses_publish(None) is None


def test_publish_parser_and_unpublish_parser_exist() -> None:
    from sase.main.parser import create_parser

    parser = create_parser()
    publish = parser.parse_args(
        ["bead", "attachment", "publish", "sase-ab", "a.bin", "-y"]
    )
    assert publish.attachment_action == "publish"
    assert publish.id == "sase-ab" and publish.name == "a.bin" and publish.yes is True
    unpublish = parser.parse_args(
        ["bead", "attachment", "unpublish", "sase-ab", "a.bin", "-y"]
    )
    assert unpublish.attachment_action == "unpublish"
    assert unpublish.id == "sase-ab" and unpublish.name == "a.bin"


def test_evidence_names_are_refused_for_publish_and_unpublish(
    project_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead import cli_attachment_publish as _publish
    from sase.bead.model import IssueType
    from sase.bead.project import BeadProject

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.chdir(project_dir)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.delenv("SASE_GATE_COMMAND", raising=False)
    with BeadProject(project_dir) as project:
        issue = project.create(
            "Evidence target",
            IssueType.TASK,
            task_type="bug",
            size="small",
            created_by="t.agent",
        )
        project.plus_one(
            issue.id,
            note="independent evidence @attachment:shot.png",
            reporter="witness.one",
            note_attachments=[
                {
                    "name": "shot.png",
                    "sha256": "b" * 64,
                    "size_bytes": 10,
                    "mime_type": "image/png",
                }
            ],
        )
        bead_id = issue.id
    out, err, code = io.StringIO(), io.StringIO(), 0
    try:
        with redirect_stdout(out), redirect_stderr(err):
            _publish.handle_bead_attachment_publish(_publish_args(bead_id, "shot.png"))
    except SystemExit as exc:
        code = int(exc.code or 0)
    assert code == 1
    assert "evidence" in err.getvalue().lower()
    out, err, code = io.StringIO(), io.StringIO(), 0
    try:
        with redirect_stdout(out), redirect_stderr(err):
            _publish.handle_bead_attachment_unpublish(
                _unpublish_args(bead_id, "shot.png")
            )
    except SystemExit as exc:
        code = int(exc.code or 0)
    assert code == 1
    assert "evidence" in err.getvalue().lower()


def _run_git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, timeout=60)


def test_withdraw_removes_public_but_keeps_private_readable(tmp_path: Path) -> None:
    from sase.bead.attachments.git_store import GitAttachmentStore
    from sase.bead.attachments.store import LocalAttachmentStore

    remote_public = tmp_path / "public.git"
    remote_private = tmp_path / "private.git"
    for remote in (remote_public, remote_private):
        _run_git(tmp_path, "init", "--bare", "-b", "main", remote.name)
    work = tmp_path / "work"
    work.mkdir()
    _run_git(
        work, "clone", "--bare", "--filter=blob:none", f"file://{remote_public}", "pub"
    )
    _run_git(
        work,
        "clone",
        "--bare",
        "--filter=blob:none",
        f"file://{remote_private}",
        "priv",
    )
    public = GitAttachmentStore(
        work / "pub", "owner/repo (public)", name="public", layout="public"
    )
    private = GitAttachmentStore(work / "priv", "owner/repo (private)")
    data = b"withdraw me bytes"
    import hashlib

    digest = hashlib.sha256(data).hexdigest()
    src = tmp_path / "payload.bin"
    src.write_bytes(data)
    public.put(digest, src, len(data), mime_type="application/octet-stream")
    private.put(digest, src, len(data))
    assert public.has(digest) is True
    assert private.has(digest) is True
    public.withdraw(digest)
    assert public.has(digest) is False
    assert private.has(digest) is True
    # The private copy still fetches into a fresh local CAS.
    fresh_root = tmp_path / "fresh-cas"
    private.get(digest, fresh_root)
    assert LocalAttachmentStore(root=fresh_root).verify(digest) is True


def test_stale_rules_rescan_reports_unpublish_command(
    project_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead import attachment_doctor as _doctor
    from sase.bead.model import BeadNote, BeadNoteAttachment, Issue, IssueType, Status
    from sase.bead.project import BeadProject

    home = tmp_path / "sase-home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SASE_HOME", str(home))
    monkeypatch.chdir(project_dir)
    data = b"clean bytes for rescan"
    import hashlib

    digest = hashlib.sha256(data).hexdigest()
    with BeadProject(project_dir) as project:
        issue = project.create(
            "Rescan target",
            IssueType.TASK,
            task_type="bug",
            size="small",
            created_by="t.agent",
        )
        bead_id = issue.id
    from sase.bead.attachments.store import LocalAttachmentStore

    local = LocalAttachmentStore()
    local.ensure_dirs()
    target = local.object_path(digest)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    try:
        target.chmod(0o444)
    except OSError:
        pass
    from sase.bead.attachments import audience as _audience

    meta = _audience.audience_metadata_path(digest)
    meta.parent.mkdir(parents=True, exist_ok=True)
    import json

    meta.write_text(
        json.dumps(
            {
                "rule": "public_evidence",
                "reason": "clean",
                "explicit": False,
                "scanner_rules_version": 1,
                "decided_at": "2026-01-01T00:00:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    attachment = BeadNoteAttachment(
        name="note.bin",
        sha256=digest,
        size_bytes=len(data),
        mime_type="text/plain",
        visibility="public",
    )
    note = BeadNote(
        id="n1",
        timestamp="2026-01-01T00:00:00Z",
        author="t",
        text="see",
        attachments=(attachment,),
    )
    issue_obj = Issue(
        id=bead_id, title="Rescan target", status=Status.OPEN, notes=[note]
    )
    monkeypatch.setattr(_doctor, "_current_scanner_rules_version", lambda: 2)
    monkeypatch.setattr(
        _audience,
        "scan_cas_object",
        lambda _path, **_kwargs: {
            "outcome": "hit",
            "hit": {"kind": "credential_pattern", "rule_id": "test-rule", "line": 1},
        },
    )
    hits = _doctor.find_stale_scanner_hits([issue_obj])
    assert len(hits) == 1
    assert hits[0].startswith("rotate the credential first")
    assert f"sase bead attachment unpublish {bead_id} note.bin" in hits[0]
    # A current rules version records no finding even with the same hit.
    meta.write_text(
        json.dumps(
            {
                "rule": "public_evidence",
                "reason": "clean",
                "explicit": False,
                "scanner_rules_version": 2,
                "decided_at": "2026-01-01T00:00:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert _doctor.find_stale_scanner_hits([issue_obj]) == []


def test_publish_confirmation_needs_tty_or_yes() -> None:
    from sase.bead import cli_attachment_publish as _publish

    assert (
        _publish._confirm_irreversible("a.bin", assume_yes=True, verb="publish") is True
    )
    with pytest.raises(SystemExit) as exc:
        _publish._confirm_irreversible("a.bin", assume_yes=False, verb="publish")
    assert int(exc.value.code or 0) == 2


def test_publish_refuses_private_store_and_size_cap(
    project_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead import cli_attachment_publish as _publish
    from sase.bead.model import IssueType
    from sase.bead.project import BeadProject

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.chdir(project_dir)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.delenv("SASE_GATE_COMMAND", raising=False)
    with BeadProject(project_dir) as project:
        issue = project.create(
            "Publish guard",
            IssueType.TASK,
            task_type="bug",
            size="small",
            created_by="t.agent",
        )
        project.append_note(
            issue.id,
            "see @attachment:big.bin",
            attachments=[
                {
                    "name": "big.bin",
                    "sha256": "c" * 64,
                    "size_bytes": 40 * 1024 * 1024,
                    "mime_type": "application/octet-stream",
                    "visibility": "private",
                }
            ],
        )
        bead_id = issue.id
    # Private bead stores can never be widened, even for small files.
    monkeypatch.setattr(
        "sase.bead.attachments.provenance.bead_store_visibility", lambda: "private"
    )
    out, err, code = io.StringIO(), io.StringIO(), 0
    try:
        with redirect_stdout(out), redirect_stderr(err):
            _publish.handle_bead_attachment_publish(_publish_args(bead_id, "big.bin"))
    except SystemExit as exc:
        code = int(exc.code or 0)
    assert code == 1
    assert "private" in err.getvalue().lower()
    # A public bead store still refuses over-cap sizes.
    monkeypatch.setattr(
        "sase.bead.attachments.provenance.bead_store_visibility", lambda: "public"
    )
    out, err, code = io.StringIO(), io.StringIO(), 0
    try:
        with redirect_stdout(out), redirect_stderr(err):
            _publish.handle_bead_attachment_publish(_publish_args(bead_id, "big.bin"))
    except SystemExit as exc:
        code = int(exc.code or 0)
    assert code == 1
    assert "public_max_bytes" in err.getvalue()


def test_private_store_anonymously_readable_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.doctor import checks_attachment_store as _check

    monkeypatch.setattr(
        "sase.bead.attachments.remote_visibility.resolve_remote_visibility",
        lambda _url: "public",
    )
    assert _check._private_store_anonymously_readable(object()) is False
    assert _check._private_store_anonymously_readable(None) is False

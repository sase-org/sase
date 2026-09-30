"""Phase lifecycle: purge, doctor, prune, and bead pages.

All tests run against a temporary bead store and an isolated ``SASE_HOME``;
no shared store, git remote, or network is touched. Purge exercises the
local-only path (tombstone to no stores, local removal, ``(purged)``
rendering); prune uses a stub shared store; the doctor matrix covers
mismatches, dangling descriptors, corrupt objects, and aged orphans plus
their repairs; pages assert the private-attachment line carries no path,
link, or digest.
"""

from __future__ import annotations

import io
import os
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.attachment_doctor import (
    inspect_attachment_health,
    manifest_mismatches,
    render_attachment_health_messages,
    repair_attachment_health,
)
from sase.bead.attachment_presentation import attachment_page_line
from sase.bead.attachments.lifecycle import (
    collect_inventory,
    orphan_digests,
    plan_prune,
)
from sase.bead.attachments.store import LocalAttachmentStore
from sase.bead.attachments.tombstones import (
    has_local_tombstone,
    parse_tombstone_bytes,
    tombstone_bytes,
)
from sase.bead.model import BeadNote, BeadNoteAttachment, Issue, IssueType, Status
from sase.bead.project import BeadProject
from sase.bead_pages.rendering_identity import render_attachments
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


def _create_task(project_dir: Path) -> str:
    with BeadProject(project_dir) as project:
        issue = project.create(
            "Lifecycle target",
            IssueType.TASK,
            task_type="bug",
            size="small",
            created_by="creator.agent",
        )
    return issue.id


def _run_attachment(argv: list[str]) -> tuple[str, str, int]:
    """Run one ``sase bead attachment …`` argv, returning (out, err, code)."""
    args = create_parser().parse_args(["bead", "attachment", *argv])
    out, err, code = io.StringIO(), io.StringIO(), 0
    try:
        with redirect_stdout(out), redirect_stderr(err):
            bead_cli.handle_bead_attachment(args)
    except SystemExit as exc:
        code = int(exc.code or 0)
    return out.getvalue(), err.getvalue(), code


def _attach(
    work_dir: Path, issue_id: str, filename: str, data: bytes
) -> BeadNoteAttachment:
    (work_dir / filename).write_bytes(data)
    args = create_parser().parse_args(["bead", "attach", issue_id, f"./{filename}"])
    out, err, code = io.StringIO(), io.StringIO(), 0
    try:
        with (
            override_flags(bead_note_attachments=True),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            bead_cli.handle_bead_attach(args)
    except SystemExit as exc:
        code = int(exc.code or 0)
    assert code == 0, err
    with BeadProject(work_dir) as project:
        issue = project.show(issue_id)
    assert issue.notes and issue.notes[-1].attachments
    return issue.notes[-1].attachments[-1]


# -- purge ---------------------------------------------------------------


def test_purge_removes_local_bytes_and_renders_purged(
    project_dir: Path, work_dir: Path
) -> None:
    issue_id = _create_task(project_dir)
    attachment = _attach(work_dir, issue_id, "shot.png", PNG_HEAD + b"pixels")
    digest = attachment.sha256
    store = LocalAttachmentStore()
    assert store.has(digest)

    out, err, code = _run_attachment(
        ["purge", issue_id, "shot.png", "-r", "contains a secret", "-y"]
    )
    assert code == 0, err
    assert "Purged shot.png" in out
    assert "filter-repo" in out
    assert not store.has(digest)
    assert has_local_tombstone(store, digest)
    payload = parse_tombstone_bytes(
        (store.tombstones_dir / f"{digest}.json").read_bytes()
    )
    assert payload["sha256"] == digest
    assert payload["reason"] == "contains a secret"

    from sase.bead.attachment_presentation import attachment_availability

    assert attachment_availability(digest, size_bytes=attachment.size_bytes) == "purged"
    list_out, _, list_code = _run_attachment(["list", issue_id])
    assert list_code == 0
    assert "(purged)" in list_out


def test_purge_refuses_without_reason_or_name(
    project_dir: Path, work_dir: Path
) -> None:
    issue_id = _create_task(project_dir)
    _attach(work_dir, issue_id, "shot.png", PNG_HEAD)
    with pytest.raises(SystemExit):
        create_parser().parse_args(
            ["bead", "attachment", "purge", issue_id, "shot.png"]
        )
    out, err, code = _run_attachment(
        ["purge", issue_id, "missing.png", "-r", "x", "-y"]
    )
    assert code == 1
    assert "attachment not found" in err
    assert out == ""


def test_purge_leaves_other_digests_cached(project_dir: Path, work_dir: Path) -> None:
    issue_id = _create_task(project_dir)
    first = _attach(work_dir, issue_id, "a.png", PNG_HEAD + b"a")
    second = _attach(work_dir, issue_id, "b.png", PNG_HEAD + b"b")
    store = LocalAttachmentStore()

    out, _, code = _run_attachment(["purge", issue_id, "a.png", "-r", "stale", "-y"])
    assert code == 0, out
    assert not store.has(first.sha256)
    assert store.has(second.sha256)
    assert not has_local_tombstone(store, second.sha256)


def test_tombstone_bytes_round_trip() -> None:
    digest = "9f" * 32
    raw = tombstone_bytes(digest, "legal hold", actor="athena")
    parsed = parse_tombstone_bytes(raw)
    assert parsed["sha256"] == digest
    assert parsed["reason"] == "legal hold"
    assert parsed["actor"] == "athena"
    assert parsed["schema_version"] == 1
    with pytest.raises(ValueError, match="not a purge tombstone"):
        parse_tombstone_bytes(b"{}")
    with pytest.raises(ValueError, match="cannot be empty"):
        tombstone_bytes(digest, "  ")


# -- doctor --------------------------------------------------------------


def _note_issue(
    name: str, text: str, manifest: tuple[BeadNoteAttachment, ...]
) -> Issue:
    return Issue(
        id="sase-zz.1",
        title="note target",
        status=Status.OPEN,
        issue_type=IssueType.TASK,
        notes=(
            BeadNote(
                id="e1",
                timestamp="2026-09-30T00:00:00Z",
                author="tester",
                text=text,
                attachments=manifest,
            ),
        ),
    )


def _descriptor(name: str, digest: str) -> BeadNoteAttachment:
    return BeadNoteAttachment(
        name=name, sha256=digest, size_bytes=8, mime_type="text/plain"
    )


def test_manifest_mismatch_detector() -> None:
    digest = "ab" * 32
    matched = _note_issue(
        "ok", "see @attachment:log.txt", (_descriptor("log.txt", digest),)
    )
    assert manifest_mismatches([matched]) == []
    orphan_token = _note_issue(
        "bad", "see @attachment:gone.txt", (_descriptor("log.txt", digest),)
    )
    lines = manifest_mismatches([orphan_token])
    assert len(lines) == 1
    assert "sase-zz.1 note#1" in lines[0]
    orphan_descriptor = _note_issue(
        "bad", "no tokens here", (_descriptor("x", digest),)
    )
    assert len(manifest_mismatches([orphan_descriptor])) == 1


def test_doctor_finds_dangling_and_corrupt(project_dir: Path, work_dir: Path) -> None:
    issue_id = _create_task(project_dir)
    attachment = _attach(work_dir, issue_id, "shot.png", PNG_HEAD + b"pixels")
    store = LocalAttachmentStore()
    # Dangling: drop the bytes without a tombstone.
    store.object_path(attachment.sha256).unlink()
    report = inspect_attachment_health()
    assert report.dangling == [attachment.sha256]
    assert render_attachment_health_messages(report) != []

    # Corrupt: restore then flip one byte.
    _attach(work_dir, issue_id, "shot2.png", PNG_HEAD + b"pixels")
    other = None
    with BeadProject(work_dir) as project:
        issue = project.show(issue_id)
        other = issue.notes[-1].attachments[-1].sha256
    assert other is not None
    os.chmod(store.object_path(other), 0o600)
    with open(store.object_path(other), "r+b") as handle:
        handle.seek(0)
        handle.write(b"\x00")
    report = inspect_attachment_health()
    assert other in report.corrupt
    results = repair_attachment_health(report)
    assert any("Quarantined" in line for line in results)
    assert not store.has(other)


def test_doctor_repairs_aged_orphans(
    project_dir: Path, work_dir: Path, tmp_path: Path
) -> None:
    from sase.bead.attachments.ingest import ingest_path

    source = tmp_path / "orphan.bin"
    source.write_bytes(b"orphan bytes")
    blob = ingest_path(source)
    store = LocalAttachmentStore()
    assert store.has(blob.sha256)
    with BeadProject(work_dir) as project:
        inventory = collect_inventory(project)
    assert orphan_digests(inventory) == []
    aged = 8 * 24 * 60 * 60
    old = time.time() - aged
    os.utime(store.object_path(blob.sha256), (old, old))
    with BeadProject(work_dir) as project:
        inventory = collect_inventory(project)
    assert orphan_digests(inventory) == [blob.sha256]
    report = inspect_attachment_health()
    assert report.orphans == [blob.sha256]
    assert "orphan" in "\n".join(render_attachment_health_messages(report))
    results = repair_attachment_health(report)
    assert any("Removed 1 orphan" in line for line in results)
    assert not store.has(blob.sha256)


def test_doctor_parser_accepts_fix_attachments_alias(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()
    for flag in ("-T", "--fix-attachments"):
        args = parser.parse_args(["bead", "doctor", flag])
        assert args.fix_attachments is True
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["bead", "doctor", "-h"])
    assert excinfo.value.code == 0
    assert "--fix-attachments" in capsys.readouterr().out


# -- prune ---------------------------------------------------------------


class _StubStore:
    """Minimal shared store stub: only ``has`` matters for prune planning."""

    name = "git"

    def __init__(self, present: set[str]) -> None:
        self._present = present

    def describe(self) -> str:
        return "stub shared store"

    def has(self, sha256: str) -> bool:
        return sha256 in self._present


def test_prune_plan_evicts_oldest_store_confirmed_first(
    project_dir: Path, work_dir: Path, tmp_path: Path
) -> None:
    from sase.bead.attachments.ingest import ingest_path

    first = tmp_path / "first.bin"
    first.write_bytes(b"first-bytes")
    second = tmp_path / "second.bin"
    second.write_bytes(b"second-bytes-longer")
    first_blob = ingest_path(first)
    second_blob = ingest_path(second)
    store = LocalAttachmentStore()
    old = time.time() - 1000
    os.utime(store.object_path(first_blob.sha256), (old, old))
    with BeadProject(work_dir) as project:
        inventory = collect_inventory(project)
    stores = {"git": _StubStore({first_blob.sha256})}
    total = first_blob.size_bytes + second_blob.size_bytes
    plan = plan_prune(inventory, stores, set(), total - 1)
    assert [candidate.sha256 for candidate in plan.evict] == [first_blob.sha256]
    assert plan.skipped_local_only == 1
    # Outbox digests are never evicted even when over budget.
    plan = plan_prune(inventory, stores, {first_blob.sha256}, total - 1)
    assert plan.evict == []
    assert plan.skipped_pending == 1


def test_prune_cli_dry_run_then_evicts(
    project_dir: Path,
    work_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.attachments.ingest import ingest_path

    source = tmp_path / "cached.bin"
    source.write_bytes(b"cached-bytes")
    blob = ingest_path(source)
    monkeypatch.setattr(
        "sase.bead.attachments.upload.discover_stores",
        lambda _context=None: {"git": _StubStore({blob.sha256})},
    )
    # One byte less forces the eviction; the dry run only plans.
    monkeypatch.setattr(
        "sase.bead.config.get_attachment_local_cache_max_bytes",
        lambda: blob.size_bytes - 1,
    )
    out, _, code = _run_attachment(["prune"])
    assert code == 0
    assert "Dry run" in out
    assert LocalAttachmentStore().has(blob.sha256)
    out, _, code = _run_attachment(["prune", "-y"])
    assert code == 0
    assert "Pruned 1 object" in out
    assert not LocalAttachmentStore().has(blob.sha256)


def test_prune_cli_without_store_prunes_nothing(
    project_dir: Path,
    work_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.attachments.ingest import ingest_path

    source = tmp_path / "local.bin"
    source.write_bytes(b"local-bytes")
    blob = ingest_path(source)
    monkeypatch.setattr(
        "sase.bead.attachments.upload.discover_stores", lambda _context=None: {}
    )
    out, _, code = _run_attachment(["prune", "-y"])
    assert code == 0
    assert "nothing to prune" in out
    assert LocalAttachmentStore().has(blob.sha256)


# -- bead pages ----------------------------------------------------------


def test_page_line_has_no_path_link_or_digest() -> None:
    line = attachment_page_line(
        name="login.png",
        mime_type="image/png",
        image=(1280, 720),
        size_bytes=188416,
    )
    assert line == "🔒 login.png · image/png · 1280×720 · 184 KiB (private attachment)"
    assert "sha256" not in line
    assert ".sase" not in line
    assert "http" not in line


def test_render_attachments_section_lists_roster() -> None:
    digest = "cd" * 32
    issue = _note_issue(
        "paged",
        "shot @attachment:shot.png",
        (_descriptor("shot.png", digest),),
    )
    lines = render_attachments(issue)
    assert lines[1] == "## Attachments"
    assert any("(private attachment)" in line for line in lines)
    assert not any("sha256" in line or ".sase/" in line for line in lines)


def test_render_attachments_empty_without_manifests() -> None:
    issue = _note_issue("plain", "just prose", ())
    assert render_attachments(issue) == []

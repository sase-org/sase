"""Attachment-store doctor check and explicit open/resolve fetch paths.

Split from ``tests.test_bead.test_attachment_fetch``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_bead._attachment_fetch_helpers import (
    create_plan,
    fetch_remote,  # noqa: F401 (registers the remote fixture)
    fetch_work_dir,  # noqa: F401 (registers the work_dir fixture)
    note_with_file,
    plant_hidden_clone,
    run_cli,
    use_home,
)

__all__ = [
    "test_doctor_check_registered",
    "test_doctor_ok_warn_and_skip",
    "test_materialize_attachment_view_fetches_on_second_home",
    "test_open_fetches_from_shared_store_on_second_home",
    "test_open_without_store_fails_with_badge_error",
]


def _doctor_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home_name: str):
    from pathlib import Path as _Path

    from sase.doctor.runner import DoctorContext

    home = tmp_path / home_name
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SASE_HOME", str(home))
    return (
        DoctorContext(
            cwd=_Path.cwd(),
            project="test-project",
            sase_home=home,
            verbose=False,
            env={},
        ),
        home,
    )


def test_doctor_ok_warn_and_skip(
    project_dir: Path,
    tmp_path: Path,
    remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    work_dir: Path,
) -> None:
    from sase.bead.attachments.outbox import OutboxEntry, enqueue_outbox
    from sase.doctor.checks_attachment_store import _check_attachment_store

    context, home = _doctor_context(tmp_path, monkeypatch, "sase-home-doc")
    check = _check_attachment_store(context)
    assert check.status == "SKIP"
    assert check.id == "project.attachment_store"

    plant_hidden_clone(home, remote)
    issue_id = create_plan(project_dir)
    note_with_file(project_dir, work_dir, issue_id, "doc.bin", b"doctor bytes")
    check = _check_attachment_store(context)
    assert check.status == "OK", check.summary

    enqueue_outbox(
        "test-project",
        [OutboxEntry(digest="a" * 64, size_bytes=3, origin="laptop")],
    )
    check = _check_attachment_store(context)
    assert check.status == "WARN"
    assert "1 queued" in check.summary

    from sase.bead.attachments.outbox import _outbox_path

    _outbox_path("test-project").write_text("{malformed", encoding="utf-8")
    check = _check_attachment_store(context)
    assert check.status == "WARN"
    assert "unreadable" in check.summary or "malformed" in check.details[0]


def test_doctor_check_registered() -> None:
    from pathlib import Path

    from sase.doctor.runner import DoctorContext, build_doctor_registry

    context = DoctorContext(
        cwd=Path.cwd(), project=None, sase_home=Path.home() / ".sase", env={}
    )
    ids = [spec.id for spec in build_doctor_registry(context).list_checks()]
    assert "project.attachment_store" in ids
    registry = build_doctor_registry(context)
    for spec in registry.list_checks(include_deep=True):
        if spec.id == "project.attachment_store":
            assert spec.aliases == ("attachments.store",)


def test_open_fetches_from_shared_store_on_second_home(
    project_dir: Path,
    work_dir: Path,
    remote: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit `attachment open` fetches on a second home like `path` does."""
    import sase.ace.tui.graphics as _graphics

    home_a = tmp_path / "sase-home-a"
    plant_hidden_clone(home_a, remote)
    data = b"open me bytes" + bytes(range(64))
    issue_id = create_plan(project_dir)
    sha = note_with_file(project_dir, work_dir, issue_id, "open_me.bin", data)

    use_home(monkeypatch, tmp_path, "sase-home-b")
    plant_hidden_clone(tmp_path / "sase-home-b", remote)

    from sase.bead.attachments.store import LocalAttachmentStore

    assert not LocalAttachmentStore().has(sha)

    seen: list[tuple[object, ...]] = []

    class _Ok:
        ok = True
        warnings: tuple[object, ...] = ()

    monkeypatch.setattr(
        _graphics,
        "view_artifact_files",
        lambda specs: seen.append(tuple(specs)) or _Ok(),
    )

    out, err, code = run_cli(["attachment", "open", issue_id, "open_me.bin"])
    assert code == 0, err
    assert seen, "open should reach the viewer"
    view_path = Path(str(seen[-1][0].path))
    assert view_path.name == "open_me.bin"
    assert view_path.read_bytes() == data
    assert LocalAttachmentStore().verify(sha)


def test_materialize_attachment_view_fetches_on_second_home(
    project_dir: Path,
    work_dir: Path,
    remote: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`attachment:` resolution fetches from the shared store when needed."""
    from sase.bead.attachment_resolve import materialize_attachment_view

    home_a = tmp_path / "sase-home-a"
    plant_hidden_clone(home_a, remote)
    data = b"resolve me bytes" + bytes(range(64))
    issue_id = create_plan(project_dir)
    sha = note_with_file(project_dir, work_dir, issue_id, "resolve_me.bin", data)

    use_home(monkeypatch, tmp_path, "sase-home-b")
    plant_hidden_clone(tmp_path / "sase-home-b", remote)

    from sase.bead.attachments.store import LocalAttachmentStore

    assert not LocalAttachmentStore().has(sha)
    view = materialize_attachment_view(issue_id, "resolve_me.bin")
    assert view.name == "resolve_me.bin"
    assert view.read_bytes() == data
    assert LocalAttachmentStore().verify(sha)


def test_open_without_store_fails_with_badge_error(
    project_dir: Path,
    work_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreachable store still fails open with the badge-bearing error."""
    data = b"local only bytes"
    issue_id = create_plan(project_dir)
    note_with_file(project_dir, work_dir, issue_id, "lonely.bin", data)

    use_home(monkeypatch, tmp_path, "sase-home-bare")
    out, err, code = run_cli(["attachment", "open", issue_id, "lonely.bin"])
    assert code != 0
    assert "not available" in err
    assert "sha256:" in err

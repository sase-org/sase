"""Attachment-fetch two-home acceptance tests.

Split from ``tests.test_bead.test_attachment_fetch``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from sase.bead.project import BeadProject
from tests.test_bead._attachment_fetch_helpers import (
    GIT_TIMEOUT,
    create_plan,
    fetch_remote,  # noqa: F401 (registers the remote fixture)
    fetch_work_dir,  # noqa: F401 (registers the work_dir fixture)
    note_with_file,
    plant_hidden_clone,
    read_full,
    run_cli,
    run_git,
    use_home,
)

__all__ = [
    "test_concurrent_attaches_converge",
    "test_corrupt_remote_blob_reports_corrupt",
    "test_large_file_not_downloaded_until_explicit",
    "test_read_fetches_small_file_cached",
]

_COMMIT_ENV = {
    "GIT_AUTHOR_NAME": "Tests",
    "GIT_AUTHOR_EMAIL": "tests@example.test",
    "GIT_COMMITTER_NAME": "Tests",
    "GIT_COMMITTER_EMAIL": "tests@example.test",
}


def test_read_fetches_small_file_cached(
    project_dir: Path,
    work_dir: Path,
    remote: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_a = tmp_path / "sase-home-a"
    plant_hidden_clone(home_a, remote)
    data = b"shared pixels" + bytes(range(256))
    issue_id = create_plan(project_dir)
    sha = note_with_file(project_dir, work_dir, issue_id, "small.bin", data)

    use_home(monkeypatch, tmp_path, "sase-home-b")
    plant_hidden_clone(tmp_path / "sase-home-b", remote)
    out, err, code = read_full(issue_id)
    assert code == 0, err
    assert "small.bin" in out
    assert "digest mismatch" not in out
    assert "not downloaded" not in out

    from sase.bead.attachment_presentation import attachment_view_path

    view = attachment_view_path(sha, "small.bin")
    assert view is not None
    assert Path(view).read_bytes() == data
    assert Path(view).name == "small.bin"

    out, err, code = run_cli(
        ["read", issue_id, "--format", "json", "--no-links", "-r", "Need fields"]
    )
    assert code == 0, err
    import json as _json

    attachments = _json.loads(out)["issue"]["notes"][0]["attachments"]
    assert attachments[0]["availability"] == "cached"
    assert attachments[0]["local_path"].endswith("small.bin")


def test_large_file_not_downloaded_until_explicit(
    project_dir: Path,
    work_dir: Path,
    remote: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.bead.config as bead_config

    monkeypatch.setattr(bead_config, "get_attachment_auto_fetch_max_bytes", lambda: 16)
    home_a = tmp_path / "sase-home-a"
    plant_hidden_clone(home_a, remote)
    data = os.urandom(4096)
    issue_id = create_plan(project_dir)
    sha = note_with_file(project_dir, work_dir, issue_id, "big.bin", data)

    use_home(monkeypatch, tmp_path, "sase-home-b")
    plant_hidden_clone(tmp_path / "sase-home-b", remote)
    out, err, code = read_full(issue_id)
    assert code == 0, err
    assert "not downloaded" in out
    assert f"sase bead attachment path {issue_id} big.bin" in out

    from sase.bead.attachments.store import LocalAttachmentStore

    assert not LocalAttachmentStore().has(sha)

    out, err, code = run_cli(
        ["attachment", "list", issue_id],
    )
    assert code == 0, err
    assert "not downloaded" in out
    assert not LocalAttachmentStore().has(sha)

    out, err, code = read_full(issue_id, "-d")
    assert code == 0, err
    assert "not downloaded" not in out
    assert LocalAttachmentStore().verify(sha)

    assert LocalAttachmentStore().remove(sha) is True
    out, err, code = run_cli(["attachment", "path", issue_id, "big.bin"])
    assert code == 0, err
    assert out.strip().endswith("big.bin")
    assert Path(out.strip()).read_bytes() == data


def test_concurrent_attaches_converge(
    project_dir: Path,
    work_dir: Path,
    remote: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_a = tmp_path / "sase-home-a"
    plant_hidden_clone(home_a, remote)
    issue_id = create_plan(project_dir)
    data_a = b"bytes from home A"
    note_with_file(project_dir, work_dir, issue_id, "from_a.txt", data_a)

    use_home(monkeypatch, tmp_path, "sase-home-b")
    plant_hidden_clone(tmp_path / "sase-home-b", remote)
    data_b = b"bytes from home B"
    note_with_file(project_dir, work_dir, issue_id, "from_b.txt", data_b)

    out, err, code = read_full(issue_id)
    assert code == 0, err
    assert "not downloaded" not in out
    assert "unavailable offline" not in out

    from sase.bead.attachment_presentation import attachment_view_path

    with BeadProject(project_dir) as project:
        issue = project.show(issue_id)
    names = {attachment.name for note in issue.notes for attachment in note.attachments}
    assert {"from_a.txt", "from_b.txt"} <= names
    for note in issue.notes:
        for attachment in note.attachments:
            view = attachment_view_path(attachment.sha256, attachment.name)
            assert view is not None, attachment.name
    assert (
        Path(
            attachment_view_path(hashlib.sha256(data_a).hexdigest(), "from_a.txt")  # type: ignore[arg-type]
        ).read_bytes()
        == data_a
    )
    assert (
        Path(
            attachment_view_path(hashlib.sha256(data_b).hexdigest(), "from_b.txt")  # type: ignore[arg-type]
        ).read_bytes()
        == data_b
    )

    monkeypatch.setenv("SASE_HOME", str(home_a))
    out, err, code = read_full(issue_id)
    assert code == 0, err
    assert "not downloaded" not in out
    assert "unavailable offline" not in out


def _tamper_remote_object(clone: Path, claimed_sha: str, tampered: bytes) -> None:
    import sase_core_rs

    relpath = sase_core_rs.artifact_object_relpath(claimed_sha)
    proc = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=clone,
        input=tampered,
        capture_output=True,
        timeout=GIT_TIMEOUT,
    )
    assert proc.returncode == 0, proc.stderr
    blob_id = proc.stdout.decode().strip()
    index = clone / "tamper-index"
    env = {**os.environ, **_COMMIT_ENV, "GIT_INDEX_FILE": str(index)}

    def plumbing(*args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=clone,
            check=True,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            env=env,
        ).stdout.strip()

    tip = plumbing("rev-parse", "refs/heads/main")
    plumbing("read-tree", tip)
    plumbing("update-index", "--cacheinfo", f"100644,{blob_id},{relpath}")
    tree = plumbing("write-tree")
    commit = plumbing("commit-tree", tree, "-p", tip, "-m", "tamper")
    plumbing("update-ref", "refs/heads/main", commit)
    run_git(clone, "push", "origin", "refs/heads/main:refs/heads/main")


def test_corrupt_remote_blob_reports_corrupt(
    project_dir: Path,
    work_dir: Path,
    remote: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_a = tmp_path / "sase-home-a"
    clone_a = plant_hidden_clone(home_a, remote)
    data = b"real bytes for corrupt test"
    issue_id = create_plan(project_dir)
    sha = note_with_file(project_dir, work_dir, issue_id, "victim.bin", data)
    _tamper_remote_object(clone_a, sha, b"tampered bytes")

    use_home(monkeypatch, tmp_path, "sase-home-b")
    plant_hidden_clone(tmp_path / "sase-home-b", remote)
    out, err, code = read_full(issue_id)
    assert code == 0, err
    assert "digest mismatch" in out

    from sase.bead.attachments.store import LocalAttachmentStore

    assert not LocalAttachmentStore().has(sha)

"""Phase fetch: lazy fetch, availability badges, and doctor (phase fetch).

Two temp ``SASE_HOME`` directories share one local bare remote through two
bare partial clones. Never the real project bead store or the real
``~/.sase`` attachment CAS. No network and no GitHub.
"""

from __future__ import annotations

import hashlib
import io
import os
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.attachments.blob_store import BlobStoreError
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.main.parser import create_parser

_HANDLERS = {
    "note": bead_cli.handle_bead_note,
    "attach": bead_cli.handle_bead_attach,
    "attachment": bead_cli.handle_bead_attachment,
    "show": bead_cli.handle_bead_show,
    "read": bead_cli.handle_bead_read,
}

_GIT_TIMEOUT = 60.0

_COMMIT_ENV = {
    "GIT_AUTHOR_NAME": "Tests",
    "GIT_AUTHOR_EMAIL": "tests@example.test",
    "GIT_COMMITTER_NAME": "Tests",
    "GIT_COMMITTER_EMAIL": "tests@example.test",
}


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
    )


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


@pytest.fixture()
def work_dir(
    project_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Isolate the CAS home and resolve ``@./`` refs inside the project."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home-a"))
    monkeypatch.chdir(project_dir)
    return project_dir


@pytest.fixture()
def remote(tmp_path: Path) -> Path:
    path = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", "-b", "main", path.name)
    _git(path, "config", "uploadpack.allowFilter", "true")
    _git(path, "config", "uploadpack.allowAnySHA1InWant", "true")
    return path


def _plant_hidden_clone(home: Path, remote: Path) -> Path:
    """Clone the shared remote into one home's hidden attachments-private slot."""
    from sase.core.paths import sase_projects_dir

    clone = sase_projects_dir() / "test-project" / "repos" / "attachments-private"
    clone.parent.mkdir(parents=True, exist_ok=True)
    if clone.exists():
        return clone
    _git(
        home,
        "clone",
        "--bare",
        "--filter=blob:none",
        f"file://{remote}",
        str(clone),
    )
    return clone


def _use_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str) -> Path:
    home = tmp_path / name
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SASE_HOME", str(home))
    return home


def _create_plan(project_dir: Path) -> str:
    with BeadProject(project_dir) as project:
        issue = project.create("Fetch target", IssueType.PLAN)
    return issue.id


def _note_with_file(
    project_dir: Path, work_dir: Path, issue_id: str, filename: str, data: bytes
) -> str:
    (work_dir / filename).write_bytes(data)
    out, err, code = _run(["note", issue_id, f"see @./{filename}"])
    assert code == 0, err
    with BeadProject(project_dir) as project:
        note = project.show(issue_id).notes[-1]
    assert note.attachments
    return note.attachments[-1].sha256


def _read_full(issue_id: str, *extra: str) -> tuple[str, str, int]:
    return _run(
        [
            "read",
            issue_id,
            "--no-links",
            "--pager",
            "never",
            "--color",
            "never",
            "-r",
            "Need the attachment",
            *extra,
        ]
    )


def test_read_without_attachments_skips_store_discovery(
    project_dir: Path,
    work_dir: Path,
    remote: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Show/read of a bead with no attachments does no store discovery."""
    import sase.bead.attachments.git_store as git_store_mod
    import sase.bead.attachments.upload as upload_mod

    home_a = tmp_path / "sase-home-a"
    _plant_hidden_clone(home_a, remote)
    issue_id = _create_plan(project_dir)

    calls = {"clone_has_remote": 0, "GitAttachmentStore": 0}
    orig_has_remote = upload_mod.clone_has_remote
    orig_store = git_store_mod.GitAttachmentStore

    def _spy_has_remote(clone: Path) -> bool:
        calls["clone_has_remote"] += 1
        return bool(orig_has_remote(clone))

    def _spy_store(*args: object, **kwargs: object) -> object:
        calls["GitAttachmentStore"] += 1
        return orig_store(*args, **kwargs)  # type: ignore[operator]

    monkeypatch.setattr(upload_mod, "clone_has_remote", _spy_has_remote)
    monkeypatch.setattr(git_store_mod, "GitAttachmentStore", _spy_store)

    out, err, code = _read_full(issue_id)
    assert code == 0, err
    assert calls == {"clone_has_remote": 0, "GitAttachmentStore": 0}, calls


# -- config ------------------------------------------------------------


def test_auto_fetch_config_default_and_fail_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.bead.config as bead_config

    monkeypatch.setattr(bead_config, "load_merged_config", lambda: {}, raising=False)
    assert (
        bead_config.get_attachment_auto_fetch_max_bytes()
        == bead_config.DEFAULT_ATTACHMENT_AUTO_FETCH_MAX_BYTES
        == 26214400
    )
    for bad in (
        {"bead": {"attachments": {"auto_fetch_max_bytes": "big"}}},
        {"bead": {"attachments": {"auto_fetch_max_bytes": True}}},
        {"bead": {"attachments": {"auto_fetch_max_bytes": 0}}},
        {"bead": {"attachments": {"auto_fetch_max_bytes": -3}}},
        {"bead": {"attachments": "nope"}},
        {"bead": "nope"},
    ):
        monkeypatch.setattr(
            bead_config, "load_merged_config", lambda bad=bad: bad, raising=False
        )
        assert (
            bead_config.get_attachment_auto_fetch_max_bytes()
            == bead_config.DEFAULT_ATTACHMENT_AUTO_FETCH_MAX_BYTES
        )
    monkeypatch.setattr(
        bead_config,
        "load_merged_config",
        lambda: {"bead": {"attachments": {"auto_fetch_max_bytes": 123}}},
        raising=False,
    )
    assert bead_config.get_attachment_auto_fetch_max_bytes() == 123


# -- badges ------------------------------------------------------------


def test_badge_table() -> None:
    from sase.bead.attachments.fetch import attachment_badge

    assert attachment_badge("cached") is None
    assert attachment_badge("remote") is None
    assert (
        attachment_badge(
            "not_downloaded", size_bytes=2048, bead_id="sase-1", name="a.bin"
        )
        == "⇣ not downloaded · 2 KiB — sase bead attachment path sase-1 a.bin"
    )
    assert (
        attachment_badge("pending_upload", origin="laptop")
        == "⇡ pending upload (laptop)"
    )
    assert attachment_badge("local_only", origin="laptop") == "⚠ only on laptop"
    assert attachment_badge("unavailable") == "✕ unavailable offline"
    assert attachment_badge("purged") == "(purged)"
    assert attachment_badge("corrupt") == "‼ digest mismatch"


# -- state machine with a fake store ------------------------------------


class _FakeStore:
    """Duck-typed stand-in for ``GitAttachmentStore`` (no subprocess)."""

    def __init__(
        self,
        objects: dict[str, bytes] | None = None,
        tombstones: set[str] | None = None,
    ) -> None:
        self.objects = dict(objects or {})
        self.tombstones = set(tombstones or {})

    def has(self, sha256: str) -> bool:
        return sha256 in self.objects

    def has_tombstone(self, sha256: str) -> bool:
        return sha256 in self.tombstones

    def get(self, sha256: str, dest: object, progress: object = None) -> None:
        from sase.bead.attachments.store import LocalAttachmentStore

        if sha256 not in self.objects:
            raise BlobStoreError(f"attachment {sha256[:16]}… is not in fake store")
        data = self.objects[sha256]
        if hashlib.sha256(data).hexdigest() != sha256:
            raise BlobStoreError(
                f"attachment {sha256[:16]}… failed digest verification",
                transient=False,
            )
        cas = LocalAttachmentStore(root=Path(str(dest)))
        cas.ensure_dirs()
        target = cas.object_path(sha256)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        os.chmod(target, 0o444)


def _cas_with(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, objects: dict[str, bytes]
) -> None:
    from sase.bead.attachments.store import LocalAttachmentStore

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    cas = LocalAttachmentStore()
    cas.ensure_dirs()
    for sha, data in objects.items():
        target = cas.object_path(sha)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        os.chmod(target, 0o444)


def test_state_machine_without_store_stays_two_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.attachments.fetch import FetchContext, attachment_state

    data = b"local only bytes"
    sha = hashlib.sha256(data).hexdigest()
    _cas_with(tmp_path, monkeypatch, {sha: data})
    context = FetchContext(mode="auto")
    assert attachment_state("0" * 64, context=context) == "unavailable"
    assert attachment_state(sha, context=context) == "cached"
    assert attachment_state(sha, size_bytes=len(data), context=context) == "cached"


def test_state_machine_with_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.attachments.fetch import FetchContext, attachment_state
    from sase.bead.attachments.outbox import OutboxEntry

    remote_data = b"remote bytes here"
    remote_sha = hashlib.sha256(remote_data).hexdigest()
    local_data = b"mine, never pushed"
    local_sha = hashlib.sha256(local_data).hexdigest()
    queued_data = b"queued for upload"
    queued_sha = hashlib.sha256(queued_data).hexdigest()
    bad_data = b"tampered locally"
    bad_sha = hashlib.sha256(b"original bytes").hexdigest()
    gone_sha = hashlib.sha256(b"purged object").hexdigest()
    _cas_with(
        tmp_path,
        monkeypatch,
        {local_sha: local_data, queued_sha: queued_data, bad_sha: bad_data},
    )
    from sase.bead.attachments.store import LocalAttachmentStore

    tombstones = LocalAttachmentStore().tombstones_dir
    tombstones.mkdir(parents=True, exist_ok=True)
    (tombstones / gone_sha).write_text("{}", encoding="utf-8")

    store = _FakeStore(objects={remote_sha: remote_data, local_sha: local_data})
    context = FetchContext(
        mode="never",
        store=store,
        outbox={
            queued_sha: OutboxEntry(
                digest=queued_sha, size_bytes=len(queued_data), origin="laptop"
            )
        },
        cap_bytes=8,
    )
    assert attachment_state(remote_sha, size_bytes=1024, context=context) == (
        "not_downloaded"
    )
    assert attachment_state(local_sha, size_bytes=len(local_data), context=context) == (
        "cached"
    )
    assert attachment_state(queued_sha, size_bytes=1, context=context) == (
        "pending_upload"
    )
    assert attachment_state("1" * 64, context=context) == "unavailable"
    assert attachment_state(bad_sha, size_bytes=1, context=context) == "corrupt"
    assert attachment_state(gone_sha, size_bytes=1, context=context) == "purged"
    for state in (
        attachment_state(remote_sha, size_bytes=1024, context=context),
        attachment_state("1" * 64, context=context),
    ):
        assert state != "remote"

    lone_data = b"only here"
    lone_sha = hashlib.sha256(lone_data).hexdigest()
    _cas_with(tmp_path, monkeypatch, {lone_sha: lone_data})
    lonely = FetchContext(mode="never", store=_FakeStore(), cap_bytes=8)
    assert attachment_state(lone_sha, size_bytes=1, context=lonely) == "local_only"


def test_state_machine_remote_tombstone_is_purged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.attachments.fetch import FetchContext, attachment_state

    sha = hashlib.sha256(b"purged upstream").hexdigest()
    _cas_with(tmp_path, monkeypatch, {})
    context = FetchContext(
        mode="force", store=_FakeStore(tombstones={sha}), cap_bytes=8
    )
    assert attachment_state(sha, size_bytes=1, context=context) == "purged"


def test_fetch_mode_auto_installs_under_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.attachments.fetch import FetchContext, attachment_state
    from sase.bead.attachments.store import LocalAttachmentStore

    data = b"small remote file"
    sha = hashlib.sha256(data).hexdigest()
    _cas_with(tmp_path, monkeypatch, {})
    context = FetchContext(
        mode="auto", store=_FakeStore(objects={sha: data}), cap_bytes=1 << 20
    )
    assert attachment_state(sha, size_bytes=len(data), context=context) == "cached"
    assert LocalAttachmentStore().verify(sha)


def test_fetch_mismatch_is_corrupt_and_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.attachments.fetch import FetchContext, attachment_state
    from sase.bead.attachments.store import LocalAttachmentStore

    claimed = hashlib.sha256(b"real bytes").hexdigest()
    _cas_with(tmp_path, monkeypatch, {})
    context = FetchContext(
        mode="force",
        store=_FakeStore(objects={claimed: b"tampered bytes"}),
        cap_bytes=1,
    )
    assert attachment_state(claimed, size_bytes=11, context=context) == "corrupt"
    assert not LocalAttachmentStore().has(claimed)


# -- two-home acceptance -------------------------------------------------


def test_read_fetches_small_file_cached(
    project_dir: Path,
    work_dir: Path,
    remote: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_a = tmp_path / "sase-home-a"
    _plant_hidden_clone(home_a, remote)
    data = b"shared pixels" + bytes(range(256))
    issue_id = _create_plan(project_dir)
    sha = _note_with_file(project_dir, work_dir, issue_id, "small.bin", data)

    _use_home(monkeypatch, tmp_path, "sase-home-b")
    _plant_hidden_clone(tmp_path / "sase-home-b", remote)
    out, err, code = _read_full(issue_id)
    assert code == 0, err
    assert "small.bin" in out
    assert "digest mismatch" not in out
    assert "not downloaded" not in out

    from sase.bead.attachment_presentation import attachment_view_path

    view = attachment_view_path(sha, "small.bin")
    assert view is not None
    assert Path(view).read_bytes() == data
    assert Path(view).name == "small.bin"

    out, err, code = _run(
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
    _plant_hidden_clone(home_a, remote)
    data = os.urandom(4096)
    issue_id = _create_plan(project_dir)
    sha = _note_with_file(project_dir, work_dir, issue_id, "big.bin", data)

    _use_home(monkeypatch, tmp_path, "sase-home-b")
    _plant_hidden_clone(tmp_path / "sase-home-b", remote)
    out, err, code = _read_full(issue_id)
    assert code == 0, err
    assert "not downloaded" in out
    assert f"sase bead attachment path {issue_id} big.bin" in out

    from sase.bead.attachments.store import LocalAttachmentStore

    assert not LocalAttachmentStore().has(sha)

    out, err, code = _run(
        ["attachment", "list", issue_id],
    )
    assert code == 0, err
    assert "not downloaded" in out
    assert not LocalAttachmentStore().has(sha)

    out, err, code = _read_full(issue_id, "-d")
    assert code == 0, err
    assert "not downloaded" not in out
    assert LocalAttachmentStore().verify(sha)

    assert LocalAttachmentStore().remove(sha) is True
    out, err, code = _run(["attachment", "path", issue_id, "big.bin"])
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
    _plant_hidden_clone(home_a, remote)
    issue_id = _create_plan(project_dir)
    data_a = b"bytes from home A"
    _note_with_file(project_dir, work_dir, issue_id, "from_a.txt", data_a)

    _use_home(monkeypatch, tmp_path, "sase-home-b")
    _plant_hidden_clone(tmp_path / "sase-home-b", remote)
    data_b = b"bytes from home B"
    _note_with_file(project_dir, work_dir, issue_id, "from_b.txt", data_b)

    out, err, code = _read_full(issue_id)
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
    out, err, code = _read_full(issue_id)
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
        timeout=_GIT_TIMEOUT,
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
            timeout=_GIT_TIMEOUT,
            env=env,
        ).stdout.strip()

    tip = plumbing("rev-parse", "refs/heads/main")
    plumbing("read-tree", tip)
    plumbing("update-index", "--cacheinfo", f"100644,{blob_id},{relpath}")
    tree = plumbing("write-tree")
    commit = plumbing("commit-tree", tree, "-p", tip, "-m", "tamper")
    plumbing("update-ref", "refs/heads/main", commit)
    _git(clone, "push", "origin", "refs/heads/main:refs/heads/main")


def test_corrupt_remote_blob_reports_corrupt(
    project_dir: Path,
    work_dir: Path,
    remote: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_a = tmp_path / "sase-home-a"
    clone_a = _plant_hidden_clone(home_a, remote)
    data = b"real bytes for corrupt test"
    issue_id = _create_plan(project_dir)
    sha = _note_with_file(project_dir, work_dir, issue_id, "victim.bin", data)
    _tamper_remote_object(clone_a, sha, b"tampered bytes")

    _use_home(monkeypatch, tmp_path, "sase-home-b")
    _plant_hidden_clone(tmp_path / "sase-home-b", remote)
    out, err, code = _read_full(issue_id)
    assert code == 0, err
    assert "digest mismatch" in out

    from sase.bead.attachments.store import LocalAttachmentStore

    assert not LocalAttachmentStore().has(sha)


# -- doctor --------------------------------------------------------------


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

    _plant_hidden_clone(home, remote)
    issue_id = _create_plan(project_dir)
    _note_with_file(project_dir, work_dir, issue_id, "doc.bin", b"doctor bytes")
    check = _check_attachment_store(context)
    assert check.status == "OK", check.summary

    enqueue_outbox(
        "test-project",
        [OutboxEntry(digest="a" * 64, size_bytes=3, origin="laptop")],
    )
    check = _check_attachment_store(context)
    assert check.status == "WARN"
    assert "1 queued" in check.summary

    from sase.bead.attachments.outbox import outbox_path

    outbox_path("test-project").write_text("{malformed", encoding="utf-8")
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

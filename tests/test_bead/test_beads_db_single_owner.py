"""Single-owner regression: Python never opens ``beads.db`` via SQLite.

Covers a new store, a legacy JSONL-only store, and a legacy store with a real
preexisting WAL mirror, each prepared in a separate completed subprocess where
applicable. Reopens across Rust mutations, asserts canonical data, preserves
the preexisting mirror inode and bytes, exercises real ``sync()`` in a
disposable git repository, and uses coordinated subprocess writers behind a
ready/go barrier to prove real mutations keep unique child IDs, retained
updates, and lock exclusion. A stalled worker dumps its stacks to its stderr
file before the parent's hang-detector bound. Never mocks Rust mutations;
stdlib SQLite opens of ``beads.db`` fail deterministically.
"""

from __future__ import annotations

import json
import os
import selectors
import sqlite3
import subprocess
import sys
import time
import unittest.mock as _mock
from pathlib import Path

import pytest

from sase.bead.model import IssueType
from sase.bead.project import BeadProject

_PROCESS_TIMEOUT_SECONDS = 120.0
_WORKER_STALL_DUMP_SECONDS = 90.0

REPO_ROOT = Path(__file__).resolve().parents[2]

_WORKER_SCRIPT = "\n".join(
    [
        "import faulthandler, sys",
        "faulthandler.dump_traceback_later(float(sys.argv[4]), exit=True)",
        "import json",
        "import traceback",
        "from pathlib import Path",
        "from sase.bead.model import IssueType",
        "from sase.bead.project import BeadProject",
        "def main():",
        "    try:",
        "        with BeadProject(Path(sys.argv[1])) as project:",
        "            sys.stdout.write(f'READY {sys.argv[3]}\\n')",
        "            sys.stdout.flush()",
        "            for line in sys.stdin:",
        "                if line.strip() == 'GO':",
        "                    break",
        "            else:",
        "                raise RuntimeError('stdin closed before GO')",
        "            child = project.create(",
        "                f'Concurrent child {sys.argv[3]}',",
        "                IssueType.PHASE,",
        "                parent_id=sys.argv[2],",
        "            )",
        "            project.update(child.id, description=f'worker {sys.argv[3]}')",
        "            sys.stdout.write(",
        "                json.dumps(",
        "                    {'worker': int(sys.argv[3]), 'child_id': child.id}",
        "                ) + '\\n'",
        "            )",
        "            sys.stdout.flush()",
        "            faulthandler.cancel_dump_traceback_later()",
        "    except BaseException:",
        "        traceback.print_exc()",
        "        sys.exit(1)",
        "main()",
    ]
)


def _guarded_sqlite_connect(
    opened: list[str],
    real_connect: object,
) -> object:
    def _guard(*args: object, **kwargs: object) -> object:
        target = str(args[0]) if args else str(kwargs.get("database", ""))
        if target.endswith("beads.db"):
            opened.append(target)
            raise AssertionError(f"Python must not open {target} via stdlib sqlite3")
        return real_connect(*args, **kwargs)  # type: ignore[arg-type]

    return _guard


def _prepare_legacy_store_in_subprocess(store_parent: Path) -> None:
    """Write a legacy JSONL store in a separate completed subprocess."""
    script = (
        "import json; from pathlib import Path; "
        f"base = Path({str(store_parent)!r}) / 'beads'; "
        "base.mkdir(parents=True, exist_ok=True); "
        "(base / 'config.json').write_text(json.dumps("
        "{'issue_prefix': 'legacy', 'next_counter': 3, 'owner': ''})); "
        "(base / 'issues.jsonl').write_text("
        "json.dumps({'id': 'legacy-1', 'title': 'Legacy epic', 'status': 'open', "
        "'issue_type': 'plan', 'tier': 'epic', "
        "'created_at': '2026-01-01T00:00:00Z', "
        "'updated_at': '2026-01-01T00:00:00Z', 'dependencies': []}) + '\\n' + "
        "json.dumps({'id': 'legacy-1.1', 'title': 'Legacy child', 'status': 'open', "
        "'issue_type': 'phase', 'parent_id': 'legacy-1', "
        "'created_at': '2026-01-01T00:00:00Z', "
        "'updated_at': '2026-01-01T00:00:00Z', 'dependencies': []}) + '\\n'); "
    )
    subprocess.run([sys.executable, "-c", script], check=True, timeout=60)


def _prepare_existing_mirror_in_subprocess(store_parent: Path) -> None:
    """Write a real WAL ``beads.db`` plus matching JSONL in a subprocess.

    Uses the existing test-only legacy helpers so the mirror is a genuine
    WAL-mode SQLite file. The connection is explicitly closed and the
    subprocess is waited on before any Rust operation runs in the parent.
    """
    script = (
        "import json, sys; "
        f"sys.path.insert(0, {str(REPO_ROOT)!r}); "
        "from pathlib import Path; "
        "from tests.test_bead.legacy_sqlite import db as db_mod; "
        "from tests.test_bead.legacy_sqlite.jsonl import export_to_jsonl; "
        "from sase.bead.model import BeadTier, Issue, IssueType, Status; "
        f"base = Path({str(store_parent)!r}) / 'beads'; "
        "base.mkdir(parents=True, exist_ok=True); "
        "(base / 'config.json').write_text(json.dumps("
        "{'issue_prefix': 'legacy', 'next_counter': 3, 'owner': ''})); "
        "db_path = base / 'beads.db'; "
        "conn = db_mod.init_db(db_path); "
        "epic = Issue(id='legacy-1', title='Legacy epic', status=Status.OPEN, "
        "issue_type=IssueType.PLAN, tier=BeadTier.EPIC, "
        "created_at='2026-01-01T00:00:00Z', updated_at='2026-01-01T00:00:00Z'); "
        "child = Issue(id='legacy-1.1', title='Legacy child', status=Status.OPEN, "
        "issue_type=IssueType.PHASE, parent_id='legacy-1', "
        "created_at='2026-01-01T00:00:00Z', updated_at='2026-01-01T00:00:00Z'); "
        "db_mod.create_issue(conn, epic); "
        "db_mod.create_issue(conn, child); "
        "export_to_jsonl(conn, base / 'issues.jsonl'); "
        "conn.commit(); conn.close(); "
    )
    subprocess.run(
        [sys.executable, "-c", script], check=True, timeout=60, cwd=REPO_ROOT
    )


def _init_disposable_git_repo(root: Path, beads_rel: str) -> None:
    """Init a disposable git repo with the production ``beads.db*`` ignore."""
    subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    (root / ".gitignore").write_text(f"{beads_rel}/beads.db*\n", encoding="utf-8")


def _assert_sync_excludes_beads_db(repo_root: Path) -> None:
    """Assert a real ``sync()`` never stages ``beads.db`` or its sidecars."""
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert not any("beads.db" in name for name in staged), staged


def _read_stderr_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"<unreadable stderr file {path}: {exc}>"


def _format_worker_diagnostics(
    workers: int,
    returncodes: dict[int, int | None],
    stdout_text: dict[int, str],
    stderr_paths: dict[int, Path],
) -> str:
    lines = []
    for idx in range(workers):
        lines.append(f"worker {idx}: returncode={returncodes.get(idx)!r}")
        lines.append(f"worker {idx} stdout: {stdout_text.get(idx, '')!r}")
        lines.append(f"worker {idx} stderr file: {stderr_paths[idx]}")
        lines.append(_read_stderr_file(stderr_paths[idx]))
    return "\n".join(lines)


def test_new_store_never_opens_beads_db(tmp_path: Path) -> None:
    _init_disposable_git_repo(tmp_path, "sdd/beads")
    opened: list[str] = []
    real_connect = sqlite3.connect
    with _mock.patch(
        "sqlite3.connect",
        side_effect=_guarded_sqlite_connect(opened, real_connect),
    ):
        with BeadProject.init(tmp_path) as project:
            epic = project.create("Epic", IssueType.PLAN)
            child = project.create("Child", IssueType.PHASE, parent_id=epic.id)
            project.add_dependency(child.id, epic.id)
            assert project.show(epic.id).id == epic.id
            assert [i.id for i in project.list_issues()] == [epic.id, child.id]
            project._export()
            assert "Epic" in (project.beads_dir / "issues.jsonl").read_text()
            project.sync()
            _assert_sync_excludes_beads_db(tmp_path)

        with BeadProject(tmp_path) as reopened:
            assert reopened.show(child.id).dependencies[0].depends_on_id == epic.id
            second = reopened.create("Second", IssueType.PHASE, parent_id=epic.id)
            assert second.id == f"{epic.id}.2"
            reopened._export()
            reopened.sync()
            _assert_sync_excludes_beads_db(tmp_path)

        with BeadProject(tmp_path) as final:
            assert sorted(i.id for i in final.list_issues()) == sorted(
                [epic.id, child.id, second.id]
            )
        assert opened == []


def test_legacy_store_adoption_never_opens_beads_db(tmp_path: Path) -> None:
    _prepare_legacy_store_in_subprocess(tmp_path)
    beads_dir = tmp_path / "beads"
    assert (beads_dir / "issues.jsonl").exists()
    assert not (beads_dir / "beads.db").exists()

    opened: list[str] = []
    real_connect = sqlite3.connect
    with _mock.patch(
        "sqlite3.connect",
        side_effect=_guarded_sqlite_connect(opened, real_connect),
    ):
        with BeadProject(tmp_path, beads_dirname="beads") as project:
            assert project.show("legacy-1").title == "Legacy epic"
            assert sorted(i.id for i in project.list_issues()) == [
                "legacy-1",
                "legacy-1.1",
            ]
            project._export()
            assert "legacy-1" in (beads_dir / "issues.jsonl").read_text()

        with BeadProject(tmp_path, beads_dirname="beads") as reopened:
            created = reopened.create("Adopted", IssueType.PLAN)
            assert created.id.startswith("legacy-")
            assert reopened.show("legacy-1.1").title == "Legacy child"

        with BeadProject(tmp_path, beads_dirname="beads") as final:
            assert "legacy-1" in {i.id for i in final.list_issues()}
            assert created.id in {i.id for i in final.list_issues()}
        assert opened == []


def test_existing_mirror_adoption_preserves_inode_and_bytes(
    tmp_path: Path,
) -> None:
    """Adopting a preexisting WAL mirror leaves its bytes and inode alone.

    The mirror is deliberately stale after the Rust mutation; reads must still
    report canonical state. ``-wal``/``-shm`` sentinels below are untouched
    placeholder files testing exclusion/preservation, not a live WAL
    reproduction: a clean SQLite close checkpoints and removes live sidecars.
    """
    _init_disposable_git_repo(tmp_path, "beads")
    _prepare_existing_mirror_in_subprocess(tmp_path)
    beads_dir = tmp_path / "beads"
    beads_db = beads_dir / "beads.db"
    assert beads_db.exists()
    assert (beads_dir / "issues.jsonl").exists()
    assert (beads_dir / "config.json").exists()

    st_before = beads_db.stat()
    bytes_before = beads_db.read_bytes()

    wal_path = beads_dir / "beads.db-wal"
    shm_path = beads_dir / "beads.db-shm"
    sentinels: dict[Path, bytes] = {}
    if wal_path.exists() or shm_path.exists():
        for sidecar in (wal_path, shm_path):
            if sidecar.exists():
                sentinels[sidecar] = sidecar.read_bytes()
    else:
        wal_path.write_bytes(b"sentinel-wal-not-live-wal\n")
        shm_path.write_bytes(b"sentinel-shm-not-live-shm\n")
        for sidecar in (wal_path, shm_path):
            sentinels[sidecar] = sidecar.read_bytes()

    opened: list[str] = []
    real_connect = sqlite3.connect
    with _mock.patch(
        "sqlite3.connect",
        side_effect=_guarded_sqlite_connect(opened, real_connect),
    ):
        with BeadProject(tmp_path, beads_dirname="beads") as project:
            assert project.show("legacy-1").title == "Legacy epic"
            assert sorted(i.id for i in project.list_issues()) == [
                "legacy-1",
                "legacy-1.1",
            ]
            project.update("legacy-1.1", description="adopted mutation")
            child = project.create(
                "Adopted child", IssueType.PHASE, parent_id="legacy-1"
            )
            assert child.id == "legacy-1.2"
            project._export()
            assert "adopted mutation" in (beads_dir / "issues.jsonl").read_text()
            project.sync()
            _assert_sync_excludes_beads_db(tmp_path)

        with BeadProject(tmp_path, beads_dirname="beads") as reopened:
            assert reopened.show("legacy-1.1").description == "adopted mutation"
            assert reopened.show(child.id).title == "Adopted child"
            assert sorted(i.id for i in reopened.list_issues()) == [
                "legacy-1",
                "legacy-1.1",
                child.id,
            ]
            reopened.sync()
            _assert_sync_excludes_beads_db(tmp_path)
        assert opened == []

    st_after = beads_db.stat()
    assert (st_after.st_dev, st_after.st_ino) == (
        st_before.st_dev,
        st_before.st_ino,
    )
    assert beads_db.read_bytes() == bytes_before
    for sidecar, before in sentinels.items():
        assert sidecar.read_bytes() == before


def test_coordinated_writers_keep_unique_child_ids(tmp_path: Path) -> None:
    with BeadProject.init(tmp_path) as project:
        epic = project.create("Epic", IssueType.PLAN)
        epic_id = epic.id

    workers = 4
    stderr_paths = {
        idx: tmp_path / f"worker-{idx}.stderr.log" for idx in range(workers)
    }
    procs: dict[int, subprocess.Popen[bytes]] = {}
    stderr_files: dict[int, object] = {}
    try:
        for idx in range(workers):
            stderr_handle = open(stderr_paths[idx], "wb")
            stderr_files[idx] = stderr_handle
            procs[idx] = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    _WORKER_SCRIPT,
                    str(tmp_path),
                    epic_id,
                    str(idx),
                    str(_WORKER_STALL_DUMP_SECONDS),
                ],
                cwd=REPO_ROOT,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr_handle,
            )
        deadline = time.monotonic() + _PROCESS_TIMEOUT_SECONDS
        buffers: dict[int, bytearray] = {idx: bytearray() for idx in range(workers)}
        ready: set[int] = set()
        eof: set[int] = set()
        selector = selectors.DefaultSelector()
        try:
            for idx, proc in procs.items():
                assert proc.stdout is not None
                selector.register(proc.stdout, selectors.EVENT_READ, data=idx)
            while len(ready) < workers:
                if len(ready) + len(eof) >= workers:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                if not selector.get_map():
                    break
                events = selector.select(timeout=remaining)
                if not events:
                    break
                for key, _mask in events:
                    idx = key.data
                    assert isinstance(idx, int)
                    if idx in ready or idx in eof:
                        continue
                    assert procs[idx].stdout is not None
                    chunk = os.read(procs[idx].stdout.fileno(), 65536)
                    if chunk == b"":
                        selector.unregister(key.fileobj)
                        eof.add(idx)
                        continue
                    buffers[idx].extend(chunk)
                    if b"\n" in buffers[idx]:
                        line, _sep, _rest = bytes(buffers[idx]).partition(b"\n")
                        if line.strip() == f"READY {idx}".encode():
                            ready.add(idx)
                            selector.unregister(key.fileobj)
            if len(ready) < workers:
                returncodes: dict[int, int | None] = {}
                for idx, proc in procs.items():
                    if idx not in ready:
                        try:
                            proc.kill()
                        except OSError:
                            pass
                for idx, proc in procs.items():
                    try:
                        returncodes[idx] = proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        returncodes[idx] = proc.poll()
                stdout_text = {
                    idx: bytes(buffers[idx]).decode("utf-8", errors="replace")
                    for idx in range(workers)
                }
                raise AssertionError(
                    "coordinated writers never reached READY barrier "
                    f"({sorted(ready)!r} of {workers}); "
                    + _format_worker_diagnostics(
                        workers, returncodes, stdout_text, stderr_paths
                    )
                )
        finally:
            selector.close()
        for idx, proc in procs.items():
            assert proc.stdin is not None
            try:
                proc.stdin.write(b"GO\n")
            except BrokenPipeError:
                pass
        for idx, proc in procs.items():
            assert proc.stdin is not None
            try:
                proc.stdin.close()
            except BrokenPipeError:
                pass
        results: list[dict[str, object]] = []
        failures: list[str] = []
        for idx in range(workers):
            proc = procs[idx]
            timeout = max(0.0, deadline - time.monotonic())
            try:
                stdout_data, _stderr_data = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                failures.append(
                    f"worker {idx} timed out waiting for result; "
                    + _format_worker_diagnostics(
                        workers,
                        {i: procs[i].poll() for i in range(workers)},
                        {
                            i: bytes(buffers[i]).decode("utf-8", errors="replace")
                            for i in range(workers)
                        },
                        stderr_paths,
                    )
                )
                continue
            if proc.returncode != 0:
                failures.append(
                    f"worker {idx} exited {proc.returncode}; "
                    + _format_worker_diagnostics(
                        workers,
                        {i: procs[i].returncode for i in range(workers)},
                        {
                            i: (
                                bytes(buffers[i]).decode("utf-8", errors="replace")
                                if i != idx
                                else (
                                    bytes(buffers[i]).decode("utf-8", errors="replace")
                                    + stdout_data.decode("utf-8", errors="replace")
                                )
                            )
                            for i in range(workers)
                        },
                        stderr_paths,
                    )
                )
                continue
            try:
                payload = json.loads(
                    stdout_data.decode("utf-8").strip().splitlines()[-1]
                )
            except (IndexError, ValueError, UnicodeDecodeError) as exc:
                failures.append(
                    f"worker {idx} produced invalid JSON ({exc}); "
                    + _format_worker_diagnostics(
                        workers,
                        {i: procs[i].returncode for i in range(workers)},
                        {
                            i: (
                                bytes(buffers[i]).decode("utf-8", errors="replace")
                                if i != idx
                                else (
                                    bytes(buffers[i]).decode("utf-8", errors="replace")
                                    + stdout_data.decode("utf-8", errors="replace")
                                )
                            )
                            for i in range(workers)
                        },
                        stderr_paths,
                    )
                )
                continue
            if (
                not isinstance(payload, dict)
                or payload.get("worker") != idx
                or not isinstance(payload.get("child_id"), str)
            ):
                failures.append(
                    f"worker {idx} produced unexpected payload {payload!r}; "
                    + _format_worker_diagnostics(
                        workers,
                        {i: procs[i].returncode for i in range(workers)},
                        {
                            i: (
                                bytes(buffers[i]).decode("utf-8", errors="replace")
                                if i != idx
                                else (
                                    bytes(buffers[i]).decode("utf-8", errors="replace")
                                    + stdout_data.decode("utf-8", errors="replace")
                                )
                            )
                            for i in range(workers)
                        },
                        stderr_paths,
                    )
                )
                continue
            results.append(payload)  # type: ignore[arg-type]
        if failures or len(results) != workers:
            raise AssertionError(
                "coordinated writers failed: "
                + "; ".join(failures)
                + ("" if failures else f" (got {len(results)} of {workers} results)")
            )
    finally:
        for proc in procs.values():
            if proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass
        for proc in procs.values():
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        for handle in stderr_files.values():
            try:
                handle.close()  # type: ignore[attr-defined]
            except OSError:
                pass
    assert [r for r in results if not r.get("child_id")] == []
    child_ids = sorted(str(r["child_id"]) for r in results)
    assert len(set(child_ids)) == workers
    assert child_ids == sorted(f"{epic_id}.{n}" for n in range(1, workers + 1))

    expected_description = {
        str(r["child_id"]): f"worker {r['worker']}" for r in results
    }
    with BeadProject(tmp_path) as project:
        children = project.get_epic_children(epic_id)
        assert sorted(c.id for c in children) == child_ids
        for child_id in child_ids:
            assert project.show(child_id).description == expected_description[child_id]

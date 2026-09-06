"""Remaining kit-rehearsal synthetic edge-case matrix cases.

Covers the matrix entries from the migration-kit plan not already exercised by
``test_driver.py`` (canonical no-op, exact conversion, interrupted write) or
``test_backup.py``/``test_restore.py`` (free-space refusal, checksum
verification, symlink/mode preservation): mixed canonical/old sections,
symlink escaping the declared root, destination conflict, a concurrent lock
holder, and disk-full.
"""

from __future__ import annotations

import errno
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from sase.migration_kit.backup import capture_backup
from sase.migration_kit.core_contract import bounded_lock
from sase.migration_kit.driver import plan_operation, resume_run, run_manifest
from sase.migration_kit.paths import (
    CUTOVER_BACKUP_DIR_ENV_VAR,
    operation_archive_dir,
    run_journal_path,
    run_lock_path,
)


@pytest.fixture(autouse=True)
def _cutover_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CUTOVER_BACKUP_DIR_ENV_VAR, str(tmp_path / "cutover"))


def _state_fixture(tmp_path: Path) -> tuple[Path, Path]:
    home = tmp_path / "home"
    sase_home = home / ".sase"
    (sase_home / "notifications").mkdir(parents=True)
    (sase_home / "agent_tags.json").write_text(
        json.dumps([{"id": ["agent", "p", None], "tag": "ops"}]),
        encoding="utf-8",
    )
    (sase_home / "agent_tribes.json").write_text("[]\n", encoding="utf-8")
    (sase_home / "notifications" / "notifications.jsonl").write_text(
        "", encoding="utf-8"
    )
    return home, sase_home


def _backup_id(sase_home: Path) -> str:
    outcome = capture_backup(sase_home, apply=True)
    assert outcome.ok, outcome.errors
    return outcome.backup_id


def _plan(
    operation: str,
    *,
    home: Path,
    sase_home: Path,
    backup_id: str | None = None,
) -> tuple[str, Path, dict[str, object]]:
    outcome = plan_operation(
        operation,
        root=sase_home,
        home=home,
        backup_id=backup_id,
    )
    assert outcome.ok, outcome.errors
    assert outcome.run_id is not None
    assert outcome.manifest_path is not None
    return (
        outcome.run_id,
        Path(outcome.manifest_path),
        outcome.details["manifest"],
    )


def test_proc_residue_mixed_matched_and_unmatched_rows_refuses_archive(
    tmp_path: Path,
) -> None:
    """Mixed canonical/old sections: one matched row, one with no counterpart."""
    home = tmp_path / "home"
    sase_home = home / ".sase"
    legacy_dir = sase_home / "tasks"
    canonical_dir = sase_home / "procs"
    legacy_dir.mkdir(parents=True)
    canonical_dir.mkdir(parents=True)
    matched = {"task_id": "proc-1", "status": "success", "log_path": "proc-1.log"}
    orphan = {"task_id": "proc-2", "status": "success", "log_path": "proc-2.log"}
    (legacy_dir / "tasks.jsonl").write_text(
        "\n".join(json.dumps(row) for row in (matched, orphan)) + "\n",
        encoding="utf-8",
    )
    (canonical_dir / "procs.jsonl").write_text(
        json.dumps({"proc_id": "proc-1", "status": "success", "log_path": "proc-1.log"})
        + "\n",
        encoding="utf-8",
    )
    backup_id = _backup_id(sase_home)

    _run_id, manifest_path, manifest = _plan(
        "procs-residue", home=home, sase_home=sase_home, backup_id=backup_id
    )

    operation = manifest["operations"][0]
    assert operation["record_counts"]["matched"] == 1
    assert operation["record_counts"]["unmatched_legacy"] == 1
    conflict_kinds = {c["kind"] for c in operation["detected_conflicts"]}
    assert "unmatched_legacy_proc" in conflict_kinds

    outcome = run_manifest(manifest_path, apply=True)

    assert not outcome.ok
    assert "detected conflicts" in outcome.message
    assert (legacy_dir / "tasks.jsonl").is_file()


def test_symlink_escaping_declared_root_is_refused(tmp_path: Path) -> None:
    home, sase_home = _state_fixture(tmp_path)
    (sase_home / "config.yml").write_text("key: value\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "payload.txt").write_text("escaped\n", encoding="utf-8")
    (home / ".xprompts").symlink_to(outside)

    _run_id, manifest_path, manifest = _plan(
        "state-residue", home=home, sase_home=sase_home
    )

    operation = manifest["operations"][0]
    conflict_kinds = {c["kind"] for c in operation["detected_conflicts"]}
    assert "symlink_escape" in conflict_kinds

    outcome = run_manifest(manifest_path, apply=True)

    assert not outcome.ok
    assert (home / ".xprompts").is_symlink()


def test_archive_destination_conflict_is_refused(tmp_path: Path) -> None:
    home, sase_home = _state_fixture(tmp_path)
    backup_id = _backup_id(sase_home)
    run_id, manifest_path, _manifest = _plan(
        "state-residue", home=home, sase_home=sase_home, backup_id=backup_id
    )
    archive_path = operation_archive_dir(
        backup_id, run_id=run_id, operation="state-residue", action_id="agent-tags"
    )
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_text("pre-existing and different\n", encoding="utf-8")

    outcome = run_manifest(manifest_path, apply=True)

    assert not outcome.ok
    assert "archive destination conflict" in outcome.message
    assert (sase_home / "agent_tags.json").is_file()


def test_concurrent_lock_holder_refuses_apply(tmp_path: Path) -> None:
    home, sase_home = _state_fixture(tmp_path)
    backup_id = _backup_id(sase_home)
    run_id, manifest_path, _manifest = _plan(
        "state-residue", home=home, sase_home=sase_home, backup_id=backup_id
    )

    with bounded_lock(
        run_lock_path(run_id), timeout_ms=5_000, operation="external-holder"
    ):
        with pytest.raises(TimeoutError):
            run_manifest(manifest_path, apply=True, lock_timeout_ms=200)

    assert (sase_home / "agent_tags.json").is_file()

    outcome = run_manifest(manifest_path, apply=True)
    assert outcome.ok, outcome.errors
    assert not (sase_home / "agent_tags.json").exists()


def test_disk_full_during_archive_is_recoverable_after_space_frees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, sase_home = _state_fixture(tmp_path)
    backup_id = _backup_id(sase_home)
    run_id, manifest_path, _manifest = _plan(
        "state-residue", home=home, sase_home=sase_home, backup_id=backup_id
    )
    archive_path = operation_archive_dir(
        backup_id, run_id=run_id, operation="state-residue", action_id="agent-tags"
    )
    real_copy2 = shutil.copy2
    calls = {"count": 0}

    def flaky_copy2(source: str, destination: str, *args: object, **kwargs: object):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_copy2(source, destination, *args, **kwargs)

    monkeypatch.setattr(shutil, "copy2", flaky_copy2)

    with pytest.raises(OSError) as excinfo:
        run_manifest(manifest_path, apply=True)
    assert excinfo.value.errno == errno.ENOSPC

    assert (sase_home / "agent_tags.json").is_file()
    assert not archive_path.exists()
    records = [
        json.loads(line)
        for line in run_journal_path(run_id).read_text("utf-8").splitlines()
    ]
    assert [record["state"] for record in records] == [
        "planned",
        "backed_up",
        "applying",
    ]

    monkeypatch.setattr(shutil, "copy2", real_copy2)
    resumed = resume_run(run_id, apply=True)

    assert resumed.ok, resumed.errors
    assert not (sase_home / "agent_tags.json").exists()
    assert archive_path.is_file()


def test_disk_full_on_real_bounded_filesystem_refuses_backup(tmp_path: Path) -> None:
    """Additionally prove the free-space refusal against a real small filesystem.

    Mounts a tiny tmpfs inside an unprivileged user+mount namespace (private
    to the child process, gone the instant it exits) so the refusal is
    exercised against genuine ``statvfs`` free space rather than a mocked
    ``shutil.disk_usage``. Skips when the sandbox forbids unprivileged
    namespaces, per the plan's explicit allowance.
    """
    if shutil.which("unshare") is None:
        pytest.skip("unshare is not available")

    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "big.bin").write_bytes(b"x" * (200 * 1024))

    mount_point = tmp_path / "tiny-fs"
    mount_point.mkdir()
    script = (
        "import json\n"
        "from pathlib import Path\n"
        "from sase.migration_kit.backup import capture_backup\n"
        f"outcome = capture_backup(Path({str(source_root)!r}), apply=True)\n"
        "print(json.dumps({'ok': outcome.ok, 'errors': list(outcome.errors)}))\n"
    )
    cmd = [
        "unshare",
        "--user",
        "--map-root-user",
        "--mount",
        "bash",
        "-c",
        'mount -t tmpfs -o size=65536 tmpfs "$0" && exec "$1" -c "$2"',
        str(mount_point),
        sys.executable,
        script,
    ]
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        CUTOVER_BACKUP_DIR_ENV_VAR: str(mount_point / "cutover"),
    }
    try:
        result = subprocess.run(
            cmd, env=env, capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"unprivileged unshare/mount unavailable: {exc}")

    if result.returncode != 0:
        pytest.skip(
            "unprivileged unshare/mount refused in this sandbox: "
            f"{result.stderr.strip()}"
        )

    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["ok"] is False
    assert any("insufficient free space" in error for error in payload["errors"])

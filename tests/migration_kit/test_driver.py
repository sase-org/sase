"""Tests for the migration kit driver, journal, and shipped operations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.migration_kit.backup import capture_backup
from sase.migration_kit.driver import (
    ABORT_AFTER_ARCHIVES_ENV_VAR,
    list_operations,
    plan_operation,
    resume_run,
    run_manifest,
    verify_run,
)
from sase.migration_kit.operations.base import MigrationInjectedAbort
from sase.migration_kit.paths import (
    CUTOVER_BACKUP_DIR_ENV_VAR,
    operation_archive_dir,
    run_journal_path,
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


def _proc_fixture(tmp_path: Path, *, conflict: bool = False) -> tuple[Path, Path]:
    home = tmp_path / "home"
    sase_home = home / ".sase"
    legacy_dir = sase_home / "tasks"
    canonical_dir = sase_home / "procs"
    legacy_dir.mkdir(parents=True)
    canonical_dir.mkdir(parents=True)
    legacy = {
        "task_id": "proc-1",
        "status": "success",
        "log_path": str(legacy_dir / "logs" / "proc-1.log"),
    }
    canonical = {
        "proc_id": "proc-1",
        "status": "failed" if conflict else "success",
        "log_path": str(canonical_dir / "logs" / "proc-1.log"),
    }
    (legacy_dir / "tasks.jsonl").write_text(
        json.dumps(legacy) + "\n",
        encoding="utf-8",
    )
    (canonical_dir / "procs.jsonl").write_text(
        json.dumps(canonical) + "\n",
        encoding="utf-8",
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


def test_list_reports_the_four_shipped_operations(tmp_path: Path) -> None:
    home, sase_home = _state_fixture(tmp_path)

    outcome = list_operations(root=sase_home, home=home)

    assert outcome.ok
    names = {row["name"] for row in outcome.details["operations"]}
    assert names == {
        "import-purge",
        "lock-residue",
        "procs-residue",
        "state-residue",
    }


def test_state_residue_plan_on_canonical_fixture_is_noop(tmp_path: Path) -> None:
    home, sase_home = _state_fixture(tmp_path)
    (sase_home / "agent_tags.json").unlink()

    _run_id, _manifest_path, manifest = _plan(
        "state-residue", home=home, sase_home=sase_home
    )

    operation = manifest["operations"][0]
    assert operation["record_counts"]["agent-tags"] == 0
    assert operation["x_actions"] == []
    assert operation["detected_conflicts"] == []


def test_state_residue_apply_archives_removes_and_reapplies_as_noop(
    tmp_path: Path,
) -> None:
    home, sase_home = _state_fixture(tmp_path)
    backup_id = _backup_id(sase_home)
    run_id, manifest_path, manifest = _plan(
        "state-residue",
        home=home,
        sase_home=sase_home,
        backup_id=backup_id,
    )

    dry_run = run_manifest(manifest_path, apply=False)
    assert dry_run.ok
    assert (sase_home / "agent_tags.json").is_file()

    applied = run_manifest(manifest_path, apply=True)
    assert applied.ok, applied.errors
    assert not (sase_home / "agent_tags.json").exists()
    archive = operation_archive_dir(
        backup_id,
        run_id=run_id,
        operation="state-residue",
        action_id="agent-tags",
    )
    assert archive.is_file()
    assert json.loads(archive.read_text("utf-8")) == [
        {"id": ["agent", "p", None], "tag": "ops"}
    ]

    reapplied = run_manifest(manifest_path, apply=True)
    assert reapplied.ok
    assert "no-op" in reapplied.message
    assert verify_run(run_id).ok

    records = [
        json.loads(line)
        for line in run_journal_path(run_id).read_text("utf-8").splitlines()
    ]
    assert [record["state"] for record in records] == [
        "planned",
        "backed_up",
        "applying",
        "applied",
        "verified",
    ]
    assert manifest["backups"][0]["verified"] is True


def test_state_residue_resume_finishes_after_interrupted_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, sase_home = _state_fixture(tmp_path)
    backup_id = _backup_id(sase_home)
    run_id, manifest_path, _manifest = _plan(
        "state-residue",
        home=home,
        sase_home=sase_home,
        backup_id=backup_id,
    )
    monkeypatch.setenv(ABORT_AFTER_ARCHIVES_ENV_VAR, "1")

    with pytest.raises(MigrationInjectedAbort):
        run_manifest(manifest_path, apply=True)

    assert (sase_home / "agent_tags.json").is_file()
    archive = operation_archive_dir(
        backup_id,
        run_id=run_id,
        operation="state-residue",
        action_id="agent-tags",
    )
    assert archive.is_file()

    monkeypatch.delenv(ABORT_AFTER_ARCHIVES_ENV_VAR)
    resumed = resume_run(run_id, apply=True)

    assert resumed.ok, resumed.errors
    assert not (sase_home / "agent_tags.json").exists()


def test_digest_gate_refuses_when_source_moves_before_apply(tmp_path: Path) -> None:
    home, sase_home = _state_fixture(tmp_path)
    backup_id = _backup_id(sase_home)
    _run_id, manifest_path, _manifest = _plan(
        "state-residue",
        home=home,
        sase_home=sase_home,
        backup_id=backup_id,
    )
    (sase_home / "agent_tags.json").write_text("changed\n", encoding="utf-8")

    outcome = run_manifest(manifest_path, apply=True)

    assert not outcome.ok
    assert "source digest gate refused" in outcome.message


def test_proc_residue_converts_exact_fixture(tmp_path: Path) -> None:
    home, sase_home = _proc_fixture(tmp_path)
    backup_id = _backup_id(sase_home)
    run_id, manifest_path, manifest = _plan(
        "procs-residue",
        home=home,
        sase_home=sase_home,
        backup_id=backup_id,
    )

    assert manifest["operations"][0]["record_counts"]["matched"] == 1
    outcome = run_manifest(manifest_path, apply=True)

    assert outcome.ok, outcome.errors
    assert not (sase_home / "tasks").exists()
    archive = operation_archive_dir(
        backup_id,
        run_id=run_id,
        operation="procs-residue",
        action_id="legacy-tasks",
    )
    assert (archive / "tasks.jsonl").is_file()


def test_proc_residue_conflict_is_refused(tmp_path: Path) -> None:
    home, sase_home = _proc_fixture(tmp_path, conflict=True)
    backup_id = _backup_id(sase_home)
    _run_id, manifest_path, manifest = _plan(
        "procs-residue",
        home=home,
        sase_home=sase_home,
        backup_id=backup_id,
    )

    operation = manifest["operations"][0]
    assert operation["detected_conflicts"]
    outcome = run_manifest(manifest_path, apply=True)

    assert not outcome.ok
    assert "detected conflicts" in outcome.message
    assert (sase_home / "tasks" / "tasks.jsonl").is_file()


def test_lock_residue_has_no_apply_path(tmp_path: Path) -> None:
    home, sase_home = _state_fixture(tmp_path)
    (sase_home / "locks").mkdir()
    (sase_home / "locks" / "code-swap-v2.lock").write_text("", encoding="utf-8")
    _run_id, manifest_path, manifest = _plan(
        "lock-residue", home=home, sase_home=sase_home
    )

    classification = manifest["operations"][0]["x_classifications"][1]
    assert classification["decision"] == "refuse_archive_current_writer"
    outcome = run_manifest(manifest_path, apply=True)

    assert not outcome.ok
    assert "no apply path" in outcome.message

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys

import pytest

from sase.axe.run_agent_exec_finalize import _enforce_artifact_retention
from sase.core.artifact_file_explicit import (
    read_artifact_file_index,
    write_artifact_file_index_unlocked,
)
from sase.core.artifact_file_protection import ProtectedArtifactIds
from sase.core.artifact_file_retention_pass import (
    _artifact_retention_lock_path,
    _artifact_retention_stamp_path,
    _read_artifact_retention_stamp,
    enforce_artifact_retention,
    maybe_enforce_artifact_retention,
)
from sase.core.artifact_file_trash import (
    list_trashed_artifact_files,
    trash_artifact_files,
)
from sase.core.artifact_file_types import ArtifactFile


def _patch_retention_config(
    monkeypatch: pytest.MonkeyPatch,
    *,
    enabled: bool,
    keep_per_label: int = 1,
    max_age_days: int = 0,
    trash_grace_days: int = 14,
) -> None:
    monkeypatch.setattr(
        "sase.config.get_artifact_retention_enabled",
        lambda: enabled,
    )
    monkeypatch.setattr(
        "sase.config.get_artifact_retention_keep_per_label",
        lambda: keep_per_label,
    )
    monkeypatch.setattr(
        "sase.config.get_artifact_retention_max_age_days",
        lambda: max_age_days,
    )
    monkeypatch.setattr(
        "sase.config.get_artifact_retention_trash_grace_days",
        lambda: trash_grace_days,
    )


def _patch_protections(
    monkeypatch: pytest.MonkeyPatch,
    protections: ProtectedArtifactIds,
) -> None:
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.collect_protected_artifact_ids",
        lambda: protections,
    )


def _artifact(
    artifact_id: str,
    path: Path,
    *,
    label: str = "report",
    created_at: str,
    explicit: bool = False,
) -> ArtifactFile:
    return ArtifactFile(
        id=artifact_id,
        label=label,
        kind="file",
        path=str(path),
        created_at=created_at,
        project="proj",
        agent_name="agent",
        explicit=explicit,
        sha256=artifact_id[-24:],
        size_bytes=path.stat().st_size,
    )


def _seed_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, ArtifactFile, ArtifactFile, ArtifactFile, ArtifactFile]:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    root = tmp_path / "artifacts"
    root.mkdir()
    old_path = root / "old.txt"
    new_path = root / "new.txt"
    explicit_path = root / "explicit.txt"
    expired_path = root / "expired.txt"
    old_path.write_text("old", encoding="utf-8")
    new_path.write_text("new", encoding="utf-8")
    explicit_path.write_text("declared", encoding="utf-8")
    expired_path.write_text("expired", encoding="utf-8")
    old = _artifact(
        "default:111111111111111111111111",
        old_path,
        created_at="2026-07-01T00:00:00Z",
    )
    new = _artifact(
        "default:222222222222222222222222",
        new_path,
        created_at="2026-07-02T00:00:00Z",
    )
    explicit = _artifact(
        "explicit:333333333333333333333333",
        explicit_path,
        label="declared",
        created_at="2026-07-01T00:00:00Z",
        explicit=True,
    )
    expired = _artifact(
        "default:444444444444444444444444",
        expired_path,
        label="trash",
        created_at="2026-06-01T00:00:00Z",
    )
    index = root / "index.jsonl"
    write_artifact_file_index_unlocked(index, [old, new, explicit, expired])
    return index, old, new, explicit, expired


def test_finalization_retention_disabled_leaves_index_byte_identical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index, _old, _new, _explicit, _expired = _seed_store(tmp_path, monkeypatch)
    _patch_retention_config(monkeypatch, enabled=False)
    before = index.read_bytes()

    _enforce_artifact_retention()

    assert index.read_bytes() == before
    assert list_trashed_artifact_files().entries == ()


def test_finalization_retention_enabled_trashes_selection_and_purges_expired(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    index, old, new, explicit, expired = _seed_store(tmp_path, monkeypatch)
    _patch_retention_config(monkeypatch, enabled=True)
    _patch_protections(
        monkeypatch,
        ProtectedArtifactIds(
            referenced_ids=frozenset(),
            consumed_ids=frozenset(),
            sources_scanned=(),
            sources_unavailable=(),
        ),
    )
    trash_artifact_files(
        [expired],
        reason="test",
        now="1970-01-01T00:00:00Z",
    )
    capsys.readouterr()

    _enforce_artifact_retention()

    assert {row.id for row in read_artifact_file_index(index)} == {
        new.id,
        explicit.id,
    }
    assert {entry.artifact_id for entry in list_trashed_artifact_files().entries} == {
        old.id
    }
    output = capsys.readouterr().out
    assert "retention: trashed 1 rows" in output
    assert "purged 1 trash entries" in output


def test_finalization_retention_unavailable_protection_source_skips_all_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    index, _old, _new, _explicit, expired = _seed_store(tmp_path, monkeypatch)
    _patch_retention_config(monkeypatch, enabled=True)
    _patch_protections(
        monkeypatch,
        ProtectedArtifactIds(
            referenced_ids=frozenset(),
            consumed_ids=frozenset(),
            sources_scanned=(),
            sources_unavailable=("proj:plans",),
        ),
    )
    expired_trash = trash_artifact_files(
        [expired],
        reason="test",
        now="1970-01-01T00:00:00Z",
    )
    before = index.read_bytes()
    capsys.readouterr()

    _enforce_artifact_retention()

    assert index.read_bytes() == before
    assert [entry.entry_id for entry in list_trashed_artifact_files().entries] == [
        expired_trash.entries[0].entry_id
    ]
    assert "retention skipped: protection sources unavailable: proj:plans" in (
        capsys.readouterr().out
    )


def test_finalization_retention_excludes_consumed_only_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    index, old, new, explicit, expired = _seed_store(tmp_path, monkeypatch)
    _patch_retention_config(monkeypatch, enabled=True)
    _patch_protections(
        monkeypatch,
        ProtectedArtifactIds(
            referenced_ids=frozenset(),
            consumed_ids=frozenset({old.id}),
            sources_scanned=(str(tmp_path / "artifacts" / "consumption.jsonl"),),
            sources_unavailable=(),
        ),
    )
    before = index.read_bytes()

    _enforce_artifact_retention()

    assert index.read_bytes() == before
    assert {row.id for row in read_artifact_file_index(index)} == {
        old.id,
        new.id,
        explicit.id,
        expired.id,
    }
    assert list_trashed_artifact_files().entries == ()
    assert "retention: trashed 0 rows" in capsys.readouterr().out


def _write_stamp(completed_at: datetime, *, outcome: str = "enforced") -> Path:
    path = _artifact_retention_stamp_path()
    path.write_text(
        json.dumps(
            {
                "completed_at": completed_at.isoformat(),
                "outcome": outcome,
                "rows_trashed": 0,
                "bytes_reclaimed": 0,
                "purged_entries": 0,
                "missing_rows": 0,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def test_runner_skips_retention_when_stamp_is_fresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index, _old, _new, _explicit, _expired = _seed_store(tmp_path, monkeypatch)
    _patch_retention_config(monkeypatch, enabled=True)
    _patch_protections(
        monkeypatch,
        ProtectedArtifactIds(
            referenced_ids=frozenset(),
            consumed_ids=frozenset(),
            sources_scanned=(),
            sources_unavailable=(),
        ),
    )
    _write_stamp(datetime.now(UTC) - timedelta(hours=1))
    before = index.read_bytes()

    result = maybe_enforce_artifact_retention()

    assert result.outcome == "stamp_fresh"
    assert result.stamped is False
    assert index.read_bytes() == before
    assert list_trashed_artifact_files().entries == ()


def test_runner_runs_retention_when_stamp_is_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index, old, new, explicit, _expired = _seed_store(tmp_path, monkeypatch)
    _patch_retention_config(monkeypatch, enabled=True)
    _patch_protections(
        monkeypatch,
        ProtectedArtifactIds(
            referenced_ids=frozenset(),
            consumed_ids=frozenset(),
            sources_scanned=(),
            sources_unavailable=(),
        ),
    )
    _write_stamp(datetime.now(UTC) - timedelta(hours=25))

    result = maybe_enforce_artifact_retention()

    assert result.outcome == "enforced"
    assert result.stamped is True
    remaining = {row.id for row in read_artifact_file_index(index)}
    assert old.id not in remaining
    assert {new.id, explicit.id} <= remaining
    assert {entry.artifact_id for entry in list_trashed_artifact_files().entries} == {
        old.id
    }
    stamp = _read_artifact_retention_stamp()
    assert stamp is not None
    assert stamp["outcome"] == "enforced"


def test_runner_runs_retention_when_stamp_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_store(tmp_path, monkeypatch)
    _patch_retention_config(monkeypatch, enabled=False)

    result = maybe_enforce_artifact_retention()

    assert result.outcome == "disabled"
    assert result.stamped is True
    stamp = _read_artifact_retention_stamp()
    assert stamp is not None
    assert stamp["outcome"] == "disabled"


def test_concurrent_retention_passes_are_excluded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index, _old, _new, _explicit, _expired = _seed_store(tmp_path, monkeypatch)
    _patch_retention_config(monkeypatch, enabled=True)
    _patch_protections(
        monkeypatch,
        ProtectedArtifactIds(
            referenced_ids=frozenset(),
            consumed_ids=frozenset(),
            sources_scanned=(),
            sources_unavailable=(),
        ),
    )
    before = index.read_bytes()
    lock_path = _artifact_retention_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import fcntl, sys, time\n"
                "handle = open(sys.argv[1], 'a', encoding='utf-8')\n"
                "fcntl.flock(handle.fileno(), fcntl.LOCK_EX)\n"
                "sys.stdout.write('locked\\n')\n"
                "sys.stdout.flush()\n"
                "time.sleep(30)\n"
            ),
            str(lock_path),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline() == "locked\n"
        result = enforce_artifact_retention()
    finally:
        holder.terminate()
        holder.wait(timeout=5)

    assert result.outcome == "lock_busy"
    assert result.stamped is False
    assert index.read_bytes() == before
    assert not _artifact_retention_stamp_path().exists()


def test_disabled_retention_stamps_and_never_trashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index, _old, _new, _explicit, _expired = _seed_store(tmp_path, monkeypatch)
    _patch_retention_config(monkeypatch, enabled=False)
    before = index.read_bytes()

    result = enforce_artifact_retention()

    assert result.outcome == "disabled"
    assert result.stamped is True
    assert index.read_bytes() == before
    assert list_trashed_artifact_files().entries == ()
    stamp = _read_artifact_retention_stamp()
    assert stamp is not None
    assert stamp["outcome"] == "disabled"


def test_finalize_wrapper_skips_when_stamp_is_fresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index, _old, _new, _explicit, _expired = _seed_store(tmp_path, monkeypatch)
    _patch_retention_config(monkeypatch, enabled=True)
    _patch_protections(
        monkeypatch,
        ProtectedArtifactIds(
            referenced_ids=frozenset(),
            consumed_ids=frozenset(),
            sources_scanned=(),
            sources_unavailable=(),
        ),
    )
    _write_stamp(datetime.now(UTC))
    before = index.read_bytes()

    _enforce_artifact_retention()

    assert index.read_bytes() == before
    assert list_trashed_artifact_files().entries == ()

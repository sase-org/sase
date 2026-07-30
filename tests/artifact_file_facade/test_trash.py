from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from sase.core.artifact_file_explicit import (
    read_artifact_file_index,
    write_artifact_file_index_unlocked,
)
from sase.core.artifact_file_trash import (
    list_trashed_artifact_files,
    purge_trashed_artifact_files,
    restore_trashed_artifact_file,
    trash_artifact_files,
)
from sase.core.artifact_file_types import ArtifactFile
from sase.core.rust import require_rust_binding


def _artifact(
    artifact_id: str,
    path: Path | None,
    *,
    label: str = "report",
) -> ArtifactFile:
    return ArtifactFile(
        id=artifact_id,
        label=label,
        kind="file",
        path=None if path is None else str(path),
        created_at="2026-07-01T00:00:00Z",
        project="proj",
        agent_name="agent",
        explicit=False,
        sha256=artifact_id[-24:],
        size_bytes=None if path is None else path.stat().st_size,
        vcs_repo="repo" if path is None else None,
        vcs_sha="commit" if path is None else None,
        vcs_relpath="report.txt" if path is None else None,
    )


def test_batch_trash_uses_one_lock_and_preserves_unparsed_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    root = tmp_path / "artifacts"
    root.mkdir()
    first_path = root / "first.txt"
    second_path = root / "second.txt"
    first_path.write_text("first", encoding="utf-8")
    second_path.write_text("second", encoding="utf-8")
    first = _artifact("default:111111111111111111111111", first_path)
    second = _artifact("default:222222222222222222222222", second_path)
    index = root / "index.jsonl"
    write_artifact_file_index_unlocked(
        index,
        [first, second],
        preserved_lines=["not-json\n"],
    )

    from sase.core import artifact_file_trash as trash_module

    original_lock = trash_module.artifact_file_index_lock
    lock_calls = 0

    @contextmanager
    def counting_lock(
        index_path: Path,
        *,
        exclusive: bool,
    ) -> Iterator[None]:
        nonlocal lock_calls
        lock_calls += 1
        with original_lock(index_path, exclusive=exclusive):
            yield

    monkeypatch.setattr(trash_module, "artifact_file_index_lock", counting_lock)

    result = trash_artifact_files(
        [first, second],
        reason="retention",
        now="2026-07-30T00:00:00Z",
    )

    assert lock_calls == 1
    assert result.rows_trashed == 2
    assert result.bytes_reclaimed == 11
    assert not first_path.exists()
    assert not second_path.exists()
    assert read_artifact_file_index(index) == []
    assert index.read_text(encoding="utf-8") == "not-json\n"


def test_byte_free_row_round_trips_with_identical_fields_and_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    root = tmp_path / "artifacts"
    root.mkdir()
    row = _artifact("default:333333333333333333333333", None)
    index = root / "index.jsonl"
    write_artifact_file_index_unlocked(index, [row])

    trashed = trash_artifact_files(
        [row],
        reason="retention",
        now="2026-07-30T00:00:00Z",
    )
    [entry] = list_trashed_artifact_files().entries

    assert entry == trashed.entries[0]
    assert entry.stored_path is None
    assert entry.stored_filename is None
    assert read_artifact_file_index(index) == []

    restored = restore_trashed_artifact_file(entry.entry_id)

    assert restored.artifact_id == row.id
    assert restored.restored_path is None
    assert restored.record == row
    assert read_artifact_file_index(index) == [row]
    assert list_trashed_artifact_files().entries == ()


def test_purge_respects_cutoff_and_all(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    root = tmp_path / "artifacts"
    root.mkdir()
    old_path = root / "old.txt"
    new_path = root / "new.txt"
    old_path.write_text("old", encoding="utf-8")
    new_path.write_text("newer", encoding="utf-8")
    old = _artifact("default:444444444444444444444444", old_path)
    new = _artifact("default:555555555555555555555555", new_path)
    index = root / "index.jsonl"
    write_artifact_file_index_unlocked(index, [old, new])
    old_result = trash_artifact_files(
        [old],
        reason="retention",
        now="2026-07-01T00:00:00Z",
    )
    new_result = trash_artifact_files(
        [new],
        reason="retention",
        now="2026-07-03T00:00:00Z",
    )

    cutoff = purge_trashed_artifact_files(before="2026-07-02T00:00:00Z")

    assert cutoff.purged_entry_ids == (old_result.entries[0].entry_id,)
    assert cutoff.freed_bytes == 3
    assert [entry.entry_id for entry in list_trashed_artifact_files().entries] == [
        new_result.entries[0].entry_id
    ]

    purge_all = purge_trashed_artifact_files(
        before="1970-01-01T00:00:00Z",
        purge_all=True,
    )
    assert purge_all.purged_entry_ids == (new_result.entries[0].entry_id,)
    assert purge_all.freed_bytes == 5


def test_core_failure_leaves_prior_rows_trashed_and_remaining_rows_live(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    root = tmp_path / "artifacts"
    root.mkdir()
    first_path = root / "first.txt"
    second_path = root / "second.txt"
    first_path.write_text("first", encoding="utf-8")
    second_path.write_text("second", encoding="utf-8")
    first = _artifact("default:666666666666666666666666", first_path)
    second = _artifact("default:777777777777777777777777", second_path)
    index = root / "index.jsonl"
    write_artifact_file_index_unlocked(index, [first, second])

    actual_store = require_rust_binding("artifact_file_trash_store")
    actual_list = require_rust_binding("artifact_file_trash_list")
    store_calls = 0

    def fake_binding(name: str):  # type: ignore[no-untyped-def]
        if name == "artifact_file_lifecycle_wire_schema_version":
            return lambda: 1
        if name == "artifact_file_trash_store":

            def store(request: dict[str, object]) -> object:
                nonlocal store_calls
                store_calls += 1
                if store_calls == 2:
                    raise RuntimeError("injected core failure")
                return actual_store(request)

            return store
        raise AssertionError(name)

    monkeypatch.setattr(
        "sase.core.artifact_file_trash.require_rust_binding",
        fake_binding,
    )

    with pytest.raises(RuntimeError, match="injected core failure"):
        trash_artifact_files(
            [first, second],
            reason="retention",
            now="2026-07-30T00:00:00Z",
        )

    assert read_artifact_file_index(index) == [second]
    assert not first_path.exists()
    assert second_path.exists()
    raw_listing = actual_list(str(root / "trash"))
    assert [entry["artifact_id"] for entry in raw_listing["entries"]] == [first.id]

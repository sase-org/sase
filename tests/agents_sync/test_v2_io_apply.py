from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agents_sync.v2_io import (
    apply_payload_atomic,
    apply_payload_batched_atomic,
)


def _batch_plan(
    batch_specs: tuple[tuple[tuple[str, ...], int], ...],
    *,
    budget_bytes: int,
    total_size_bytes: int,
) -> SimpleNamespace:
    return SimpleNamespace(
        schema_version=1,
        budget_bytes=budget_bytes,
        total_size_bytes=total_size_bytes,
        batches=tuple(
            SimpleNamespace(paths=paths, size_bytes=size) for paths, size in batch_specs
        ),
    )


def test_payload_apply_rolls_back_every_prior_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync import v2_io

    first = tmp_path / "a.txt"
    first.write_text("old", encoding="utf-8")
    real_write = v2_io.atomic_write_bytes
    calls = 0

    def fail_once(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected")
        real_write(path, payload)

    monkeypatch.setattr(v2_io, "atomic_write_bytes", fail_once)
    with pytest.raises(OSError, match="injected"):
        apply_payload_atomic(
            tmp_path,
            {"a.txt": b"new", "nested/b.txt": b"created"},
        )

    assert first.read_text(encoding="utf-8") == "old"
    assert not (tmp_path / "nested" / "b.txt").exists()


def test_batched_payload_ignores_unchanged_bytes_when_planning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync import v2_io

    (tmp_path / "unchanged-a.txt").write_bytes(b"a" * 8)
    (tmp_path / "unchanged-b.txt").write_bytes(b"b" * 8)
    seen: list[tuple[tuple[str, int], ...]] = []

    def fake_plan(records, *, budget_bytes: int):  # type: ignore[no-untyped-def]
        materialized = tuple((record.path, record.size_bytes) for record in records)
        seen.append(materialized)
        return _batch_plan(
            tuple(((path,), size) for path, size in materialized),
            budget_bytes=budget_bytes,
            total_size_bytes=sum(size for _path, size in materialized),
        )

    monkeypatch.setattr(v2_io, "plan_agent_publication_batches", fake_plan)

    assert apply_payload_batched_atomic(
        tmp_path,
        {
            "unchanged-a.txt": b"a" * 8,
            "unchanged-b.txt": b"b" * 8,
            "changed.txt": b"c",
        },
        batch_budget_bytes=1,
    )

    assert seen == [(("changed.txt", 1),)]
    assert (tmp_path / "changed.txt").read_bytes() == b"c"


def test_batched_payload_applies_all_changed_payload_over_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync import v2_io

    planned: list[tuple[int, tuple[tuple[str, int], ...]]] = []

    def fake_plan(records, *, budget_bytes: int):  # type: ignore[no-untyped-def]
        materialized = tuple((record.path, record.size_bytes) for record in records)
        planned.append((budget_bytes, materialized))
        return _batch_plan(
            (
                (("a.txt", "b.txt"), 4),
                (("c.txt",), 2),
            ),
            budget_bytes=budget_bytes,
            total_size_bytes=sum(size for _path, size in materialized),
        )

    monkeypatch.setattr(v2_io, "plan_agent_publication_batches", fake_plan)

    assert apply_payload_batched_atomic(
        tmp_path,
        {"a.txt": b"aa", "b.txt": b"bb", "c.txt": b"cc"},
        batch_budget_bytes=4,
    )

    assert planned == [(4, (("a.txt", 2), ("b.txt", 2), ("c.txt", 2)))]
    assert (tmp_path / "a.txt").read_bytes() == b"aa"
    assert (tmp_path / "b.txt").read_bytes() == b"bb"
    assert (tmp_path / "c.txt").read_bytes() == b"cc"


def test_batched_payload_rolls_back_across_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync import v2_io

    first = tmp_path / "a.txt"
    first.write_text("old", encoding="utf-8")

    def fake_plan(records, *, budget_bytes: int):  # type: ignore[no-untyped-def]
        materialized = tuple(record.path for record in records)
        assert materialized == ("a.txt", "nested/b.txt")
        return _batch_plan(
            (
                (("a.txt",), 3),
                (("nested/b.txt",), 3),
            ),
            budget_bytes=budget_bytes,
            total_size_bytes=6,
        )

    real_write = v2_io.atomic_write_bytes
    calls = 0

    def fail_second_batch(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected")
        real_write(path, payload)

    monkeypatch.setattr(v2_io, "plan_agent_publication_batches", fake_plan)
    monkeypatch.setattr(v2_io, "atomic_write_bytes", fail_second_batch)

    with pytest.raises(OSError, match="injected"):
        apply_payload_batched_atomic(
            tmp_path,
            {"a.txt": b"new", "nested/b.txt": b"new"},
            batch_budget_bytes=3,
        )

    assert first.read_text(encoding="utf-8") == "old"
    assert not (tmp_path / "nested" / "b.txt").exists()
    assert not tuple(tmp_path.glob(".sase-v2-stage-*"))
    assert not tuple(tmp_path.glob(".sase-v2-backup-*"))


def test_batched_payload_stage_failure_leaves_destinations_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync import v2_io

    first = tmp_path / "a.txt"
    first.write_text("old", encoding="utf-8")

    def fake_plan(records, *, budget_bytes: int):  # type: ignore[no-untyped-def]
        materialized = tuple(record.path for record in records)
        return _batch_plan(
            tuple(((path,), 3) for path in materialized),
            budget_bytes=budget_bytes,
            total_size_bytes=3 * len(materialized),
        )

    def fail_stage(_stage, _changed):  # type: ignore[no-untyped-def]
        raise OSError("staging failed")

    monkeypatch.setattr(v2_io, "plan_agent_publication_batches", fake_plan)
    monkeypatch.setattr(v2_io, "_stage_changed_payload", fail_stage)

    with pytest.raises(OSError, match="staging failed"):
        apply_payload_batched_atomic(
            tmp_path,
            {"a.txt": b"new", "nested/b.txt": b"new"},
            batch_budget_bytes=3,
        )

    assert first.read_text(encoding="utf-8") == "old"
    assert not (tmp_path / "nested" / "b.txt").exists()
    assert not tuple(tmp_path.glob(".sase-v2-stage-*"))
    assert not tuple(tmp_path.glob(".sase-v2-backup-*"))

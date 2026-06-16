from __future__ import annotations

from pathlib import Path

from sase.ace.tui.models.agent import AgentType
from sase.core.agent_artifact_index_lifecycle import (
    _quarantine_corrupt_index,
    sync_dismissed_agent_artifact_index_report,
)
from sase.core.agent_scan_wire import AgentArtifactIndexUpdateWire

from .helpers import (
    fake_replace_update,
    install_projection_meta_store,
    patch_projection_sources,
    read_projection_meta,
)


def test_corrupt_index_quarantined_rebuilt_and_resynced(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    """A malformed index is quarantined, rebuilt, force-synced, and reported."""
    index = tmp_path / "agent_artifact_index.sqlite"
    index.write_bytes(b"this is not a sqlite database " * 64)
    stale_quarantine = tmp_path / (
        "agent_artifact_index.sqlite.corrupt-20200101T000000Z"
    )
    stale_quarantine.write_bytes(b"older corrupt copy")
    patch_projection_sources(monkeypatch)
    meta_store = install_projection_meta_store(
        monkeypatch,
        corrupt_prefix=b"this is not",
    )

    def fake_rebuild(index_path: Path, projects_root: Path) -> object:
        del projects_root
        index_path.touch()
        return AgentArtifactIndexUpdateWire(
            schema_version=1,
            index_path=str(index_path),
            projects_root="",
            rows_indexed=0,
        )

    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle.rebuild_agent_artifact_index",
        fake_rebuild,
    )
    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle."
        "replace_agent_artifact_index_dismissed_agents",
        fake_replace_update,
    )

    report = sync_dismissed_agent_artifact_index_report(
        {(AgentType.RUNNING, "feature", "20260501010101")},
        index_path=index,
    )

    assert report.synced
    assert report.changed
    assert report.healed
    assert report.quarantined_path is not None
    assert report.quarantined_path.read_bytes().startswith(b"this is not")
    quarantines = sorted(tmp_path.glob("agent_artifact_index.sqlite.corrupt-*"))
    assert quarantines == [report.quarantined_path]
    assert read_projection_meta(meta_store, index)["projected_identity_count"] == 1

    # The healed index's metadata must satisfy the fast path on the next
    # sync; the pre-fix failure mode was a full rescan on every launch.
    def fail_replace(*args: object, **kwargs: object) -> object:
        raise AssertionError("fast path should have skipped the projection")

    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle."
        "replace_agent_artifact_index_dismissed_agents",
        fail_replace,
    )
    second = sync_dismissed_agent_artifact_index_report(index_path=index)
    assert second.synced
    assert not second.changed
    assert not second.healed


def test_corruption_reported_by_replace_triggers_heal(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    """Rust-facade corruption errors (RuntimeError) also trigger the heal."""
    index = tmp_path / "agent_artifact_index.sqlite"
    index.touch()
    patch_projection_sources(monkeypatch)
    install_projection_meta_store(monkeypatch)
    replace_calls: list[int] = []

    def flaky_replace(index_path: Path, identities: list[object]) -> object:
        replace_calls.append(1)
        if len(replace_calls) == 1:
            raise RuntimeError("database disk image is malformed (11)")
        return fake_replace_update(index_path, identities)

    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle."
        "replace_agent_artifact_index_dismissed_agents",
        flaky_replace,
    )
    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle.rebuild_agent_artifact_index",
        lambda index_path, projects_root: index_path.touch(),
    )

    report = sync_dismissed_agent_artifact_index_report(
        {(AgentType.RUNNING, "feature", "20260501010101")},
        index_path=index,
    )

    assert report.synced
    assert report.healed
    assert len(replace_calls) == 2


def test_transient_lock_errors_do_not_quarantine(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    """Lock/busy errors fail the sync quietly without touching the index."""
    index = tmp_path / "agent_artifact_index.sqlite"
    index.touch()
    patch_projection_sources(monkeypatch)
    install_projection_meta_store(monkeypatch)

    def locked_replace(*args: object, **kwargs: object) -> object:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle."
        "replace_agent_artifact_index_dismissed_agents",
        locked_replace,
    )

    report = sync_dismissed_agent_artifact_index_report(
        {(AgentType.RUNNING, "feature", "20260501010101")},
        index_path=index,
    )

    assert not report.synced
    assert not report.healed
    assert index.is_file()
    assert list(tmp_path.glob("agent_artifact_index.sqlite.corrupt-*")) == []


def test_quarantine_race_loser_skips(tmp_path: Path) -> None:
    """When another process already renamed the index, the heal is skipped."""
    assert _quarantine_corrupt_index(tmp_path / "missing.sqlite") is None


def test_quarantine_renames_sqlite_sidecars(tmp_path: Path) -> None:
    """Corrupt-index quarantine preserves WAL sidecars with the corrupt copy."""
    index = tmp_path / "agent_artifact_index.sqlite"
    index.write_bytes(b"bad db")
    wal = Path(f"{index}-wal")
    shm = Path(f"{index}-shm")
    wal.write_bytes(b"wal")
    shm.write_bytes(b"shm")

    quarantined = _quarantine_corrupt_index(index)

    assert quarantined is not None
    assert quarantined.read_bytes() == b"bad db"
    assert Path(f"{quarantined}-wal").read_bytes() == b"wal"
    assert Path(f"{quarantined}-shm").read_bytes() == b"shm"
    assert not wal.exists()
    assert not shm.exists()

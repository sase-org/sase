from __future__ import annotations

from pathlib import Path

from sase.core.agent_artifact_index_lifecycle import (
    _projects_root_for_artifact_dir,
    delete_agent_artifact_index_artifacts,
    delete_agent_artifact_index_artifacts_bounded,
    update_agent_artifact_index_for_marker_mutation,
    upsert_agent_artifact_index_artifacts,
)
from sase.core.agent_scan_wire import AgentArtifactIndexUpdateWire


def test_projects_root_for_artifact_dir_derives_projects_root(tmp_path: Path) -> None:
    artifact_dir = (
        tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / "ts"
    )

    assert (
        _projects_root_for_artifact_dir(artifact_dir) == tmp_path / ".sase" / "projects"
    )


def test_delete_agent_artifact_index_artifacts_is_best_effort(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    index = tmp_path / "agent_artifact_index.sqlite"
    index.touch()
    deleted_paths: list[str] = []

    def fake_delete(index_path: Path, artifact_dir: Path) -> object:
        del index_path
        deleted_paths.append(str(artifact_dir))
        raise RuntimeError("stale index")

    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle.delete_agent_artifact_index_row",
        fake_delete,
    )

    assert (
        delete_agent_artifact_index_artifacts(["/tmp/missing"], index_path=index) == 0
    )
    assert deleted_paths == ["/tmp/missing"]


def test_bounded_delete_reports_process_lock_contention(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    index = tmp_path / "agent_artifact_index.sqlite"
    index.touch()
    calls: list[tuple[float, float]] = []

    def fake_delete(
        index_path: Path,
        artifact_dir: Path,
        *,
        lock_timeout_seconds: float,
        busy_timeout_seconds: float,
    ) -> None:
        del index_path, artifact_dir
        calls.append((lock_timeout_seconds, busy_timeout_seconds))
        return None

    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle."
        "delete_agent_artifact_index_row_bounded",
        fake_delete,
    )

    assert not delete_agent_artifact_index_artifacts_bounded(
        ["/tmp/busy"],
        index_path=index,
        timeout_seconds=0.25,
    )
    assert calls == [(0.25, 0.25)]


def test_bounded_delete_accepts_completed_zero_row_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    index = tmp_path / "agent_artifact_index.sqlite"
    index.touch()

    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle."
        "delete_agent_artifact_index_row_bounded",
        lambda *args, **kwargs: AgentArtifactIndexUpdateWire(
            schema_version=1,
            index_path=str(index),
            projects_root="",
        ),
    )

    assert delete_agent_artifact_index_artifacts_bounded(
        ["/tmp/already-gone"],
        index_path=index,
        timeout_seconds=0.25,
    )


def test_upsert_agent_artifact_index_artifacts_derives_root(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    artifact_dir = (
        tmp_path
        / ".sase"
        / "projects"
        / "proj"
        / "artifacts"
        / "ace-run"
        / "20260501010101"
    )
    artifact_dir.mkdir(parents=True)
    calls: list[tuple[Path, Path, Path]] = []

    def fake_upsert(
        index_path: Path,
        projects_root: Path,
        upsert_dir: Path,
        options: object,
    ) -> object:
        del options
        calls.append((index_path, projects_root, upsert_dir))
        return AgentArtifactIndexUpdateWire(
            schema_version=1,
            index_path=str(index_path),
            projects_root=str(projects_root),
            rows_indexed=1,
        )

    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle.upsert_agent_artifact_index_row",
        fake_upsert,
    )

    assert upsert_agent_artifact_index_artifacts([artifact_dir, artifact_dir]) == 1
    assert calls == [
        (
            Path.home() / ".sase" / "agent_artifact_index.sqlite",
            tmp_path / ".sase" / "projects",
            artifact_dir,
        )
    ]


def test_marker_mutation_helper_wraps_single_artifact_upsert(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    calls: list[tuple[list[Path | str | None], Path | str | None]] = []

    def fake_upsert(
        artifact_dirs: list[Path | str | None],
        *,
        index_path: Path | str | None = None,
    ) -> int:
        calls.append((artifact_dirs, index_path))
        return 1

    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle."
        "upsert_agent_artifact_index_artifacts",
        fake_upsert,
    )

    assert update_agent_artifact_index_for_marker_mutation(
        tmp_path,
        index_path=tmp_path / "index.sqlite",
    )
    assert calls == [([tmp_path], tmp_path / "index.sqlite")]

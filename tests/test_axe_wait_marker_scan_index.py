"""Index-backed waiting-marker scan: parity with the walk, reads, and fallback."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import sase.axe.wait_marker_scan as marker_scan
import sase.core.agent_artifact_index_recent as index_recent
from sase.axe.wait_marker_scan import (
    WAIT_SCAN_FULL_WALK_INTERVAL_SECONDS,
    record_wait_scan_full_walk,
    scan_waiting_markers,
    wait_scan_full_walk_due,
)
from sase.core.agent_artifact_index_recent import load_ace_run_index_listing
from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    rebuild_agent_artifact_index,
)


def _run_dir(projects_root: Path, project: str, timestamp: str) -> Path:
    artifact_dir = (
        projects_root
        / project
        / "artifacts"
        / "ace-run"
        / timestamp[:6]
        / timestamp[6:8]
        / timestamp
    )
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps({"name": f"agent-{timestamp}"}), encoding="utf-8"
    )
    return artifact_dir


def _write_waiting(artifact_dir: Path, **extra: object) -> None:
    (artifact_dir / "waiting.json").write_text(
        json.dumps({"waiting_for": ["dep"], **extra}), encoding="utf-8"
    )


@pytest.fixture
def projects_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("SASE_HOME", raising=False)
    root = tmp_path / ".sase" / "projects"
    root.mkdir(parents=True)
    return root


def _corpus(projects_root: Path) -> dict[str, Path]:
    dirs = {
        "pending": _run_dir(projects_root, "proj", "20260101120000"),
        "released": _run_dir(projects_root, "proj", "20260101120100"),
        "idle": _run_dir(projects_root, "proj", "20260102090000"),
        "hijacked": _run_dir(projects_root, "proj", "20260102090100"),
        "other": _run_dir(projects_root, "other", "20260103100000"),
    }
    _write_waiting(dirs["pending"])
    _write_waiting(dirs["released"])
    (dirs["released"] / "ready.json").write_text("{}\n", encoding="utf-8")
    _write_waiting(dirs["hijacked"], cancelled_by_hijack=True)
    _write_waiting(dirs["other"])
    (projects_root / "empty").mkdir()
    return dirs


def _rebuild_index(projects_root: Path) -> Path:
    index_path = default_agent_artifact_index_path()
    rebuild_agent_artifact_index(index_path, projects_root)
    return index_path


def _summary(scan: object) -> tuple[object, ...]:
    return (
        scan.projects,  # type: ignore[attr-defined]
        scan.artifacts,  # type: ignore[attr-defined]
        scan.waiting,  # type: ignore[attr-defined]
        scan.already_ready,  # type: ignore[attr-defined]
        [m.waiting_path for m in scan.pending],  # type: ignore[attr-defined]
        [m.waiting_path for m in scan.already_ready_markers],  # type: ignore[attr-defined]
        scan.dirs_by_project,  # type: ignore[attr-defined]
    )


def test_index_scan_matches_walk(projects_root: Path) -> None:
    _corpus(projects_root)
    _rebuild_index(projects_root)

    walked = scan_waiting_markers(projects_root)
    indexed = scan_waiting_markers(projects_root, prefer_index=True)

    assert walked.source == "walk"
    assert indexed.source == "index"
    assert indexed.fallback_reason is None
    assert _summary(indexed) == _summary(walked)
    assert indexed.projects == 3
    assert indexed.waiting == 3
    assert indexed.dirs_by_project["empty"] == []


def test_index_scan_reads_markers_only_for_indexed_waiters(
    projects_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = _corpus(projects_root)
    _rebuild_index(projects_root)
    recorded: list[Path] = []
    original = marker_scan._record_waiting_marker

    def recording(scan: object, project_name: str, artifact_dir: Path) -> None:
        recorded.append(artifact_dir)
        original(scan, project_name, artifact_dir)  # type: ignore[arg-type]

    monkeypatch.setattr(marker_scan, "_record_waiting_marker", recording)
    monkeypatch.setattr(
        marker_scan,
        "iter_agent_artifact_dirs",
        lambda *_a, **_k: pytest.fail("index scan must not walk artifact dirs"),
    )

    scan = scan_waiting_markers(projects_root, prefer_index=True)

    assert scan.source == "index"
    assert sorted(recorded) == sorted(
        dirs[key] for key in ("pending", "released", "hijacked", "other")
    )
    assert dirs["idle"] not in recorded


def test_index_scan_rereads_marker_files_not_index_state(projects_root: Path) -> None:
    dirs = _corpus(projects_root)
    _rebuild_index(projects_root)
    # The index still says these hold waiting.json; the files decide.
    (dirs["pending"] / "waiting.json").unlink()
    (dirs["other"] / "ready.json").write_text("{}\n", encoding="utf-8")

    scan = scan_waiting_markers(projects_root, prefer_index=True)

    assert scan.source == "index"
    assert scan.pending == []
    assert {m.waiting_path.parent for m in scan.already_ready_markers} == {
        dirs["other"],
        dirs["released"],
    }


def test_unindexed_marker_is_seen_only_by_the_walk(projects_root: Path) -> None:
    _corpus(projects_root)
    _rebuild_index(projects_root)
    late = _run_dir(projects_root, "proj", "20260104080000")
    _write_waiting(late)

    indexed = scan_waiting_markers(projects_root, prefer_index=True)
    walked = scan_waiting_markers(projects_root)

    assert late not in [m.waiting_path.parent for m in indexed.pending]
    assert late in [m.waiting_path.parent for m in walked.pending]


def test_missing_index_falls_back_to_walk(projects_root: Path) -> None:
    dirs = _corpus(projects_root)

    scan = scan_waiting_markers(projects_root, prefer_index=True)

    assert scan.source == "walk"
    assert scan.fallback_reason == "index_unavailable"
    assert {m.waiting_path.parent for m in scan.pending} == {
        dirs["pending"],
        dirs["other"],
    }


def test_failing_index_falls_back_to_walk(
    projects_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _corpus(projects_root)
    _rebuild_index(projects_root)

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("index locked")

    monkeypatch.setattr(index_recent, "load_agent_artifact_index_projection", _boom)

    scan = scan_waiting_markers(projects_root, prefer_index=True)

    assert scan.source == "walk"
    assert scan.fallback_reason == "index_unavailable"
    assert scan.waiting == 3


def test_listing_ignores_rows_outside_the_projects_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "projects"
    rows = [
        [f"{root}/proj/artifacts/ace-run/202601/01/20260101120000", "ace-run", 1],
        [f"{root}/proj/artifacts/ace-run/202601/01/20260101110000", "ace-run", 0],
        [f"{root}/proj/artifacts/fix-hook/20260101120000", "fix-hook", 1],
        [f"{tmp_path}/elsewhere/proj/artifacts/ace-run/20260101120000", "ace-run", 1],
        [f"{root}/proj-file", "ace-run", 1],
    ]
    monkeypatch.setattr(
        index_recent,
        "load_agent_artifact_index_projection",
        lambda *_a, **_k: {"rows": rows},
    )

    listing = load_ace_run_index_listing(tmp_path / "index.sqlite", root)

    assert listing.dirs_by_project == {
        "proj": [
            f"{root}/proj/artifacts/ace-run/202601/01/20260101110000",
            f"{root}/proj/artifacts/ace-run/202601/01/20260101120000",
        ]
    }
    assert listing.waiting_dirs_by_project == {
        "proj": [f"{root}/proj/artifacts/ace-run/202601/01/20260101120000"]
    }


def test_walked_dirs_is_derived_from_the_listing(projects_root: Path) -> None:
    dirs = _corpus(projects_root)

    scan = scan_waiting_markers(projects_root)

    assert scan.walked_dirs == set(dirs.values())


def test_full_walk_cadence(projects_root: Path) -> None:
    now = 1_800_000_000.0
    assert wait_scan_full_walk_due(now) is True

    record_wait_scan_full_walk(now)

    assert wait_scan_full_walk_due(now + 1) is False
    assert (
        wait_scan_full_walk_due(now + WAIT_SCAN_FULL_WALK_INTERVAL_SECONDS - 1) is False
    )
    assert wait_scan_full_walk_due(now + WAIT_SCAN_FULL_WALK_INTERVAL_SECONDS) is True
    # A stamp from the future (clock step back) must not suppress walks.
    assert wait_scan_full_walk_due(now - 60) is True


def test_full_walk_interval_matches_wait_checks_max_quiet() -> None:
    from sase.axe.config import load_axe_config

    cfg = load_axe_config()
    (chop,) = [
        c for c in cfg.lumberjacks["agent_waits"].chops if c.name == "wait_checks"
    ]
    assert isinstance(chop.trigger, dict)
    assert chop.trigger["max_quiet"] == f"{int(WAIT_SCAN_FULL_WALK_INTERVAL_SECONDS)}s"

from __future__ import annotations

import fcntl
import json
from pathlib import Path

from sase.memory.episodes import auto_build as auto_build_mod
from sase.memory.episodes.auto_build import (
    AUTO_BUILD_STATE_SCHEMA_VERSION,
    BUILD_STATE_FILE_NAME,
    BUILD_STATE_PREV_FILE_NAME,
    build_episode_auto_doctor_report,
    run_episode_auto_build,
)
from sase.memory.episodes.index import (
    episode_index_lock_path,
    episode_index_path,
    read_episode_index,
)
from sase.main.parser import create_parser
from sase.memory.cli_episodes import handle_memory_episodes_command


def test_auto_build_builds_new_done_markers_and_advances_checkpoint(
    tmp_path: Path,
) -> None:
    projects_root, repo_root = _seed_project(tmp_path)
    clock = _clock(
        "2026-05-28T21:30:00Z",
        "2026-05-28T21:30:01Z",
        "2026-05-28T21:30:02Z",
        "2026-05-28T21:30:03Z",
    )

    report = run_episode_auto_build(
        "proj",
        projects_root=projects_root,
        repo_root=repo_root,
        limit=10,
        now_fn=clock,
    )

    assert report.status == "success"
    assert report.built_count == 2
    assert report.changed_count == 2
    assert report.checkpoint_after == "20260519121000"
    state_path = projects_root / "proj" / "episodes" / BUILD_STATE_FILE_NAME
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["checkpoint_timestamp"] == "20260519121000"
    assert len(read_episode_index("proj", projects_root=projects_root)) == 2

    metrics_path = projects_root / "proj" / "episodes" / "metrics" / "202605.jsonl"
    metrics_rows = [
        json.loads(line)
        for line in metrics_path.read_text(encoding="utf-8").splitlines()
    ]
    assert metrics_rows[0]["components_built"] == 2
    assert metrics_rows[0]["episodes_changed"] == 2
    assert sum(metrics_rows[0]["importance_histogram"].values()) == 2

    idle_report = run_episode_auto_build(
        "proj",
        projects_root=projects_root,
        repo_root=repo_root,
        limit=10,
        now_fn=clock,
    )

    assert idle_report.status == "idle"
    assert idle_report.built_count == 0
    assert metrics_path.read_text(encoding="utf-8").count("\n") == 1


def test_auto_build_dry_run_does_not_write_state_metrics_or_episodes(
    tmp_path: Path,
) -> None:
    projects_root, repo_root = _seed_project(tmp_path, count=1)

    report = run_episode_auto_build(
        "proj",
        projects_root=projects_root,
        repo_root=repo_root,
        limit=10,
        dry_run=True,
        now_fn=_clock("2026-05-28T21:31:00Z", "2026-05-28T21:31:01Z"),
    )

    episodes_dir = projects_root / "proj" / "episodes"
    assert report.status == "dry_run"
    assert report.built_count == 1
    assert not (episodes_dir / BUILD_STATE_FILE_NAME).exists()
    assert not (episodes_dir / "metrics").exists()
    assert read_episode_index("proj", projects_root=projects_root) == []


def test_auto_build_does_not_advance_checkpoint_after_failed_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    projects_root, repo_root = _seed_project(tmp_path, count=1)

    def fail_write(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(auto_build_mod, "write_project_episode_unlocked", fail_write)

    report = run_episode_auto_build(
        "proj",
        projects_root=projects_root,
        repo_root=repo_root,
        limit=10,
        now_fn=_clock("2026-05-28T21:32:00Z", "2026-05-28T21:32:01Z"),
    )

    state = json.loads(
        (projects_root / "proj" / "episodes" / BUILD_STATE_FILE_NAME).read_text(
            encoding="utf-8"
        )
    )
    assert report.status == "error"
    assert state["checkpoint_timestamp"] is None
    assert state["consecutive_failures"] == 1
    assert "boom" in state["last_error"]


def test_auto_build_reports_lock_contention_without_writes(tmp_path: Path) -> None:
    projects_root, repo_root = _seed_project(tmp_path, count=1)
    lock_path = episode_index_lock_path(
        episode_index_path("proj", projects_root=projects_root)
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        report = run_episode_auto_build(
            "proj",
            projects_root=projects_root,
            repo_root=repo_root,
            limit=10,
        )
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    assert report.status == "lock_busy"
    assert not (projects_root / "proj" / "episodes" / BUILD_STATE_FILE_NAME).exists()


def test_auto_build_doctor_reports_and_repairs_corrupt_state(
    tmp_path: Path,
) -> None:
    episodes_dir = tmp_path / "projects" / "proj" / "episodes"
    episodes_dir.mkdir(parents=True)
    (episodes_dir / BUILD_STATE_PREV_FILE_NAME).write_text(
        json.dumps(
            {
                "schema_version": AUTO_BUILD_STATE_SCHEMA_VERSION,
                "project": "proj",
                "checkpoint_timestamp": "20260519120000",
                "checkpoint_artifact_dirs": [],
            }
        ),
        encoding="utf-8",
    )
    (episodes_dir / BUILD_STATE_FILE_NAME).write_text("{not-json", encoding="utf-8")

    report = build_episode_auto_doctor_report(
        "proj",
        projects_root=tmp_path / "projects",
    )

    assert report.status == "WARN"
    assert [repair["id"] for repair in report.repairs] == ["restore_build_state_prev"]
    assert report.repairs[0]["executed"] is False

    repaired = build_episode_auto_doctor_report(
        "proj",
        projects_root=tmp_path / "projects",
        repair=True,
    )

    state = json.loads(
        (episodes_dir / BUILD_STATE_FILE_NAME).read_text(encoding="utf-8")
    )
    assert repaired.repaired is True
    assert repaired.repairs[0]["executed"] is True
    assert state["checkpoint_timestamp"] == "20260519120000"


def test_memory_episodes_auto_status_and_doctor_cli_json(
    tmp_path: Path,
    capsys,
) -> None:
    projects_root, repo_root = _seed_project(tmp_path, count=1)

    auto_args = create_parser().parse_args(
        ["memory", "episodes", "auto", "-p", "proj", "-l", "1", "-j"]
    )
    handle_memory_episodes_command(
        auto_args,
        projects_root=projects_root,
        repo_root=repo_root,
    )
    auto_payload = json.loads(capsys.readouterr().out)
    assert auto_payload["status"] == "success"
    assert auto_payload["built_count"] == 1

    status_args = create_parser().parse_args(
        ["memory", "episodes", "status", "-p", "proj", "-j"]
    )
    handle_memory_episodes_command(status_args, projects_root=projects_root)
    status_payload = json.loads(capsys.readouterr().out)
    assert status_payload["state_status"] == "ok"
    assert status_payload["state"]["checkpoint_timestamp"] == "20260519120000"

    doctor_args = create_parser().parse_args(
        ["memory", "episodes", "doctor", "-p", "proj", "-j"]
    )
    handle_memory_episodes_command(doctor_args, projects_root=projects_root)
    doctor_payload = json.loads(capsys.readouterr().out)
    assert doctor_payload["status"] == "OK"


def _seed_project(
    tmp_path: Path,
    *,
    count: int = 2,
) -> tuple[Path, Path]:
    projects_root = tmp_path / "projects"
    chats_dir = tmp_path / "chats"
    chats_dir.mkdir()
    for index in range(count):
        timestamp = f"2026051912{index * 10:02d}00"
        name = f"component-{index}"
        _seed_agent_artifact(
            projects_root,
            timestamp=timestamp,
            name=name,
            chat_path=_write_chat(chats_dir / f"{name}-260519_120000.md", name),
        )
    return projects_root, tmp_path


def _seed_agent_artifact(
    projects_root: Path,
    *,
    timestamp: str,
    name: str,
    chat_path: Path,
) -> None:
    artifact_dir = projects_root / "proj" / "artifacts" / "ace-run" / timestamp
    artifact_dir.mkdir(parents=True)
    output_path = artifact_dir / "output.txt"
    output_path.write_text(f"{name}\ncompleted\n", encoding="utf-8")
    (artifact_dir / "submitted_xprompt.md").write_text(
        f"# {name}\n\nBuild one component.\n",
        encoding="utf-8",
    )
    _write_json(
        artifact_dir / "agent_meta.json",
        {
            "name": name,
            "chat_path": str(chat_path),
            "phase_bead_id": "sase-48.8",
            "agent_family": "memory-episodes",
        },
    )
    _write_json(
        artifact_dir / "done.json",
        {
            "name": name,
            "outcome": "completed",
            "finished_at": 1.0,
            "response_path": str(chat_path),
            "output_path": str(output_path),
        },
    )


def _write_chat(path: Path, prompt: str) -> Path:
    path.write_text(
        f"## Prompt\n\n{prompt}\n\n## Response\n\nDone.\n",
        encoding="utf-8",
    )
    return path


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _clock(*timestamps: str):
    values = iter(timestamps)
    last = timestamps[-1]

    def now() -> str:
        nonlocal last
        try:
            last = next(values)
        except StopIteration:
            pass
        return last

    return now

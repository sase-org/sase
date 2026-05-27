from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from sase.core.episode_wire import (
    EPISODE_WIRE_SCHEMA_VERSION,
    EpisodeEventWire,
    EpisodeLessonWire,
    EpisodeNodeWire,
    EpisodeSourceRefWire,
    EpisodeWire,
)
from sase.memory.episodes.index import read_episode_index
from sase.memory.episodes.storage import (
    gc_corrupt_episode_temp_dirs,
    write_project_episode,
)


def test_write_project_episode_persists_files_and_index_idempotently(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    episode = _episode(tmp_path, summary="Storage summary.")

    first = write_project_episode(
        episode,
        lesson_markdown="# Custom Lesson\n",
        projects_root=projects_root,
    )
    second = write_project_episode(
        episode,
        lesson_markdown="# Custom Lesson\n",
        projects_root=projects_root,
    )

    assert first.changed is True
    assert second.changed is False
    assert first.episode_dir == projects_root / "proj" / "episodes" / "ep-storage"
    assert (
        json.loads(first.episode_json_path.read_text(encoding="utf-8"))["episode_id"]
        == "ep-storage"
    )
    assert first.lesson_path.read_text(encoding="utf-8") == "# Custom Lesson\n"

    source_rows = [
        json.loads(line)
        for line in first.sources_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [row["id"] for row in source_rows] == ["src-storage"]

    rows = read_episode_index("proj", projects_root=projects_root)
    assert len(rows) == 1
    row = rows[0]
    assert row.episode_id == "ep-storage"
    assert row.project == "proj"
    assert row.title == "Storage Episode"
    assert row.root_agent_names == ["planner"]
    assert row.changespec_name == "storage-cl"
    assert row.bead_ids == ["sase-45.4"]
    assert row.outcome == "completed"
    assert row.first_event_at == "2026-05-26T12:00:00Z"
    assert row.last_event_at == "2026-05-26T12:10:00Z"
    assert row.source_count == 1
    assert row.lesson_path == str(first.lesson_path.resolve(strict=False))
    assert row.content_sha256 == first.index_row.content_sha256


def test_write_project_episode_updates_same_index_row_when_content_changes(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    original = _episode(tmp_path, summary="Original summary.")
    updated = _episode(tmp_path, summary="Updated summary.")

    first = write_project_episode(original, projects_root=projects_root)
    second = write_project_episode(updated, projects_root=projects_root)

    rows = read_episode_index("proj", projects_root=projects_root)
    assert len(rows) == 1
    assert rows[0].episode_id == "ep-storage"
    assert rows[0].content_sha256 == second.index_row.content_sha256
    assert rows[0].content_sha256 != first.index_row.content_sha256
    assert "Updated summary." in second.episode_json_path.read_text(encoding="utf-8")


def test_gc_corrupt_episode_temp_dirs_only_removes_storage_temps(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    episodes_dir = projects_root / "proj" / "episodes"
    temp_dir = episodes_dir / ".ep-storage.tmp.abandoned"
    visible_dir = episodes_dir / "ep-storage"
    temp_dir.mkdir(parents=True)
    visible_dir.mkdir()
    (visible_dir / "lesson.md").write_text("# keep\n", encoding="utf-8")

    removed = gc_corrupt_episode_temp_dirs("proj", projects_root=projects_root)

    assert removed == [temp_dir]
    assert not temp_dir.exists()
    assert (visible_dir / "lesson.md").read_text(encoding="utf-8") == "# keep\n"


def test_concurrent_episode_writes_leave_one_complete_index_row(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    start_marker = tmp_path / "start"
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{repo_root / 'src'}{os.pathsep}{env.get('PYTHONPATH', '')}"
    procs = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                _CONCURRENT_WRITER,
                str(projects_root),
                str(start_marker),
                label,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        for label in ("A", "B")
    ]
    start_marker.write_text("go\n", encoding="utf-8")
    for proc in procs:
        stdout, stderr = proc.communicate(timeout=20)
        assert proc.returncode == 0, stdout + stderr

    rows = read_episode_index("proj", projects_root=projects_root)
    assert len(rows) == 1
    row = rows[0]
    episode_path = (
        projects_root / "proj" / "episodes" / "ep-concurrent" / ("episode.json")
    )
    lesson_path = episode_path.with_name("lesson.md")
    sources_path = episode_path.with_name("sources.jsonl")
    episode_data = json.loads(episode_path.read_text(encoding="utf-8"))

    assert row.episode_id == "ep-concurrent"
    assert row.title == episode_data["title"]
    assert lesson_path.read_text(encoding="utf-8").startswith(
        f"# {episode_data['title']}\n"
    )
    assert len(sources_path.read_text(encoding="utf-8").splitlines()) == 1


def _episode(tmp_path: Path, *, summary: str) -> EpisodeWire:
    source_path = tmp_path / "source.md"
    source_path.write_text("episode source\n", encoding="utf-8")
    source = EpisodeSourceRefWire(
        id="src-storage",
        kind="chat",
        path=str(source_path.resolve(strict=False)),
        label="source.md",
        exists=True,
        size_bytes=len("episode source\n"),
        sha256=hashlib.sha256(b"episode source\n").hexdigest(),
    )
    return EpisodeWire(
        schema_version=EPISODE_WIRE_SCHEMA_VERSION,
        episode_id="ep-storage",
        project="proj",
        title="Storage Episode",
        summary=summary,
        root_source_id=source.id,
        sources=[source],
        nodes=[
            EpisodeNodeWire(
                id="node-agent",
                kind="agent_run",
                label="planner",
                metadata={"outcome": "completed"},
            ),
            EpisodeNodeWire(
                id="node-changespec",
                kind="changespec",
                label="storage-cl",
                metadata={"name": "storage-cl"},
            ),
            EpisodeNodeWire(
                id="node-bead",
                kind="bead",
                label="sase-45.4",
                metadata={"id": "sase-45.4"},
            ),
        ],
        edges=[],
        events=[
            EpisodeEventWire(
                id="event-start",
                kind="agent_start",
                title="Agent started",
                timestamp="2026-05-26T12:00:00Z",
                evidence_ids=[source.id],
            ),
            EpisodeEventWire(
                id="event-finish",
                kind="agent_finish",
                title="Agent finished",
                timestamp="2026-05-26T12:10:00Z",
                evidence_ids=[source.id],
            ),
        ],
        lessons=[
            EpisodeLessonWire(
                id="lesson-1",
                kind="verification",
                text="Storage was verified.",
                evidence_ids=[source.id],
            )
        ],
    )


_CONCURRENT_WRITER = r"""
import hashlib
import sys
import time
from pathlib import Path

from sase.core.episode_wire import (
    EPISODE_WIRE_SCHEMA_VERSION,
    EpisodeNodeWire,
    EpisodeSourceRefWire,
    EpisodeWire,
)
from sase.memory.episodes.storage import write_project_episode

projects_root = Path(sys.argv[1])
start_marker = Path(sys.argv[2])
label = sys.argv[3]
deadline = time.time() + 10
while not start_marker.exists():
    if time.time() > deadline:
        raise RuntimeError("timed out waiting for start marker")
    time.sleep(0.01)

source_path = projects_root / f"source-{label}.txt"
source_path.parent.mkdir(parents=True, exist_ok=True)
content = f"source {label}\n"
source_path.write_text(content, encoding="utf-8")
source = EpisodeSourceRefWire(
    id=f"src-{label}",
    kind="chat",
    path=str(source_path.resolve(strict=False)),
    label=source_path.name,
    exists=True,
    size_bytes=len(content.encode("utf-8")),
    sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
)
episode = EpisodeWire(
    schema_version=EPISODE_WIRE_SCHEMA_VERSION,
    episode_id="ep-concurrent",
    project="proj",
    title=f"Concurrent {label}",
    summary=f"Summary {label}",
    root_source_id=source.id,
    sources=[source],
    nodes=[
        EpisodeNodeWire(
            id=f"node-{label}",
            kind="agent_run",
            label=f"agent-{label}",
            metadata={"outcome": "completed"},
        )
    ],
    edges=[],
    events=[],
    lessons=[],
)
write_project_episode(
    episode,
    lesson_markdown=f"# Concurrent {label}\n",
    projects_root=projects_root,
)
"""

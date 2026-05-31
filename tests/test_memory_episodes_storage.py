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
from sase.memory.episodes.identity import (
    read_episode_alias_rows,
    read_episode_member_rows,
)
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


def test_write_project_episode_omits_lesson_file_for_v2_components(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    chat_path = tmp_path / "component-chat.md"
    episode = _identity_episode(
        "ep-v2-component",
        component_key="component/v2",
        sources=[_source_ref(chat_path, kind="chat", content="component\n")],
        title="V2 Component",
    )

    result = write_project_episode(
        episode,
        lesson_markdown="# Should Not Persist\n",
        projects_root=projects_root,
    )

    assert result.episode_json_path.is_file()
    assert result.sources_path.is_file()
    assert not result.lesson_path.exists()
    assert result.index_row.lesson_path == ""
    assert result.index_row.legacy_lesson_path is None


def test_write_project_episode_records_component_members(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    chat_path = tmp_path / "chat-a.md"
    artifact_dir = projects_root / "proj" / "artifacts" / "ace-run" / "20260526120000"
    done_path = artifact_dir / "done.json"
    episode = _identity_episode(
        "ep-root",
        component_key="component/root",
        sources=[
            _source_ref(chat_path, kind="chat", content="chat a\n"),
            _source_ref(done_path, kind="artifact", content='{"done":true}\n'),
        ],
    )

    write_project_episode(episode, projects_root=projects_root)

    member_keys = {
        row.member_key
        for row in read_episode_member_rows("proj", projects_root=projects_root)
    }
    chat_digest = episode.sources[0].sha256[:16] if episode.sources[0].sha256 else ""
    assert member_keys == {
        "component:component/root",
        "artifact:proj/ace-run/20260526120000",
        f"chat:{chat_path.resolve(strict=False)}",
        f"chat:{chat_path.name}/{chat_digest}",
        f"artifact:{artifact_dir.resolve(strict=False)}",
    }
    assert read_episode_alias_rows("proj", projects_root=projects_root) == []


def test_write_project_episode_reuses_existing_canonical_for_connected_member(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    shared_chat = tmp_path / "shared-chat.md"
    fork_chat = tmp_path / "fork-chat.md"
    first = _identity_episode(
        "ep-root",
        component_key="component/root",
        sources=[_source_ref(shared_chat, kind="chat", content="shared\n")],
    )
    fork = _identity_episode(
        "ep-fork",
        component_key="component/fork",
        sources=[
            _source_ref(shared_chat, kind="chat", content="shared\n"),
            _source_ref(fork_chat, kind="chat", content="fork\n"),
        ],
        title="Fork Episode",
    )

    first_result = write_project_episode(first, projects_root=projects_root)
    fork_result = write_project_episode(fork, projects_root=projects_root)

    assert first_result.episode_id == "ep-root"
    assert fork_result.episode_id == "ep-root"
    aliases = read_episode_alias_rows("proj", projects_root=projects_root)
    assert [
        (row.alias_episode_id, row.canonical_episode_id, row.reason) for row in aliases
    ] == [("ep-fork", "ep-root", "existing_member")]
    members = read_episode_member_rows("proj", projects_root=projects_root)
    assert {row.member_key: row.canonical_episode_id for row in members}[
        f"chat:{fork_chat.resolve(strict=False)}"
    ] == "ep-root"


def test_write_project_episode_late_bridge_aliases_noncanonical_directory(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    chat_a = tmp_path / "a.md"
    chat_b = tmp_path / "b.md"
    write_project_episode(
        _identity_episode(
            "ep-a",
            component_key="component/a",
            sources=[_source_ref(chat_a, kind="chat", content="a\n")],
            title="Episode A",
        ),
        projects_root=projects_root,
    )
    write_project_episode(
        _identity_episode(
            "ep-b",
            component_key="component/b",
            sources=[_source_ref(chat_b, kind="chat", content="b\n")],
            title="Episode B",
        ),
        projects_root=projects_root,
    )

    bridge_result = write_project_episode(
        _identity_episode(
            "ep-a",
            component_key="component/a",
            sources=[
                _source_ref(chat_a, kind="chat", content="a\n"),
                _source_ref(chat_b, kind="chat", content="b\n"),
            ],
            title="Bridge Episode",
        ),
        projects_root=projects_root,
    )

    assert bridge_result.episode_id == "ep-a"
    aliases = read_episode_alias_rows("proj", projects_root=projects_root)
    assert [
        (row.alias_episode_id, row.canonical_episode_id, row.reason) for row in aliases
    ] == [("ep-b", "ep-a", "late_bridge")]
    old_episode = json.loads(
        (projects_root / "proj" / "episodes" / "ep-b" / "episode.json").read_text(
            encoding="utf-8"
        )
    )
    assert old_episode["episode_id"] == "ep-b"
    assert old_episode["title"] == "Episode B"


def test_write_project_episode_aliases_legacy_v1_without_rewriting_it(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    chat_path = tmp_path / "legacy-chat.md"
    legacy = _identity_episode(
        "ep-v1",
        component_key="",
        sources=[_source_ref(chat_path, kind="chat", content="legacy\n")],
        schema_version=1,
        status="legacy",
        title="Legacy Episode",
    )
    v2 = _identity_episode(
        "ep-v2",
        component_key="component/v2",
        sources=[_source_ref(chat_path, kind="chat", content="legacy\n")],
        title="V2 Episode",
    )

    write_project_episode(legacy, projects_root=projects_root)
    v2_result = write_project_episode(v2, projects_root=projects_root)

    assert v2_result.episode_id == "ep-v2"
    aliases = read_episode_alias_rows("proj", projects_root=projects_root)
    assert [
        (row.alias_episode_id, row.canonical_episode_id, row.reason) for row in aliases
    ] == [("ep-v1", "ep-v2", "v1_migration")]
    legacy_payload = json.loads(
        (projects_root / "proj" / "episodes" / "ep-v1" / "episode.json").read_text(
            encoding="utf-8"
        )
    )
    assert legacy_payload["title"] == "Legacy Episode"


def test_write_project_episode_migrates_old_path_dependent_v2_id(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "store" / "projects"
    timestamp = "20260526120000"
    old_artifact_dir = (
        tmp_path
        / "old-root"
        / "projects"
        / "proj"
        / "artifacts"
        / "ace-run"
        / timestamp
    )
    new_artifact_dir = (
        tmp_path
        / "new-root"
        / "projects"
        / "proj"
        / "artifacts"
        / "ace-run"
        / timestamp
    )
    old_component_key = (
        f"component/artifact/proj/{timestamp}/{old_artifact_dir.resolve(strict=False)}"
    )
    old = _identity_episode(
        "ep-old",
        component_key=old_component_key,
        sources=[
            _source_ref(
                old_artifact_dir / "done.json",
                kind="artifact",
                content='{"done":true}\n',
            )
        ],
        title="Old Path Dependent",
    )
    new = _identity_episode(
        "ep-new",
        component_key=f"component/artifact/proj/ace-run/{timestamp}",
        sources=[
            _source_ref(
                new_artifact_dir / "done.json",
                kind="artifact",
                content='{"done":true}\n',
            )
        ],
        title="New Logical",
    )

    write_project_episode(old, projects_root=projects_root)
    _write_old_v2_member_rows(
        projects_root,
        old_episode_id="ep-old",
        old_component_key=old_component_key,
        old_artifact_dir=old_artifact_dir,
    )
    new_result = write_project_episode(new, projects_root=projects_root)

    assert new_result.episode_id == "ep-new"
    aliases = read_episode_alias_rows("proj", projects_root=projects_root)
    assert [
        (row.alias_episode_id, row.canonical_episode_id, row.reason) for row in aliases
    ] == [("ep-old", "ep-new", "component_key_migration")]
    old_payload = json.loads(
        (projects_root / "proj" / "episodes" / "ep-old" / "episode.json").read_text(
            encoding="utf-8"
        )
    )
    assert old_payload["title"] == "Old Path Dependent"
    members = read_episode_member_rows("proj", projects_root=projects_root)
    assert {row.member_key: row.canonical_episode_id for row in members}[
        f"artifact:proj/ace-run/{timestamp}"
    ] == "ep-new"


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


def _source_ref(
    path: Path,
    *,
    kind: str,
    content: str,
) -> EpisodeSourceRefWire:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    data = content.encode("utf-8")
    return EpisodeSourceRefWire(
        id=f"src-{kind}-{hashlib.sha256(str(path).encode('utf-8')).hexdigest()[:12]}",
        kind=kind,
        path=str(path.resolve(strict=False)),
        label=path.name,
        exists=True,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def _identity_episode(
    episode_id: str,
    *,
    component_key: str,
    sources: list[EpisodeSourceRefWire],
    schema_version: int = EPISODE_WIRE_SCHEMA_VERSION,
    status: str = "active",
    title: str = "Identity Episode",
) -> EpisodeWire:
    return EpisodeWire(
        schema_version=schema_version,
        episode_id=episode_id,
        project="proj",
        title=title,
        summary=f"{title} summary.",
        root_source_id=sources[0].id,
        component_key=component_key,
        component_root_kind="artifact" if component_key else "",
        status=status,
        sources=sources,
        nodes=[],
        edges=[],
        events=[
            EpisodeEventWire(
                id=f"event-{episode_id}",
                kind="agent_finish",
                title="Agent finished",
                timestamp="2026-05-26T12:00:00Z",
                evidence_ids=[sources[0].id],
            )
        ],
        lessons=[],
    )


def _write_old_v2_member_rows(
    projects_root: Path,
    *,
    old_episode_id: str,
    old_component_key: str,
    old_artifact_dir: Path,
) -> None:
    rows = [
        {
            "schema_version": 1,
            "project": "proj",
            "member_key": f"component:{old_component_key}",
            "member_kind": "component",
            "canonical_episode_id": old_episode_id,
        },
        {
            "schema_version": 1,
            "project": "proj",
            "member_key": f"artifact:{old_artifact_dir.resolve(strict=False)}",
            "member_kind": "artifact",
            "canonical_episode_id": old_episode_id,
        },
    ]
    members_path = projects_root / "proj" / "episodes" / "members.jsonl"
    members_path.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


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

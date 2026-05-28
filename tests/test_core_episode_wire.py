from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sase.core.episode_facade import (
    canonical_episode_json,
    episode_wire_schema_version,
    generate_episode_id,
    generate_source_id,
    generate_v2_episode_id,
    verify_episode_sources,
)
from sase.core.episode_wire import (
    EPISODE_WIRE_SCHEMA_VERSION,
    EpisodeEdgeWire,
    EpisodeEventWire,
    EpisodeImportanceFactorWire,
    EpisodeLessonWire,
    EpisodeNodeWire,
    EpisodeSafetyWire,
    EpisodeSourceRefWire,
    EpisodeStorageIndexRowWire,
    EpisodeWeakRefsWire,
    EpisodeWire,
    episode_storage_index_row_from_dict,
    episode_wire_from_dict,
)


def _source(
    id: str,
    kind: str,
    path: str,
    size_bytes: int,
    sha256: str,
) -> EpisodeSourceRefWire:
    return EpisodeSourceRefWire(
        id=id,
        kind=kind,
        path=path,
        exists=True,
        size_bytes=size_bytes,
        sha256=sha256,
    )


def test_episode_round_trips_through_rust_canonical_json() -> None:
    episode = EpisodeWire(
        schema_version=EPISODE_WIRE_SCHEMA_VERSION,
        episode_id="ep-test",
        project="sase",
        title="Episode",
        summary="Summary",
        root_source_id="src-b",
        sources=[
            _source("src-b", "chat", "b.md", 2, "bbb"),
            _source("src-a", "plan", "a.md", 1, "aaa"),
        ],
        nodes=[
            EpisodeNodeWire(id="node-b", kind="chat"),
            EpisodeNodeWire(id="node-a", kind="plan"),
        ],
        edges=[
            EpisodeEdgeWire(
                id="edge-a",
                from_node_id="node-a",
                to_node_id="node-b",
                kind="links",
                evidence_ids=["src-b", "src-a"],
            )
        ],
        events=[
            EpisodeEventWire(
                id="event-b",
                kind="finish",
                title="Finish",
                timestamp="2026-05-02T00:00:00Z",
            ),
            EpisodeEventWire(
                id="event-a",
                kind="start",
                title="Start",
                timestamp="2026-05-01T00:00:00Z",
            ),
        ],
        lessons=[
            EpisodeLessonWire(
                id="lesson-a",
                kind="goal",
                text="Goal",
                evidence_ids=["src-b", "src-a"],
            )
        ],
    )

    canonical = canonical_episode_json(episode)
    payload = json.loads(canonical)
    round_tripped = episode_wire_from_dict(payload)

    assert canonical.endswith("\n")
    assert [source.id for source in round_tripped.sources] == ["src-a", "src-b"]
    assert [node.id for node in round_tripped.nodes] == ["node-a", "node-b"]
    assert round_tripped.edges[0].evidence_ids == ["src-a", "src-b"]
    assert canonical_episode_json(round_tripped) == canonical
    assert episode_wire_schema_version() == EPISODE_WIRE_SCHEMA_VERSION


def test_episode_ids_are_stable_across_source_order() -> None:
    source_a = _source("src-a", "chat", "chat.md", 8, "aaa")
    source_b = _source("src-b", "plan", "plan.md", 9, "bbb")

    assert generate_source_id(source_a) == generate_source_id(source_a)
    assert generate_source_id(source_a) != generate_source_id(source_b)
    assert generate_episode_id("sase", "src-root", [source_a, source_b]) == (
        generate_episode_id("sase", "src-root", [source_b, source_a])
    )
    assert generate_v2_episode_id("sase", "component/chat/root") == (
        generate_v2_episode_id("sase", "component/chat/root")
    )
    assert generate_v2_episode_id("sase", "component/chat/root") != (
        generate_v2_episode_id("sase", "component/chat/other")
    )


def test_v2_episode_with_no_lessons_round_trips_and_uses_component_id() -> None:
    component_key = "component/chat/src-root"
    episode = EpisodeWire(
        schema_version=EPISODE_WIRE_SCHEMA_VERSION,
        episode_id=generate_v2_episode_id("sase", component_key),
        project="sase",
        title="Component Episode",
        summary="Connected component evidence.",
        root_source_id="src-root",
        component_key=component_key,
        component_root_kind="chat",
        status="active",
        importance_score=84,
        importance_band="high",
        importance_factors=[
            EpisodeImportanceFactorWire(
                kind="verification",
                label="Focused checks passed",
                score=25,
                evidence_ids=["src-root"],
                metadata={"command": "cargo test"},
            )
        ],
        safety=EpisodeSafetyWire(
            untrusted_transcript_text=True,
            private_or_missing_source_flags=["private-chat"],
        ),
        weak_refs=EpisodeWeakRefsWire(
            changespec_names=["memory"],
            bead_ids=["sase-48.1"],
            agent_families=["coder"],
            touched_paths=["src/sase/core/episode_wire.py"],
        ),
        lessons=[],
    )

    payload = json.loads(canonical_episode_json(episode))
    round_tripped = episode_wire_from_dict(payload)

    assert payload["schema_version"] == 2
    assert payload["lessons"] == []
    assert payload["episode_id"] == generate_v2_episode_id("sase", component_key)
    assert round_tripped == episode


def test_v1_episode_and_index_row_parse_with_compatibility_defaults(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "legacy.md"
    source_path.write_text("legacy evidence\n", encoding="utf-8")
    source_bytes = source_path.read_bytes()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    episode = episode_wire_from_dict(
        {
            "schema_version": 1,
            "episode_id": "ep-legacy",
            "project": "sase",
            "title": "Legacy Episode",
            "summary": "Legacy lesson summary.",
            "root_source_id": "src-legacy",
            "sources": [
                {
                    "id": "src-legacy",
                    "kind": "chat",
                    "path": str(source_path),
                    "label": None,
                    "exists": True,
                    "size_bytes": len(source_bytes),
                    "sha256": source_sha,
                }
            ],
            "nodes": [],
            "edges": [],
            "events": [],
            "lessons": [
                {
                    "id": "lesson-1",
                    "kind": "goal",
                    "text": "Legacy lessons remain readable.",
                    "evidence_ids": ["src-legacy"],
                    "source_confidence": "deterministic",
                }
            ],
            "metadata": {},
        }
    )
    row = episode_storage_index_row_from_dict(
        {
            "schema_version": 1,
            "episode_id": "ep-legacy",
            "project": "sase",
            "title": "Legacy Episode",
            "source_count": 1,
            "lesson_path": "/tmp/lesson.md",
            "content_sha256": "abc123",
        }
    )
    report = verify_episode_sources(episode.episode_id, episode.sources)

    assert episode.status == "legacy"
    assert episode.lessons[0].text == "Legacy lessons remain readable."
    assert row == EpisodeStorageIndexRowWire(
        schema_version=1,
        episode_id="ep-legacy",
        project="sase",
        title="Legacy Episode",
        source_count=1,
        content_sha256="abc123",
        status="legacy",
        lesson_path="/tmp/lesson.md",
        legacy_lesson_path="/tmp/lesson.md",
    )
    assert report.ok is True


def test_verify_episode_sources_reports_drift(tmp_path: Path) -> None:
    ok_path = tmp_path / "ok.txt"
    ok_path.write_text("ok\n", encoding="utf-8")
    changed_path = tmp_path / "changed.txt"
    changed_path.write_text("new\n", encoding="utf-8")

    ok_sha = hashlib.sha256(b"ok\n").hexdigest()
    report = verify_episode_sources(
        "ep-test",
        [
            EpisodeSourceRefWire(
                id="src-ok",
                kind="artifact",
                path=str(ok_path),
                exists=True,
                size_bytes=3,
                sha256=ok_sha,
            ),
            EpisodeSourceRefWire(
                id="src-missing",
                kind="artifact",
                path=str(tmp_path / "missing.txt"),
                exists=True,
                size_bytes=1,
                sha256="bad",
            ),
            EpisodeSourceRefWire(
                id="src-changed",
                kind="artifact",
                path=str(changed_path),
                exists=True,
                size_bytes=3,
                sha256="old",
            ),
        ],
    )

    statuses = {result.source_id: result.status for result in report.results}
    assert report.ok is False
    assert report.ok_count == 1
    assert report.missing_count == 1
    assert report.changed_count == 1
    assert statuses == {
        "src-changed": "changed",
        "src-missing": "missing",
        "src-ok": "ok",
    }

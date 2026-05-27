from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.core.episode_facade import canonical_episode_json
from sase.core.episode_wire import (
    EPISODE_WIRE_SCHEMA_VERSION,
    EpisodeEdgeWire,
    EpisodeEventWire,
    EpisodeNodeWire,
    EpisodeSourceRefWire,
)
from sase.memory.episodes.builder import build_episode
from sase.memory.episodes.collector import EpisodeDraft
from sase.memory.episodes.render import render_lesson_markdown
from sase.memory.episodes.verify import verify_episode


def test_build_episode_renders_source_grounded_golden_lesson(tmp_path: Path) -> None:
    draft = _draft_fixture(tmp_path)

    episode = build_episode(draft)
    canonical = canonical_episode_json(episode)
    lesson_md = render_lesson_markdown(episode)

    assert canonical == canonical_episode_json(build_episode(draft))
    assert canonical.endswith("\n")
    assert episode.schema_version == EPISODE_WIRE_SCHEMA_VERSION
    assert episode.title == "Build Deterministic Lesson Builder"
    assert all(lesson.evidence_ids for lesson in episode.lessons)
    assert {lesson.kind for lesson in episode.lessons} >= {
        "decision",
        "feedback",
        "goal",
        "implementation",
        "memory_context",
        "question_answer",
        "verification",
    }
    assert "`just check`" in lesson_md
    assert "missing.diff" in lesson_md

    normalized_payload = _normalize_payload(json.loads(canonical), tmp_path)
    assert normalized_payload["title"] == "Build Deterministic Lesson Builder"
    assert normalized_payload["metadata"] == {
        "agent_names": "builder-agent",
        "agent_record_count": "1",
        "chat_count": "1",
        "first_event_at": "2026-05-26T12:00:00Z",
        "last_event_at": "2026-05-26T12:05:00Z",
        "lesson_count": "8",
        "selector_kind": "artifact_dir",
        "selector_value": "$TMP/artifacts/20260526120000",
        "source_count": "11",
    }
    lesson_rows = [
        (lesson["kind"], lesson["text"], lesson["evidence_ids"])
        for lesson in normalized_payload["lessons"]
    ]
    kind_order = {
        "goal": 0,
        "decision": 1,
        "feedback": 2,
        "question_answer": 3,
        "implementation": 4,
        "verification": 5,
        "memory_context": 6,
    }
    assert sorted(lesson_rows, key=lambda row: (kind_order[row[0]], row[1])) == [
        (
            "goal",
            "Goal: Build Deterministic Lesson Builder",
            ["src-prompt"],
        ),
        (
            "decision",
            "Plan decision recorded action `approve` with approval.",
            ["src-meta"],
        ),
        (
            "feedback",
            "Feedback was recorded: `tighten the renderer output`.",
            ["src-feedback"],
        ),
        (
            "question_answer",
            "Question and answer evidence was recorded: `include hashes?`.",
            ["src-qa"],
        ),
        (
            "implementation",
            "Work evidence includes `missing.diff`, `output.txt`, `plan.md`.",
            ["src-diff", "src-output", "src-plan"],
        ),
        (
            "verification",
            "Recorded agent outcomes: `builder-agent`=`completed`.",
            ["src-done"],
        ),
        (
            "verification",
            "Verification command(s) were explicitly mentioned: `just check`.",
            ["src-chat", "src-output"],
        ),
        (
            "memory_context",
            "Memory context was captured from `dynamic_memory.json`, `memory_reads.jsonl`.",
            ["src-dynamic", "src-memory-read"],
        ),
    ]

    normalized_lesson = _normalize_text(lesson_md, tmp_path)
    assert normalized_lesson.startswith("# Build Deterministic Lesson Builder\n\n")
    assert "## Sources\n\n" in normalized_lesson
    assert "- [src-chat] chat `chat.md`: `$TMP/chat.md`" in normalized_lesson
    assert (
        "[src-diff] artifact `missing.diff`: `$TMP/missing.diff` (missing)"
        in normalized_lesson
    )


def test_verify_episode_reports_source_drift_without_mutation(tmp_path: Path) -> None:
    draft = _draft_fixture(tmp_path)
    episode = build_episode(draft)
    prompt_source = next(
        source for source in episode.sources if source.id == "src-prompt"
    )
    expected_sha = prompt_source.sha256

    assert verify_episode(episode).ok is True

    (tmp_path / "submitted_xprompt.md").write_text(
        "# Changed Goal\n\nA different prompt.\n",
        encoding="utf-8",
    )

    report = verify_episode(episode)

    assert report.ok is False
    assert report.changed_count == 1
    assert {result.source_id: result.status for result in report.results}[
        "src-prompt"
    ] == "changed"
    assert prompt_source.sha256 == expected_sha


def _draft_fixture(tmp_path: Path) -> EpisodeDraft:
    artifact_dir = tmp_path / "artifacts" / "20260526120000"
    artifact_dir.mkdir(parents=True)

    prompt = tmp_path / "submitted_xprompt.md"
    prompt.write_text(
        "# Build Deterministic Lesson Builder\n\n"
        "Render a source-grounded episode lesson.\n",
        encoding="utf-8",
    )
    meta = artifact_dir / "agent_meta.json"
    _write_json(
        meta,
        {
            "name": "builder-agent",
            "plan_action": "approve",
            "plan_approved": True,
            "plan_submitted_at": ["2026-05-26T12:01:00Z"],
        },
    )
    done = artifact_dir / "done.json"
    _write_json(
        done,
        {
            "name": "builder-agent",
            "outcome": "completed",
            "finished_at": datetime(2026, 5, 26, 12, 5, tzinfo=UTC).timestamp(),
        },
    )
    feedback = artifact_dir / "plan_feedback.jsonl"
    feedback.write_text(
        json.dumps({"feedback": "tighten the renderer output"}) + "\n",
        encoding="utf-8",
    )
    qa = artifact_dir / "qa_log.jsonl"
    qa.write_text(
        json.dumps({"question": "include hashes?", "selected": ["yes"]}) + "\n",
        encoding="utf-8",
    )
    dynamic = artifact_dir / "dynamic_memory.json"
    _write_json(dynamic, {"matches": ["episode design"]})
    memory_read = artifact_dir / "memory_reads.jsonl"
    memory_read.write_text(
        json.dumps({"path": "memory/long/generated_skills.md"}) + "\n",
        encoding="utf-8",
    )

    chat = tmp_path / "chat.md"
    chat.write_text(
        "## Prompt\n\nBuild it.\n\n"
        "## Response\n\nImplemented renderer. Ran `just check` and it passed.\n",
        encoding="utf-8",
    )
    output = tmp_path / "output.txt"
    output.write_text("just check\nall checks passed\n", encoding="utf-8")
    plan = tmp_path / "plan.md"
    plan.write_text("# Episode Builder Plan\n\nBuild the renderer.\n", encoding="utf-8")
    missing_diff = tmp_path / "missing.diff"

    sources = [
        _file_source("src-chat", "chat", chat, "chat.md"),
        _file_source("src-done", "artifact", done, "done.json"),
        _missing_source("src-diff", "artifact", missing_diff, "missing.diff"),
        _file_source("src-dynamic", "dynamic_memory", dynamic, "dynamic_memory.json"),
        _file_source("src-feedback", "feedback", feedback, "plan_feedback.jsonl"),
        _file_source(
            "src-memory-read", "memory_read", memory_read, "memory_reads.jsonl"
        ),
        _file_source("src-meta", "artifact", meta, "agent_meta.json"),
        _file_source("src-output", "artifact", output, "output.txt"),
        _file_source("src-plan", "plan", plan, "plan.md"),
        _file_source("src-prompt", "artifact", prompt, "submitted_xprompt.md"),
        _file_source("src-qa", "question", qa, "qa_log.jsonl"),
    ]
    nodes = [
        EpisodeNodeWire(
            id="node-agent",
            kind="agent_run",
            label="builder-agent",
            source_id="src-meta",
            metadata={"outcome": "completed"},
        ),
        EpisodeNodeWire(
            id="node-chat",
            kind="chat",
            label="chat.md",
            source_id="src-chat",
            metadata={"path": str(chat)},
        ),
        EpisodeNodeWire(
            id="node-plan",
            kind="plan",
            label="plan.md",
            source_id="src-plan",
            metadata={"path": str(plan)},
        ),
    ]
    edges = [
        EpisodeEdgeWire(
            id="edge-chat",
            from_node_id="node-agent",
            to_node_id="node-chat",
            kind="response_chat",
            evidence_ids=["src-chat"],
        ),
        EpisodeEdgeWire(
            id="edge-plan",
            from_node_id="node-agent",
            to_node_id="node-plan",
            kind="plan",
            evidence_ids=["src-plan"],
        ),
    ]
    events = [
        EpisodeEventWire(
            id="event-start",
            kind="agent_start",
            title="Agent builder-agent started",
            timestamp="2026-05-26T12:00:00Z",
            evidence_ids=["src-meta"],
        ),
        EpisodeEventWire(
            id="event-finish",
            kind="agent_finish",
            title="Agent builder-agent finished",
            timestamp="2026-05-26T12:05:00Z",
            description="completed",
            evidence_ids=["src-done"],
        ),
    ]
    return EpisodeDraft(
        schema_version=EPISODE_WIRE_SCHEMA_VERSION,
        project="proj",
        selector_kind="artifact_dir",
        selector_value=str(artifact_dir),
        root_source_id="src-prompt",
        root_node_id="node-agent",
        sources=sources,
        nodes=nodes,
        edges=edges,
        events=events,
        chat_turns=[],
        metadata={"agent_record_count": "1", "chat_count": "1"},
        warnings=[],
    )


def _file_source(
    source_id: str,
    kind: str,
    path: Path,
    label: str,
) -> EpisodeSourceRefWire:
    content = path.read_bytes()
    return EpisodeSourceRefWire(
        id=source_id,
        kind=kind,
        path=str(path.resolve(strict=False)),
        label=label,
        exists=True,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def _missing_source(
    source_id: str,
    kind: str,
    path: Path,
    label: str,
) -> EpisodeSourceRefWire:
    return EpisodeSourceRefWire(
        id=source_id,
        kind=kind,
        path=str(path.resolve(strict=False)),
        label=label,
        exists=False,
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _normalize_payload(value: Any, tmp_path: Path) -> Any:
    if isinstance(value, dict):
        return {
            key: "ep-normalized"
            if key == "episode_id"
            else _normalize_payload(item, tmp_path)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_normalize_payload(item, tmp_path) for item in value]
    if isinstance(value, str):
        return _normalize_text(value, tmp_path)
    return value


def _normalize_text(value: str, tmp_path: Path) -> str:
    return value.replace(str(tmp_path), "$TMP")

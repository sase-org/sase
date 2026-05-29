from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sase.core.episode_wire import (
    EPISODE_WIRE_SCHEMA_VERSION,
    EpisodeEdgeWire,
    EpisodeEventWire,
    EpisodeImportanceFactorWire,
    EpisodeLessonWire,
    EpisodeNodeWire,
    EpisodeSafetyWire,
    EpisodeSourceRefWire,
    EpisodeWeakRefsWire,
    EpisodeWire,
)


def _seed_agent_artifacts(tmp_path: Path) -> tuple[Path, Path]:
    projects_root = tmp_path / "projects"
    artifact_dir = projects_root / "proj" / "artifacts" / "ace-run" / "20260526120000"
    artifact_dir.mkdir(parents=True)
    chat_path = tmp_path / "chat.md"
    chat_path.write_text(
        "## Prompt\n\nBuild retry feedback memory.\n\n"
        "## Response\n\nImplemented it and ran `just check`.\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "output.txt"
    output_path.write_text("just check\npassed\n", encoding="utf-8")
    (artifact_dir / "submitted_xprompt.md").write_text(
        "# Retry Feedback Memory\n\nBuild an episode.\n",
        encoding="utf-8",
    )
    _write_json(
        artifact_dir / "agent_meta.json",
        {
            "name": "episode-agent",
            "chat_path": str(chat_path),
            "phase_bead_id": "sase-45.5",
            "plan_action": "approve",
            "plan_approved": True,
            "plan_submitted_at": ["2026-05-26T12:01:00Z"],
        },
    )
    _write_json(
        artifact_dir / "done.json",
        {
            "name": "episode-agent",
            "outcome": "completed",
            "finished_at": 1.0,
            "response_path": str(chat_path),
            "output_path": str(output_path),
        },
    )
    return projects_root, tmp_path


def _seed_split_agent_artifacts(tmp_path: Path) -> tuple[Path, Path]:
    projects_root = tmp_path / "projects"
    chats_dir = tmp_path / "chats"
    chats_dir.mkdir()
    _seed_agent_artifact(
        projects_root,
        timestamp="20260519120000",
        name="component-a",
        chat_path=_write_chat(chats_dir / "a-260519_120000.md", "Build split A."),
    )
    _seed_agent_artifact(
        projects_root,
        timestamp="20260519121000",
        name="component-b",
        chat_path=_write_chat(chats_dir / "b-260519_121000.md", "Build split B."),
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
            "changespec_name": "shared-cl",
            "phase_bead_id": "sase-48.5",
            "agent_family": "shared-family",
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


def _episode(source_path: Path) -> EpisodeWire:
    content = source_path.read_bytes()
    source = EpisodeSourceRefWire(
        id="src-cli",
        kind="chat",
        path=str(source_path.resolve(strict=False)),
        label=source_path.name,
        exists=True,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )
    return EpisodeWire(
        schema_version=EPISODE_WIRE_SCHEMA_VERSION,
        episode_id="ep-cli",
        project="proj",
        title="Retry Feedback Episode",
        summary="Captured retry feedback for deterministic memory.",
        root_source_id=source.id,
        sources=[source],
        nodes=[
            EpisodeNodeWire(
                id="node-agent",
                kind="agent_run",
                label="episode-agent",
                metadata={"outcome": "completed"},
            )
        ],
        edges=[],
        events=[
            EpisodeEventWire(
                id="event-finish",
                kind="agent_finish",
                title="Agent finished",
                timestamp="2026-05-26T12:00:00Z",
                evidence_ids=[source.id],
            )
        ],
        lessons=[
            EpisodeLessonWire(
                id="lesson-feedback",
                kind="feedback",
                text="Retry feedback should stay deterministic.",
                evidence_ids=[source.id],
            )
        ],
    )


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


def _inventory_episode(
    episode_id: str,
    tmp_path: Path,
    *,
    title: str,
    timestamp: str,
    agent: str,
    band: str,
    score: int,
    changespec: str,
    bead_id: str,
    warnings: list[str] | None = None,
    extra_timestamp: str | None = None,
) -> EpisodeWire:
    source = _source_ref(
        tmp_path / f"{episode_id}.md",
        kind="chat",
        content=f"{title}\n",
    )
    events = [
        EpisodeEventWire(
            id=f"event-{episode_id}-start",
            kind="agent_finish",
            title="Agent finished",
            timestamp=timestamp,
            evidence_ids=[source.id],
        )
    ]
    if extra_timestamp is not None:
        events.append(
            EpisodeEventWire(
                id=f"event-{episode_id}-end",
                kind="agent_finish",
                title="Agent finished later",
                timestamp=extra_timestamp,
                evidence_ids=[source.id],
            )
        )
    return EpisodeWire(
        schema_version=EPISODE_WIRE_SCHEMA_VERSION,
        episode_id=episode_id,
        project="proj",
        title=title,
        summary=f"{title} summary for inventory.",
        root_source_id=source.id,
        component_key=f"component/{episode_id}",
        component_root_kind="artifact",
        status="active",
        importance_score=score,
        importance_band=band,
        safety=EpisodeSafetyWire(warnings=warnings or []),
        sources=[source],
        nodes=[
            EpisodeNodeWire(
                id=f"agent-{episode_id}",
                kind="agent_run",
                label=agent,
                metadata={"outcome": "completed"},
            ),
            EpisodeNodeWire(
                id=f"chat-{episode_id}",
                kind="chat",
                label=f"{episode_id}.md",
                source_id=source.id,
            ),
        ],
        edges=[],
        events=events,
        lessons=[],
        metadata={
            "bead_ids": bead_id,
            "changespec_name": changespec,
        },
    )


def _identity_episode(
    episode_id: str,
    *,
    component_key: str,
    sources: list[EpisodeSourceRefWire],
    title: str,
) -> EpisodeWire:
    return EpisodeWire(
        schema_version=EPISODE_WIRE_SCHEMA_VERSION,
        episode_id=episode_id,
        project="proj",
        title=title,
        summary=f"{title} summary.",
        root_source_id=sources[0].id,
        component_key=component_key,
        component_root_kind="artifact",
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


def _drilldown_episode(tmp_path: Path) -> EpisodeWire:
    source = _source_ref(
        tmp_path / "drilldown.md",
        kind="chat",
        content="Planner prompt and response.\n",
    )
    return EpisodeWire(
        schema_version=EPISODE_WIRE_SCHEMA_VERSION,
        episode_id="ep-drill",
        project="proj",
        title="Drilldown Episode",
        summary="A connected planner/coder/retry episode for renderer drill-down.",
        root_source_id=source.id,
        component_key="component/drilldown",
        component_root_kind="artifact",
        status="active",
        importance_score=55,
        importance_band="medium",
        importance_factors=[
            EpisodeImportanceFactorWire(
                kind="verification_present",
                label="Verification evidence is present",
                score=12,
                evidence_ids=[source.id],
            )
        ],
        safety=EpisodeSafetyWire(warnings=["missing-source:src-missing"]),
        weak_refs=EpisodeWeakRefsWire(
            changespec_names=["cl-drill"],
            bead_ids=["sase-48.6"],
            agent_families=["planner"],
            touched_paths=["src/sase/memory/episodes/render.py"],
        ),
        sources=[source],
        nodes=[
            EpisodeNodeWire(
                id="node-agent",
                kind="agent_run",
                label="planner",
                source_id=source.id,
                metadata={"outcome": "completed"},
            ),
            EpisodeNodeWire(
                id="node-chat",
                kind="chat",
                label="drilldown.md",
                source_id=source.id,
            ),
            EpisodeNodeWire(
                id="node-changespec",
                kind="changespec",
                label="cl-drill",
                metadata={"name": "cl-drill"},
            ),
        ],
        edges=[
            EpisodeEdgeWire(
                id="edge-chat",
                from_node_id="node-agent",
                to_node_id="node-chat",
                kind="response_chat",
                evidence_ids=[source.id],
            ),
            EpisodeEdgeWire(
                id="edge-cl",
                from_node_id="node-agent",
                to_node_id="node-changespec",
                kind="changespec",
            ),
        ],
        events=[
            EpisodeEventWire(
                id="event-finish",
                kind="agent_finish",
                title="Planner finished",
                timestamp="2026-05-26T12:00:00Z",
                evidence_ids=[source.id],
            )
        ],
        lessons=[],
    )


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")

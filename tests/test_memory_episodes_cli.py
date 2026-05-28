from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

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
from sase.main.parser import create_parser
from sase.memory.cli_episodes import handle_memory_episodes_command
from sase.memory.episodes.storage import write_project_episode


def test_memory_episodes_cli_lists_shows_verifies_and_recalls(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projects_root = tmp_path / "projects"
    source_path = tmp_path / "source.md"
    source_path.write_text("retry feedback source\n", encoding="utf-8")
    episode = _episode(source_path)
    write_project_episode(
        episode,
        lesson_markdown=(
            "# Retry Feedback Episode\n\n"
            "The agent learned to preserve deterministic retry feedback.\n"
        ),
        projects_root=projects_root,
    )

    list_args = create_parser().parse_args(
        ["memory", "episodes", "list", "-p", "proj", "-j"]
    )
    handle_memory_episodes_command(list_args, projects_root=projects_root)
    list_payload = json.loads(capsys.readouterr().out)
    assert [row["episode_id"] for row in list_payload["episodes"]] == ["ep-cli"]

    show_args = create_parser().parse_args(
        ["memory", "episodes", "show", "ep-cli", "-p", "proj"]
    )
    handle_memory_episodes_command(show_args, projects_root=projects_root)
    assert "deterministic retry feedback" in capsys.readouterr().out

    timeline_args = create_parser().parse_args(
        ["memory", "episodes", "show", "ep-cli", "-p", "proj", "-f", "timeline"]
    )
    handle_memory_episodes_command(timeline_args, projects_root=projects_root)
    assert "Agent finished" in capsys.readouterr().out

    verify_args = create_parser().parse_args(
        ["memory", "episodes", "verify", "ep-cli", "-p", "proj", "-j"]
    )
    handle_memory_episodes_command(verify_args, projects_root=projects_root)
    verify_payload = json.loads(capsys.readouterr().out)
    assert verify_payload["reports"][0]["ok"] is True

    recall_args = create_parser().parse_args(
        [
            "memory",
            "episodes",
            "recall",
            "-p",
            "proj",
            "-q",
            "retry feedback",
            "-j",
        ]
    )
    handle_memory_episodes_command(recall_args, projects_root=projects_root)
    recall_payload = json.loads(capsys.readouterr().out)
    assert recall_payload["matches"][0]["episode_id"] == "ep-cli"
    assert recall_payload["matches"][0]["matched_terms"] == ["feedback", "retry"]


def test_memory_episodes_cli_resolves_alias_ids(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projects_root = tmp_path / "projects"
    chat_a = tmp_path / "chat-a.md"
    chat_b = tmp_path / "chat-b.md"
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
    write_project_episode(
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

    list_args = create_parser().parse_args(
        ["memory", "episodes", "list", "-p", "proj", "-j"]
    )
    handle_memory_episodes_command(list_args, projects_root=projects_root)
    list_payload = json.loads(capsys.readouterr().out)
    assert [row["episode_id"] for row in list_payload["episodes"]] == ["ep-a"]
    assert [
        (row["alias_episode_id"], row["canonical_episode_id"])
        for row in list_payload["aliases"]
    ] == [("ep-b", "ep-a")]

    show_args = create_parser().parse_args(
        ["memory", "episodes", "show", "ep-b", "-p", "proj"]
    )
    handle_memory_episodes_command(show_args, projects_root=projects_root)
    captured = capsys.readouterr()
    assert "Bridge Episode" in captured.out
    assert "`ep-b` is an alias for `ep-a`" in captured.err

    verify_args = create_parser().parse_args(
        ["memory", "episodes", "verify", "ep-b", "-p", "proj", "-j"]
    )
    handle_memory_episodes_command(verify_args, projects_root=projects_root)
    captured = capsys.readouterr()
    assert json.loads(captured.out)["reports"][0]["episode_id"] == "ep-a"
    assert "`ep-b` is an alias for `ep-a`" in captured.err

    recall_args = create_parser().parse_args(
        ["memory", "episodes", "recall", "-p", "proj", "-q", "ep-b", "-j"]
    )
    handle_memory_episodes_command(recall_args, projects_root=projects_root)
    recall_payload = json.loads(capsys.readouterr().out)
    assert recall_payload["matches"][0]["episode_id"] == "ep-a"


def test_memory_episodes_build_writes_episode_from_agent_selector(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
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

    build_args = create_parser().parse_args(
        ["memory", "episodes", "build", "-p", "proj", "-n", "episode-agent", "-j"]
    )
    handle_memory_episodes_command(
        build_args,
        projects_root=projects_root,
        repo_root=tmp_path,
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["wrote"] is True
    assert payload["episode_id"].startswith("ep-")
    assert payload["project"] == "proj"
    assert payload["source_count"] >= 4
    assert payload["schema_version"] == EPISODE_WIRE_SCHEMA_VERSION
    assert payload["build_request"] == {
        "schema_version": EPISODE_WIRE_SCHEMA_VERSION,
        "project": "proj",
        "selector_kind": "agent",
        "selector_value": "episode-agent",
        "since": None,
        "until": None,
        "limit": None,
        "dry_run": False,
        "force": False,
        "source_refs": payload["episode"]["sources"],
    }
    assert payload["build_report"] == {
        "schema_version": EPISODE_WIRE_SCHEMA_VERSION,
        "project": "proj",
        "source_count": payload["source_count"],
        "lesson_count": payload["lesson_count"],
        "episode_id": payload["episode_id"],
        "would_write": False,
        "changed": payload["changed"],
        "warnings": payload["warnings"],
    }
    assert Path(payload["episode_dir"], "episode.json").is_file()


def test_memory_episodes_split_build_writes_component_reports(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projects_root, repo_root = _seed_split_agent_artifacts(tmp_path)

    build_args = create_parser().parse_args(
        [
            "memory",
            "episodes",
            "build",
            "-p",
            "proj",
            "-s",
            "2026-05-19",
            "-u",
            "2026-05-19",
            "--split",
            "-j",
        ]
    )
    handle_memory_episodes_command(
        build_args,
        projects_root=projects_root,
        repo_root=repo_root,
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["split"] is True
    assert payload["aggregate"] is False
    assert payload["component_count"] == 2
    assert len(payload["build_reports"]) == 2
    assert len({component["episode_id"] for component in payload["components"]}) == 2
    assert all(
        component["build_report"]["episode_id"] == component["episode_id"]
        for component in payload["components"]
    )
    assert all(
        component["episode"]["lessons"] == [] for component in payload["components"]
    )
    assert all(
        not Path(component["episode_dir"], "lesson.md").exists()
        for component in payload["components"]
    )

    list_args = create_parser().parse_args(
        ["memory", "episodes", "list", "-p", "proj", "-j"]
    )
    handle_memory_episodes_command(list_args, projects_root=projects_root)
    list_payload = json.loads(capsys.readouterr().out)
    assert len(list_payload["episodes"]) == 2
    assert {episode["version"] for episode in list_payload["episodes"]} == {"v2"}


def test_memory_episodes_list_inventory_filters_groups_and_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projects_root = tmp_path / "projects"
    write_project_episode(
        _inventory_episode(
            "ep-high",
            tmp_path,
            title="Retry Recovery",
            timestamp="2026-05-19T10:00:00Z",
            agent="agent-a",
            band="high",
            score=90,
            changespec="cl-retry",
            bead_id="sase-48.5",
            warnings=["missing-source:chat"],
        ),
        projects_root=projects_root,
    )
    write_project_episode(
        _inventory_episode(
            "ep-low",
            tmp_path,
            title="No-Op Cleanup",
            timestamp="2026-05-21T10:00:00Z",
            agent="agent-b",
            band="low",
            score=10,
            changespec="cl-cleanup",
            bead_id="sase-48.7",
        ),
        projects_root=projects_root,
    )
    write_project_episode(
        _inventory_episode(
            "ep-span",
            tmp_path,
            title="Bridge Episode",
            timestamp="2026-05-18T22:00:00Z",
            agent="agent-c",
            band="medium",
            score=50,
            changespec="cl-bridge",
            bead_id="sase-48.6",
            extra_timestamp="2026-05-20T01:00:00Z",
        ),
        projects_root=projects_root,
    )

    human_args = create_parser().parse_args(
        [
            "memory",
            "episodes",
            "list",
            "-p",
            "proj",
            "-s",
            "2026-05-19",
            "-u",
            "2026-05-20",
            "-g",
            "day",
            "-b",
            "high",
        ]
    )
    handle_memory_episodes_command(human_args, projects_root=projects_root)
    human = capsys.readouterr().out
    assert "2026-05-19:" in human
    assert "ep-high" in human
    assert "Retry Recovery" in human
    assert "chats=1" in human
    assert "sources=1" in human
    assert "warnings=1" in human
    assert "ep-low" not in human

    json_args = create_parser().parse_args(
        [
            "memory",
            "episodes",
            "list",
            "-p",
            "proj",
            "-s",
            "2026-05-19",
            "-u",
            "2026-05-20",
            "-n",
            "agent-a",
            "-c",
            "cl-retry",
            "-B",
            "sase-48.5",
            "-q",
            "retry",
            "-o",
            "importance",
            "-j",
        ]
    )
    handle_memory_episodes_command(json_args, projects_root=projects_root)
    payload = json.loads(capsys.readouterr().out)
    assert [episode["episode_id"] for episode in payload["episodes"]] == ["ep-high"]
    assert payload["episodes"][0]["version"] == "v2"
    assert payload["episodes"][0]["warnings"] == ["missing-source:chat"]
    assert payload["filters"]["bead"] == "sase-48.5"

    span_args = create_parser().parse_args(
        [
            "memory",
            "episodes",
            "list",
            "-p",
            "proj",
            "-s",
            "2026-05-19",
            "-u",
            "2026-05-19",
            "-q",
            "bridge",
            "-j",
        ]
    )
    handle_memory_episodes_command(span_args, projects_root=projects_root)
    span_payload = json.loads(capsys.readouterr().out)
    assert [episode["episode_id"] for episode in span_payload["episodes"]] == [
        "ep-span"
    ]


def test_memory_episodes_show_v2_drill_down_formats(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projects_root = tmp_path / "projects"
    episode = _drilldown_episode(tmp_path)
    write_project_episode(episode, projects_root=projects_root)

    default_args = create_parser().parse_args(
        ["memory", "episodes", "show", "ep-drill", "-p", "proj"]
    )
    handle_memory_episodes_command(default_args, projects_root=projects_root)
    overview = capsys.readouterr().out
    assert "# Drilldown Episode" in overview
    assert "Importance: medium (55)" in overview
    assert "Weak Metadata" in overview

    graph_args = create_parser().parse_args(
        [
            "memory",
            "episodes",
            "show",
            "ep-drill",
            "-p",
            "proj",
            "-f",
            "graph",
            "-e",
            "all",
        ]
    )
    handle_memory_episodes_command(graph_args, projects_root=projects_root)
    graph = capsys.readouterr().out
    assert "Edge mode: all" in graph
    assert "planner -> drilldown.md [response_chat; strong]" in graph
    assert "planner -> cl-drill [changespec; weak]" in graph

    sources_args = create_parser().parse_args(
        ["memory", "episodes", "show", "ep-drill", "-p", "proj", "-f", "sources"]
    )
    handle_memory_episodes_command(sources_args, projects_root=projects_root)
    sources = capsys.readouterr().out
    assert "# Sources: Drilldown Episode" in sources
    assert "sha256=" in sources

    agent_args = create_parser().parse_args(
        [
            "memory",
            "episodes",
            "show",
            "ep-drill",
            "-p",
            "proj",
            "-f",
            "agent",
            "-j",
        ]
    )
    handle_memory_episodes_command(agent_args, projects_root=projects_root)
    payload = json.loads(capsys.readouterr().out)
    assert payload["episode_id"] == "ep-drill"
    assert payload["framing"].startswith("This is historical evidence")
    assert payload["source_refs"][0]["kind"] == "chat"


def test_memory_episodes_build_prints_progress_to_stderr_in_human_mode(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projects_root, repo_root = _seed_agent_artifacts(tmp_path)

    build_args = create_parser().parse_args(
        ["memory", "episodes", "build", "-p", "proj", "-n", "episode-agent"]
    )
    handle_memory_episodes_command(
        build_args, projects_root=projects_root, repo_root=repo_root
    )
    captured = capsys.readouterr()

    for label in ("Collecting", "Building", "Rendering", "Writing"):
        assert label in captured.err, (
            f"expected phase label {label!r} in stderr, got: {captured.err!r}"
        )
    assert captured.out.startswith("Built episode ep-")
    assert "project: proj" in captured.out
    assert "episode_dir:" in captured.out


def test_memory_episodes_build_is_silent_on_stderr_in_json_mode(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projects_root, repo_root = _seed_agent_artifacts(tmp_path)

    build_args = create_parser().parse_args(
        ["memory", "episodes", "build", "-p", "proj", "-n", "episode-agent", "-j"]
    )
    handle_memory_episodes_command(
        build_args, projects_root=projects_root, repo_root=repo_root
    )
    captured = capsys.readouterr()

    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["wrote"] is True


def test_memory_episodes_build_quiet_flag_suppresses_progress(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projects_root, repo_root = _seed_agent_artifacts(tmp_path)

    build_args = create_parser().parse_args(
        ["memory", "episodes", "build", "-p", "proj", "-n", "episode-agent", "-q"]
    )
    handle_memory_episodes_command(
        build_args, projects_root=projects_root, repo_root=repo_root
    )
    captured = capsys.readouterr()

    assert captured.err == ""
    assert captured.out.startswith("Built episode ep-")


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

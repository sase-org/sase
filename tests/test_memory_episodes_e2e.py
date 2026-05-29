from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import pytest

from sase.main.parser import create_parser
from sase.memory.cli_episodes import handle_memory_episodes_command


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "memory_episodes" / "e2e"
PROJECT = "sase-memory-e2e"


@dataclass(frozen=True)
class EpisodeE2EFixture:
    root: Path
    projects_root: Path
    repo_root: Path
    planner_chat: Path
    diff_path: Path


def test_memory_episodes_end_to_end_fixture_cli_flows(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = _materialize_fixture(tmp_path)

    agent_payload = _run_json(
        [
            "build",
            "-p",
            PROJECT,
            "-n",
            "episode-planner",
            "-j",
        ],
        fixture,
        capsys,
    )
    episode_id = agent_payload["episode_id"]
    episode = agent_payload["episode"]

    assert agent_payload["wrote"] is True
    assert episode["metadata"]["selector_kind"] == "agent"
    assert episode["metadata"]["agent_record_count"] == "3"
    assert episode["metadata"]["chat_count"] == "3"
    assert episode["metadata"]["changespec_names"] == "episode-e2e-cl"
    assert episode["metadata"]["bead_ids"] == "sase-45.8"
    assert {lesson["kind"] for lesson in episode["lessons"]} >= {
        "decision",
        "failure",
        "feedback",
        "goal",
        "implementation",
        "memory_context",
        "question_answer",
        "retry",
        "verification",
    }
    assert any(
        source["kind"] == "bead" and source["path"].endswith("issues.jsonl")
        for source in episode["sources"]
    )
    assert any(
        source["path"] == str(fixture.diff_path) and source["exists"] is True
        for source in episode["sources"]
    )

    changespec_payload = _run_json(
        [
            "build",
            "-p",
            PROJECT,
            "-c",
            "episode-e2e-cl",
            "-D",
            "-j",
        ],
        fixture,
        capsys,
    )
    assert changespec_payload["dry_run"] is True
    assert changespec_payload["episode"]["metadata"]["selector_kind"] == "changespec"
    assert (
        changespec_payload["episode"]["metadata"]["changespec_names"]
        == "episode-e2e-cl"
    )

    chat_payload = _run_json(
        [
            "build",
            "-p",
            PROJECT,
            "-C",
            str(fixture.planner_chat),
            "-D",
            "-j",
        ],
        fixture,
        capsys,
    )
    assert chat_payload["dry_run"] is True
    assert chat_payload["episode"]["metadata"]["selector_kind"] == "chat"
    assert chat_payload["episode"]["metadata"]["agent_record_count"] == "3"

    list_payload = _run_json(["list", "-p", PROJECT, "-j"], fixture, capsys)
    assert [row["episode_id"] for row in list_payload["episodes"]] == [episode_id]

    _run(["show", episode_id, "-p", PROJECT], fixture, capsys)
    lesson = capsys.readouterr().out
    assert "Keep retry evidence linked to the failed coder run" in lesson
    assert "Memory context was captured" in lesson
    assert "Retry lineage was recorded" in lesson

    _run(["show", episode_id, "-p", PROJECT, "-f", "timeline"], fixture, capsys)
    timeline = capsys.readouterr().out
    assert "Question round 1" in timeline
    assert "Retry started 1" in timeline
    assert "## episode-planner" in timeline
    assert "## episode-retry" in timeline
    assert "## episode_trace.json" not in timeline

    _run(["show", episode_id, "-p", PROJECT, "-f", "graph"], fixture, capsys)
    graph = capsys.readouterr().out
    assert "Edge mode: strong" in graph
    assert "episode-coder -> episode-coder" not in graph
    for weak_edge_kind in (
        "artifact",
        "diff",
        "feedback",
        "memory_context",
        "output",
        "plan",
        "question",
        "source",
    ):
        assert f"[{weak_edge_kind};" not in graph

    verify_payload = _run_json(
        ["verify", episode_id, "-p", PROJECT, "-j"], fixture, capsys
    )
    assert verify_payload["reports"][0]["ok"] is True

    recall_payload = _run_json(
        [
            "recall",
            "-p",
            PROJECT,
            "-q",
            "retry feedback",
            "-j",
        ],
        fixture,
        capsys,
    )
    assert recall_payload["matches"][0]["episode_id"] == episode_id

    fixture.diff_path.unlink()
    _run(
        ["verify", episode_id, "-p", PROJECT, "-j"],
        fixture,
        capsys,
        expected_exit=1,
    )
    drift_payload = json.loads(capsys.readouterr().out)
    drift_report = drift_payload["reports"][0]
    assert drift_report["ok"] is False
    assert drift_report["missing_count"] == 1
    assert any(
        result["path"] == str(fixture.diff_path) and result["status"] == "missing"
        for result in drift_report["results"]
    )


def _run_json(
    episode_args: list[str],
    fixture: EpisodeE2EFixture,
    capsys: pytest.CaptureFixture[str],
) -> dict[str, object]:
    _run(episode_args, fixture, capsys)
    return json.loads(capsys.readouterr().out)


def _run(
    episode_args: list[str],
    fixture: EpisodeE2EFixture,
    capsys: pytest.CaptureFixture[str],
    *,
    expected_exit: int | None = None,
) -> None:
    capsys.readouterr()
    args = create_parser().parse_args(["memory", "episodes", *episode_args])
    if expected_exit is None:
        handle_memory_episodes_command(
            args,
            projects_root=fixture.projects_root,
            repo_root=fixture.repo_root,
        )
        return

    with pytest.raises(SystemExit) as exc_info:
        handle_memory_episodes_command(
            args,
            projects_root=fixture.projects_root,
            repo_root=fixture.repo_root,
        )
    assert exc_info.value.code == expected_exit


def _materialize_fixture(tmp_path: Path) -> EpisodeE2EFixture:
    root = tmp_path / "episode-fixture"
    projects_root = root / "projects"
    repo_root = root / "repo"
    planner_chat = root / "chats" / "planner-260526_120000.md"
    coder_chat = root / "chats" / "coder-260526_121000.md"
    retry_chat = root / "chats" / "retry-260526_122000.md"
    plan_path = root / "plans" / "episode_plan.md"
    diff_path = root / "diffs" / "episode.diff"
    planner_artifact_dir = (
        projects_root / PROJECT / "artifacts" / "ace-run" / "20260526120000"
    )
    replacements = {
        "__CODER_CHAT__": str(coder_chat),
        "__CODER_OUTPUT__": str(root / "logs" / "coder-output.txt"),
        "__DIFF_PATH__": str(diff_path),
        "__PLAN_PATH__": str(plan_path),
        "__PLANNER_ARTIFACT_DIR__": str(planner_artifact_dir),
        "__PLANNER_CHAT__": str(planner_chat),
        "__PLANNER_OUTPUT__": str(root / "logs" / "planner-output.txt"),
        "__RETRY_CHAT__": str(retry_chat),
        "__RETRY_OUTPUT__": str(root / "logs" / "retry-output.txt"),
    }

    for source in sorted(FIXTURE_ROOT.rglob("*")):
        if source.is_dir():
            continue
        relative = source.relative_to(FIXTURE_ROOT)
        if relative.name.endswith(".tmpl"):
            relative = relative.with_name(relative.name.removesuffix(".tmpl"))
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        text = source.read_text(encoding="utf-8")
        for token, replacement in replacements.items():
            text = text.replace(token, replacement)
        target.write_text(text, encoding="utf-8")

    return EpisodeE2EFixture(
        root=root,
        projects_root=projects_root,
        repo_root=repo_root,
        planner_chat=planner_chat,
        diff_path=diff_path,
    )

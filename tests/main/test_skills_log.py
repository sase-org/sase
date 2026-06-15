"""Tests for ``sase skills log`` rendering and filtering."""

from __future__ import annotations

from dataclasses import asdict
import json
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from sase.main.parser import create_parser
from sase.skills.cli_log import (
    _render_skills_log_event,
    _render_skills_log_summary,
    handle_skills_log_command,
)
from sase.skills.use_log import SkillUseEvent, append_skill_use_event


def skill_use_event(
    *,
    use_id: str,
    skill_name: str,
    agent_name: str,
    timestamp: str,
    reason: str,
    runtime: str | None = "codex",
    project: str = "demo",
) -> SkillUseEvent:
    return SkillUseEvent(
        schema_version=1,
        id=use_id,
        timestamp=timestamp,
        project=project,
        cwd="/tmp/demo",
        skill_name=skill_name,
        agent_name=agent_name,
        agent_source="SASE_AGENT_NAME",
        artifacts_dir=None,
        reason=reason,
        runtime=runtime,
    )


def _console(output: StringIO, *, width: int = 180) -> Console:
    return Console(file=output, force_terminal=False, color_system=None, width=width)


def _append_events(events: tuple[SkillUseEvent, ...]) -> None:
    for event in events:
        append_skill_use_event(event)


def test_skills_log_summary_renders_grouped_use_stats() -> None:
    events = (
        skill_use_event(
            use_id="use-a",
            skill_name="sase_plan",
            agent_name="agent-a",
            timestamp="2026-06-14T12:00:00+00:00",
            reason="Need plan context",
        ),
        skill_use_event(
            use_id="use-b",
            skill_name="sase_plan",
            agent_name="agent-b",
            timestamp="2026-06-14T12:01:00+00:00",
            reason="Need updated plan context",
            runtime="claude",
        ),
        skill_use_event(
            use_id="use-c",
            skill_name="sase_questions",
            agent_name="agent-a",
            timestamp="2026-06-14T12:02:00+00:00",
            reason="Need question workflow",
        ),
    )
    output = StringIO()

    _render_skills_log_summary(events, console=_console(output), project_name="demo")

    text = output.getvalue()
    assert "SASE Skill Use Log" in text
    assert "Skill uses" in text
    assert "3" in text
    assert "Skills (2)" in text
    assert "sase_plan" in text
    assert "sase_questions" in text
    assert "agent-b" in text
    assert "Need updated plan context" in text


def test_skills_log_summary_renders_empty_state_for_unknown_filter() -> None:
    output = StringIO()

    _render_skills_log_summary(
        (),
        console=_console(output, width=120),
        project_name="demo",
        skill_filter="missing",
    )

    text = output.getvalue()
    assert "skill=missing" in text
    assert "No skill-use events match the current filters." in text


def test_skills_log_skill_drilldown_renders_individual_events() -> None:
    events = (
        skill_use_event(
            use_id="use-a",
            skill_name="sase_plan",
            agent_name="agent-a",
            timestamp="2026-06-14T12:00:00+00:00",
            reason="Need plan context",
        ),
        skill_use_event(
            use_id="use-b",
            skill_name="sase_plan",
            agent_name="agent-b",
            timestamp="2026-06-14T12:01:00+00:00",
            reason="Need updated plan context",
            runtime="claude",
        ),
    )
    output = StringIO()

    _render_skills_log_summary(
        events,
        console=_console(output),
        project_name="demo",
        skill_filter="sase_plan",
    )

    text = output.getvalue()
    assert "skill=sase_plan" in text
    assert "Skills (1)" in text
    assert "Skill Use Events (2)" in text
    assert "use-a" in text
    assert "use-b" in text
    assert "claude" in text
    assert "Need updated plan context" in text


def test_skills_log_agent_filter_renders_agents_panel() -> None:
    events = (
        skill_use_event(
            use_id="use-a",
            skill_name="sase_plan",
            agent_name="agent-a",
            timestamp="2026-06-14T12:00:00+00:00",
            reason="Need plan context",
        ),
        skill_use_event(
            use_id="use-c",
            skill_name="sase_questions",
            agent_name="agent-a",
            timestamp="2026-06-14T12:02:00+00:00",
            reason="Need question workflow",
        ),
    )
    output = StringIO()

    _render_skills_log_summary(
        events,
        console=_console(output),
        project_name="demo",
        agent_filter="agent-a",
    )

    text = output.getvalue()
    assert "agent=agent-a" in text
    assert "Agents (1)" in text
    assert "agent-a" in text
    assert "sase_questions" in text
    assert "Skill Use Events (2)" in text


def test_skills_log_runtime_filter_renders_runtimes_panel() -> None:
    events = (
        skill_use_event(
            use_id="use-a",
            skill_name="sase_plan",
            agent_name="agent-a",
            timestamp="2026-06-14T12:00:00+00:00",
            reason="Need plan context",
            runtime="codex",
        ),
        skill_use_event(
            use_id="use-c",
            skill_name="sase_questions",
            agent_name="agent-a",
            timestamp="2026-06-14T12:02:00+00:00",
            reason="Need question workflow",
            runtime="codex",
        ),
    )
    output = StringIO()

    _render_skills_log_summary(
        events,
        console=_console(output),
        project_name="demo",
        runtime_filter="codex",
    )

    text = output.getvalue()
    assert "runtime=codex" in text
    assert "Runtimes (1)" in text
    assert "codex" in text
    assert "Skill Use Events (2)" in text
    assert "Need question workflow" in text


def test_skills_log_composed_filters_render_matching_drilldown() -> None:
    events = (
        skill_use_event(
            use_id="use-b",
            skill_name="sase_plan",
            agent_name="agent-b",
            timestamp="2026-06-14T12:01:00+00:00",
            reason="Need updated plan context",
            runtime="codex",
        ),
    )
    output = StringIO()

    _render_skills_log_summary(
        events,
        console=_console(output),
        project_name="demo",
        agent_filter="agent-b",
        runtime_filter="codex",
        skill_filter="sase_plan",
    )

    text = output.getvalue()
    assert "agent=agent-b, runtime=codex, skill=sase_plan" in text
    assert "Skills (1)" in text
    assert "Agents (1)" in text
    assert "Runtimes (1)" in text
    assert "Skill Use Events (1)" in text
    assert "use-b" in text


def test_skills_log_json_output_filters_and_summarizes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path.name
    home = tmp_path / "home"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    _append_events(
        (
            skill_use_event(
                use_id="use-a",
                skill_name="sase_plan",
                agent_name="agent-a",
                timestamp="2026-06-14T12:00:00+00:00",
                reason="First",
                project=project,
            ),
            skill_use_event(
                use_id="use-b",
                skill_name="sase_plan",
                agent_name="agent-b",
                timestamp="2026-06-14T12:01:00+00:00",
                reason="Second",
                runtime="claude",
                project=project,
            ),
            skill_use_event(
                use_id="use-c",
                skill_name="sase_questions",
                agent_name="agent-b",
                timestamp="2026-06-14T12:02:00+00:00",
                reason="Third",
                project=project,
            ),
        )
    )
    args = create_parser().parse_args(
        ["skills", "log", "--skill", "sase_plan", "--runtime", "claude", "--json"]
    )

    handle_skills_log_command(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "filters": {"agent": None, "runtime": "claude", "skill": "sase_plan"},
        "project": project,
        "summary": [
            {
                "distinct_agent_count": 1,
                "last_agent": "agent-b",
                "last_reason": "Second",
                "last_used_at": "2026-06-14T12:01:00+00:00",
                "skill_name": "sase_plan",
                "use_count": 1,
            }
        ],
        "total_agents": 1,
        "total_runtimes": 1,
        "total_skill_uses": 1,
        "total_skills": 1,
    }


def test_skills_log_json_id_output_emits_raw_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path.name
    home = tmp_path / "home"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    event = skill_use_event(
        use_id="use-abcdef",
        skill_name="sase_plan",
        agent_name="agent-a",
        timestamp="2026-06-14T12:00:00+00:00",
        reason="Need plan",
        runtime=None,
        project=project,
    )
    append_skill_use_event(event)
    args = create_parser().parse_args(["skills", "log", "--id", "use-ab", "--json"])

    handle_skills_log_command(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload == asdict(event)


def test_skills_log_id_detail_renders_runtime_row() -> None:
    event = skill_use_event(
        use_id="use-a",
        skill_name="sase_plan",
        agent_name="agent-a",
        timestamp="2026-06-14T12:00:00+00:00",
        reason="Need plan",
        runtime="codex",
    )
    output = StringIO()

    _render_skills_log_event(event, console=_console(output), project_name="demo")

    text = output.getvalue()
    assert "Skill Use Event use-a" in text
    assert "Runtime" in text
    assert "codex" in text
    assert "Artifacts dir" in text
    assert "none" in text


def test_skills_log_unknown_id_reports_prefixed_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path.name
    home = tmp_path / "home"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: home)
    append_skill_use_event(
        skill_use_event(
            use_id="use-a",
            skill_name="sase_plan",
            agent_name="agent-a",
            timestamp="2026-06-14T12:00:00+00:00",
            reason="Need plan",
            project=project,
        )
    )
    args = create_parser().parse_args(["skills", "log", "--id", "missing"])

    with pytest.raises(SystemExit) as exc:
        handle_skills_log_command(args)

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("sase skills log:")
    assert "unknown skill-use event id: missing" in err

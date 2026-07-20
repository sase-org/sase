"""Tests for applying and representing Agents-tab wait conditions."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.actions.agents._wait_resume import (
    _prompt_wait_spec,
    _wait_modal_candidates,
)
from sase.ace.tui.modals import WaitModalResult
from sase.xprompt.directive_edit import PromptWaitDirective, set_prompt_wait
from tests.ace.tui._agent_wait_resume_helpers import (
    FakeWaitResumeApp,
    make_waiting_agent,
)


def test_apply_wait_overwrites_wait_conditions(tmp_path: Path) -> None:
    waiting_path = tmp_path / "waiting.json"
    waiting_path.write_text(
        json.dumps(
            {
                "waiting_for": ["old_dep"],
                "wait_duration": 300.0,
                "wait_until": "2026-05-01T12:00:00",
                "cl_name": "test_cl",
                "timestamp": "20240101120000",
            }
        ),
        encoding="utf-8",
    )
    agent = make_waiting_agent()
    app = FakeWaitResumeApp()

    with patch(
        "sase.ace.tui.actions.agents._directive_persistence."
        "update_agent_artifact_index_for_marker_mutation"
    ) as update_index:
        app._apply_wait(
            str(tmp_path),
            agent,
            WaitModalResult(agents=["alice", "bob"], time_token=None),
        )

    data = json.loads(waiting_path.read_text(encoding="utf-8"))
    assert data == {
        "cl_name": "test_cl",
        "timestamp": "20240101120000",
        "waiting_for": ["alice", "bob"],
    }
    assert agent.waiting_for == ["alice", "bob"]
    assert agent.wait_duration is None
    assert agent.wait_until is None
    assert app.notifications == [("Now waiting for: alice, bob", "information")]
    assert app.refresh_calls == 1
    assert update_index.call_count == 2
    update_index.assert_any_call(str(tmp_path))


def test_apply_wait_empty_submission_keeps_run_now_behavior(tmp_path: Path) -> None:
    agent = make_waiting_agent(
        waiting_for=["old_dep"],
        waiting_for_beads=["sase-87.2"],
        wait_duration=None,
    )
    app = FakeWaitResumeApp()

    with patch(
        "sase.ace.tui.actions.agents._directive_persistence."
        "update_agent_artifact_index_for_marker_mutation"
    ) as update_index:
        app._apply_wait(
            str(tmp_path),
            agent,
            WaitModalResult(agents=[], time_token=None, run_now=True),
        )

    ready_path = tmp_path / "ready.json"
    assert json.loads(ready_path.read_text(encoding="utf-8")) == {
        "resolved_deps": ["old_dep"],
        "unwait": True,
    }
    assert agent.waiting_for == []
    assert agent.waiting_for_beads == []
    assert app.notifications == [("Wait: test_cl", "information")]
    update_index.assert_not_called()


def test_apply_wait_updates_parked_runner_threshold_in_place(tmp_path: Path) -> None:
    (tmp_path / "raw_xprompt.md").write_text("Do work", encoding="utf-8")
    (tmp_path / "agent_meta.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "waiting.json").write_text(
        json.dumps(
            {
                "waiting_for": [],
                "cl_name": "test_cl",
                "timestamp": "20240101120000",
                "wait_runners": 9,
                "wait_runners_explicit": False,
                "slot_requested_at": "2026-07-12T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    agent = make_waiting_agent(
        artifacts_dir=str(tmp_path),
        waiting_for=[],
        wait_duration=None,
        wait_until=None,
        wait_runners=9,
        wait_runners_explicit=False,
        slot_requested_at="2026-07-12T12:00:00Z",
    )
    app = FakeWaitResumeApp()

    with patch(
        "sase.ace.tui.actions.agents._directive_persistence."
        "update_agent_artifact_index_for_marker_mutation"
    ):
        app._apply_wait(
            str(tmp_path),
            agent,
            WaitModalResult(agents=[], time_token=None, runners=0),
        )

    waiting = json.loads((tmp_path / "waiting.json").read_text(encoding="utf-8"))
    assert waiting["wait_runners"] == 0
    assert waiting["wait_runners_explicit"] is True
    assert waiting["slot_requested_at"] == "2026-07-12T12:00:00Z"
    assert (tmp_path / "raw_xprompt.md").read_text(encoding="utf-8") == (
        "%wait(runners=0)\nDo work"
    )
    assert json.loads((tmp_path / "agent_meta.json").read_text())["wait_runners"] == 0
    assert agent.wait_runners == 0
    assert agent.wait_runners_explicit is True
    assert app.killed_agents == []


def test_apply_wait_run_now_releases_parked_runner_slot(tmp_path: Path) -> None:
    (tmp_path / "raw_xprompt.md").write_text(
        "%wait(runners=0)\nDo work", encoding="utf-8"
    )
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"wait_runners": 0}), encoding="utf-8"
    )
    (tmp_path / "waiting.json").write_text(
        json.dumps(
            {
                "waiting_for": [],
                "wait_runners": 0,
                "wait_runners_explicit": True,
                "slot_requested_at": "2026-07-12T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    agent = make_waiting_agent(
        artifacts_dir=str(tmp_path),
        waiting_for=[],
        wait_duration=None,
        wait_until=None,
        wait_runners=0,
        wait_runners_explicit=True,
        slot_requested_at="2026-07-12T12:00:00Z",
    )
    app = FakeWaitResumeApp()

    with patch(
        "sase.ace.tui.actions.agents._directive_persistence."
        "update_agent_artifact_index_for_marker_mutation"
    ):
        app._apply_wait(
            str(tmp_path),
            agent,
            WaitModalResult(agents=[], time_token=None, run_now=True),
        )

    assert json.loads((tmp_path / "ready.json").read_text()) == {
        "resolved_deps": [],
        "unwait": True,
    }
    assert json.loads((tmp_path / "agent_meta.json").read_text()) == {}
    assert (tmp_path / "raw_xprompt.md").read_text() == "Do work"
    assert agent.wait_runners is None
    assert agent.wait_runners_explicit is False
    assert agent.slot_requested_at is None
    assert app.killed_agents == []


def test_prompt_wait_spec_builds_canonical_forms() -> None:
    assert _prompt_wait_spec(
        WaitModalResult(agents=["alice", "bob"], time_token="5m")
    ) == PromptWaitDirective(agents=("alice", "bob"), time_token="5m")
    assert (
        set_prompt_wait(
            "Do work",
            _prompt_wait_spec(WaitModalResult(agents=[], time_token="5m")),
        )
        == "%wait(time=5m)\nDo work"
    )
    assert (
        set_prompt_wait(
            "Do work",
            _prompt_wait_spec(WaitModalResult(agents=["alice"], time_token=None)),
        )
        == "%wait(alice)\nDo work"
    )
    assert _prompt_wait_spec(
        WaitModalResult(
            agents=["alice"],
            time_token=None,
            beads=["sase-87.2"],
        )
    ) == PromptWaitDirective(agents=("alice",), beads=("sase-87.2",))


def test_apply_wait_preserves_bead_conditions(tmp_path: Path) -> None:
    (tmp_path / "raw_xprompt.md").write_text(
        "%wait(old, bead=sase-87.2)\nDo work",
        encoding="utf-8",
    )
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"wait_for": ["old"], "wait_for_beads": ["sase-87.2"]}),
        encoding="utf-8",
    )
    (tmp_path / "waiting.json").write_text(
        json.dumps({"waiting_for": ["old"], "wait_for_beads": ["sase-87.2"]}),
        encoding="utf-8",
    )
    agent = make_waiting_agent(
        artifacts_dir=str(tmp_path),
        waiting_for=["old"],
        waiting_for_beads=["sase-87.2"],
        wait_duration=None,
        wait_until=None,
    )
    app = FakeWaitResumeApp()

    with patch(
        "sase.ace.tui.actions.agents._directive_persistence."
        "update_agent_artifact_index_for_marker_mutation"
    ):
        app._apply_wait(
            str(tmp_path),
            agent,
            WaitModalResult(
                agents=["new"],
                time_token=None,
                beads=["sase-87.2"],
            ),
        )

    assert (tmp_path / "raw_xprompt.md").read_text(encoding="utf-8") == (
        "%wait(new)\n%wait(bead=sase-87.2)\nDo work"
    )
    assert json.loads((tmp_path / "agent_meta.json").read_text()) == {
        "wait_for": ["new"],
        "wait_for_beads": ["sase-87.2"],
    }
    assert json.loads((tmp_path / "waiting.json").read_text()) == {
        "waiting_for": ["new"],
        "wait_for_beads": ["sase-87.2"],
    }
    assert agent.waiting_for_beads == ["sase-87.2"]


def test_wait_modal_candidates_excludes_self_unnamed_and_duplicates() -> None:
    selected = make_waiting_agent(
        cl_name="selected",
        raw_suffix="20240101120000",
        agent_name="selected",
    )
    planner = make_waiting_agent(
        cl_name="planner",
        raw_suffix="20240101120100",
        agent_name="planner",
        llm_provider="claude",
        model="sonnet",
        reasoning_effort="xhigh",
    )
    duplicate = make_waiting_agent(
        cl_name="planner-2",
        raw_suffix="20240101120200",
        agent_name="planner",
    )
    unnamed = make_waiting_agent(
        cl_name="unnamed",
        raw_suffix="20240101120300",
        agent_name=None,
    )

    candidates = _wait_modal_candidates(
        selected,
        [selected, planner, duplicate, unnamed],
    )

    assert [candidate.wait_name for candidate in candidates] == ["planner"]
    assert candidates[0].model == "claude / sonnet@xhigh"


def test_strip_existing_wait_directives_removes_wait_and_time_refs() -> None:
    raw_prompt = "%w:old #t:5m %time:1430 do the thing"

    assert set_prompt_wait(raw_prompt, None) == "do the thing"


def test_apply_wait_with_time_relaunches_with_replacement_directive(
    tmp_path: Path,
) -> None:
    (tmp_path / "raw_xprompt.md").write_text(
        "%w:old #t:5m do the thing",
        encoding="utf-8",
    )
    agent = make_waiting_agent(
        artifacts_dir=str(tmp_path),
        wait_duration=300.0,
        waiting_for=["old"],
    )
    app = FakeWaitResumeApp()

    app._apply_wait(
        str(tmp_path),
        agent,
        WaitModalResult(agents=["new"], time_token="10m"),
    )

    assert len(app.pushed_screens) == 1
    modal, callback = app.pushed_screens[0]
    assert "waiting for new, then 10m" in modal.agent_description  # type: ignore[attr-defined]
    assert callable(callback)
    callback(True)

    assert app.killed_agents == [agent]
    assert app.launch_prompts == ["%wait(new, time=10m)\ndo the thing"]
    assert "%w:old" not in app.launch_prompts[0]
    assert "#t:5m" not in app.launch_prompts[0]


def test_apply_wait_running_relaunches_with_canonical_wait(tmp_path: Path) -> None:
    (tmp_path / "raw_xprompt.md").write_text("%id:kept do the thing", encoding="utf-8")
    agent = make_waiting_agent(
        status="RUNNING",
        artifacts_dir=str(tmp_path),
        agent_name="runner",
    )
    app = FakeWaitResumeApp()

    app._apply_wait_running(agent, WaitModalResult(agents=["dep"], time_token=None))

    assert len(app.pushed_screens) == 1
    _modal, callback = app.pushed_screens[0]
    assert callable(callback)
    callback(True)

    assert app.killed_agents == [agent]
    assert app.launch_prompts == ["%wait(dep)\n%id:kept do the thing"]


def test_apply_wait_running_run_now_is_noop() -> None:
    agent = make_waiting_agent(status="RUNNING")
    app = FakeWaitResumeApp()

    app._apply_wait_running(
        agent,
        WaitModalResult(agents=[], time_token=None, run_now=True),
    )

    assert app.notifications == [("Agent is already running", "warning")]
    assert app.pushed_screens == []

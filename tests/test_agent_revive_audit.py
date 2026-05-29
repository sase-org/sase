"""Revival audit log integration tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.models.agent import Agent
from sase.core.agent_group_archive_wire import SavedAgentGroupPageWire

from tests._agent_revive_helpers import FakeReviveApp, make_agent


def _read_revive_events(events_file: Path) -> list[dict[str, object]]:
    from sase.logs.run_log import iter_revive_events

    return list(iter_revive_events(events_file=str(events_file)))


def test_single_revive_emits_started_and_success_events(tmp_path: Path) -> None:
    events_file = tmp_path / "events.jsonl"
    app = FakeReviveApp()
    agent = make_agent(cl_name="feature_a", raw_suffix="20260201120000")
    agent._dismissed_bundle_path = "/fake/bundles/202602/20260201120000.json"
    app._dismissed_agent_objects = [agent]
    app._dismissed_agents = {agent.identity}

    with (
        patch("sase.logs.run_log.EVENTS_FILE", str(events_file)),
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.mark_bundles_revived_by_suffixes"),
    ):
        app._do_revive_agent(agent)

    events = _read_revive_events(events_file)
    # Reverse-chronological order.
    assert [e["event"] for e in events] == [
        "agent_revived",
        "agent_revive_started",
    ]
    success = events[0]
    assert success["cl_name"] == "feature_a"
    assert success["raw_suffix"] == "20260201120000"
    assert success["bundle_path"] == "/fake/bundles/202602/20260201120000.json"
    assert success["outcome"] == "success"
    assert success["batch_size"] == 1


def test_single_revive_failure_emits_failed_event_and_notifies(
    tmp_path: Path,
) -> None:
    events_file = tmp_path / "events.jsonl"
    app = FakeReviveApp()
    agent = make_agent(cl_name="feature_b", raw_suffix="20260202120000")
    app._dismissed_agent_objects = [agent]
    app._dismissed_agents = {agent.identity}

    def _boom(*_args: object, **_kwargs: object) -> None:  # noqa: ARG001
        raise RuntimeError("artifact restore broke")

    app._restore_agent_artifacts = _boom  # type: ignore[assignment]

    with (
        patch("sase.logs.run_log.EVENTS_FILE", str(events_file)),
        patch("sase.ace.dismissed_agents.save_dismissed_agents") as mock_save,
        patch("sase.ace.dismissed_agents.mark_bundles_revived_by_suffixes"),
    ):
        app._do_revive_agent(agent)

    events = _read_revive_events(events_file)
    assert any(e["event"] == "agent_revive_failed" for e in events)
    failure = next(e for e in events if e["event"] == "agent_revive_failed")
    assert failure["stage"] == "artifact_restore"
    assert failure["error_type"] == "RuntimeError"
    assert failure["error_message"] == "artifact restore broke"
    assert failure["cl_name"] == "feature_b"
    # Caller saw an error toast.
    assert any(sev == "error" for _, sev in app.notifications)
    # No success event was emitted.
    assert not any(e["event"] == "agent_revived" for e in events)
    assert app._dismissed_agents == {agent.identity}
    mock_save.assert_not_called()


def test_no_dismissed_agents_emits_failure_event(tmp_path: Path) -> None:
    events_file = tmp_path / "events.jsonl"
    app = FakeReviveApp()  # no dismissed agents

    with (
        patch("sase.logs.run_log.EVENTS_FILE", str(events_file)),
        patch(
            "sase.ace.dismissed_agents.list_dismissed_agent_groups",
            return_value=SavedAgentGroupPageWire(groups=(), next_cursor=None),
        ),
    ):
        app._revive_agent()

    events = _read_revive_events(events_file)
    assert len(events) == 1
    assert events[0]["event"] == "agent_revive_failed"
    assert events[0]["reason"] == "no_dismissed_agents"
    assert events[0]["stage"] == "no_dismissed_agents"


def test_batch_revive_emits_per_agent_terminal_events(tmp_path: Path) -> None:
    events_file = tmp_path / "events.jsonl"
    app = FakeReviveApp()
    parent_one = make_agent(
        cl_name="f1",
        raw_suffix="20260301120000",
    )
    parent_two = make_agent(
        cl_name="f2",
        raw_suffix="20260301130000",
        workflow="wf_two",
    )
    parent_three = make_agent(
        cl_name="f3",
        raw_suffix="20260301140000",
        workflow="wf_three",
    )
    app._dismissed_agent_objects = [parent_one, parent_two, parent_three]
    app._dismissed_agents = {
        parent_one.identity,
        parent_two.identity,
        parent_three.identity,
    }

    original_restore = app._restore_agent_artifacts

    def _fail_for_parent_two(
        agent: Agent, *, parent_artifacts_dir: object = None
    ) -> None:
        if agent.cl_name == "f2":
            raise RuntimeError("middle agent broke")
        original_restore(agent, parent_artifacts_dir=parent_artifacts_dir)  # type: ignore[arg-type]

    app._restore_agent_artifacts = _fail_for_parent_two  # type: ignore[assignment]

    with (
        patch("sase.logs.run_log.EVENTS_FILE", str(events_file)),
        patch("sase.ace.dismissed_agents.save_dismissed_agents") as mock_save,
        patch(
            "sase.ace.dismissed_agents.mark_bundles_revived_by_suffixes"
        ) as mock_mark,
    ):
        app._do_revive_agents([parent_one, parent_two, parent_three])

    events = _read_revive_events(events_file)
    started = [e for e in events if e["event"] == "agent_revive_started"]
    successes = [e for e in events if e["event"] == "agent_revived"]
    failures = [e for e in events if e["event"] == "agent_revive_failed"]
    assert len(started) == 1
    assert started[0]["batch_size"] == 3
    assert len(successes) == 2
    assert len(failures) == 1
    assert failures[0]["cl_name"] == "f2"
    assert failures[0]["stage"] == "artifact_restore"
    assert failures[0]["error_type"] == "RuntimeError"
    success_cl_names = {e["cl_name"] for e in successes}
    assert success_cl_names == {"f1", "f3"}
    assert app._dismissed_agents == {parent_two.identity}
    mock_save.assert_called_once()
    mock_mark.assert_called_once_with({"20260301120000", "20260301140000"})

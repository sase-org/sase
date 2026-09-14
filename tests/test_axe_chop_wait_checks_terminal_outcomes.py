"""Terminal-outcome and notification tests for the wait_checks chop script."""

import json
from pathlib import Path

import pytest

from sase.notifications.store import load_notifications

from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent, run_wait_checks


def test_named_agent_killed_newest_does_not_resolve(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    make_agent(tmp_path, "proj", "20260506010101", "foo", done=True)
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "foo",
        done=True,
        outcome="killed",
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_later_same_name_completed_agent_resolves_after_killed(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="killed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "foo",
        done=True,
        outcome="completed",
    )

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["foo"]}


def test_repeat_stopped_completed_marker_resolves_downstream_wait(
    tmp_path: Path, monkeypatch
) -> None:
    """A repeat-stopped slot still reports `completed`, so the cascade is generic.

    The next downstream waiter must resolve off the stopped predecessor exactly
    like any other completed producer -- the chop never inspects `repeat_stopped`.
    """
    waiter_dir = make_waiting_agent(tmp_path, "foo.2")
    producer_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo.2",
        done=True,
        outcome="completed",
    )
    # Mark the predecessor as a repeat-stopped slot, as the runner would.
    done = json.loads((producer_dir / "done.json").read_text(encoding="utf-8"))
    done.update({"repeat_stopped": True, "stopped_by": "foo.1"})
    (producer_dir / "done.json").write_text(json.dumps(done), encoding="utf-8")

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["foo.2"]}


def test_completed_named_agent_success_path_writes_ready(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="completed",
    )

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["foo"]}
    out = capsys.readouterr().out
    assert "[wait_checks] Dependencies satisfied for waiter-cl" in out
    assert "wait_checks: projects=1 artifacts=2 waiting=1 ready_written=1" in out


@pytest.mark.parametrize(
    ("outcome", "should_resolve"),
    [
        ("completed", True),
        ("noop", True),
        ("epic_approved", True),
        ("plan_committed", True),
        ("failed", False),
        ("killed", False),
        ("stopped", False),
        ("epic_launch_failed", False),
        ("plan_rejected", False),
    ],
)
def test_named_agent_terminal_done_outcome_classification(
    tmp_path: Path,
    monkeypatch,
    outcome: str,
    should_resolve: bool,
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome=outcome,
    )

    run_wait_checks(tmp_path, monkeypatch)

    ready_path = waiter_dir / "ready.json"
    assert ready_path.exists() is should_resolve
    if should_resolve:
        assert json.loads(ready_path.read_text(encoding="utf-8")) == {
            "resolved_deps": ["foo"]
        }


def test_epic_approved_land_member_resolves_next_wait_cycle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "sase-i1.land")
    dependency_dir = make_agent(
        tmp_path,
        "proj",
        "20260809074248",
        "sase-i1.land",
        done=True,
        outcome="epic_approved",
    )
    meta_path = dependency_dir / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update(
        {
            "agent_clan": "sase-i1",
            "agent_clan_generation": "20260809074248",
        }
    )
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    run_wait_checks(tmp_path, monkeypatch)

    assert json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8")) == {
        "resolved_deps": ["sase-i1.land"]
    }


def test_unknown_terminal_done_outcome_is_reported(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    dependency_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="mystery_success",
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()
    out = capsys.readouterr().out
    assert "unknown_outcome=1" in out
    assert "Unknown done outcome blocks waiter" in out
    assert str(dependency_dir) in out
    assert "mystery_success" in out


def test_terminal_blocked_waiter_upserts_one_notification(
    tmp_path: Path,
    monkeypatch,
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    dependency_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="failed",
    )

    run_wait_checks(tmp_path, monkeypatch)
    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()
    notifications = load_notifications()
    assert len(notifications) == 1
    notification = notifications[0]
    assert notification.sender == "wait_checks"
    assert notification.dedup_key == f"wait_checks:terminal-blocked:{waiter_dir}"
    assert notification.plus_one_count == 1
    assert str(waiter_dir) in notification.files
    assert str(dependency_dir) in notification.files
    assert notification.action_data["waiter"] == "waiter-cl"
    assert notification.action_data["dependency"] == "foo"
    assert notification.action_data["blocking_artifact_dir"] == str(dependency_dir)
    assert notification.action_data["blocking_outcome"] == "failed"
    assert any("never self-resolve" in note for note in notification.notes)
    assert any("Kill and relaunch" in note for note in notification.notes)


def test_later_resolved_waiter_does_not_notify(
    tmp_path: Path,
    monkeypatch,
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "late-dep")

    run_wait_checks(tmp_path, monkeypatch)
    make_agent(
        tmp_path,
        "proj",
        "20260506020202",
        "late-dep",
        done=True,
        outcome="completed",
    )
    run_wait_checks(tmp_path, monkeypatch)

    assert json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8")) == {
        "resolved_deps": ["late-dep"]
    }
    assert load_notifications() == []


def test_superseded_start_failed_monitor_member_resolves_waiter(
    tmp_path: Path, monkeypatch
) -> None:
    """Reproduces the sase-zt.6.5.3 incident through the wait_checks chop.

    A land agent's ``%w`` on a family whose newest generation contains a
    start-failed ``--mon`` (no follow-up) and a later ``--mon-0`` retry that
    handed off to a completed successor must get its ``ready.json`` written,
    instead of hanging on the superseded start failure forever.
    """
    waiter_dir = make_waiting_agent(tmp_path, "sase-zt.6.5.3")
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260913170029",
        "sase-zt.6.5.3--plan",
        workflow_name="sase-zt.6.5.3",
        agent_family="sase-zt.6.5.3",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    mon_dir = make_agent(
        tmp_path,
        "proj",
        "20260913170758",
        "sase-zt.6.5.3--mon",
        workflow_name="sase-zt.6.5.3",
        agent_family="sase-zt.6.5.3",
        role_suffix="--mon",
        parent_timestamp=root_dir.name,
    )
    (mon_dir / "done.json").write_text(
        json.dumps(
            {
                "outcome": "monitored",
                "monitor_state": "failed",
                "error": "could not claim workspace for monitor",
            }
        ),
        encoding="utf-8",
    )
    mon_0_dir = make_agent(
        tmp_path,
        "proj",
        "20260913171010",
        "sase-zt.6.5.3--mon-0",
        workflow_name="sase-zt.6.5.3",
        agent_family="sase-zt.6.5.3",
        role_suffix="--mon-0",
        parent_timestamp=mon_dir.name,
        extra_meta={
            "monitor_state": "timeout",
            "monitor_followup_outcome": "launched",
            "monitor_followup_agent": "sase-zt.6.5.3--2",
        },
    )
    (mon_0_dir / "done.json").write_text(
        json.dumps(
            {
                "outcome": "monitored",
                "monitor_state": "timeout",
                "monitor_followup_outcome": "launched",
            }
        ),
        encoding="utf-8",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260913171100",
        "sase-zt.6.5.3--2",
        workflow_name="sase-zt.6.5.3",
        agent_family="sase-zt.6.5.3",
        role_suffix="--2",
        parent_timestamp=mon_0_dir.name,
        done=True,
        outcome="completed",
    )

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["sase-zt.6.5.3"]}

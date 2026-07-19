"""Tests for the Agents-tab tribe modal action (``N`` keymap)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.agents._display import AgentDisplayMixin
from sase.ace.tui.actions.agents._tribe_assignment import AgentTribeAssignmentMixin
from sase.ace.tui.actions.task_actions import TrackedTaskCompletion, TrackedTaskResult
from sase.ace.tui.modals.agent_tribe_modal import AgentTribeModal, AgentTribeModalResult
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.task_queue import TaskInfo


def _make_agent(suffix: str = "20240101120000", **overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "fix-bug",
        "project_file": "/tmp/projects/myproj/myproj.sase",
        "status": "RUNNING",
        "start_time": datetime(2024, 1, 1, 12, 0, 0),
        "raw_suffix": suffix,
        "pid": 4242,
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class _FakeApp(AgentTribeAssignmentMixin, AgentDisplayMixin):
    """Minimal stub of AceApp for exercising AgentTribeAssignmentMixin."""

    def __init__(self, agents: list[Agent]) -> None:
        self.current_tab: Any = "agents"  # type: ignore[assignment]
        self.current_idx = 0
        self._agents: list[Agent] = list(agents)
        self._agents_with_children: list[Agent] = list(agents)
        self._marked_agents: set[tuple[AgentType, str, str | None]] = set()
        self.notifications: list[tuple[str, str]] = []
        self.pushed_modals: list[Any] = []
        self.pushed_callbacks: list[Any] = []
        self.refresh_calls = 0
        self.events: list[str] = []
        self._agent_panel_index_cache: tuple[Any, Any] | None = ("agents", "index")
        self._panel_keys_cache: tuple[Any, ...] | None = ("agents", "keys")
        self._nav_stops_cache: tuple[Any, ...] | None = ("agents", "stops")

    def _get_selected_agent(self) -> Agent | None:
        if 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None

    def notify(
        self, message: str, *, severity: str = "information"
    ) -> None:  # pragma: no cover - trivial
        self.notifications.append((message, severity))

    def push_screen(
        self, modal: Any, callback: Any = None
    ) -> None:  # pragma: no cover - trivial
        self.pushed_modals.append(modal)
        self.pushed_callbacks.append(callback)

    def _refresh_agents_display(
        self, *, list_changed: bool = False
    ) -> None:  # pragma: no cover - trivial
        self.refresh_calls += 1
        self.events.append(f"refresh:{list_changed}")

    def _invalidate_agent_panel_cache(self) -> None:
        super()._invalidate_agent_panel_cache()
        self.events.append("invalidate")

    def _submit_tracked_task(
        self,
        task_type: str,
        cl_name: str,
        project_file: str,
        task_callable: Any,
        *,
        display_name: str | None = None,
        dedup_key: str | None = None,
        duplicate_message: str | None = None,
        on_complete: Any = None,
        reload_on_complete: bool = True,
        notify_on_complete: bool = True,
    ) -> TaskInfo:
        del duplicate_message, reload_on_complete, notify_on_complete
        task_info = TaskInfo(
            task_id=f"task-{len(self.events)}",
            task_type=task_type,
            cl_name=cl_name,
            project_file=project_file,
            status="running",
            message="running",
            started_at=datetime.now(),
            display_name=display_name,
            dedup_key=dedup_key,
        )
        try:
            result = task_callable()
        except Exception as exc:
            result = TrackedTaskResult(
                success=False,
                message=str(exc),
                error=str(exc),
            )
        task_info.status = "success" if result.success else "error"
        task_info.message = result.message
        task_info.error = result.error
        if on_complete is not None:
            on_complete(
                TrackedTaskCompletion(
                    task_info=task_info,
                    success=result.success,
                    message=result.message,
                    output="",
                    payload=result.payload,
                    error=result.error,
                )
            )
        return task_info


def test_action_no_op_when_not_on_agents_tab(tmp_path: Path) -> None:
    app = _FakeApp([_make_agent()])
    app.current_tab = "changespecs"
    with patch(
        "sase.ace.agent_tribes._AGENT_TRIBES_FILE",
        tmp_path / "agent_tribes.json",
    ):
        app.action_edit_agent_tribe()
    assert app.pushed_modals == []


def test_action_warns_when_no_agent_selected(tmp_path: Path) -> None:
    app = _FakeApp([])
    app.current_idx = -1
    with patch(
        "sase.ace.agent_tribes._AGENT_TRIBES_FILE",
        tmp_path / "agent_tribes.json",
    ):
        app.action_edit_agent_tribe()
    assert app.pushed_modals == []
    assert any("No agent selected" in m for m, _ in app.notifications)


def test_action_pushes_modal_for_focused_agent(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    tribe_file.write_text(
        json.dumps(
            [
                {"id": ["run", "fix-bug", "ts-other"], "tribe": "alpha"},
                {"id": ["run", "fix-bug", "ts-other2"], "tribe": "beta"},
            ]
        )
    )
    agent = _make_agent()
    agent.tribe = "primary"
    app = _FakeApp([agent])
    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app.action_edit_agent_tribe()
    assert len(app.pushed_modals) == 1
    modal = app.pushed_modals[0]
    assert isinstance(modal, AgentTribeModal)
    assert modal._target_label == agent.display_name
    assert modal._current_tribe == "primary"
    assert modal._known_tribes == ("alpha", "beta")


def test_action_seeds_pinned_for_focused_agent_without_tribe(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    agent = _make_agent()
    assert agent.tribe is None
    app = _FakeApp([agent])
    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app.action_edit_agent_tribe()
    modal = app.pushed_modals[0]
    assert isinstance(modal, AgentTribeModal)
    assert modal._current_tribe is None
    assert modal._default_tribe == "pinned"


def test_action_does_not_seed_pinned_for_bulk_path(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    a1 = _make_agent(suffix="t1")
    a2 = _make_agent(suffix="t2")
    app = _FakeApp([a1, a2])
    app._marked_agents = {a1.identity, a2.identity}
    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app.action_edit_agent_tribe()
    modal = app.pushed_modals[0]
    assert isinstance(modal, AgentTribeModal)
    assert modal._default_tribe is None


def test_apply_set_persists_and_updates_agent(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    agent = _make_agent()
    app = _FakeApp([agent])
    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app.action_edit_agent_tribe()
        callback = app.pushed_callbacks[0]
        callback(AgentTribeModalResult(action="set", tribe="release-blockers"))
    assert agent.tribe == "release-blockers"
    persisted = json.loads(tribe_file.read_text())
    assert persisted == [
        {"id": ["run", "fix-bug", "20240101120000"], "tribe": "release-blockers"}
    ]
    assert app.refresh_calls == 1


def test_tribe_modal_round_trip_rewrites_id_tribe_keyword(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    prompt_path = artifacts_dir / "raw_xprompt.md"
    prompt_path.write_text("%id:worker\nDo work", encoding="utf-8")
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"name": "worker"}),
        encoding="utf-8",
    )
    agent = _make_agent(
        artifacts_dir=str(artifacts_dir),
        agent_name="worker",
    )
    app = _FakeApp([agent])

    with (
        patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file),
        patch(
            "sase.core.agent_artifact_index_lifecycle."
            "update_agent_artifact_index_for_marker_mutation"
        ),
    ):
        app._apply_agent_tribe_change(
            AgentTribeModalResult(action="set", tribe="review"),
            [agent],
        )
        assert prompt_path.read_text(encoding="utf-8") == (
            "%id(worker, tribe=review)\nDo work"
        )

        app._apply_agent_tribe_change(
            AgentTribeModalResult(action="unset", tribe=None),
            [agent],
        )

    assert prompt_path.read_text(encoding="utf-8") == "%id:worker\nDo work"


def test_apply_set_replaces_existing_tribe(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    tribe_file.write_text(
        json.dumps([{"id": ["run", "fix-bug", "20240101120000"], "tribe": "old"}])
    )
    agent = _make_agent()
    agent.tribe = "old"
    app = _FakeApp([agent])
    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app.action_edit_agent_tribe()
        callback = app.pushed_callbacks[0]
        callback(AgentTribeModalResult(action="set", tribe="new"))
    assert agent.tribe == "new"
    persisted = json.loads(tribe_file.read_text())
    assert persisted == [{"id": ["run", "fix-bug", "20240101120000"], "tribe": "new"}]


def test_apply_unset_drops_tribe(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    tribe_file.write_text(
        json.dumps([{"id": ["run", "fix-bug", "20240101120000"], "tribe": "foo"}])
    )
    agent = _make_agent()
    agent.tribe = "foo"
    app = _FakeApp([agent])
    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app.action_edit_agent_tribe()
        callback = app.pushed_callbacks[0]
        callback(AgentTribeModalResult(action="unset", tribe=None))
    assert agent.tribe is None
    persisted = json.loads(tribe_file.read_text())
    assert persisted == []


def test_apply_unset_strips_legacy_meta_tag(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    artifacts_dir = tmp_path / "artifacts" / "ace-run" / "20240101120000"
    artifacts_dir.mkdir(parents=True)
    meta_path = artifacts_dir / "agent_meta.json"
    meta_path.write_text(
        json.dumps({"name": "foo.bar", "tag": "foo", "model": "test-model"}),
        encoding="utf-8",
    )
    agent = _make_agent(artifacts_dir=str(artifacts_dir), agent_name="foo.bar")
    agent.tribe = "foo"
    app = _FakeApp([agent])

    with (
        patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file),
        patch(
            "sase.core.agent_artifact_index_lifecycle."
            "update_agent_artifact_index_for_marker_mutation"
        ),
    ):
        app._apply_agent_tribe_change(
            AgentTribeModalResult(action="unset", tribe=None),
            [agent],
        )

    assert agent.tribe is None
    assert not tribe_file.exists()
    assert json.loads(meta_path.read_text(encoding="utf-8")) == {
        "name": "foo.bar",
        "model": "test-model",
    }
    assert app.refresh_calls == 1


def test_clan_tribe_reassignment_rewrites_only_declaring_prompt(tmp_path: Path) -> None:
    declarer_dir = tmp_path / "declarer"
    joiner_dir = tmp_path / "joiner"
    for artifacts_dir, prompt, name in (
        (
            declarer_dir,
            "%id:research.lead\n%clan(research, tribe=old)\nLead",
            "research.lead",
        ),
        (
            joiner_dir,
            "%id(worker, clan=research)\nWork",
            "research.worker",
        ),
    ):
        artifacts_dir.mkdir()
        (artifacts_dir / "raw_xprompt.md").write_text(prompt, encoding="utf-8")
        (artifacts_dir / "agent_meta.json").write_text(
            json.dumps(
                {
                    "name": name,
                    "agent_clan": "research",
                    "agent_clan_generation": "g1",
                    "clan_tribe": "old",
                }
            ),
            encoding="utf-8",
        )

    declarer = _make_agent(
        suffix="declarer",
        artifacts_dir=str(declarer_dir),
        agent_name="research.lead",
        agent_clan="research",
        agent_clan_generation="g1",
        clan_tribe="old",
    )
    joiner = _make_agent(
        suffix="joiner",
        artifacts_dir=str(joiner_dir),
        agent_name="research.worker",
        agent_clan="research",
        agent_clan_generation="g1",
        clan_tribe="old",
    )
    app = _FakeApp([declarer, joiner])

    with patch(
        "sase.core.agent_artifact_index_lifecycle."
        "update_agent_artifact_index_for_marker_mutation"
    ):
        app._apply_agent_tribe_change(
            AgentTribeModalResult(action="set", tribe="new"),
            [declarer, joiner],
        )

    assert (declarer_dir / "raw_xprompt.md").read_text(encoding="utf-8") == (
        "%id:research.lead\n%clan(research, tribe=new)\nLead"
    )
    assert (joiner_dir / "raw_xprompt.md").read_text(encoding="utf-8") == (
        "%id(worker, clan=research)\nWork"
    )
    assert (
        json.loads((declarer_dir / "agent_meta.json").read_text(encoding="utf-8"))[
            "clan_tribe"
        ]
        == "new"
    )
    assert (
        json.loads((joiner_dir / "agent_meta.json").read_text(encoding="utf-8"))[
            "clan_tribe"
        ]
        == "new"
    )


def test_marked_bulk_path_targets_marked_agents(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    a1 = _make_agent(suffix="t1")
    a2 = _make_agent(suffix="t2")
    a3 = _make_agent(suffix="t3")
    app = _FakeApp([a1, a2, a3])
    app._marked_agents = {a1.identity, a3.identity}
    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app.action_edit_agent_tribe()
        modal = app.pushed_modals[0]
        assert isinstance(modal, AgentTribeModal)
        assert modal._target_label == "2 marked agent(s)"
        assert modal._current_tribe is None  # bulk doesn't show per-agent tribe
        callback = app.pushed_callbacks[0]
        callback(AgentTribeModalResult(action="set", tribe="release-blockers"))
    assert a1.tribe == "release-blockers"
    assert a2.tribe is None  # not marked → not changed
    assert a3.tribe == "release-blockers"
    persisted = {
        tuple(row["id"]): row["tribe"] for row in json.loads(tribe_file.read_text())
    }
    assert persisted == {
        ("run", "fix-bug", "t1"): "release-blockers",
        ("run", "fix-bug", "t3"): "release-blockers",
    }


def test_marked_bulk_success_clears_affected_marks(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    a1 = _make_agent(suffix="t1")
    a2 = _make_agent(suffix="t2")
    a3 = _make_agent(suffix="t3")
    unrelated_identity = (AgentType.RUNNING, "other", "t4")
    app = _FakeApp([a1, a2, a3])
    app._marked_agents = {a1.identity, a3.identity, unrelated_identity}

    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app._apply_agent_tribe_change(
            AgentTribeModalResult(action="set", tribe="release-blockers"),
            [a1, a3],
        )

    assert app._marked_agents == {unrelated_identity}


def test_successful_tribe_change_invalidates_panel_cache_before_refresh(
    tmp_path: Path,
) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    agent = _make_agent()
    app = _FakeApp([agent])

    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app._apply_agent_tribe_change(
            AgentTribeModalResult(action="set", tribe="release-blockers"),
            [agent],
        )

    assert app._agent_panel_index_cache is None
    assert app._panel_keys_cache is None
    assert app._nav_stops_cache is None
    assert app.events == ["invalidate", "refresh:True"]


def test_modal_dismiss_with_none_is_noop(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    agent = _make_agent()
    app = _FakeApp([agent])
    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app.action_edit_agent_tribe()
        callback = app.pushed_callbacks[0]
        callback(None)
    assert agent.tribe is None
    assert not tribe_file.exists()
    assert app.refresh_calls == 0


def test_apply_set_no_change_does_not_rewrite_file(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    tribe_file.write_text(
        json.dumps([{"id": ["run", "fix-bug", "20240101120000"], "tribe": "already"}])
    )
    mtime_before = tribe_file.stat().st_mtime_ns
    agent = _make_agent()
    agent.tribe = "already"
    app = _FakeApp([agent])
    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app.action_edit_agent_tribe()
        callback = app.pushed_callbacks[0]
        callback(AgentTribeModalResult(action="set", tribe="already"))
    # Tribe was already present — no write occurred.
    assert tribe_file.stat().st_mtime_ns == mtime_before


def test_modal_returns_normalized_result_via_validation() -> None:
    """Validation rejects '@'-prefixed input from the modal layer."""
    from sase.ace.agent_tribes import InvalidTribeError, validate_tribe_name

    try:
        validate_tribe_name("@bad")
    except InvalidTribeError as exc:
        assert "must not start with '@'" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected InvalidTribeError")

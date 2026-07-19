"""Tests for the Agents-tab tag modal action (`t` keymap)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.agents._display import AgentDisplayMixin
from sase.ace.tui.actions.agents._tagging import AgentTaggingMixin
from sase.ace.tui.actions.task_actions import TrackedTaskCompletion, TrackedTaskResult
from sase.ace.tui.modals.agent_tag_modal import AgentTagModal, AgentTagModalResult
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


class _FakeApp(AgentTaggingMixin, AgentDisplayMixin):
    """Minimal stub of AceApp for exercising AgentTaggingMixin."""

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
    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", tmp_path / "agent_tags.json"):
        app.action_add_agent_tag()
    assert app.pushed_modals == []


def test_action_warns_when_no_agent_selected(tmp_path: Path) -> None:
    app = _FakeApp([])
    app.current_idx = -1
    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", tmp_path / "agent_tags.json"):
        app.action_add_agent_tag()
    assert app.pushed_modals == []
    assert any("No agent selected" in m for m, _ in app.notifications)


def test_action_pushes_modal_for_focused_agent(tmp_path: Path) -> None:
    tag_file = tmp_path / "agent_tags.json"
    tag_file.write_text(
        json.dumps(
            [
                {"id": ["run", "fix-bug", "ts-other"], "tag": "alpha"},
                {"id": ["run", "fix-bug", "ts-other2"], "tag": "beta"},
            ]
        )
    )
    agent = _make_agent()
    agent.tag = "primary"
    app = _FakeApp([agent])
    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", tag_file):
        app.action_add_agent_tag()
    assert len(app.pushed_modals) == 1
    modal = app.pushed_modals[0]
    assert isinstance(modal, AgentTagModal)
    assert modal._target_label == agent.display_name
    assert modal._current_tag == "primary"
    assert modal._known_tags == ("alpha", "beta")


def test_action_seeds_pinned_for_untagged_focused_agent(tmp_path: Path) -> None:
    tag_file = tmp_path / "agent_tags.json"
    agent = _make_agent()
    assert agent.tag is None
    app = _FakeApp([agent])
    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", tag_file):
        app.action_add_agent_tag()
    modal = app.pushed_modals[0]
    assert isinstance(modal, AgentTagModal)
    assert modal._current_tag is None
    assert modal._default_tag == "pinned"


def test_action_does_not_seed_pinned_for_bulk_path(tmp_path: Path) -> None:
    tag_file = tmp_path / "agent_tags.json"
    a1 = _make_agent(suffix="t1")
    a2 = _make_agent(suffix="t2")
    app = _FakeApp([a1, a2])
    app._marked_agents = {a1.identity, a2.identity}
    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", tag_file):
        app.action_add_agent_tag()
    modal = app.pushed_modals[0]
    assert isinstance(modal, AgentTagModal)
    assert modal._default_tag is None


def test_apply_set_persists_and_updates_agent(tmp_path: Path) -> None:
    tag_file = tmp_path / "agent_tags.json"
    agent = _make_agent()
    app = _FakeApp([agent])
    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", tag_file):
        app.action_add_agent_tag()
        callback = app.pushed_callbacks[0]
        callback(AgentTagModalResult(action="set", tag="release-blockers"))
    assert agent.tag == "release-blockers"
    persisted = json.loads(tag_file.read_text())
    assert persisted == [
        {"id": ["run", "fix-bug", "20240101120000"], "tribe": "release-blockers"}
    ]
    assert app.refresh_calls == 1


def test_apply_set_replaces_existing_tag(tmp_path: Path) -> None:
    tag_file = tmp_path / "agent_tags.json"
    tag_file.write_text(
        json.dumps([{"id": ["run", "fix-bug", "20240101120000"], "tag": "old"}])
    )
    agent = _make_agent()
    agent.tag = "old"
    app = _FakeApp([agent])
    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", tag_file):
        app.action_add_agent_tag()
        callback = app.pushed_callbacks[0]
        callback(AgentTagModalResult(action="set", tag="new"))
    assert agent.tag == "new"
    persisted = json.loads(tag_file.read_text())
    assert persisted == [{"id": ["run", "fix-bug", "20240101120000"], "tribe": "new"}]


def test_apply_unset_drops_tag(tmp_path: Path) -> None:
    tag_file = tmp_path / "agent_tags.json"
    tag_file.write_text(
        json.dumps([{"id": ["run", "fix-bug", "20240101120000"], "tag": "foo"}])
    )
    agent = _make_agent()
    agent.tag = "foo"
    app = _FakeApp([agent])
    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", tag_file):
        app.action_add_agent_tag()
        callback = app.pushed_callbacks[0]
        callback(AgentTagModalResult(action="unset", tag=None))
    assert agent.tag is None
    persisted = json.loads(tag_file.read_text())
    assert persisted == []


def test_apply_unset_strips_meta_only_tag(tmp_path: Path) -> None:
    tag_file = tmp_path / "agent_tags.json"
    artifacts_dir = tmp_path / "artifacts" / "ace-run" / "20240101120000"
    artifacts_dir.mkdir(parents=True)
    meta_path = artifacts_dir / "agent_meta.json"
    meta_path.write_text(
        json.dumps({"name": "foo.bar", "tag": "foo", "model": "test-model"}),
        encoding="utf-8",
    )
    agent = _make_agent(artifacts_dir=str(artifacts_dir), agent_name="foo.bar")
    agent.tag = "foo"
    app = _FakeApp([agent])

    with (
        patch("sase.ace.agent_tags._AGENT_TAGS_FILE", tag_file),
        patch(
            "sase.core.agent_artifact_index_lifecycle."
            "update_agent_artifact_index_for_marker_mutation"
        ),
    ):
        app._apply_agent_tag_change(
            AgentTagModalResult(action="unset", tag=None),
            [agent],
        )

    assert agent.tag is None
    assert not tag_file.exists()
    assert json.loads(meta_path.read_text(encoding="utf-8")) == {
        "name": "foo.bar",
        "model": "test-model",
    }
    assert app.refresh_calls == 1


def test_clan_retag_rewrites_only_declaring_prompt(tmp_path: Path) -> None:
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
        app._apply_agent_tag_change(
            AgentTagModalResult(action="set", tag="new"),
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
    tag_file = tmp_path / "agent_tags.json"
    a1 = _make_agent(suffix="t1")
    a2 = _make_agent(suffix="t2")
    a3 = _make_agent(suffix="t3")
    app = _FakeApp([a1, a2, a3])
    app._marked_agents = {a1.identity, a3.identity}
    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", tag_file):
        app.action_add_agent_tag()
        modal = app.pushed_modals[0]
        assert isinstance(modal, AgentTagModal)
        assert modal._target_label == "2 marked agent(s)"
        assert modal._current_tag is None  # bulk doesn't show per-agent tag
        callback = app.pushed_callbacks[0]
        callback(AgentTagModalResult(action="set", tag="release-blockers"))
    assert a1.tag == "release-blockers"
    assert a2.tag is None  # not marked → not changed
    assert a3.tag == "release-blockers"
    persisted = {
        tuple(row["id"]): row["tribe"] for row in json.loads(tag_file.read_text())
    }
    assert persisted == {
        ("run", "fix-bug", "t1"): "release-blockers",
        ("run", "fix-bug", "t3"): "release-blockers",
    }


def test_marked_bulk_success_clears_affected_marks(tmp_path: Path) -> None:
    tag_file = tmp_path / "agent_tags.json"
    a1 = _make_agent(suffix="t1")
    a2 = _make_agent(suffix="t2")
    a3 = _make_agent(suffix="t3")
    unrelated_identity = (AgentType.RUNNING, "other", "t4")
    app = _FakeApp([a1, a2, a3])
    app._marked_agents = {a1.identity, a3.identity, unrelated_identity}

    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", tag_file):
        app._apply_agent_tag_change(
            AgentTagModalResult(action="set", tag="release-blockers"),
            [a1, a3],
        )

    assert app._marked_agents == {unrelated_identity}


def test_successful_tag_change_invalidates_panel_cache_before_refresh(
    tmp_path: Path,
) -> None:
    tag_file = tmp_path / "agent_tags.json"
    agent = _make_agent()
    app = _FakeApp([agent])

    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", tag_file):
        app._apply_agent_tag_change(
            AgentTagModalResult(action="set", tag="release-blockers"),
            [agent],
        )

    assert app._agent_panel_index_cache is None
    assert app._panel_keys_cache is None
    assert app._nav_stops_cache is None
    assert app.events == ["invalidate", "refresh:True"]


def test_modal_dismiss_with_none_is_noop(tmp_path: Path) -> None:
    tag_file = tmp_path / "agent_tags.json"
    agent = _make_agent()
    app = _FakeApp([agent])
    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", tag_file):
        app.action_add_agent_tag()
        callback = app.pushed_callbacks[0]
        callback(None)
    assert agent.tag is None
    assert not tag_file.exists()
    assert app.refresh_calls == 0


def test_apply_set_no_change_does_not_rewrite_file(tmp_path: Path) -> None:
    tag_file = tmp_path / "agent_tags.json"
    tag_file.write_text(
        json.dumps([{"id": ["run", "fix-bug", "20240101120000"], "tag": "already"}])
    )
    mtime_before = tag_file.stat().st_mtime_ns
    agent = _make_agent()
    agent.tag = "already"
    app = _FakeApp([agent])
    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", tag_file):
        app.action_add_agent_tag()
        callback = app.pushed_callbacks[0]
        callback(AgentTagModalResult(action="set", tag="already"))
    # Tag was already present — no write occurred.
    assert tag_file.stat().st_mtime_ns == mtime_before


def test_modal_returns_normalized_result_via_validation() -> None:
    """Validation rejects '@'-prefixed input from the modal layer."""
    from sase.ace.agent_tags import InvalidTagError, validate_tag_name

    try:
        validate_tag_name("@bad")
    except InvalidTagError as exc:
        assert "must not start with '@'" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected InvalidTagError")

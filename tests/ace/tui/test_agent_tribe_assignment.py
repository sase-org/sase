"""Tests for the Agents-tab tribe modal action (``N`` keymap)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.agents._display import AgentDisplayMixin
from sase.ace.tui.actions.agents._tribe_assignment import AgentTribeAssignmentMixin
from sase.ace.tui.actions.proc_actions import TrackedProcCompletion, TrackedProcResult
from sase.ace.tui.modals.agent_tribe_modal import AgentTribeModal, AgentTribeModalResult
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.proc_observer import ObservedProc as ProcInfo


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

    def _submit_durable_proc(
        self,
        argv: Any,
        *,
        operation: str = "",
        request: Any = None,
        request_fingerprint: str = "",
        concurrency_keys: Any = (),
        proc_type: str | None = None,
        display_name: str | None = None,
        cl_name: str = "",
        project_file: str = "",
        duplicate_message: str | None = None,
        on_complete: Any = None,
        reload_on_complete: bool = True,
        notify_on_complete: bool = True,
        **kwargs: Any,
    ) -> ProcInfo:
        del argv, operation, request_fingerprint, concurrency_keys
        del duplicate_message, reload_on_complete, notify_on_complete, kwargs
        from sase.ops.commands.agent import _persist_directive_from_payload

        proc_info = ProcInfo(
            proc_id=f"task-{len(self.events)}",
            proc_type=proc_type or "agent-directive",
            cl_name=cl_name,
            project_file=project_file,
            status="running",
            message="running",
            started_at=datetime.now(),
            display_name=display_name,
        )
        try:
            payload = dict(request or {})
            updates = payload.get("updates")
            if isinstance(updates, list):
                for item in updates:
                    if isinstance(item, dict):
                        _persist_directive_from_payload(
                            item,
                            artifacts_dir=str(
                                item.get("artifacts_dir") or project_file
                            ),
                        )
            else:
                _persist_directive_from_payload(
                    payload,
                    artifacts_dir=str(payload.get("artifacts_dir") or project_file),
                )
            result = TrackedProcResult(success=True, message="ok")
        except Exception as exc:
            result = TrackedProcResult(
                success=False,
                message=str(exc),
                error=str(exc),
            )
        proc_info.status = "success" if result.success else "error"
        proc_info.message = result.message
        proc_info.error = result.error
        if on_complete is not None:
            on_complete(
                TrackedProcCompletion(
                    proc_info=proc_info,
                    success=result.success,
                    message=result.message,
                    output="",
                    payload=result.payload,
                    error=result.error,
                )
            )
        return proc_info


def test_action_no_op_when_not_on_agents_tab(tmp_path: Path) -> None:
    app = _FakeApp([_make_agent()])
    app.current_tab = "patches"
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


def test_standalone_tribe_assignment_does_not_create_agent_tribes_directory(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    monkeypatch.chdir(tmp_path)
    agent = _make_agent()
    app = _FakeApp([agent])

    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app._apply_agent_tribe_change(
            AgentTribeModalResult(action="set", tribe="release-blockers"),
            [agent],
        )

    assert agent.tribe == "release-blockers"
    assert json.loads(tribe_file.read_text()) == [
        {"id": ["run", "fix-bug", "20240101120000"], "tribe": "release-blockers"}
    ]
    assert not (tmp_path / "agent-tribes").exists()
    assert not (
        tmp_path / "agent-tribes" / ".agent_directive_persistence.lock"
    ).exists()


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


def test_clan_tribe_reassignment_rewrites_only_declaring_prompt(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    declarer_dir = tmp_path / "declarer"
    joiner_dir = tmp_path / "joiner"
    for artifacts_dir, prompt, name in (
        (
            declarer_dir,
            "%id:research.lead\n"
            "%clan(research, tribe=old, "
            "summary_script=sase_clan_summary_epic)\n"
            "Lead",
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
        "%id:research.lead\n"
        "%clan(research, tribe=new, "
        "summary_script=sase_clan_summary_epic)\n"
        "Lead"
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


def _make_clan_member(
    artifacts_dir: Path,
    *,
    clan: str = "research",
    generation: str = "g1",
    clan_tribe: str | None = "old",
    prompt: str | None = None,
    name: str = "research.lead",
) -> Agent:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "raw_xprompt.md").write_text(
        prompt
        or (
            "%id:research.lead\n"
            "%clan(research, tribe=old, summary_script=sase_clan_summary_epic)\n"
            "Lead"
        ),
        encoding="utf-8",
    )
    meta: dict[str, Any] = {
        "name": name,
        "agent_clan": clan,
        "agent_clan_generation": generation,
    }
    if clan_tribe is not None:
        meta["clan_tribe"] = clan_tribe
    (artifacts_dir / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return _make_agent(
        artifacts_dir=str(artifacts_dir),
        agent_name=name,
        agent_clan=clan,
        agent_clan_generation=generation,
        clan_tribe=clan_tribe,
    )


def _make_clan_container(
    *,
    clan: str = "research",
    generation: str = "g1",
    clan_tribe: str | None = "old",
) -> Agent:
    return _make_agent(
        artifacts_dir=None,
        raw_suffix=None,
        agent_name=None,
        agent_clan=clan,
        agent_clan_generation=generation,
        clan_tribe=clan_tribe,
        is_clan_container=True,
    )


def test_modal_names_clan_for_single_clan_target(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    member = _make_agent(agent_clan="research", clan_tribe="old")
    app = _FakeApp([member])
    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app.action_edit_agent_tribe()
    modal = app.pushed_modals[0]
    assert isinstance(modal, AgentTribeModal)
    assert modal._target_label == "clan research"
    assert modal._current_tribe == "old"


def test_modal_names_clan_for_bulk_clan_targets(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    a1 = _make_agent(suffix="t1", agent_clan="research", clan_tribe="old")
    a2 = _make_agent(suffix="t2", agent_clan="research", clan_tribe="old")
    app = _FakeApp([a1, a2])
    app._marked_agents = {a1.identity, a2.identity}
    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app.action_edit_agent_tribe()
    modal = app.pushed_modals[0]
    assert isinstance(modal, AgentTribeModal)
    assert modal._target_label == "clan research (2 members)"


def test_synthetic_clan_row_edit_writes_record_only(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from sase.core.agent_clan_record import load_clan_record

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    tribe_file = tmp_path / "agent_tribes.json"
    container = _make_clan_container()
    app = _FakeApp([container])
    assert container.get_artifacts_dir() is None

    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app._apply_agent_tribe_change(
            AgentTribeModalResult(action="set", tribe="new"),
            [container],
        )

    assert container.clan_tribe == "new"
    record = load_clan_record("research", strict=True)
    assert record is not None
    attribute = record["generations"]["g1"]["tribe"]
    assert attribute["value"] == "new"
    assert attribute["source"] == "edited"
    assert attribute["source_identity"] == "tui"
    assert not tribe_file.exists()
    assert any("for clan research" in m for m, _ in app.notifications)


def test_member_edit_writes_meta_and_record(tmp_path: Path, monkeypatch: Any) -> None:
    from sase.core.agent_clan_record import load_clan_record

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    member_dir = tmp_path / "member"
    member = _make_clan_member(member_dir)
    app = _FakeApp([member])

    with (
        patch(
            "sase.core.agent_artifact_index_lifecycle."
            "update_agent_artifact_index_for_marker_mutation"
        ),
    ):
        app._apply_agent_tribe_change(
            AgentTribeModalResult(action="set", tribe="new"),
            [member],
        )

    assert member.clan_tribe == "new"
    meta = json.loads((member_dir / "agent_meta.json").read_text(encoding="utf-8"))
    assert meta["clan_tribe"] == "new"
    prompt = (member_dir / "raw_xprompt.md").read_text(encoding="utf-8")
    assert "%clan(research, tribe=new" in prompt
    record = load_clan_record("research", strict=True)
    assert record is not None
    assert record["generations"]["g1"]["tribe"]["value"] == "new"
    assert record["generations"]["g1"]["tribe"]["source"] == "edited"


def test_clan_edits_deduplicate_to_one_record_write(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    declarer_dir = tmp_path / "declarer"
    joiner_dir = tmp_path / "joiner"
    declarer = _make_clan_member(declarer_dir)
    joiner = _make_clan_member(
        joiner_dir,
        prompt="%id(worker, clan=research)\nWork",
        name="research.worker",
    )
    app = _FakeApp([declarer, joiner])

    captured: dict[str, Any] = {}

    def _capture_submit(target: Any, **kwargs: Any) -> bool:
        captured.update(kwargs)
        return True

    with (
        patch(
            "sase.ace.tui.actions.agent_durable.submit_agent_directive",
            _capture_submit,
        ),
        patch(
            "sase.core.agent_artifact_index_lifecycle."
            "update_agent_artifact_index_for_marker_mutation"
        ),
    ):
        app._apply_agent_tribe_change(
            AgentTribeModalResult(action="set", tribe="new"),
            [declarer, joiner],
        )

    updates = captured["payload"]["updates"]
    records = [u["clan_record"] for u in updates if "clan_record" in u]
    assert len(records) == 1
    assert records[0] == {"clan": "research", "generation": "g1", "tribe": "new"}


def test_unset_tombstone_beats_newer_epic_member_after_reload(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from sase.core.agent_scan_facade import scan_agent_artifacts

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    projects_root = tmp_path / "projects"
    member_dir = projects_root / "myproj" / "artifacts" / "ace-run" / "20260506120000"
    member = _make_clan_member(
        member_dir,
        prompt="%id(worker, clan=research)\nWork",
        name="research.worker",
    )
    app = _FakeApp([member])

    with (
        patch(
            "sase.core.agent_artifact_index_lifecycle."
            "update_agent_artifact_index_for_marker_mutation"
        ),
    ):
        app._apply_agent_tribe_change(
            AgentTribeModalResult(action="unset", tribe=None),
            [member],
        )

    # A newer epic member still carrying clan_tribe=epic must not win.
    newer_dir = projects_root / "myproj" / "artifacts" / "ace-run" / "20260506120100"
    newer_dir.mkdir(parents=True)
    (newer_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "research.newer",
                "agent_clan": "research",
                "agent_clan_generation": "g1",
                "clan_tribe": "epic",
            }
        ),
        encoding="utf-8",
    )
    snapshot = scan_agent_artifacts(projects_root)
    contexts = [
        context
        for context in snapshot.clan_context
        if context.agent_clan == "research" and context.agent_clan_generation == "g1"
    ]
    assert len(contexts) == 1
    assert contexts[0].clan_tribe is None


def test_failed_clan_edit_rolls_back_siblings_and_container(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from sase.ace.tui.proc_observer import ObservedProc as ProcInfo

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    member_dir = tmp_path / "member"
    sibling_dir = tmp_path / "sibling"
    member = _make_clan_member(member_dir)
    sibling = _make_clan_member(
        sibling_dir,
        prompt="%id(worker, clan=research)\nWork",
        name="research.worker",
    )
    container = _make_clan_container()
    app = _FakeApp([member, sibling, container])

    captured: dict[str, Any] = {}

    def _capture_submit(target: Any, **kwargs: Any) -> bool:
        captured.update(kwargs)
        return True

    with patch(
        "sase.ace.tui.actions.agent_durable.submit_agent_directive",
        _capture_submit,
    ):
        app._apply_agent_tribe_change(
            AgentTribeModalResult(action="set", tribe="new"),
            [member],
        )

    # Optimistic display covers the edited member, its sibling, and the
    # synthetic container sharing the same (clan, generation).
    assert member.clan_tribe == "new"
    assert sibling.clan_tribe == "new"
    assert container.clan_tribe == "new"

    proc_info = ProcInfo(
        proc_id="task-0",
        proc_type="agent-directive",
        cl_name="agent-tribes",
        project_file="agent-tribes",
        status="error",
        message="boom",
        started_at=datetime.now(),
    )
    captured["on_complete"](
        TrackedProcCompletion(
            proc_info=proc_info,
            success=False,
            message="boom",
            output="",
            payload=None,
            error="boom",
        )
    )

    assert member.clan_tribe == "old"
    assert sibling.clan_tribe == "old"
    assert container.clan_tribe == "old"
    assert any("persist failed" in m for m, _ in app.notifications)

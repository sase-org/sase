"""Tests for moving agents between agent tabs (phase tab-moves)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Label

from sase.ace.tui.modals.agent_tribe_modal import AgentTribeModal
from tests.ace.tui._agent_tribe_assignment_helpers import _FakeApp, _make_agent


def _write_agent(artifacts_dir: Path, *, prompt: str, meta: dict[str, Any]) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "raw_xprompt.md").write_text(prompt, encoding="utf-8")
    (artifacts_dir / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _read_meta(artifacts_dir: Path) -> dict[str, Any]:
    with open(artifacts_dir / "agent_meta.json", encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, dict)
    return data


def test_set_tab_prompt_mutator_rewrites_and_removes() -> None:
    from sase.ops.commands._agent_directive import _prompt_mutator_from_spec

    set_mutator = _prompt_mutator_from_spec({"kind": "set_tab", "tab": "blog"})
    assert set_mutator is not None
    assert set_mutator("%id:worker\nWork") == "%tab:blog\n%id:worker\nWork"
    # Replacing an existing tab does not duplicate the directive.
    assert set_mutator("%tab:old\n%id:worker\nWork") == "%tab:blog\n%id:worker\nWork"

    unset_mutator = _prompt_mutator_from_spec({"kind": "set_tab", "tab": None})
    assert unset_mutator is not None
    assert unset_mutator("%tab:blog\n%id:worker\nWork") == "%id:worker\nWork"

    # Tribe-only specs without a tab key leave %tab directives untouched.
    tribe_mutator = _prompt_mutator_from_spec({"kind": "set_tribe", "tribe": "new"})
    assert tribe_mutator is not None
    assert (
        tribe_mutator("%tab:blog\n%id:worker\nWork")
        == "%tab:blog\n%id(worker, tribe=new)\nWork"
    )
    # A composed tribe+tab spec rewrites both in one pass.
    composed = _prompt_mutator_from_spec(
        {"kind": "set_tribe", "tribe": "new", "tab": "blog"}
    )
    assert composed is not None
    assert (
        composed("%tab:old\n%id:worker\nWork")
        == "%tab:blog\n%id(worker, tribe=new)\nWork"
    )


def test_persist_directive_tab_meta_and_prompt(tmp_path: Path) -> None:
    from sase.ops.commands._agent_directive import persist_directive_from_payload

    artifacts_dir = tmp_path / "agent"
    _write_agent(
        artifacts_dir,
        prompt="%id:worker\nWork",
        meta={"name": "worker"},
    )
    with patch(
        "sase.core.agent_artifact_index_lifecycle."
        "update_agent_artifact_index_for_marker_mutation"
    ):
        persist_directive_from_payload(
            {
                "artifacts_dir": str(artifacts_dir),
                "prompt": {"kind": "set_tab", "tab": "blog"},
                "meta_set": {"agent_tab": "blog", "agent_tab_source": "moved"},
            },
            artifacts_dir=str(artifacts_dir),
        )
    meta = _read_meta(artifacts_dir)
    assert meta["agent_tab"] == "blog"
    assert meta["agent_tab_source"] == "moved"
    assert (
        (artifacts_dir / "raw_xprompt.md")
        .read_text(encoding="utf-8")
        .startswith("%tab:blog\n")
    )

    with patch(
        "sase.core.agent_artifact_index_lifecycle."
        "update_agent_artifact_index_for_marker_mutation"
    ):
        persist_directive_from_payload(
            {
                "artifacts_dir": str(artifacts_dir),
                "prompt": {"kind": "set_tab", "tab": None},
                "meta_remove": ["agent_tab", "agent_tab_source"],
            },
            artifacts_dir=str(artifacts_dir),
        )
    meta = _read_meta(artifacts_dir)
    assert "agent_tab" not in meta
    assert "agent_tab_source" not in meta
    assert "%tab" not in (artifacts_dir / "raw_xprompt.md").read_text(encoding="utf-8")


def test_cli_tab_set_moves_session_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    from sase.agent.names._common import NamedAgent
    from sase.agents import cli_tab

    root_dir = tmp_path / "root"
    follow_dir = tmp_path / "follow"
    other_dir = tmp_path / "other"
    _write_agent(
        root_dir,
        prompt="%id:worker\nWork",
        meta={"name": "worker", "agent_session": "s1"},
    )
    _write_agent(
        follow_dir,
        prompt="%id:helper\nHelp",
        meta={"name": "helper", "agent_session": "s1"},
    )
    _write_agent(
        other_dir,
        prompt="%id:solo\nSolo",
        meta={"name": "solo"},
    )
    monkeypatch.setattr(
        cli_tab,
        "find_named_agent",
        lambda name: NamedAgent(
            name=name, artifacts_dir=str(root_dir), is_done=False, outcome=None
        ),
    )
    monkeypatch.setattr(
        cli_tab,
        "_iter_local_metas",
        lambda: iter(
            [
                (root_dir, _read_meta(root_dir)),
                (follow_dir, _read_meta(follow_dir)),
                (other_dir, _read_meta(other_dir)),
            ]
        ),
    )
    with patch(
        "sase.core.agent_artifact_index_lifecycle."
        "update_agent_artifact_index_for_marker_mutation"
    ):
        cli_tab._move_root("worker", "Blog")
    out = capsys.readouterr().out
    assert "blog" in out
    assert _read_meta(root_dir)["agent_tab"] == "blog"
    assert _read_meta(follow_dir)["agent_tab"] == "blog"
    assert _read_meta(follow_dir)["agent_tab_source"] == "moved"
    assert "agent_tab" not in _read_meta(other_dir)

    with patch(
        "sase.core.agent_artifact_index_lifecycle."
        "update_agent_artifact_index_for_marker_mutation"
    ):
        cli_tab._move_root("worker", None)
    assert "agent_tab" not in _read_meta(root_dir)
    assert "agent_tab" not in _read_meta(follow_dir)


def test_cli_tab_set_rejects_reserved_tab(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.names._common import NamedAgent
    from sase.agents import cli_tab

    root_dir = tmp_path / "root"
    _write_agent(root_dir, prompt="%id:worker\nWork", meta={"name": "worker"})
    monkeypatch.setattr(
        cli_tab,
        "find_named_agent",
        lambda name: NamedAgent(
            name=name, artifacts_dir=str(root_dir), is_done=False, outcome=None
        ),
    )
    with pytest.raises(SystemExit) as excinfo:
        cli_tab._move_root("worker", "local")
    assert excinfo.value.code == 2


def test_modal_apply_tab_move_with_remote_refusal(tmp_path: Path) -> None:
    from sase.ace.tui.modals.agent_tribe_modal import AgentTribeModalResult

    local_dir = tmp_path / "local"
    _write_agent(local_dir, prompt="%id:worker\nWork", meta={"name": "worker"})
    local = _make_agent(
        suffix="local",
        artifacts_dir=str(local_dir),
        agent_name="worker",
    )
    remote = _make_agent(
        suffix="remote",
        agent_name="far",
        fleet_origin_alias="apollo",
    )
    app = _FakeApp([local, remote])

    with patch(
        "sase.core.agent_artifact_index_lifecycle."
        "update_agent_artifact_index_for_marker_mutation"
    ):
        app._apply_agent_tribe_change(
            AgentTribeModalResult(
                action="keep", tribe=None, tab_action="set", tab="blog"
            ),
            [local, remote],
        )
    assert local.agent_tab == "blog"
    assert remote.agent_tab is None
    assert _read_meta(local_dir)["agent_tab"] == "blog"
    assert _read_meta(local_dir)["agent_tab_source"] == "moved"
    messages = [message for message, _severity in app.notifications]
    assert any("owning machine" in message for message in messages)
    assert any("Moved 1 agent to blog" in message for message in messages)


def test_modal_apply_remote_only_tab_move_refuses(tmp_path: Path) -> None:
    from sase.ace.tui.modals.agent_tribe_modal import AgentTribeModalResult

    remote = _make_agent(
        suffix="remote",
        agent_name="far",
        fleet_origin_alias="apollo",
    )
    app = _FakeApp([remote])
    app._apply_agent_tribe_change(
        AgentTribeModalResult(action="keep", tribe=None, tab_action="set", tab="blog"),
        [remote],
    )
    assert remote.agent_tab is None
    assert any("owning machine" in message for message, _severity in app.notifications)


class _ModalTestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


async def test_tribe_and_tab_modal_shows_tab_input() -> None:
    async with _ModalTestApp().run_test() as pilot:
        modal = AgentTribeModal(
            target_label="agent-x",
            current_tribe=None,
            known_tribes=(),
            tab_enabled=True,
            current_tab="blog",
            known_tabs=("blog", "sase"),
        )
        pilot.app.push_screen(modal)
        await pilot.pause()
        title = modal.query_one("#modal-title", Label).render()
        assert title.plain == "Tribe & Tab: agent-x"
        current = modal.query_one("#agent-tab-current", Label).render()
        assert current.plain == "Tab: blog"
        # The tab input exists alongside the tribe input.
        modal.query_one("#agent-tribe-input")
        modal.query_one("#agent-tab-input")


async def test_tribe_only_modal_has_no_tab_input() -> None:
    async with _ModalTestApp().run_test() as pilot:
        modal = AgentTribeModal(
            target_label="agent-x",
            current_tribe=None,
            known_tribes=(),
        )
        pilot.app.push_screen(modal)
        await pilot.pause()
        title = modal.query_one("#modal-title", Label).render()
        assert title.plain == "Tribe: agent-x"
        assert not modal.query("#agent-tab-input")

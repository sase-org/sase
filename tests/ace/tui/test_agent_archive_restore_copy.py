"""Archive restore copy-palette, footer, and help tests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents._archive_view import init_agents_archive_view_state
from sase.feature_flags import override_flags
from tests.ace.tui._agent_archive_restore_helpers import make_agent, open_archive

__all__ = [
    "test_copy_artifacts_dir_missing_warns",
    "test_copy_handoff_prefills_prompt",
    "test_artifacts_copy_reference_ignores_agents_tab",
    "test_artifacts_copy_reference_on_artifacts_tab",
    "test_copy_json_archive_copies_bundle",
    "test_copy_json_payload_is_metadata",
    "test_copy_link_format_is_followable",
    "test_copy_palette_new_targets_dispatch",
    "test_footer_offers_restore_without_live_chips",
    "test_help_archive_box_lists_action_rows",
    "test_help_copy_mode_lists_new_targets",
    "test_y_copies_agent_reference_on_agents_tab",
]


def test_y_copies_agent_reference_on_agents_tab(monkeypatch: Any) -> None:
    import sase.ace.tui.actions.clipboard._agents as agents_clipboard
    from sase.ace.tui.actions.clipboard._agents import ClipboardAgentsMixin
    from sase.ace.tui.actions.clipboard._artifacts import ClipboardArtifactsMixin

    copied: dict[str, Any] = {}
    monkeypatch.setattr(
        agents_clipboard,
        "schedule_copy_delivery",
        lambda _o, content, **kwargs: copied.update(content=content, kwargs=kwargs),
    )
    monkeypatch.setattr(
        agents_clipboard, "reference_for_agent_row", lambda _agent: "test.1"
    )

    class App(ClipboardArtifactsMixin, ClipboardAgentsMixin):
        pass

    app = App()
    agent = make_agent()
    app.__dict__.update(
        {
            "current_tab": "agents",
            "current_artifacts_pane_key": "agents",
            "_inbox_agent": agent,
            "notify": lambda *a, **k: None,
            "_get_selected_agent": lambda: agent,
        }
    )
    init_agents_archive_view_state(app)
    app.action_agents_copy_reference()
    assert copied.get("content") == "@test.1"


def test_artifacts_copy_reference_ignores_agents_tab(monkeypatch: Any) -> None:
    from sase.ace.tui.actions.clipboard._agents import ClipboardAgentsMixin
    from sase.ace.tui.actions.clipboard._artifacts import ClipboardArtifactsMixin

    copied: list[str] = []

    class App(ClipboardArtifactsMixin, ClipboardAgentsMixin):
        pass

    app = App()
    app.__dict__.update(
        {
            "current_tab": "agents",
            "current_artifacts_pane_key": "agents",
            "notify": lambda *a, **k: None,
            "_copy_agent_reference": lambda: copied.append("agent"),
            "_run_artifact_reference_action": lambda **k: copied.append("artifact"),
            "_copy_patch_reference": lambda: copied.append("patch"),
        }
    )
    app.action_artifacts_copy_reference()
    assert copied == []


def test_artifacts_copy_reference_on_artifacts_tab() -> None:
    from sase.ace.tui.actions.clipboard._artifacts import ClipboardArtifactsMixin

    ran: list[object] = []

    class App(ClipboardArtifactsMixin):
        pass

    app = App()
    app.__dict__.update(
        {
            "current_tab": "artifacts",
            "current_artifacts_subtab": "stitches",
            "_run_artifact_reference_action": lambda **kwargs: ran.append(kwargs),
            "_copy_patch_reference": lambda: ran.append("patch"),
        }
    )
    app.action_artifacts_copy_reference()
    assert ran == [{"handoff": False}]


def test_copy_palette_new_targets_dispatch(monkeypatch: Any) -> None:
    from sase.ace.tui.actions.clipboard._core import ClipboardCoreMixin

    handled: list[str] = []

    class App(ClipboardCoreMixin):
        pass

    app = App()
    app.__dict__.update(
        {
            "_keymap_registry": SimpleNamespace(
                copy_mode=SimpleNamespace(
                    keys={
                        "agents": {
                            "chat": "c",
                            "file_path": "E",
                            "name": "n",
                            "prompt": "p",
                            "reference": "at",
                            "handoff": "!",
                            "link": "l",
                            "json": "j",
                            "artifacts_dir": "d",
                            "tool_run_id": "r",
                            "snapshot": "s",
                        }
                    }
                )
            ),
            "notify": lambda *a, **k: None,
        }
    )
    for target in ("handoff", "link", "json", "artifacts_dir"):
        monkeypatch.setattr(
            App,
            f"_copy_agent_{target}",
            lambda self, _t=target: handled.append(_t),
            raising=False,
        )
    for key, target in (
        ("!", "handoff"),
        ("l", "link"),
        ("j", "json"),
        ("d", "artifacts_dir"),
    ):
        assert app._handle_agents_copy_key(key) is True
    assert handled == ["handoff", "link", "json", "artifacts_dir"]


def test_copy_link_format_is_followable(monkeypatch: Any) -> None:
    import sase.ace.tui.actions.clipboard._agents as agents_clipboard
    from sase.ace.tui.actions.clipboard._agents import ClipboardAgentsMixin
    from sase.ace.tui.actions.clipboard._artifact_reference_resolution import (
        reference_for_agent_row,
    )
    from sase.ace.tui.actions.clipboard._helpers import format_markdown_link

    copied: dict[str, Any] = {}
    monkeypatch.setattr(
        agents_clipboard,
        "schedule_copy_delivery",
        lambda _o, content, **kwargs: copied.update(content=content),
    )

    class App(ClipboardAgentsMixin):
        pass

    app = App()
    agent = make_agent()
    app.__dict__.update(
        {
            "notify": lambda *a, **k: None,
            "_get_selected_agent": lambda: agent,
        }
    )
    init_agents_archive_view_state(app)
    app._copy_agent_link()
    reference = reference_for_agent_row(agent)
    assert reference is not None
    assert copied.get("content") == format_markdown_link(f"@{reference}", reference)
    assert "agent:agent:" not in str(copied.get("content"))


def test_copy_json_payload_is_metadata(monkeypatch: Any) -> None:
    import sase.ace.tui.actions.clipboard._agents as agents_clipboard
    from sase.ace.tui.actions.clipboard._agents import ClipboardAgentsMixin

    copied: dict[str, Any] = {}
    monkeypatch.setattr(
        agents_clipboard,
        "schedule_copy_delivery",
        lambda _o, content, **kwargs: copied.update(content=content),
    )

    class App(ClipboardAgentsMixin):
        pass

    app = App()
    app.__dict__.update(
        {
            "notify": lambda *a, **k: None,
            "_get_selected_agent": lambda: make_agent(),
        }
    )
    init_agents_archive_view_state(app)
    app._copy_agent_json()
    payload = json.loads(copied["content"])
    assert payload["agent_name"] == "bob-cli-5p.4"
    assert payload["status"] == "DONE"


def test_copy_json_archive_copies_bundle(monkeypatch: Any, tmp_path: Any) -> None:
    import sase.ace.tui.actions.clipboard._agents as agents_clipboard
    from sase.ace.tui.actions.clipboard._agents import ClipboardAgentsMixin

    copied: dict[str, Any] = {}
    monkeypatch.setattr(
        agents_clipboard,
        "schedule_copy_delivery",
        lambda _o, content, **kwargs: copied.update(content=content, kwargs=kwargs),
    )
    bundle = tmp_path / "run.json"
    bundle.write_text('{"agent_name": "bob-cli-5p.4"}', encoding="utf-8")

    class App(ClipboardAgentsMixin):
        pass

    app = App()
    agent = make_agent()
    app.__dict__.update(
        {
            "notify": lambda *a, **k: None,
            "_get_selected_agent": lambda: agent,
        }
    )
    init_agents_archive_view_state(app)
    open_archive(app)
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._archive_column.archive_light_row",
        lambda _o, _k: {"bundle_path": str(bundle), "agent_name": "bob-cli-5p.4"},
    )
    app._copy_agent_json()
    assert copied["kwargs"]["copied_label"] == "archive bundle JSON"
    assert callable(copied["content"])
    assert json.loads(copied["content"]())["agent_name"] == "bob-cli-5p.4"


def test_copy_artifacts_dir_missing_warns() -> None:
    from sase.ace.tui.actions.clipboard._agents import ClipboardAgentsMixin

    class App(ClipboardAgentsMixin):
        pass

    app = App()
    notices: list[str] = []
    app.__dict__.update(
        {
            "notify": lambda message, **_k: notices.append(message),
            "_get_selected_agent": lambda: make_agent(artifacts_dir=None),
        }
    )
    init_agents_archive_view_state(app)
    app._copy_agent_artifacts_dir()
    assert notices == ["Selected agent has no artifacts directory"]


def test_copy_handoff_prefills_prompt(monkeypatch: Any) -> None:
    import sase.ace.tui.actions.clipboard._agents as agents_clipboard
    from sase.ace.tui.actions.clipboard._agents import ClipboardAgentsMixin

    monkeypatch.setattr(
        agents_clipboard, "reference_for_agent_row", lambda _agent: "test.1"
    )

    class App(ClipboardAgentsMixin):
        pass

    app = App()
    prompted: dict[str, Any] = {}
    app.__dict__.update(
        {
            "notify": lambda *a, **k: None,
            "_get_selected_agent": lambda: make_agent(),
            "_show_prompt_input_bar_for_home": lambda **kwargs: prompted.update(kwargs),
        }
    )
    init_agents_archive_view_state(app)
    app._copy_agent_handoff()
    assert prompted.get("initial_text") == "@test.1 "


def test_footer_offers_restore_without_live_chips() -> None:
    from sase.ace.tui.widgets._keybinding_bindings_agents import AgentBindingsMixin

    mixin = AgentBindingsMixin()
    mixin._kd = lambda name: name  # type: ignore[attr-defined]
    bindings = mixin._compute_archive_bindings(
        marked_count=0,
        has_selection=True,
        selection_is_container=False,
    )
    assert ("act_on_agent", "restore…") in bindings
    text = " ".join(f"{key} {label}" for key, label in bindings)
    for live in ("kill", "wait", "retry", "cleanup", "tabs", "Inbox"):
        assert live not in text


def test_help_archive_box_lists_action_rows() -> None:
    from sase.ace.tui.keymaps import load_keymap_registry
    from sase.ace.tui.modals.help_modal.agents_archive_sections import archive_sections

    km = load_keymap_registry({})
    boxes = dict(archive_sections(km))
    rows = boxes["Archive (read-only)"]
    assert rows[0][0] == ",a"
    assert all(len(key) <= 16 for key, _description in rows)
    assert all(len(description) <= 32 for _key, description in rows)
    descriptions = [description for _key, description in rows]
    assert "Restore archived run" in descriptions
    assert "Open archived chat" in descriptions
    assert "Fork archived run" in descriptions
    assert "Copy @agent: reference" in descriptions
    assert "More copy targets" in descriptions


def test_help_copy_mode_lists_new_targets() -> None:
    from sase.ace.tui.keymaps import load_keymap_registry
    from sase.ace.tui.modals.help_modal.agents_mode_sections import mode_sections

    km = load_keymap_registry({})
    boxes = dict(mode_sections(km))
    copy_rows = next(
        rows for title, rows in boxes.items() if title.startswith("Copy Mode")
    )
    descriptions = [description for _key, description in copy_rows]
    assert "Prefill prompt with @agent" in descriptions
    assert "Copy Markdown agent link" in descriptions
    assert "Copy agent JSON" in descriptions
    assert "Copy artifacts directory" in descriptions
    assert "Copy @agent: reference" in descriptions
    assert all(len(key) <= 16 for key, _description in copy_rows)
    assert all(len(description) <= 32 for _key, description in copy_rows)

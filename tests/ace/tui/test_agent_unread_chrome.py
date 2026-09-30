"""Batched unread chrome helper tests (phase sase-1d7.6).

Screenshot shape: unread inside collapsed clans of an expanded tribe, a
collapsed tribe panel, and off-tab rows. After a bulk clear the header,
machine chip / tab strip, and every tribe title settle on the same paint,
no panel expands, no full display rebuild runs, and patched rows are
bounded by visible changed rows.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from rich.text import Text

from sase.ace.tui.actions.agents._display_helpers import panel_widget_id_for_key
from sase.ace.tui.actions.agents._notification_unread_projection import (
    AgentNotificationUnreadMixin,
)
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_panels import AgentPanelGroup

from ._agent_unread_helpers import make_agent


class _FakeWidget:
    def __init__(self, agents: list[Agent]) -> None:
        self._agents = list(agents)
        self.titles: list[Text] = []


class _ChromeApp(AgentNotificationUnreadMixin):
    """Minimal owner for the batched unread chrome helper."""

    def __init__(
        self,
        agents: list[Agent],
        *,
        collapsed_panels: set[Any] | None = None,
        failing: set[tuple[AgentType, str, str | None]] | None = None,
    ) -> None:
        self._agents = list(agents)
        self._agents_with_children = list(agents)
        self.current_tab = "agents"
        self.current_idx = 0
        self._agent_panels_grouped = False
        self._collapsed_panel_keys = set(collapsed_panels or ())
        self._panel_group = AgentPanelGroup.from_agents(
            agents,
            collapsed_panel_keys=self._collapsed_panel_keys,
        )
        self._unread_completed_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._manual_unread_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._failing = set(failing or ())
        self.patch_calls: list[Agent] = []
        self.patch_kwargs: list[dict[str, object]] = []
        self.refresh_calls: list[dict[str, Any]] = []
        self.header_calls = 0
        self.info_calls = 0
        self.tribe_calls = 0
        self.title_calls: list[Any] = []
        self.panel_rebuild_calls: list[set[Any]] = []
        self._widgets: dict[str, _FakeWidget] = {}
        for key in self._panel_group.panel_keys:
            self._widgets[panel_widget_id_for_key(key)] = _FakeWidget([])

    def sync_widgets(self) -> None:
        """Paint the current roster into the fake panel widgets."""
        panel_index = self._agent_panel_index()
        for key in self._panel_group.panel_keys:
            wid = panel_widget_id_for_key(key)
            if key in self._collapsed_panel_keys:
                self._widgets[wid] = _FakeWidget([])
            else:
                self._widgets[wid] = _FakeWidget(panel_index.slice_for(key).agents)

    def _agent_panel_index(self):  # type: ignore[no-untyped-def]
        from sase.ace.tui.actions.agents._loading import DISMISSABLE_STATUSES
        from sase.ace.tui.models.agent_panel_index import build_agent_panel_index

        return build_agent_panel_index(
            self._agents,
            dismissable_statuses=DISMISSABLE_STATUSES,
            merge_tribe_panels=self._agent_panels_grouped,
        )

    def query_one(self, selector: str, *args: object) -> object:
        if selector == "#agent-list-container":
            return object()
        try:
            return self._widgets[selector.lstrip("#")]
        except KeyError:
            raise LookupError(f"no widget for {selector}") from None

    def _try_patch_agent_row(self, agent: Agent, **kwargs: object) -> bool:
        self.patch_calls.append(agent)
        self.patch_kwargs.append(kwargs)
        return agent.identity not in self._failing

    def _refresh_agents_display(self, **kwargs: Any) -> None:
        self.refresh_calls.append(kwargs)

    def _refresh_affected_panel_widgets(
        self, affected_keys: set[Any], **_: Any
    ) -> bool:
        self.panel_rebuild_calls.append(set(affected_keys))
        return True

    def _agent_panel_title_for_key(self, key: Any, panel_agents: list[Agent]) -> Text:
        self.title_calls.append(key)
        return Text(f"{key} unread=0")

    @staticmethod
    def _set_agent_panel_title(widget: _FakeWidget, title: Text) -> None:
        widget.titles.append(title)

    def _update_agents_header(self) -> None:
        self.header_calls += 1

    def _update_agents_info_panel(self) -> None:
        self.info_calls += 1

    def _refresh_tribe_summary_only(self) -> bool:
        self.tribe_calls += 1
        return True

    def _get_selected_agent(self) -> None:
        return None


def _clear_unread(app: _ChromeApp) -> set[tuple[AgentType, str, str | None]]:
    before = set(app._unread_completed_agent_ids)
    app._unread_completed_agent_ids = set()
    return before


def test_visible_rows_patch_and_collapsed_panel_skips() -> None:
    visible = make_agent(name="v", status="DONE", raw_suffix="v", tribe="alpha")
    hidden = make_agent(name="h", status="DONE", raw_suffix="h", tribe="beta")
    app = _ChromeApp([visible, hidden], collapsed_panels={"beta"})
    app.sync_widgets()
    app._unread_completed_agent_ids = {visible.identity, hidden.identity}

    ok = app._patch_unread_completed_agent_changes(_clear_unread(app))

    assert ok is True
    assert app.patch_calls == [visible]
    assert app.refresh_calls == []
    # The collapsed panel never expands: its widget still holds no rows.
    assert app._widgets[panel_widget_id_for_key("beta")]._agents == []
    assert app._collapsed_panel_keys == {"beta"}
    # Collapsed counts still settle via the batched title refresh.
    assert sorted(app.title_calls, key=str) == sorted(
        app._panel_group.panel_keys, key=str
    )
    assert app.header_calls == 1
    assert app.info_calls == 1
    assert app.tribe_calls == 1


def test_collapsed_clan_member_patches_only_its_container() -> None:
    member = make_agent(name="research.done", status="DONE", raw_suffix="done")
    member.agent_clan = "research"
    member.agent_clan_generation = "generation"
    complete = project_clan_tree([member])
    container = complete[0]
    app = _ChromeApp([container])
    app._agents_with_children = [container, member]
    app.sync_widgets()
    app._unread_completed_agent_ids = {member.identity}

    ok = app._patch_unread_completed_agent_changes(_clear_unread(app))

    assert ok is True
    assert app.patch_calls == [container]
    assert app.refresh_calls == []
    assert app.header_calls == 1
    assert app.info_calls == 1
    assert app.tribe_calls == 1


def test_failing_visible_row_rebuilds_only_its_panel() -> None:
    first = make_agent(name="first", status="DONE", raw_suffix="first", tribe="alpha")
    second = make_agent(name="second", status="DONE", raw_suffix="second", tribe="beta")
    app = _ChromeApp([first, second], failing={second.identity})
    app.sync_widgets()
    app._unread_completed_agent_ids = {first.identity, second.identity}

    ok = app._patch_unread_completed_agent_changes(_clear_unread(app))

    assert ok is True
    assert app.patch_calls == [first, second]
    assert app.refresh_calls == []
    assert len(app.panel_rebuild_calls) == 1
    [rebuilt] = app.panel_rebuild_calls
    assert rebuilt != set(app._panel_group.panel_keys)
    assert app.header_calls == 1
    assert app.info_calls == 1
    assert app.tribe_calls == 1


def test_row_patches_skip_per_row_chrome() -> None:
    first = make_agent(name="first", status="DONE", raw_suffix="first")
    second = make_agent(name="second", status="DONE", raw_suffix="second")
    app = _ChromeApp([first, second])
    app.sync_widgets()
    app._unread_completed_agent_ids = {first.identity, second.identity}

    app._patch_unread_completed_agent_changes(_clear_unread(app))

    assert len(app.patch_calls) == 2
    assert app.patch_kwargs == [
        {"refresh_info": False, "refresh_title": False},
        {"refresh_info": False, "refresh_title": False},
    ]
    assert len(app.title_calls) <= len(app._panel_group.panel_keys)


def test_off_tab_unread_change_paints_nothing() -> None:
    agent = make_agent(status="DONE")
    app = _ChromeApp([agent])
    app.sync_widgets()
    app.current_tab = "artifacts"  # type: ignore[assignment]
    app._unread_completed_agent_ids = {agent.identity}

    ok = app._patch_unread_completed_agent_changes(_clear_unread(app))

    assert ok is True
    assert app.patch_calls == []
    assert app.refresh_calls == []
    assert app.header_calls == 0
    assert app.info_calls == 0
    assert app.tribe_calls == 0


def test_chrome_apply_span_reports_counters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trace_path = tmp_path / "tui_trace.jsonl"
    monkeypatch.setenv("SASE_TUI_TRACE", "1")
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", str(trace_path))
    visible = make_agent(name="v", status="DONE", raw_suffix="v", tribe="alpha")
    hidden = make_agent(name="h", status="DONE", raw_suffix="h", tribe="beta")
    app = _ChromeApp([visible, hidden], collapsed_panels={"beta"})
    app.sync_widgets()
    app._unread_completed_agent_ids = {visible.identity, hidden.identity}

    app._patch_unread_completed_agent_changes(_clear_unread(app))

    from sase.ace.tui.util.trace import _flush_trace_writes

    _flush_trace_writes()
    spans = [
        json.loads(line) for line in trace_path.read_text().splitlines() if line.strip()
    ]
    chrome = [s for s in spans if s.get("span") == "unread.chrome_apply"]
    assert len(chrome) == 1
    (span,) = chrome
    assert span["changed"] == 2
    assert span["visible_patched"] == 1
    assert span["collapsed_skipped"] == 1
    assert span["panel_rebuilds"] == 0

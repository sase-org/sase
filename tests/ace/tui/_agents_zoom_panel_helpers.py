"""Shared helpers for Agents-tab zoom panel tests."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.text import Text
from textual.app import App, ComposeResult
from textual.notifications import SeverityLevel

from sase.ace.testing import wait_for
from sase.ace.tui.actions.agents._panel_detail import AgentPanelDetailMixin
from sase.ace.tui.modals import ZoomPanelModal, ZoomPanelSeed, ZoomPanelTarget
from sase.ace.tui.modals.zoom_panel_modal import _renderable_to_text
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.agent_detail import AgentDetail


def _make_agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "zoom-agent",
        "project_file": "/tmp/project/project.sase",
        "status": "RUNNING",
        "start_time": datetime(2026, 6, 12, 12, 0, 0),
        "raw_suffix": "20260612-120000",
        "agent_name": "zoom.agent",
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class _FakePanel:
    def __init__(self, content: object) -> None:
        self.content = content


class _FakeFilePanel(_FakePanel):
    def __init__(self) -> None:
        super().__init__(Text("file"))
        self._file_list = ["/tmp/one.diff", "/tmp/two.md"]
        self.current_file_index = 1


class _FakeDetail:
    def __init__(
        self,
        *,
        info: bool = False,
        file_visible: bool = True,
        tools_visible: bool = False,
        layout_swapped: bool = False,
        has_file: bool = True,
        has_tools: bool = False,
    ) -> None:
        self._info = info
        self._file_visible = file_visible
        self._tools_visible = tools_visible
        self._layout_swapped = layout_swapped
        self._has_file_content = has_file
        self._has_tools_content = has_tools
        self.attempt_view_mode = "current-only"
        self._prompt = _FakePanel(Text("metadata"))
        self._file = _FakeFilePanel()
        self._tools = _FakePanel(Text("tools"))

    def is_info_mode(self) -> bool:
        return self._info

    def is_file_visible(self) -> bool:
        return self._file_visible

    def is_tools_visible(self) -> bool:
        return self._tools_visible

    def is_layout_swapped(self) -> bool:
        return self._layout_swapped

    def query_one(self, selector: str, *_: Any) -> Any:
        return {
            "#agent-prompt-panel": self._prompt,
            "#agent-file-panel": self._file,
            "#agent-tools-panel": self._tools,
        }[selector]


class _FakeZoomApp(AgentPanelDetailMixin):
    def __init__(
        self,
        *,
        agent: Agent | None = None,
        detail: _FakeDetail | None = None,
        current_attempt_number: int | None = None,
        isolation_owned: bool = False,
    ) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self.current_attempt_number = current_attempt_number
        self.refresh_interval = 10
        self._agent = agent
        self._agents = [agent] if agent is not None else []
        self._agents_with_children = list(self._agents)
        self._marked_agents = set()
        self._detail = detail or _FakeDetail()
        self._isolation_owned = isolation_owned
        self.isolation_calls = 0
        self.pushed: list[Any] = []
        self.notifications: list[tuple[str, str | None]] = []

    def _isolate_focused_panel(self) -> bool:
        self.isolation_calls += 1
        return self._isolation_owned

    def _get_selected_agent(self) -> Agent | None:
        return self._agent

    def query_one(self, selector: str, *_: Any) -> Any:
        if selector == "#agent-detail-panel":
            return self._detail
        raise KeyError(selector)

    def push_screen(self, screen: Any, callback: Any = None) -> None:
        del callback
        self.pushed.append(screen)

    def notify(self, message: str, *, severity: str | None = None, **_: Any) -> None:
        self.notifications.append((message, severity))


class _ModalTestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


class _RecordingZoomPanelModal(ZoomPanelModal):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.notifications: list[tuple[str, SeverityLevel]] = []

    def notify(
        self,
        message: str,
        *,
        title: str = "",
        severity: SeverityLevel = "information",
        timeout: float | None = None,
        markup: bool = True,
    ) -> None:
        del title, timeout, markup
        self.notifications.append((message, severity))


class _DetailTestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


async def _wait_for_file_content(
    pilot: Any,
    panel: Any,
    expected: str,
    *,
    attempts: int = 20,
) -> str:
    timeout = max(5.0, attempts * 0.05)

    def has_expected_content() -> bool:
        rendered = _renderable_to_text(getattr(panel, "content", None)) or ""
        return bool(panel._full_content is not None and expected in rendered)

    await wait_for(pilot, has_expected_content, timeout=timeout)
    rendered = _renderable_to_text(getattr(panel, "content", None)) or ""
    assert panel._full_content is not None
    assert expected in rendered
    return rendered


def _collapsed_file_modal(agent: Agent) -> ZoomPanelModal:
    return ZoomPanelModal(
        agent_provider=lambda: agent,
        initial_agent=agent,
        initial_target=ZoomPanelTarget.METADATA,
        seed=ZoomPanelSeed(metadata_renderable=Text("seed metadata")),
        refresh_interval=10,
    )


def _write_named_files(tmp_path: Any, names: list[str]) -> list[str]:
    """Write ``<name>.md`` files containing ``<name> file body`` and return paths."""
    paths: list[str] = []
    for name in names:
        path = tmp_path / f"{name}.md"
        path.write_text(f"{name} file body\n", encoding="utf-8")
        paths.append(str(path))
    return paths


def _seeded_files_modal(paths: list[str], *, file_index: int = 0) -> ZoomPanelModal:
    """Zoom modal opened on FILE with a fully seeded file list for a DONE agent."""
    agent = _make_agent(status="DONE", extra_files=paths)
    return ZoomPanelModal(
        agent_provider=lambda: agent,
        initial_agent=agent,
        initial_target=ZoomPanelTarget.FILE,
        seed=ZoomPanelSeed(
            file_list=tuple(agent.all_files),
            file_index=file_index,
            has_file_content=True,
        ),
        refresh_interval=10,
    )

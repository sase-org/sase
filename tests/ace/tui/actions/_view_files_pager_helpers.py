"""Shared pager harnesses for view-file hint action tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Static

from sase.ace.tui._app_action_availability import check_app_action
from sase.ace.tui.actions.hints._files import _COMMIT_TARGET_KIND, FileViewingMixin
from sase.ace.tui.actions.hints._processing import InputProcessingMixin
from sase.pager import PagerExit
from sase.pager.document import (
    AttachedTarget,
    PagerDocument,
    PagerOrigin,
    PagerSection,
    PagerTargetSpan,
)


class _FakeScreen:
    def __init__(self) -> None:
        self.notify = MagicMock()
        self.app = SimpleNamespace(push_screen=MagicMock())


class _PagerHost(App[None]):
    """Minimal Textual host used to exercise nested pager-screen behavior."""

    BINDINGS = [Binding("a", "host_a", "Host A", show=False)]

    def __init__(self) -> None:
        super().__init__()
        self.dismissed: list[PagerExit] = []
        self.host_a_count = 0

    def compose(self) -> ComposeResult:
        yield Static("host")

    def action_host_a(self) -> None:
        self.host_a_count += 1


class _PriorityTabPagerHost(_PagerHost):
    """Pager host with ACE-style priority Tab switching enabled."""

    BINDINGS = [
        *_PagerHost.BINDINGS,
        Binding("tab", "next_tab", "Next Tab", show=False, priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.current_tab = "agents"
        self.host_tab_count = 0

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        return check_app_action(self, action, parameters, super().check_action)

    def action_next_tab(self) -> None:
        self.host_tab_count += 1


class _ViewHost(InputProcessingMixin, FileViewingMixin, App[None]):
    """A real Textual host for the ACE view-file mixins."""

    def __init__(self, hint_mappings: dict[int, str]) -> None:
        super().__init__()
        self._hint_mappings = hint_mappings
        self._hint_tool_call_reports = {}
        self._hint_glossary_reports = {}
        self._hint_memory_reports = {}
        self._hint_artifact_read_refs = {}
        self._hint_commit_views = {}
        self._hint_patch_name = "cs"

    def compose(self) -> ComposeResult:
        yield Static("host")


def _target(spec: object, *, text: str = "abc1234") -> PagerTargetSpan:
    return PagerTargetSpan(
        kind=_COMMIT_TARGET_KIND,
        target=spec,
        start=0,
        end=len(text),
        text=text,
        source="attached",
    )


def _multi_section_document() -> PagerDocument:
    sections = tuple(
        PagerSection(
            identity=f"file:/tmp/{name}.py",
            title=f"{name}.py",
            kind="file",
            body="\n".join(f"{name} line {index}" for index in range(12)) + "\n",
        )
        for name in ("alpha", "beta")
    )
    return PagerDocument(sections=sections, title="2 files", origin=PagerOrigin.FILE)


def _attached_label_document(count: int) -> PagerDocument:
    lines: list[str] = []
    targets: list[AttachedTarget] = []
    offset = 0
    for index in range(count):
        label = f"commit{index:02d}"
        line = f"{label} subject {index}"
        targets.append(
            AttachedTarget(
                kind=_COMMIT_TARGET_KIND,
                target=f"target-{index}",
                start=offset,
                end=offset + len(label),
            )
        )
        lines.append(line)
        offset += len(line) + 1
    section = PagerSection(
        identity="pager-commits",
        title="Selected commits",
        kind=_COMMIT_TARGET_KIND,
        body="\n".join(lines) + "\n",
        targets=tuple(targets),
    )
    return PagerDocument(sections=(section,), title="commits", origin=PagerOrigin.FILE)

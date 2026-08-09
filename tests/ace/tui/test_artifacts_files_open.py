"""Smart-open, viewer hand-off, external-open, and agent-jump coverage."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.artifacts_files import ArtifactsFilesActionsMixin
from sase.ace.tui.graphics._viewer_types import ArtifactViewMode
from sase.core.artifact_file_types import ArtifactFile

from tests.ace.tui._artifacts_files_helpers import artifact_file


class _Pane:
    def __init__(
        self,
        entries: tuple[ArtifactFile, ...],
        *,
        modes: dict[str, ArtifactViewMode],
        selected: int | None = 0,
    ) -> None:
        self.entries = entries
        self.modes = modes
        self.selected = selected

    @property
    def selected_entry(self) -> ArtifactFile | None:
        if self.selected is None:
            return None
        return self.entries[self.selected]

    @property
    def selected_view_mode(self) -> ArtifactViewMode | None:
        entry = self.selected_entry
        return None if entry is None else self.modes[entry.id]

    def entry_targets(self) -> tuple[tuple[str, str], ...]:
        return tuple(("file", entry.id) for entry in self.entries)

    def entries_for_targets(
        self,
        targets: tuple[tuple[str, str], ...],
    ) -> tuple[ArtifactFile, ...]:
        by_target = {("file", entry.id): entry for entry in self.entries}
        return tuple(by_target[target] for target in targets if target in by_target)


class _FakeApp(ArtifactsFilesActionsMixin):
    def __init__(self, pane: _Pane) -> None:
        self.pane = pane
        self.notifications: list[tuple[str, str]] = []
        self.pushed: list[Any] = []
        self.opened_single: list[ArtifactFile] = []
        self.opened_many: list[list[ArtifactFile]] = []
        self._artifacts_marked_targets: dict[str, set[tuple[str, str]]] = {
            "other": set()
        }
        self.toggle_result = False
        self.current_tab = "patches"
        self.current_idx = 0
        self._agents: list[Any] = []
        self._dismissed_agent_objects: list[Any] = []
        self._dismissed_agents: set[tuple[Any, ...]] = set()
        self.saved_positions = 0
        self.revived: list[Any] = []
        self.reloaded_agent: Any | None = None

    def _files_pane(self) -> _Pane:
        return self.pane

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def push_screen(self, screen: Any) -> None:
        self.pushed.append(screen)

    def _open_artifact_file(self, entry: ArtifactFile) -> None:
        self.opened_single.append(entry)

    def _open_artifact_files(self, entries: list[ArtifactFile]) -> None:
        self.opened_many.append(entries)

    def _toggle_tracked_artifact_file_tmux_pane(self) -> bool:
        return self.toggle_result

    def _save_current_tab_position(self) -> None:
        self.saved_positions += 1

    def _do_revive_agent(self, agent: Any) -> None:
        self.revived.append(agent)
        if self.reloaded_agent is not None:
            self._agents.append(self.reloaded_agent)

    def _select_revived_agent(self, _agent: Any) -> bool:
        return False


def _pane(
    *entries: ArtifactFile,
    modes: tuple[ArtifactViewMode, ...],
    selected: int | None = 0,
) -> _Pane:
    return _Pane(
        entries,
        modes={entry.id: mode for entry, mode in zip(entries, modes, strict=True)},
        selected=selected,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "suffix", "default_view", "lexer"),
    [
        ("markdown", ".md", "rendered", "markdown"),
        ("text", ".py", "source", "python"),
    ],
)
async def test_files_enter_opens_text_like_rows_in_preview_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: ArtifactViewMode,
    suffix: str,
    default_view: str,
    lexer: str,
) -> None:
    stored = tmp_path / f"report{suffix}"
    stored.write_bytes(b"hello \xff world")
    entry = artifact_file("preview", path=str(stored))
    app = _FakeApp(_pane(entry, modes=(mode,)))
    pending: list[Any] = []

    def capture_task(_owner: Any, awaitable: Any, **_kwargs: Any) -> None:
        pending.append(awaitable)

    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts_files.spawn_pump_free_task",
        capture_task,
    )

    app.action_files_view_selected()
    await pending.pop()

    assert len(app.pushed) == 1
    payload = app.pushed[0]._payload
    assert payload.content == "hello \ufffd world"
    assert payload.reference == f"file:{entry.id}"
    assert payload.source_path == str(stored)
    assert payload.default_view == default_view
    assert payload.lexer == lexer
    assert app.opened_single == []


@pytest.mark.parametrize("mode", ["image", "pdf", "video"])
def test_files_enter_dispatches_media_directly_to_rich_viewer(
    mode: ArtifactViewMode,
) -> None:
    entry = artifact_file(mode, path=f"/tmp/example.{mode}")
    app = _FakeApp(_pane(entry, modes=(mode,)))

    app.action_files_view_selected()

    assert app.opened_single == [entry]
    assert app.pushed == []


def test_files_explicit_viewer_handoff_uses_visible_mark_order() -> None:
    first = artifact_file("first")
    second = artifact_file("second")
    third = artifact_file("third")
    app = _FakeApp(_pane(first, second, third, modes=("text", "image", "pdf")))
    app._artifacts_marked_targets["other"] = {
        ("file", third.id),
        ("file", first.id),
    }

    app.action_files_open_viewer()

    assert app.opened_many == [[first, third]]


def test_files_explicit_viewer_handoff_toggles_tracked_tmux_pane() -> None:
    entry = artifact_file("one")
    app = _FakeApp(_pane(entry, modes=("image",)))
    app.toggle_result = True

    app.action_files_open_viewer()

    assert app.opened_many == []


@contextmanager
def _record_suspend(
    calls: list[tuple[list[str], dict[str, Any]]],
    _app: Any,
    **metadata: Any,
) -> Iterator[None]:
    calls.append(([], metadata))
    yield


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("text", ["helix", "--", "/tmp/example.txt"]),
        ("markdown", ["helix", "--", "/tmp/example.txt"]),
        ("image", ["xdg-open", "--", "/tmp/example.txt"]),
        ("pdf", ["xdg-open", "--", "/tmp/example.txt"]),
        ("video", ["xdg-open", "--", "/tmp/example.txt"]),
    ],
)
def test_files_open_external_uses_editor_or_xdg_open_with_boundary(
    monkeypatch: pytest.MonkeyPatch,
    mode: ArtifactViewMode,
    expected: list[str],
) -> None:
    entry = artifact_file("external", path="/tmp/example.txt")
    app = _FakeApp(_pane(entry, modes=(mode,)))
    commands: list[list[str]] = []
    suspends: list[tuple[list[str], dict[str, Any]]] = []
    monkeypatch.setenv("EDITOR", "helix")
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts_files.suspend_for_external_tool",
        lambda app, **metadata: _record_suspend(suspends, app, **metadata),
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts_files.subprocess.run",
        lambda command, **_kwargs: (
            commands.append(command) or SimpleNamespace(returncode=0)
        ),
    )

    app.action_files_open_external()

    assert commands == [expected]
    assert suspends[0][1]["path_count"] == 1
    assert app.notifications == []


def test_files_open_external_names_missing_xdg_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = artifact_file("external")
    app = _FakeApp(_pane(entry, modes=("image",)))

    def missing_xdg_open(*_args: Any, **_kwargs: Any) -> None:
        raise FileNotFoundError("xdg-open")

    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts_files.suspend_for_external_tool",
        lambda app, **metadata: _record_suspend([], app, **metadata),
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts_files.subprocess.run",
        missing_xdg_open,
    )

    app.action_files_open_external()

    assert app.notifications == [("xdg-open executable not found", "warning")]


def _agent(
    entry: ArtifactFile,
    *,
    identity: str,
    raw_suffix: str | None = None,
) -> Any:
    return SimpleNamespace(
        identity=("run", identity, raw_suffix),
        raw_suffix=raw_suffix or Path(entry.agent_artifacts_dir or "").name,
        artifacts_dir=entry.agent_artifacts_dir,
        agent_name=entry.agent_name,
        project_file=f"/tmp/projects/{entry.project}/{entry.project}.sase",
    )


def test_files_open_agent_selects_live_match() -> None:
    entry = artifact_file(
        "linked",
        agent_artifacts_dir="/tmp/projects/alpha/artifacts/code/20260729010101",
    )
    target = _agent(entry, identity="target")
    other_entry = artifact_file(
        "other",
        agent_artifacts_dir="/tmp/projects/alpha/artifacts/code/20260729000000",
        agent_name="alpha.other--code",
    )
    app = _FakeApp(_pane(entry, modes=("text",)))
    app._agents = [_agent(other_entry, identity="other"), target]

    app.action_files_open_agent()

    assert app.current_tab == "agents"
    assert app.current_idx == 1
    assert app.saved_positions == 1
    assert app.revived == []
    assert app.notifications == []


def test_files_open_agent_revives_dismissed_match_once() -> None:
    entry = artifact_file(
        "dismissed",
        agent_artifacts_dir="/tmp/projects/alpha/artifacts/code/20260729020202",
    )
    dismissed = _agent(entry, identity="old")
    reloaded = _agent(entry, identity="new")
    app = _FakeApp(_pane(entry, modes=("text",)))
    app._dismissed_agent_objects = [dismissed]
    app._dismissed_agents = {dismissed.identity}
    app.reloaded_agent = reloaded

    app.action_files_open_agent()

    assert app.revived == [dismissed]
    assert app.current_tab == "agents"
    assert app.current_idx == 0
    assert app._agents[app.current_idx] is reloaded
    assert app.notifications == []


def test_files_open_agent_without_local_match_preserves_tab() -> None:
    entry = artifact_file(
        "unlinked",
        agent_artifacts_dir=None,
        agent_name=None,
    )
    app = _FakeApp(_pane(entry, modes=("text",)))

    app.action_files_open_agent()

    assert app.current_tab == "patches"
    assert app.saved_positions == 0
    assert app.notifications == [
        ("No local agent artifact backs this file.", "warning")
    ]


@pytest.mark.parametrize(
    "action",
    [
        "action_files_view_selected",
        "action_files_open_viewer",
        "action_files_open_external",
        "action_files_open_agent",
    ],
)
def test_files_open_actions_warn_on_empty_selection(action: str) -> None:
    app = _FakeApp(_pane(modes=(), selected=None))

    getattr(app, action)()

    assert app.notifications == [("No artifact file selected", "warning")]

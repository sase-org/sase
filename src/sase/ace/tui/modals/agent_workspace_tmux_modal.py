"""Modal for choosing which tmux workspace to open for an agent.

When the selected Agents-tab row has a visible ``WORKSPACES`` lane in
``SASE CONTEXT``, pressing ``t`` opens this keyboard-first chooser instead of
immediately opening the agent's own workspace. It offers one ``CURRENT`` option
for the agent's own project / ChangeSpec workspace plus one ``LINKED`` option
for every unique repository the agent context opened through ``sase repo open``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.models.agent import Agent
from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent
from sase.project_display_names import humanize_cl_name, project_display_name_for

from .base import OptionListNavigationMixin

# Workspace accent colors mirrored from the WORKSPACES SASE CONTEXT lane so the
# chooser visually echoes the lane that gates it (_agent_context_common.py).
_COLOR_SELECTOR = "bold #D7AF5F"
_COLOR_GLYPH = "bold #FF87D7"
_COLOR_TYPE_CURRENT = "bold #FF87D7"
_COLOR_TYPE_LINKED = "bold #AF87D7"
_COLOR_PRIMARY = "bold #FFAFD7"
_COLOR_PROJECT = "dim #D7AFD7"
_COLOR_PATH = "dim #D7AFD7"
_COLOR_REASON = "dim #D7D7AF"
_COLOR_ROLE = "italic #AF87FF"

_WORKSPACE_GLYPH = "▣"  # ▣ fallback workspace glyph
_PATH_CONNECTOR = "→"  # →

_MAX_LABEL_LEN = 30
_MAX_PROJECT_LEN = 16
_MAX_PATH_LEN = 30
_MAX_REASON_LEN = 28
_MAX_ROLE_LEN = 10

# Selector pool large enough for ``MAX_KEPT_OPENED_WORKSPACES`` (50) plus the
# always-present ``CURRENT`` option, while skipping the keys reserved for modal
# navigation (j/k) and cancel (q) in both cases.
_RESERVED_LOWER = {"j", "k", "q"}
_RESERVED_UPPER = {"J", "K", "Q"}


@dataclass(frozen=True)
class AgentWorkspaceTmuxChoice:
    """One tmux workspace target offered by :class:`AgentWorkspaceTmuxModal`."""

    kind: str  # "current" or "linked"
    label: str
    window_name: str
    project_name: str | None = None
    workspace_dir: str | None = None
    reason: str = ""
    agent_label: str | None = None


def _selector_pool() -> list[str]:
    """Return the ordered single-key selector pool for the chooser."""
    lower = [c for c in "abcdefghijklmnopqrstuvwxyz" if c not in _RESERVED_LOWER]
    digits = list("0123456789")
    upper = [c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if c not in _RESERVED_UPPER]
    return lower + digits + upper


def _workspace_tmux_selector_keys(count: int) -> list[str]:
    """Return ``count`` quick-select keys that avoid navigation/cancel keys."""
    return _selector_pool()[:count]


def _short_text(value: object, *, max_len: int) -> str:
    text = str(value or "")
    if len(text) <= max_len:
        return text
    if max_len <= 1:
        return text[:max_len]
    return text[: max_len - 1] + "…"


def _linked_window_name(event: OpenedWorkspaceDisplayEvent) -> str:
    """Return the tmux window name for a linked workspace event.

    Prefers the workspace directory basename (e.g. ``sase-core_12``) so sibling
    workspaces stay distinguishable on disk, falling back to the repo name.
    """
    workspace_dir = (event.workspace_dir or "").rstrip("/")
    if workspace_dir:
        basename = Path(workspace_dir).name
        if basename:
            return basename
    return event.name


def build_agent_workspace_tmux_choices(
    agent: Agent,
    events: tuple[OpenedWorkspaceDisplayEvent, ...],
    *,
    current_workspace_dir: str | None = None,
) -> list[AgentWorkspaceTmuxChoice]:
    """Build chooser targets: ``CURRENT`` first, then deduped ``LINKED`` repos.

    Pure and I/O-free: ``events`` are the cached opened-workspace events already
    loaded for the detail panel. Linked repos are deduped by
    ``(name, workspace_dir)`` so an agent-family context yields one option per
    repo destination, keeping the newest event's reason / role label.
    """
    project_name = (
        project_display_name_for(Path(agent.project_file).parent.name)
        if agent.project_file
        else None
    )
    current = AgentWorkspaceTmuxChoice(
        kind="current",
        label=agent.display_name or humanize_cl_name(agent.cl_name) or "workspace",
        window_name="",
        project_name=project_name,
        workspace_dir=current_workspace_dir,
    )
    choices: list[AgentWorkspaceTmuxChoice] = [current]

    seen: set[tuple[str, str]] = set()
    for event in events:
        workspace_dir = (event.workspace_dir or "").rstrip("/")
        if not workspace_dir:
            continue
        dedupe_key = (event.name, workspace_dir)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        choices.append(
            AgentWorkspaceTmuxChoice(
                kind="linked",
                label=event.name,
                window_name=_linked_window_name(event),
                workspace_dir=workspace_dir,
                reason=event.reason,
                agent_label=event.agent_label,
            )
        )
    return choices


def _agent_workspace_tmux_option_text(
    selector: str | None,
    choice: AgentWorkspaceTmuxChoice,
) -> Text:
    """Render one workspace choice as compact OptionList text."""
    text = Text()
    if selector is None:
        text.append("   ", style="dim")
    else:
        text.append(f"{selector}  ", style=_COLOR_SELECTOR)

    text.append(f"{_WORKSPACE_GLYPH} ", style=_COLOR_GLYPH)

    if choice.kind == "current":
        text.append("CURRENT", style=_COLOR_TYPE_CURRENT)
    else:
        text.append("LINKED ", style=_COLOR_TYPE_LINKED)
    text.append("  ")

    text.append(
        _short_text(choice.label, max_len=_MAX_LABEL_LEN),
        style=_COLOR_PRIMARY,
    )

    if choice.kind == "current" and choice.project_name:
        text.append("  · ")
        text.append(
            _short_text(choice.project_name, max_len=_MAX_PROJECT_LEN),
            style=_COLOR_PROJECT,
        )

    if choice.workspace_dir:
        text.append(f"  {_PATH_CONNECTOR} ")
        text.append(
            _short_text(_compact_path(choice.workspace_dir), max_len=_MAX_PATH_LEN),
            style=_COLOR_PATH,
        )

    if choice.agent_label:
        text.append("  ")
        text.append(
            _short_text(choice.agent_label, max_len=_MAX_ROLE_LEN),
            style=_COLOR_ROLE,
        )

    if choice.reason:
        text.append("  · ")
        text.append(
            _short_text(choice.reason, max_len=_MAX_REASON_LEN),
            style=_COLOR_REASON,
        )
    return text


def _compact_path(path: str) -> str:
    """Return a home-relative display for ``path`` when possible."""
    try:
        home = str(Path.home())
    except (OSError, RuntimeError):
        home = ""
    if home and path.startswith(home):
        return "~" + path[len(home) :]
    return path


class AgentWorkspaceTmuxModal(
    OptionListNavigationMixin,
    ModalScreen[int | None],
):
    """Keyboard-first chooser for an agent's tmux workspace targets."""

    _option_list_id = "agent-workspace-tmux-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("enter", "select_highlighted", "Open"),
    ]

    def __init__(self, choices: list[AgentWorkspaceTmuxChoice]) -> None:
        super().__init__()
        self._choices = choices
        selectors = _workspace_tmux_selector_keys(len(choices))
        self._selector_by_index = selectors
        self._index_by_selector = {key: index for index, key in enumerate(selectors)}

    def compose(self) -> ComposeResult:
        with Container(id="agent-workspace-tmux-container"):
            yield Label(self._title_text(), id="agent-workspace-tmux-title")
            yield OptionList(*self._create_options(), id=self._option_list_id)
            yield Static(self._hint_text(), id="agent-workspace-tmux-hints")

    def _title_text(self) -> str:
        count = len(self._choices)
        plural = "" if count == 1 else "s"
        return f"Tmux Workspace · {count} target{plural}"

    def _hint_text(self) -> str:
        return "a-z/0-9 select  enter open  j/k move  q/esc close"

    def _create_options(self) -> list[Option]:
        options: list[Option] = []
        for index, choice in enumerate(self._choices):
            selector = (
                self._selector_by_index[index]
                if index < len(self._selector_by_index)
                else None
            )
            options.append(
                Option(
                    _agent_workspace_tmux_option_text(selector, choice),
                    id=str(index),
                )
            )
        return options

    def on_mount(self) -> None:
        self.query_one(f"#{self._option_list_id}", OptionList).focus()

    def on_key(self, event: events.Key) -> None:
        if event.key not in self._index_by_selector:
            return
        self.dismiss(self._index_by_selector[event.key])
        event.prevent_default()
        event.stop()

    def action_select_highlighted(self) -> None:
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        index = option_list.highlighted
        if index is None or not 0 <= index < len(self._choices):
            return
        self.dismiss(index)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option and event.option.id is not None:
            self.dismiss(int(str(event.option.id)))

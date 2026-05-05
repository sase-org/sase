"""Unified artifact graph modal skeleton for ace."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option
from textual.worker import Worker, WorkerState

from sase.core.artifact_wire import (
    ArtifactDetailWire,
    ArtifactLinkWire,
    ArtifactNodeWire,
)

from .base import OptionListNavigationMixin

ArtifactShowFunc = Callable[[Path | str, str], ArtifactDetailWire]


def _default_artifact_index_path() -> Path:
    """Return the default unified artifact SQLite index path."""
    return Path.home() / ".sase" / "artifacts.sqlite"


class ArtifactPanelModal(OptionListNavigationMixin, ModalScreen[None]):
    """Modal that loads and displays one artifact graph node."""

    _option_list_id = "artifact-panel-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("enter", "noop", "Open"),
        ("ctrl+d", "scroll_detail_down", "Scroll down"),
        ("ctrl+u", "scroll_detail_up", "Scroll up"),
    ]

    def __init__(
        self,
        *,
        artifact_id: str,
        index_path: Path | str | None = None,
        show_func: ArtifactShowFunc | None = None,
    ) -> None:
        super().__init__()
        self._artifact_id = artifact_id
        self._index_path = index_path or _default_artifact_index_path()
        self._show_func = show_func
        self._detail: ArtifactDetailWire | None = None
        self._error_message: str | None = None
        self._load_worker: Worker[ArtifactDetailWire] | None = None

    def compose(self) -> ComposeResult:
        with Container(id="artifact-panel-container"):
            yield Label(f"Artifacts: {self._artifact_id}", id="artifact-panel-title")
            with Horizontal(id="artifact-panel-body"):
                with Vertical(id="artifact-panel-left"):
                    yield OptionList(
                        Option("Loading artifact...", id="__loading__", disabled=True),
                        id="artifact-panel-list",
                    )
                with Vertical(id="artifact-panel-right"):
                    with VerticalScroll(id="artifact-panel-detail-scroll"):
                        yield Static("Loading artifact...", id="artifact-panel-detail")
            yield Static(
                "j/k: navigate  enter: open  q/Esc: close  Ctrl+D/U: scroll",
                id="artifact-panel-hints",
            )

    def on_mount(self) -> None:
        """Start the initial artifact detail load."""
        self._render_loading()
        self._load_worker = self.run_worker(self._load_detail, thread=True)

    def _load_detail(self) -> ArtifactDetailWire:
        show_func = self._show_func
        if show_func is None:
            from sase.core.artifact_facade import artifact_show

            show_func = artifact_show
        return show_func(self._index_path, self._artifact_id)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Render the artifact load result."""
        if event.worker != self._load_worker:
            return

        if event.state == WorkerState.SUCCESS:
            self._detail = event.worker.result
            self._error_message = None
            self._render_detail()
        elif event.state == WorkerState.ERROR:
            self._detail = None
            self._error_message = str(event.worker.error or "Unknown artifact error")
            self._render_error()

    def _render_loading(self) -> None:
        self._replace_options(
            [Option("Loading artifact...", id="__loading__", disabled=True)]
        )
        self._update_detail("Loading artifact...")

    def _render_error(self) -> None:
        message = self._error_message or "Artifact could not be loaded."
        self._replace_options([Option("Load failed", id="__error__", disabled=True)])
        text = Text()
        text.append("Artifact load failed\n", style="bold red")
        text.append(message, style="red")
        self._update_detail(text)

    def _render_detail(self) -> None:
        detail = self._detail
        if detail is None or detail.node is None:
            self._replace_options([Option("Artifact not found", disabled=True)])
            self._update_detail(f"Artifact not found: {self._artifact_id}")
            return

        title = self.query_one("#artifact-panel-title", Label)
        title.update(f"Artifacts: {detail.node.display_title}")

        self._replace_options(self._build_options(detail))
        self._update_detail(self._build_detail_text(detail))

    def _build_options(self, detail: ArtifactDetailWire) -> list[Option]:
        options: list[Option] = []
        if detail.path_to_root:
            options.append(Option("Path to root", id="__path__", disabled=True))
            for node in detail.path_to_root:
                options.append(Option(_node_label(node), id=f"path:{node.id}"))

        if detail.children:
            options.append(Option("Children", id="__children__", disabled=True))
            for node in detail.children:
                options.append(Option(_node_label(node), id=f"child:{node.id}"))

        for label, links in (
            ("Outbound links", detail.outbound_links),
            ("Inbound links", detail.inbound_links),
        ):
            if not links:
                continue
            section_id = label.lower().replace(" ", "_")
            options.append(Option(label, id=f"__{section_id}__", disabled=True))
            for link in links[:25]:
                options.append(Option(_link_label(link), id=f"link:{link.id}"))

        if not options:
            options.append(Option("No linked artifacts", disabled=True))
        return options

    def _build_detail_text(self, detail: ArtifactDetailWire) -> Text:
        node = detail.node
        assert node is not None

        outbound_counts = _link_counts(detail.outbound_links)
        inbound_counts = _link_counts(detail.inbound_links)

        text = Text()
        text.append("Artifact\n", style="bold")
        text.append("ID: ", style="bold")
        text.append(f"{node.id}\n")
        text.append("Kind: ", style="bold")
        text.append(f"{node.kind}\n")
        text.append("Title: ", style="bold")
        text.append(f"{node.display_title}\n")
        if node.subtitle:
            text.append("Subtitle: ", style="bold")
            text.append(f"{node.subtitle}\n")
        text.append("Provenance: ", style="bold")
        text.append(f"{node.provenance}\n")
        text.append("\n")
        text.append(f"Path to root: {len(detail.path_to_root)}\n")
        text.append(f"Children: {len(detail.children)}\n")
        text.append(f"Outbound links: {_format_counts(outbound_counts)}\n")
        text.append(f"Inbound links: {_format_counts(inbound_counts)}\n")
        if detail.payloads:
            text.append(f"Payloads: {len(detail.payloads)}\n")
        if detail.diagnostics:
            text.append("\nDiagnostics\n", style="bold yellow")
            for issue in detail.diagnostics[:5]:
                text.append(f"- {issue.severity}: {issue.message}\n")
        return text

    def _replace_options(self, options: list[Option]) -> None:
        option_list = self.query_one("#artifact-panel-list", OptionList)
        option_list.clear_options()
        option_list.add_options(options)

    def _update_detail(self, content: str | Text) -> None:
        self.query_one("#artifact-panel-detail", Static).update(content)

    def action_noop(self) -> None:
        """Placeholder open action for the Phase 4.2 navigation model."""

    def action_scroll_detail_down(self) -> None:
        self.query_one("#artifact-panel-detail-scroll", VerticalScroll).scroll_down(
            animate=False
        )

    def action_scroll_detail_up(self) -> None:
        self.query_one("#artifact-panel-detail-scroll", VerticalScroll).scroll_up(
            animate=False
        )


def _node_label(node: ArtifactNodeWire) -> Text:
    text = Text()
    text.append(f"{node.kind} ", style="dim")
    text.append(node.display_title)
    text.append(f"  {node.id}", style="dim")
    return text


def _link_label(link: ArtifactLinkWire) -> Text:
    text = Text()
    text.append(f"{link.link_type} ", style="bold")
    text.append(link.target_id)
    if link.source_id != link.target_id:
        text.append(f"  from {link.source_id}", style="dim")
    return text


def _link_counts(links: list[ArtifactLinkWire]) -> dict[str, int]:
    return dict(Counter(link.link_type for link in links))


def _format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "0"
    return ", ".join(f"{kind}={count}" for kind, count in sorted(counts.items()))

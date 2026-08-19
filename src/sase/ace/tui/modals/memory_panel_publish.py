"""Publish confirmation for the Memory panel.

After a panel write — or on demand via ``I`` — the user chooses whether
``sase memory init`` should fold a commit. Both branches run off the event
loop through ``run_noninteractive``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from sase.ace.tui.actions._durable_ops import sase_argv
from sase.ace.tui.memory_panel_catalog import MemoryScopeRef

_STDERR_TAIL_LINES = 12


@dataclass(frozen=True, slots=True)
class MemoryPublishChoice:
    """The commit decision collected by :class:`MemoryPublishModal`."""

    commit: bool
    subject: str


def memory_publish_argv(*, commit: bool, subject: str) -> list[str]:
    """Return the ``sase memory init`` argv for one publish branch."""
    if commit:
        return sase_argv("memory", "init", "--message", subject.strip())
    return sase_argv("memory", "init", "--no-commit")


def memory_publish_cwd(scope: MemoryScopeRef) -> Path:
    """Return the working directory ``sase memory init`` should run in.

    Home always uses the real home directory even when the scope's content
    root is the chezmoi source tree. Project scopes use their content root.
    """
    if scope.kind == "home":
        return Path.home()
    return Path(scope.content_root)


def memory_publish_subject(
    scope_display_name: str,
    *,
    kind: str | None = None,
    stem: str | None = None,
) -> str:
    """Return a prefilled commit subject for a write or an on-demand publish."""
    if stem and kind == "add":
        return f"Add memory note {stem}"
    if stem and kind == "edit":
        return f"Update memory note {stem}"
    if stem and kind == "delete":
        return f"Delete memory note {stem}"
    return f"Publish memory notes for {scope_display_name}"


def _memory_publish_stderr_tail(stderr: str, *, lines: int = _STDERR_TAIL_LINES) -> str:
    """Return the last non-empty lines of a failed publish's stderr."""
    parts = [line.rstrip() for line in stderr.splitlines() if line.strip()]
    if not parts:
        return ""
    return "\n".join(parts[-lines:])


def format_memory_publish_failure(
    result: subprocess.CompletedProcess[str] | None,
    *,
    timeout: bool = False,
) -> str:
    """Return a toast-sized explanation of a failed ``sase memory init``."""
    if timeout:
        return "sase memory init timed out"
    if result is None:
        return "sase memory init failed"
    tail = _memory_publish_stderr_tail(result.stderr or "")
    if tail:
        compact = " | ".join(tail.splitlines())
        return compact[:240]
    return f"sase memory init failed (exit {result.returncode})"


class MemoryPublishModal(ModalScreen[MemoryPublishChoice | None]):
    """Collect an explicit commit decision for ``sase memory init``."""

    AUTO_FOCUS = "#memory-publish-subject"
    DEFAULT_CSS = """
    MemoryPublishModal {
        align: center middle;
    }
    #memory-publish-container {
        width: 78;
        max-width: 94%;
        height: auto;
        max-height: 90%;
        border: double $primary;
        background: $surface;
        padding: 1 2;
    }
    #memory-publish-subject {
        height: 3;
    }
    #memory-publish-buttons {
        height: auto;
        margin-top: 1;
    }
    """
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False, priority=True),
        Binding(
            "ctrl+s",
            "publish_commit",
            "Publish & commit",
            show=False,
            priority=True,
        ),
        Binding(
            "ctrl+o",
            "publish_only",
            "Publish only",
            show=False,
            priority=True,
        ),
    ]

    def __init__(
        self,
        *,
        scope_display_name: str,
        default_subject: str,
        accent: str = "#87D7FF",
    ) -> None:
        super().__init__()
        self._scope_display_name = scope_display_name
        self._default_subject = default_subject
        self._accent = accent

    def compose(self) -> ComposeResult:
        with Container(id="memory-publish-container"):
            yield Static(self._title_text(), id="memory-publish-title")
            with Vertical(id="memory-publish-fields"):
                yield Static(
                    "Commit subject",
                    classes="memory-publish-label",
                )
                yield Input(
                    value=self._default_subject,
                    placeholder="Required for Publish & commit",
                    id="memory-publish-subject",
                )
                yield Static(
                    "",
                    id="memory-publish-subject-error",
                    classes="memory-publish-error",
                )
            with Horizontal(id="memory-publish-buttons"):
                yield Button(
                    "Publish & commit  Ctrl+S",
                    id="memory-publish-commit",
                    variant="primary",
                )
                yield Button(
                    "Publish only  Ctrl+O",
                    id="memory-publish-only",
                )
                yield Button("Cancel  Esc", id="memory-publish-cancel")
            yield Static(
                "ctrl+s publish & commit  ·  ctrl+o publish only  ·  esc cancel",
                id="memory-publish-hints",
            )

    def on_mount(self) -> None:
        subject = self.query(Input)
        if subject:
            subject.first().focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_publish_commit(self) -> None:
        subject = self._subject()
        if not subject:
            self.query_one("#memory-publish-subject-error", Static).update(
                "commit subject is required"
            )
            self.query_one("#memory-publish-subject", Input).focus()
            return
        self.dismiss(MemoryPublishChoice(commit=True, subject=subject))

    def action_publish_only(self) -> None:
        self.dismiss(MemoryPublishChoice(commit=False, subject=self._subject()))

    @on(Button.Pressed, "#memory-publish-commit")
    def _on_commit_pressed(self) -> None:
        self.action_publish_commit()

    @on(Button.Pressed, "#memory-publish-only")
    def _on_only_pressed(self) -> None:
        self.action_publish_only()

    @on(Button.Pressed, "#memory-publish-cancel")
    def _on_cancel_pressed(self) -> None:
        self.action_cancel()

    def _title_text(self) -> Text:
        text = Text()
        text.append("Publish memory notes", style=f"bold {self._accent}")
        if self._scope_display_name:
            text.append("  ·  ", style="dim")
            text.append(self._scope_display_name, style="bold")
        return text

    def _subject(self) -> str:
        return self.query_one("#memory-publish-subject", Input).value.strip()


__all__ = [
    "MemoryPublishChoice",
    "MemoryPublishModal",
    "format_memory_publish_failure",
    "memory_publish_argv",
    "memory_publish_cwd",
    "memory_publish_subject",
]

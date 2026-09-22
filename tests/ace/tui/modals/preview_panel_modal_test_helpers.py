"""Shared helpers for preview-panel modal tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.testing import wait_for
from sase.ace.tui.modals.preview_panel_modal import PreviewPanelModal
from sase.ace.tui.widgets._prompt_preview_target import PreviewPayload
from sase.xprompt.cli_show_model import ShowInput
from sase.xprompt.properties import XPromptProperties


class _PreviewModalTestApp(App[None]):
    def __init__(self, payload: PreviewPayload) -> None:
        super().__init__()
        self.payload = payload

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(PreviewPanelModal(self.payload))


def _payload() -> PreviewPayload:
    return PreviewPayload(
        kind_label="file",
        icon="@",
        title="src/example.py",
        source_path="/tmp/src/example.py",
        content="\n".join(f"print({idx})" for idx in range(120)),
        lexer="python",
        reference="file:src/example.py",
    )


def _markdown_payload(
    *,
    default_view: Literal["source", "rendered"] = "source",
    content: str | None = None,
) -> PreviewPayload:
    return PreviewPayload(
        kind_label="proposal",
        icon="◆",
        title="Ship the plan browser",
        source_path="/tmp/plan.md",
        content=content
        or (
            "---\n"
            "title: Ship the plan browser\n"
            "status: wip\n"
            "---\n\n"
            "# Ship the Plan Browser\n\n"
            "Render this plan as Markdown.\n"
        ),
        lexer="markdown",
        reference="plan:202607/plan.md",
        default_view=default_view,
    )


def _properties_payload(
    *,
    default_view: Literal["source", "rendered"] = "source",
) -> PreviewPayload:
    return PreviewPayload(
        kind_label="xprompt",
        icon="#",
        title="#bd/review_tasks",
        source_path="/tmp/sase.yml",
        content="Can you review all of the current task sase beads ...",
        lexer="markdown",
        reference="#bd/review_tasks",
        default_view=default_view,
        properties=XPromptProperties(
            reference="#bd/review_tasks",
            kind="xprompt",
            description="Review open task beads for a project.",
            input_signature="(project?: line)",
            inputs=[ShowInput("project", "line", False, "sase", None, False, 0)],
            local_xprompts=[],
            steps=[],
            tags=["bd"],
            skill=None,
            skill_name=None,
            snippet=None,
            log_skill_use=None,
            memory_type=None,
            segment_count=1,
            project=None,
            source_bucket="config",
            definition_path="/tmp/sase.yml",
        ),
    )


async def _wait_for_modal_state(
    pilot: Any,
    predicate: Callable[[], bool],
    *,
    attempts: int = 20,
) -> None:
    del attempts
    await wait_for(pilot, predicate)


class _StyledPreviewModalTestApp(App[None]):
    from pathlib import Path as _Path

    CSS_PATH = str(
        _Path(__file__).resolve().parents[4]
        / "src"
        / "sase"
        / "ace"
        / "tui"
        / "styles.tcss"
    )

    def __init__(self, payload: PreviewPayload) -> None:
        super().__init__()
        self.payload = payload

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(PreviewPanelModal(self.payload))


def _short_payload() -> PreviewPayload:
    return PreviewPayload(
        kind_label="file",
        icon="@",
        title="short.py",
        source_path="/tmp/short.py",
        content="\n".join(f"print({idx})" for idx in range(5)),
        lexer="python",
        reference="file:short.py",
    )


def _long_narrow_payload() -> PreviewPayload:
    return PreviewPayload(
        kind_label="file",
        icon="@",
        title="long.py",
        source_path="/tmp/long.py",
        content="\n".join(f"print({idx})" for idx in range(300)),
        lexer="python",
        reference="file:long.py",
    )


def _long_wide_payload() -> PreviewPayload:
    line = "x = '" + "y" * 130 + "'  # wide line to force full width"
    return PreviewPayload(
        kind_label="file",
        icon="@",
        title="wide.py",
        source_path="/tmp/wide.py",
        content="\n".join(f"{line}  # {idx}" for idx in range(300)),
        lexer="python",
        reference="file:wide.py",
    )

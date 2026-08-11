"""Shared helpers for prompt stack state tests."""

from __future__ import annotations

from sase.ace.tui.widgets.prompt_stack import SnippetPaneTarget


def snippet_target(
    trigger: str = "todo",
    *,
    loaded_body: str | None = None,
) -> SnippetPaneTarget:
    return SnippetPaneTarget(
        trigger=trigger,
        read_path="/tmp/sase.yml",
        write_path="/tmp/sase.yml",
        display_path="~/sase.yml",
        apply_target=None,
        via_chezmoi=False,
        exists=loaded_body is not None,
        loaded_body=loaded_body,
        loaded_fingerprint=None,
    )

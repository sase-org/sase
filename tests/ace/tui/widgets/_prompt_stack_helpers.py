"""Shared helpers for prompt stack state tests."""

from __future__ import annotations

from sase.ace.tui.widgets.prompt_stack import (
    MiniXPromptPaneTarget,
    SnippetPaneTarget,
    mini_xprompt_draft_hash,
)
from sase.xprompt.save import SaveTargetFormat


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


def mini_xprompt_target(
    name: str = "review",
    *,
    body: str = "body",
    frontmatter: str = "",
    exists: bool = True,
) -> MiniXPromptPaneTarget:
    return MiniXPromptPaneTarget(
        name=name,
        reference=f"#{name}",
        location_path="/tmp/xprompts",
        read_path=f"/tmp/{name}.md",
        write_path=f"/tmp/{name}.md",
        display_path=f"~/sase/xprompts/{name}.md",
        apply_target=None,
        via_chezmoi=False,
        target_format=SaveTargetFormat.MARKDOWN,
        entry_name=None,
        storage_name=name,
        exists=exists,
        frontmatter=frontmatter,
        loaded_body=body if exists else None,
        loaded_markdown=None,
        loaded_fingerprint=None,
        clean_hash=mini_xprompt_draft_hash(frontmatter, body),
    )

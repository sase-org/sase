"""Shared loader for opening xprompt definitions in the prompt bar."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from sase.ace.tui.widgets.prompt_stack import XPromptBinding
from sase.xprompt.prompt_frontmatter import PromptFrontmatter
from sase.xprompt.save import load_config_xprompt_markdown

from .xprompt_browser_helpers import (
    is_yaml_backed_source,
    resolve_source_to_file_path,
)


@dataclass(frozen=True, slots=True)
class _XPromptDefinitionLoad:
    """Loaded definition payload ready for the home prompt bar."""

    markdown: str
    display_name: str
    binding: XPromptBinding | None
    read_only: bool
    read_only_path: str | None
    has_comments: bool


async def load_xprompt_definition_for_prompt_bar(
    *,
    name: str,
    source_path: str | None,
    editable: bool,
    reference: str,
) -> _XPromptDefinitionLoad:
    """Read one simple xprompt definition and build its optional edit target."""
    file_path = resolve_source_to_file_path(source_path)
    if file_path is None:
        raise FileNotFoundError("Definition source is unavailable")

    config_backed = is_yaml_backed_source(source_path)
    if config_backed:
        markdown = await asyncio.to_thread(
            load_config_xprompt_markdown, file_path, name
        )
        binding = (
            XPromptBinding.for_config(file_path, name, reference=reference)
            if editable
            else None
        )
    else:
        markdown = await asyncio.to_thread(Path(file_path).read_text, encoding="utf-8")
        binding = (
            XPromptBinding.for_file(file_path, reference=reference)
            if editable
            else None
        )

    return _XPromptDefinitionLoad(
        markdown=markdown,
        display_name=reference,
        binding=binding,
        read_only=not editable,
        read_only_path=file_path if not editable else None,
        has_comments=PromptFrontmatter.parse(markdown).has_comments,
    )

"""Persistence helpers for saving prompt drafts as reusable xprompts."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from sase.xprompt.config_yaml import insert_xprompt_into_config
from sase.xprompt.prompt_frontmatter import PromptFrontmatter


class SaveTargetFormat(StrEnum):
    """Supported xprompt persistence formats."""

    MARKDOWN = "markdown"
    CONFIG = "config"


def _build_markdown_xprompt(frontmatter: PromptFrontmatter, body: str) -> str:
    """Return the canonical markdown xprompt text for *frontmatter* and *body*."""
    clean_body = body.rstrip()
    frontmatter_block = frontmatter.serialize()
    if frontmatter_block and clean_body:
        return f"{frontmatter_block}\n\n{clean_body}\n"
    if frontmatter_block:
        return f"{frontmatter_block}\n"
    return f"{clean_body}\n"


def save_markdown_xprompt(
    path: str | Path,
    frontmatter: PromptFrontmatter,
    body: str,
) -> None:
    """Write a markdown xprompt file."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(_build_markdown_xprompt(frontmatter, body), encoding="utf-8")


def save_config_xprompt(
    config_path: str | Path,
    name: str,
    frontmatter: PromptFrontmatter,
    body: str,
) -> bool:
    """Insert or replace a config-backed xprompt entry."""
    return insert_xprompt_into_config(
        str(config_path),
        name,
        [],
        body,
        frontmatter=frontmatter,
    )


__all__ = [
    "SaveTargetFormat",
    "save_config_xprompt",
    "save_markdown_xprompt",
]

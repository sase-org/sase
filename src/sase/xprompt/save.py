"""Persistence helpers for saving prompt drafts as reusable xprompts."""

from __future__ import annotations

from enum import StrEnum
import os
from pathlib import Path
import tempfile

import yaml  # type: ignore[import-untyped]

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
    _atomic_write_text(file_path, _build_markdown_xprompt(frontmatter, body))


def save_markdown_document(path: str | Path, markdown: str) -> None:
    """Atomically write already-assembled xprompt Markdown."""
    _atomic_write_text(Path(path), markdown)


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


def load_config_xprompt_markdown(config_path: str | Path, name: str) -> str:
    """Reconstruct editable markdown for one simple config-backed xprompt."""
    path = Path(config_path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("xprompts"), dict):
        raise ValueError("config has no xprompts mapping")
    entry = payload["xprompts"].get(name)
    if entry is None:
        raise KeyError(f"xprompt {name!r} is not present in {path}")
    if isinstance(entry, str):
        return entry
    if not isinstance(entry, dict):
        raise ValueError(f"xprompt {name!r} is not a simple config entry")
    mapping = dict(entry)
    body = str(mapping.pop("content", ""))
    mapping.pop("name", None)
    frontmatter = PromptFrontmatter.parse(
        yaml.safe_dump(mapping, sort_keys=False, allow_unicode=True)
    )
    return _build_markdown_xprompt(frontmatter, body)


def _atomic_write_text(path: Path, text: str) -> None:
    """Durably replace *path* from a sibling temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


__all__ = [
    "SaveTargetFormat",
    "load_config_xprompt_markdown",
    "save_config_xprompt",
    "save_markdown_xprompt",
    "save_markdown_document",
]

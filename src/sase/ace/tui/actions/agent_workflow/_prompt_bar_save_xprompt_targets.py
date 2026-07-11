"""Filesystem target helpers for prompt-bar xprompt saves."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from sase.xprompt.prompt_frontmatter import PromptFrontmatter
from sase.xprompt.save import (
    SaveTargetFormat,
    save_config_xprompt,
    save_markdown_xprompt,
)

if TYPE_CHECKING:
    from sase.ace.tui.modals import XPromptLocation, XPromptSaveTarget
    from sase.ace.tui.widgets.prompt_stack import XPromptBinding


def write_target_sync(
    target: XPromptSaveTarget,
    frontmatter: PromptFrontmatter,
    body: str,
) -> None:
    if target.target_format == SaveTargetFormat.MARKDOWN:
        save_markdown_xprompt(target.path, frontmatter, body)
        return
    if target.target_format == SaveTargetFormat.CONFIG:
        entry_name = target.entry_name or target.name
        if not save_config_xprompt(target.path, entry_name, frontmatter, body):
            raise RuntimeError("config insertion failed")
        return
    raise RuntimeError("unsupported xprompt save target")


def write_binding_sync(
    binding: XPromptBinding,
    frontmatter: PromptFrontmatter,
    body: str,
) -> None:
    """Write a bound stack without depending on modal target types."""
    if binding.target_format == SaveTargetFormat.MARKDOWN:
        save_markdown_xprompt(binding.path, frontmatter, body)
        return
    if binding.target_format == SaveTargetFormat.CONFIG and binding.entry_name:
        if save_config_xprompt(binding.path, binding.entry_name, frontmatter, body):
            return
        raise RuntimeError("config insertion failed")
    raise RuntimeError("invalid xprompt binding")


def target_for_new_xprompt(
    location: XPromptLocation,
    name: str,
) -> XPromptSaveTarget:
    from ...modals import XPromptSaveTarget

    if location.location_type == "directory":
        filename = name.replace("/", "_") + ".md"
        path = str(Path(location.path) / filename)
        return XPromptSaveTarget(
            kind="overwrite",
            name=name,
            path=path,
            target_format=SaveTargetFormat.MARKDOWN,
            display_path=short_display_path(path),
        )
    return XPromptSaveTarget(
        kind="overwrite",
        name=name,
        path=location.path,
        target_format=SaveTargetFormat.CONFIG,
        entry_name=name,
        display_path=short_display_path(location.path),
    )


def frontmatter_for_new_target(
    target: XPromptSaveTarget,
    frontmatter: PromptFrontmatter,
    name: str,
) -> PromptFrontmatter:
    if target.target_format == SaveTargetFormat.MARKDOWN and frontmatter.name == name:
        return replace(frontmatter, name=None)
    return frontmatter


def existing_names_for_location(location: XPromptLocation) -> set[str]:
    if location.location_type == "directory":
        path = Path(location.path)
        if not path.is_dir():
            return set()
        return {entry.stem for entry in path.glob("*.md") if entry.is_file()}

    import yaml  # type: ignore[import-untyped]

    config_path = Path(location.path)
    if not config_path.is_file():
        return set()
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if not isinstance(data, dict):
        return set()
    xprompts = data.get("xprompts")
    if not isinstance(xprompts, dict):
        return set()
    return {str(name) for name in xprompts}


def name_exists_at_location(
    location: XPromptLocation,
    name: str,
    existing_names: set[str],
) -> bool:
    if location.location_type == "directory":
        return name.replace("/", "_") in existing_names
    return name in existing_names


def short_display_path(path: str) -> str:
    home = str(Path.home())
    cwd = str(Path.cwd())
    if path.startswith(cwd + "/"):
        return "./" + path[len(cwd) + 1 :]
    if path.startswith(home + "/"):
        return "~" + path[len(home) :]
    return path


__all__ = [
    "existing_names_for_location",
    "frontmatter_for_new_target",
    "name_exists_at_location",
    "short_display_path",
    "target_for_new_xprompt",
    "write_target_sync",
    "write_binding_sync",
]

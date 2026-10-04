"""Write helpers for prompt-bar macro saves."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.macro.prompt_frontmatter import PromptFrontmatter
from sase.macro.save import (
    SaveTargetFormat,
    save_config_macro,
    save_markdown_macro,
)

if TYPE_CHECKING:
    from sase.ace.tui.modals.unified_macro_save_modal import (
        UnifiedMacroSaveResult,
    )
    from sase.ace.tui.widgets.prompt_stack import MacroBinding as MacroBinding


def write_target_sync(
    target: UnifiedMacroSaveResult,
    frontmatter: PromptFrontmatter,
    body: str,
) -> None:
    if target.target_format == SaveTargetFormat.MARKDOWN:
        save_markdown_macro(target.path, frontmatter, body)
        return
    if target.target_format == SaveTargetFormat.CONFIG:
        entry_name = target.entry_name or target.name
        if not save_config_macro(target.path, entry_name, frontmatter, body):
            raise RuntimeError("config insertion failed")
        return
    raise RuntimeError("unsupported macro save target")


def write_binding_sync(
    binding: MacroBinding,
    frontmatter: PromptFrontmatter,
    body: str,
) -> None:
    """Write a bound stack without depending on modal target types."""
    if binding.target_format == SaveTargetFormat.MARKDOWN:
        save_markdown_macro(binding.write_path, frontmatter, body)
        return
    if binding.target_format == SaveTargetFormat.CONFIG and binding.entry_name:
        if save_config_macro(
            binding.write_path,
            binding.entry_name,
            frontmatter,
            body,
        ):
            return
        raise RuntimeError("config insertion failed")
    raise RuntimeError("invalid macro binding")


__all__ = ["write_binding_sync", "write_target_sync"]

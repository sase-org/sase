"""Write helpers for prompt-bar xprompt saves."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.xprompt.prompt_frontmatter import PromptFrontmatter
from sase.xprompt.save import (
    SaveTargetFormat,
    save_config_xprompt,
    save_markdown_xprompt,
)

if TYPE_CHECKING:
    from sase.ace.tui.modals.unified_xprompt_save_modal import (
        UnifiedXPromptSaveResult,
    )
    from sase.ace.tui.widgets.prompt_stack import XPromptBinding


def write_target_sync(
    target: UnifiedXPromptSaveResult,
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
        save_markdown_xprompt(binding.write_path, frontmatter, body)
        return
    if binding.target_format == SaveTargetFormat.CONFIG and binding.entry_name:
        if save_config_xprompt(
            binding.write_path,
            binding.entry_name,
            frontmatter,
            body,
        ):
            return
        raise RuntimeError("config insertion failed")
    raise RuntimeError("invalid xprompt binding")


__all__ = ["write_binding_sync", "write_target_sync"]

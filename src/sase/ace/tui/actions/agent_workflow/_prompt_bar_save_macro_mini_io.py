"""Disk and markdown helpers for mini-macro pane saves."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sase.macro.prompt_frontmatter import PromptFrontmatter
from sase.macro.save import (
    SaveTargetFormat,
    load_config_macro_markdown,
    save_config_macro,
    save_markdown_document,
)

if TYPE_CHECKING:
    from sase.ace.tui.widgets.prompt_stack import (
        MiniMacroPaneTarget,
        SourceFingerprint,
    )


@dataclass(frozen=True, slots=True)
class MiniMacroSaveDiskState:
    existing_markdown: str | None
    changed_on_disk: bool
    current_fingerprint: SourceFingerprint | None


@dataclass(frozen=True, slots=True)
class _MiniMacroWriteResult:
    source_markdown: str | None


def load_mini_macro_save_disk_state(
    target: MiniMacroPaneTarget,
) -> MiniMacroSaveDiskState:
    from sase.ace.tui.widgets.prompt_stack import SourceFingerprint

    existing_markdown = _load_existing_mini_macro_markdown(target)
    try:
        current_fingerprint = SourceFingerprint.from_path(target.write_path)
    except OSError:
        current_fingerprint = None
    return MiniMacroSaveDiskState(
        existing_markdown=existing_markdown,
        changed_on_disk=current_fingerprint != target.loaded_fingerprint,
        current_fingerprint=current_fingerprint,
    )


def _load_existing_mini_macro_markdown(
    target: MiniMacroPaneTarget,
) -> str | None:
    path = Path(target.write_path)
    if not path.exists():
        return None
    if target.target_format is SaveTargetFormat.CONFIG:
        if not target.entry_name:
            raise ValueError("config-backed mini-macro is missing an entry name")
        try:
            return load_config_macro_markdown(path, target.entry_name)
        except KeyError:
            return None
        except ValueError:
            if not target.exists:
                return None
            raise
    return path.read_text(encoding="utf-8")


def write_mini_macro_sync(
    target: MiniMacroPaneTarget,
    frontmatter: str,
    body: str,
) -> _MiniMacroWriteResult:
    """Write one mini-macro through the established macro save primitives."""
    from sase.macro.models import Macro
    from sase.macro.segment_separators import macro_has_segment_separators

    if not body.strip():
        raise ValueError("mini-macro body is empty")
    if macro_has_segment_separators(Macro(name=target.name, content=body)):
        raise ValueError("mini-macro body contains a top-level --- separator")

    frontmatter_model = _mini_macro_frontmatter_for_save(frontmatter)
    if target.target_format is SaveTargetFormat.MARKDOWN:
        source_markdown = _mini_macro_markdown_document(target, frontmatter, body)
        save_markdown_document(target.write_path, source_markdown)
        return _MiniMacroWriteResult(source_markdown=source_markdown)
    if target.target_format is SaveTargetFormat.CONFIG:
        entry_name = target.entry_name or target.storage_name or target.name
        if not save_config_macro(
            target.write_path,
            entry_name,
            frontmatter_model,
            body,
        ):
            raise RuntimeError("config insertion failed")
        return _MiniMacroWriteResult(source_markdown=None)
    raise RuntimeError("unsupported mini-macro save target")


def _mini_macro_frontmatter_for_save(raw: str) -> PromptFrontmatter:
    """Parse frontmatter strictly enough for a final write."""
    import yaml  # type: ignore[import-untyped]

    from sase.macro.loader_parsing import parse_yaml_front_matter

    text = raw.strip()
    if not text:
        return PromptFrontmatter()
    if text.startswith("---"):
        mapping, _ = parse_yaml_front_matter(text)
        if mapping is None:
            raise ValueError("frontmatter block is invalid or unterminated")
    else:
        try:
            mapping = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"frontmatter YAML is invalid: {exc}") from exc
        if mapping is not None and not isinstance(mapping, dict):
            raise ValueError("frontmatter must be a YAML mapping")
    return PromptFrontmatter.parse(raw)


def _mini_macro_markdown_document(
    target: MiniMacroPaneTarget,
    frontmatter: str,
    body: str,
) -> str:
    """Build the markdown file text, preserving unchanged source body bytes."""
    if target.loaded_markdown is not None and target.loaded_body == body:
        from sase.ace.tui.widgets.prompt_stack import split_frontmatter

        old_frontmatter, _ = split_frontmatter(target.loaded_markdown)
        return _replace_markdown_frontmatter(
            target.loaded_markdown,
            old_frontmatter,
            frontmatter.strip(),
        )
    return _raw_markdown_macro(frontmatter, body)


def _replace_markdown_frontmatter(
    source_markdown: str,
    old_frontmatter: str,
    new_frontmatter: str,
) -> str:
    if old_frontmatter:
        remainder = source_markdown[len(old_frontmatter) :]
        return (
            new_frontmatter + remainder if new_frontmatter else remainder.lstrip("\r\n")
        )
    if new_frontmatter:
        return f"{new_frontmatter}\n\n{source_markdown}"
    return source_markdown


def _raw_markdown_macro(frontmatter: str, body: str) -> str:
    clean_frontmatter = frontmatter.strip()
    clean_body = body.rstrip()
    if clean_frontmatter and clean_body:
        return f"{clean_frontmatter}\n\n{clean_body}\n"
    if clean_frontmatter:
        return f"{clean_frontmatter}\n"
    return f"{clean_body}\n"


def mini_macro_save_warning(target: MiniMacroPaneTarget) -> str | None:
    if target.save_warning:
        return target.save_warning
    if target.derived_from:
        return (
            f"# {target.name} comes from {target.derived_from} - "
            f"this save writes {target.display_path}"
        )
    if target.loaded_body is not None and not target.exists:
        return (
            f"# {target.name} was loaded from another source - "
            f"this save writes {target.display_path}"
        )
    return None


def refresh_mini_macro_save_warning(
    project: str | None,
    target: MiniMacroPaneTarget,
) -> str | None:
    """Recompute the redefinition warning from the current loader state.

    A missing destination row is an error so the caller can retain the warning
    captured when the name step opened the pane.
    """

    from sase.ace.tui.modals.mini_macro_redefinition import (
        macro_redefinition,
        macro_redefinition_warning,
    )
    from sase.ace.tui.modals.mini_macro_target_catalog import (
        load_mini_macro_target_catalog,
    )
    from sase.ace.tui.modals.unified_macro_save_support import (
        load_unified_save_locations,
    )

    rows = load_unified_save_locations(project)
    row = next(
        (item for item in rows if item.location.path == target.location_path),
        None,
    )
    if row is None:
        raise LookupError(
            f"Mini-macro save destination is no longer available: {target.location_path}"
        )
    catalog = load_mini_macro_target_catalog(project, locations=rows)
    return macro_redefinition_warning(macro_redefinition(catalog, target.name, row))


__all__ = [
    "MiniMacroSaveDiskState",
    "load_mini_macro_save_disk_state",
    "mini_macro_save_warning",
    "refresh_mini_macro_save_warning",
    "write_mini_macro_sync",
]

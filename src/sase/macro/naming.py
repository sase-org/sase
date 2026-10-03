"""Pure naming and resolution helpers for saving xprompts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import re
from collections.abc import Sequence

from ._parsing_references import XPROMPT_REFERENCE_NAME_FRAGMENT
from .prompt_frontmatter import PromptFrontmatter
from .snippet_bridge import is_valid_snippet_trigger

_VALID_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-/]+$")
_SEPARATORS = "._-/"


def is_inline_reference_name_char(character: str) -> bool:
    """Return whether *character* can continue an inline reference name."""
    return len(character) == 1 and (
        "a" <= character <= "z"
        or "A" <= character <= "Z"
        or "0" <= character <= "9"
        or character in "_/"
    )


def is_inline_reference_name(name: str) -> bool:
    """Return whether *name* matches the inline xprompt reference grammar."""
    return re.fullmatch(XPROMPT_REFERENCE_NAME_FRAGMENT, name) is not None


def validate_xprompt_name(name: str) -> str | None:
    """Return a specific validation error for *name*, or ``None``."""
    if not name:
        return "Name is required"
    lowered = name.casefold()
    if lowered.endswith((".md", ".yml", ".yaml")):
        return "Do not include an extension; it is added automatically"
    if name.startswith("#"):
        return "Do not include the leading #"
    if any(character.isspace() for character in name):
        return "Whitespace is not allowed"
    if not _VALID_NAME_RE.fullmatch(name):
        return "Use only letters, digits, _, -, ., and /"
    if name[0] in _SEPARATORS or name[-1] in _SEPARATORS:
        return "A name cannot start or end with a separator"
    if "//" in name:
        return "Namespace segments cannot be empty"
    return None


def _markdown_filename(name: str) -> str:
    """Return the safe flat markdown filename used for *name*."""
    return name.replace("/", "_") + ".md"


def validate_snippet_trigger(name: str) -> str | None:
    """Return a validation error for an ACE snippet trigger, or ``None``."""
    if not name:
        return "Trigger is required"
    if not is_valid_snippet_trigger(name):
        return "Use only letters, digits, and underscores"
    return None


def markdown_save_plan(
    name: str,
    frontmatter: PromptFrontmatter,
) -> tuple[str, PromptFrontmatter]:
    """Return a filename/frontmatter pair that loads as exactly *name*.

    Markdown xprompts remain flat files. Namespaces therefore use an underscore
    in the filename and carry their authoritative callable name in frontmatter.
    A mismatching pre-existing ``name:`` is also replaced rather than silently
    winning over what the user typed.
    """
    filename = _markdown_filename(name)
    stem = Path(filename).stem
    if stem != name or (frontmatter.name is not None and frontmatter.name != name):
        return filename, replace(frontmatter, name=name)
    return filename, replace(frontmatter, name=None)


@dataclass(frozen=True, slots=True)
class ResolutionSource:
    """One source in first-wins discovery order for a single candidate name."""

    path: str
    defines_name: bool


@dataclass(frozen=True, slots=True)
class SaveResolution:
    """How a saved definition participates in first-wins resolution."""

    shadowed_by: str | None = None
    shadows: str | None = None


def resolution_after_save(
    target_path: str,
    sources: Sequence[ResolutionSource],
) -> SaveResolution:
    """Describe higher/lower definitions around *target_path*.

    ``sources`` must be in the loader's first-wins order. The target is treated
    as defining the name after the save even when it does not exist yet.
    """
    target_index = next(
        (index for index, source in enumerate(sources) if source.path == target_path),
        None,
    )
    if target_index is None:
        return SaveResolution()
    higher = next(
        (source.path for source in sources[:target_index] if source.defines_name),
        None,
    )
    lower = next(
        (source.path for source in sources[target_index + 1 :] if source.defines_name),
        None,
    )
    return SaveResolution(shadowed_by=higher, shadows=lower)


__all__ = [
    "ResolutionSource",
    "SaveResolution",
    "is_inline_reference_name",
    "is_inline_reference_name_char",
    "markdown_save_plan",
    "resolution_after_save",
    "validate_snippet_trigger",
    "validate_xprompt_name",
]

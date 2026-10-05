"""Compatibility names for pre-rename data and pinned-core xprompt contracts.

Every ``LEGACY_*`` constant names a file, key, or value SASE wrote before the
xprompt-to-macro rename, or a core API spelling that remains until ``core-flip``.
Durable readers prefer the canonical macro spelling and fall back to the
legacy spelling unconditionally: durable data is never flag-gated, and nothing
rewrites history in place.

Writers emit only the canonical name. Later codemods must skip this module,
every ``LEGACY_*`` identifier, and fixtures named ``*legacy_xprompt*``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

# Agent prompt artifacts.
RAW_PROMPT_FILENAME = "raw_prompt.md"
LEGACY_RAW_XPROMPT_FILENAME = "raw_xprompt.md"
SUBMITTED_PROMPT_FILENAME = "submitted_prompt.md"
LEGACY_SUBMITTED_XPROMPT_FILENAME = "submitted_xprompt.md"
MACROS_FILENAME = "macros.json"
MACROS_DIRNAME = "macros"
LEGACY_MACROS_FILENAME = "xprompts.json"
LEGACY_XPROMPTS_DIRNAME = "xprompts"
LEGACY_XPROMPT_ENABLED_DIRECTIVE_NAME: Literal["xprompts_enabled"] = "xprompts_enabled"

# The pinned core still accepts these Rust editor-scope and source-kind values,
# and exports this completion binding, until the macro contract flip.
LEGACY_XPROMPT_JINJA_SCOPE_KIND: Literal["xprompt"] = "xprompt"
LEGACY_XPROMPT_SOURCE_KIND: Literal["xprompt"] = "xprompt"


def require_legacy_xprompt_completion_spacer_binding() -> Any:
    """Load the pinned-core editor binding by its pre-rename name."""
    from sase.core.rust import require_rust_binding

    return require_rust_binding("xprompt_completion_spacer_to_parentheses_edit")


def macros_step_filename(step_name: str) -> str:
    """Return the canonical per-step macro metadata filename."""
    return f"macros_{step_name}.json"


def legacy_macros_step_filename(step_name: str) -> str:
    """Return the pre-rename per-step macro metadata filename."""
    return f"xprompts_{step_name}.json"


# Home-state files. Readers try the canonical file, fall back to the legacy
# file, write only the canonical file, and delete the legacy file after the
# first successful write.
VCS_MACRO_MRU_FILENAME = "vcs_macro_mru.json"
LEGACY_VCS_XPROMPT_MRU_FILENAME = "vcs_xprompt_mru.json"
MACRO_SAVE_STATE_FILENAME = "macro_save_state.json"
LEGACY_XPROMPT_SAVE_STATE_FILENAME = "xprompt_save_state.json"
MACRO_SAVE_STATE_KEY = "macro"
LEGACY_XPROMPT_SAVE_STATE_KEY = "xprompt"

# Skills-manifest provenance key.
MACRO_SET_SHA256_KEY = "macro_set_sha256"
LEGACY_XPROMPT_SET_SHA256_KEY = "xprompt_set_sha256"

# Proc payload field and origin value.
PROMPT_PROC_FIELD = "prompt_proc"
LEGACY_XPROMPT_PROC_FIELD = "xprompt_proc"
PROMPT_PROC_ORIGIN = "prompt-proc"
LEGACY_XPROMPT_PROC_ORIGIN = "xprompt-proc"

# Rebuildable cache directories. Legacy names are removable residue.
MACRO_LSP_DIRNAME = "macro_lsp"
LEGACY_XPROMPT_LSP_DIRNAME = "xprompt_lsp"
MACROS_CATALOG_DIRNAME = "macros_catalog"
LEGACY_XPROMPTS_CATALOG_DIRNAME = "xprompts_catalog"


def artifact_candidates(
    directory: Path,
    canonical_name: str,
    legacy_name: str,
) -> tuple[Path, ...]:
    """Return the canonical path first, then the legacy fallback path."""
    return (directory / canonical_name, directory / legacy_name)


def resolve_artifact_path(
    directory: Path,
    canonical_name: str,
    legacy_name: str,
) -> Path | None:
    """Return the first existing artifact path, preferring the canonical name."""
    for candidate in artifact_candidates(directory, canonical_name, legacy_name):
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _read_artifact_text(
    directory: Path,
    canonical_name: str,
    legacy_name: str,
) -> str | None:
    """Read an artifact file, trying the canonical name before the legacy one."""
    path = resolve_artifact_path(directory, canonical_name, legacy_name)
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def read_raw_prompt_text(directory: Path) -> str | None:
    """Read an agent directory's raw prompt, accepting the pre-rename name."""
    return _read_artifact_text(
        directory, RAW_PROMPT_FILENAME, LEGACY_RAW_XPROMPT_FILENAME
    )


def resolve_raw_prompt_path(directory: Path) -> Path | None:
    """Resolve an agent directory's raw prompt path, new name first."""
    return resolve_artifact_path(
        directory, RAW_PROMPT_FILENAME, LEGACY_RAW_XPROMPT_FILENAME
    )


def read_json_new_first(
    canonical_path: Path,
    legacy_path: Path,
) -> tuple[Any | None, Path | None]:
    """Read JSON from the canonical path, falling back to the legacy path.

    Returns the decoded payload and the path it was read from, or
    ``(None, None)`` when neither file exists or decodes.
    """
    for candidate in (canonical_path, legacy_path):
        try:
            if not candidate.is_file():
                continue
            return json.loads(candidate.read_text(encoding="utf-8")), candidate
        except (OSError, ValueError):
            continue
    return None, None


def macro_set_sha256(manifest: Mapping[str, Any]) -> str | None:
    """Return a skills manifest's macro-set hash, accepting the legacy key."""
    value = manifest.get(MACRO_SET_SHA256_KEY)
    if value is None:
        value = manifest.get(LEGACY_XPROMPT_SET_SHA256_KEY)
    if value is None:
        return None
    text = str(value)
    return text if text else None


def prompt_proc_origin_matches(origin: object) -> bool:
    """Return whether a proc origin is the prompt-proc origin, either spelling."""
    return origin in (PROMPT_PROC_ORIGIN, LEGACY_XPROMPT_PROC_ORIGIN)


def prompt_proc_payload(data: Mapping[str, Any]) -> Any | None:
    """Return a proc mapping's prompt-proc payload, accepting the legacy field."""
    if data.get(PROMPT_PROC_FIELD) is not None:
        return data.get(PROMPT_PROC_FIELD)
    return data.get(LEGACY_XPROMPT_PROC_FIELD)


__all__ = [
    "LEGACY_MACROS_FILENAME",
    "LEGACY_RAW_XPROMPT_FILENAME",
    "LEGACY_SUBMITTED_XPROMPT_FILENAME",
    "LEGACY_VCS_XPROMPT_MRU_FILENAME",
    "LEGACY_XPROMPTS_CATALOG_DIRNAME",
    "LEGACY_XPROMPT_ENABLED_DIRECTIVE_NAME",
    "LEGACY_XPROMPT_LSP_DIRNAME",
    "LEGACY_XPROMPT_JINJA_SCOPE_KIND",
    "LEGACY_XPROMPT_PROC_FIELD",
    "LEGACY_XPROMPT_PROC_ORIGIN",
    "LEGACY_XPROMPT_SAVE_STATE_FILENAME",
    "LEGACY_XPROMPT_SAVE_STATE_KEY",
    "LEGACY_XPROMPT_SOURCE_KIND",
    "LEGACY_XPROMPT_SET_SHA256_KEY",
    "LEGACY_XPROMPTS_DIRNAME",
    "MACROS_CATALOG_DIRNAME",
    "MACROS_DIRNAME",
    "MACROS_FILENAME",
    "MACRO_LSP_DIRNAME",
    "MACRO_SAVE_STATE_FILENAME",
    "MACRO_SAVE_STATE_KEY",
    "MACRO_SET_SHA256_KEY",
    "PROMPT_PROC_FIELD",
    "PROMPT_PROC_ORIGIN",
    "RAW_PROMPT_FILENAME",
    "SUBMITTED_PROMPT_FILENAME",
    "VCS_MACRO_MRU_FILENAME",
    "artifact_candidates",
    "legacy_macros_step_filename",
    "macros_step_filename",
    "macro_set_sha256",
    "prompt_proc_origin_matches",
    "prompt_proc_payload",
    "read_json_new_first",
    "read_raw_prompt_text",
    "require_legacy_xprompt_completion_spacer_binding",
    "resolve_artifact_path",
    "resolve_raw_prompt_path",
]

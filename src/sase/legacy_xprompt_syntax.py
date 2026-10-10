"""Compatibility normalizers for retired xprompt user syntax.

Keep every temporary alias for the xprompt-to-macro terminology migration in
this module. Durable readers live in :mod:`sase.legacy_xprompt_names`;
authored input always accepts the retired spellings as aliases of their
macro replacements.

This module never duplicates backend normalization: layer mapping policy is
owned by ``sase_core::config::macro_syntax`` and reached through the
``normalize_macro_config_layer`` binding, whose retired policy bit is
accepted and ignored.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: Retired authored config keys paired with their macro replacements.
#: Reusable alias metadata for doctor reporting (``config.retired_xprompt_names``).
RETIRED_CONFIG_KEYS: tuple[tuple[str, str], ...] = (
    ("xprompts", "macros"),
    ("xprompt_aliases", "macro_aliases"),
    ("auto_xprompt_menu", "auto_macro_menu"),
    ("xprompt_placeholder_args", "macro_placeholder_args"),
    ("xprompt", "macro"),
)

#: Retired public environment variables paired with their replacements.
#: Supplying both public names for one pair is an actionable error.
RETIRED_ENV_VARS: tuple[tuple[str, str], ...] = (
    ("SASE_XPROMPT_LSP_CMD", "SASE_MACRO_LSP_CMD"),
    ("SASE_DISABLE_PLUGIN_XPROMPTS", "SASE_DISABLE_PLUGIN_MACROS"),
)

#: Retired plugin entry-point group and its canonical replacement.
RETIRED_PLUGIN_GROUP = "sase_xprompts"
CANONICAL_PLUGIN_GROUP = "sase_macros"

#: Retired LSP binary name and its canonical replacement.
RETIRED_LSP_BINARY = "sase-xprompt-lsp"
CANONICAL_LSP_BINARY = "sase-macro-lsp"

#: Retired frontmatter/workflow local-helper key and its replacement.
RETIRED_FRONTMATTER_KEY = "xprompts"
CANONICAL_FRONTMATTER_KEY = "macros"

#: Retired root command and its canonical replacement.
RETIRED_ROOT_COMMAND = "xprompt"
CANONICAL_ROOT_COMMAND = "macro"

#: Retired ``sase path`` targets paired with their canonical replacements.
RETIRED_PATH_TARGETS: tuple[tuple[str, str], ...] = (
    ("xprompts-dir", "macros-dir"),
    ("xprompts-schema", "macros-schema"),
    ("xprompts-collection-schema", "macros-collection-schema"),
)

#: Retired TUI keymap actions paired with their canonical replacements.
#: Authored keymap aliases are always accepted; both spellings in one
#: mapping are an error.
RETIRED_KEYMAP_ACTIONS: tuple[tuple[str, str], ...] = (
    ("focus_xprompt", "focus_macro"),
    ("clear_xprompt_focus", "clear_macro_focus"),
    ("start_last_vcs_xprompt_in_editor", "start_last_vcs_macro_in_editor"),
)

_RETIRED_PATH_TARGET_MAP = dict(RETIRED_PATH_TARGETS)
_RETIRED_CONFIG_KEY_BY_CANONICAL = {
    canonical: retired for retired, canonical in RETIRED_CONFIG_KEYS
}


def retired_config_key(canonical: str) -> str | None:
    """Return the retired config key paired with *canonical*, if any."""
    return _RETIRED_CONFIG_KEY_BY_CANONICAL.get(canonical)


def normalize_config_layer(
    layer: Mapping[str, Any],
    *,
    source: str = "",
    accept_legacy: bool | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Normalize one authored config layer to canonical macro spellings.

    Retired xprompt spellings are always accepted as aliases; the retired
    ``accept_legacy`` bit is accepted for compatibility and ignored.
    Returns the canonical mapping plus source-qualified diagnostics. Both
    spellings in one mapping raises ``ValueError`` naming the macro
    replacement.
    """
    from sase.core.rust import require_rust_binding

    # Retired switch kept for compatibility and ignored.
    _ = accept_legacy
    accept_legacy = True
    binding = require_rust_binding("normalize_macro_config_layer")
    result = binding(
        {
            "layer": dict(layer),
            "accept_legacy_xprompt_names": accept_legacy,
            "source": source,
        }
    )
    canonical = result.get("canonical")
    if not isinstance(canonical, dict):
        raise ValueError("normalize_macro_config_layer returned no mapping")
    diagnostics = result.get("diagnostics", [])
    return canonical, list(diagnostics)


def normalize_keymap_actions(
    mapping: Mapping[str, Any] | None,
    *,
    source: str = "",
    accept_legacy: bool | None = None,
) -> dict[str, Any]:
    """Rewrite retired keymap action keys to their canonical names.

    A legacy key is always accepted as its macro action; the retired
    ``accept_legacy`` bit is accepted for compatibility and ignored. Both
    spellings in one mapping are an error. Presence (not truthiness)
    decides.
    """
    # Retired switch kept for compatibility and ignored.
    _ = accept_legacy
    if not isinstance(mapping, dict):
        return {}
    result = dict(mapping)
    suffix = f" ({source})" if source else ""
    for old, new in RETIRED_KEYMAP_ACTIONS:
        has_old = old in result
        has_new = new in result
        if has_old and has_new:
            raise ValueError(
                f"{old} and {new} cannot be combined; use only {new}{suffix}"
            )
        if not has_old:
            continue
        result[new] = result.pop(old)
    return result


def normalize_frontmatter_macros(
    mapping: Mapping[str, Any] | None,
    *,
    source: str = "",
    accept_legacy: bool | None = None,
) -> dict[str, Any]:
    """Return the local-helper entries from a frontmatter/workflow mapping.

    Accepts canonical ``macros`` and always accepts retired ``xprompts`` as
    an alias; the retired ``accept_legacy`` bit is accepted for
    compatibility and ignored. Both spellings in one mapping are rejected.
    Presence (not truthiness) decides: a legacy key holding null, an empty
    mapping, false, or an empty string still counts. A both-spellings
    failure raises ``ValueError`` naming the replacement and must never be
    reduced to empty helpers by a broad caller catch.
    """
    # Retired switch kept for compatibility and ignored.
    _ = accept_legacy
    if not isinstance(mapping, dict):
        return {}
    has_legacy = RETIRED_FRONTMATTER_KEY in mapping
    has_canonical = CANONICAL_FRONTMATTER_KEY in mapping
    if has_legacy and has_canonical:
        raise ValueError(
            f"{RETIRED_FRONTMATTER_KEY} and {CANONICAL_FRONTMATTER_KEY} "
            f"cannot be combined; use only {CANONICAL_FRONTMATTER_KEY}"
            + (f" ({source})" if source else "")
        )
    if has_canonical:
        entries = mapping[CANONICAL_FRONTMATTER_KEY]
        return entries if isinstance(entries, dict) else {}
    if not has_legacy:
        return {}
    entries = mapping[RETIRED_FRONTMATTER_KEY]
    return entries if isinstance(entries, dict) else {}


def normalize_legacy_root_args(argv: list[str] | None = None) -> None:
    """Rewrite retired root-position spellings to their canonical forms.

    Takes ``sys.argv`` (after ``consume_global_options``). Locates the root
    command with ``sase.main.parser_root_args.root_command_index``, the same
    way ``parser_only_hint`` does. Rewrites a root ``xprompt`` to ``macro``,
    and rewrites the first positional after a root ``path`` from a retired
    ``xprompts-*`` target to its ``macros-*`` replacement. Retired spellings
    are always accepted. Never rewrites any other token (for example
    ``sase run "xprompt ..."`` or ``sase macro show xprompt``).

    Mutates *argv* (default ``sys.argv``) in place.
    """
    import sys

    from sase.main.parser_root_args import root_command_index

    target = sys.argv if argv is None else argv
    args = target[1:]
    command_index = root_command_index(args)
    if command_index is None:
        return
    candidate = args[command_index]
    if candidate == RETIRED_ROOT_COMMAND:
        target[command_index + 1] = CANONICAL_ROOT_COMMAND
        return
    if candidate != "path":
        return
    for offset in range(command_index + 1, len(args)):
        token = args[offset]
        if token == "--":
            continue
        if token.startswith("-"):
            continue
        replacement = _RETIRED_PATH_TARGET_MAP.get(token)
        if replacement is None:
            return
        target[offset + 1] = replacement
        return


__all__ = [
    "CANONICAL_FRONTMATTER_KEY",
    "CANONICAL_LSP_BINARY",
    "CANONICAL_PLUGIN_GROUP",
    "CANONICAL_ROOT_COMMAND",
    "RETIRED_CONFIG_KEYS",
    "RETIRED_ENV_VARS",
    "RETIRED_FRONTMATTER_KEY",
    "RETIRED_KEYMAP_ACTIONS",
    "RETIRED_LSP_BINARY",
    "RETIRED_PATH_TARGETS",
    "RETIRED_PLUGIN_GROUP",
    "RETIRED_ROOT_COMMAND",
    "normalize_config_layer",
    "normalize_frontmatter_macros",
    "normalize_keymap_actions",
    "normalize_legacy_root_args",
    "retired_config_key",
]

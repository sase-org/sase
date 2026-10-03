"""Compatibility normalizers for retired xprompt user syntax.

Keep every temporary alias for the xprompt-to-macro terminology migration in
this module. Durable readers live in :mod:`sase.legacy_xprompt_names` and are
never flag-gated; authored input follows the ``legacy_xprompt_syntax``
sunset flag through this host adapter.

This module never duplicates backend normalization: layer mapping policy is
owned by ``sase_core::config::macro_syntax`` and reached through the
``normalize_macro_config_layer`` binding with an explicit policy bit, so raw
flag-bootstrap layers (read via ``load_config_layers()`` before any flag
snapshot exists) cannot recurse into flag resolution.
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


def legacy_xprompt_syntax_enabled() -> bool:
    """Return whether retired xprompt syntax is accepted."""
    from sase.feature_flags import FeatureFlag, current_flags

    return current_flags().enabled(FeatureFlag.legacy_xprompt_syntax)


def normalize_config_layer(
    layer: Mapping[str, Any],
    *,
    source: str = "",
    accept_legacy: bool | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Normalize one authored config layer to canonical macro spellings.

    The policy bit is explicit at the Rust boundary: callers that already
    know the flag state (including raw flag-bootstrap readers) pass
    ``accept_legacy`` directly, otherwise the current flag snapshot decides.
    Returns the canonical mapping plus source-qualified diagnostics. Both
    spellings in one mapping, or a legacy spelling while the flag is off,
    raises ``ValueError`` naming the macro replacement.
    """
    from sase.core.rust import require_rust_binding

    if accept_legacy is None:
        accept_legacy = legacy_xprompt_syntax_enabled()
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


__all__ = [
    "CANONICAL_LSP_BINARY",
    "CANONICAL_PLUGIN_GROUP",
    "RETIRED_CONFIG_KEYS",
    "RETIRED_ENV_VARS",
    "RETIRED_LSP_BINARY",
    "RETIRED_PLUGIN_GROUP",
    "legacy_xprompt_syntax_enabled",
    "normalize_config_layer",
]

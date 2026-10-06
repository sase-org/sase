"""Provider-specific single-turn directive texts for bundle sections.

Each getter lazily imports its adapter module and returns the exact directive
object the adapter delivers at runtime; this module never copies directive
text. Providers without a directive (``fakey``, ``opencode``, ``qwen``)
return null. Muse's mode is resolved the way the adapter does.
"""

from __future__ import annotations

#: Providers whose adapters deliver a single-turn directive.
DIRECTIVE_PROVIDERS = ("agy", "claude", "codex", "grok", "muse")

#: Display names for provider section headings.
PROVIDER_DISPLAY_NAMES = {
    "agy": "Antigravity",
    "claude": "Claude",
    "codex": "Codex",
    "grok": "Grok",
    "muse": "Muse",
}

#: Adapter modules owning each provider directive (``name`` may be a
#: constant or a zero-argument factory).
_DIRECTIVE_SYMBOLS = {
    "agy": ("sase.llm_provider.agy", "_AGY_PRINT_MODE_DIRECTIVE"),
    "claude": ("sase.llm_provider.claude", "_SINGLE_TURN_DIRECTIVE"),
    "codex": ("sase.llm_provider.codex", "_codex_single_turn_directive"),
    "grok": ("sase.llm_provider.grok", "_GROK_SINGLE_TURN_DIRECTIVE"),
    "muse": ("sase.llm_provider._muse_directive", "_muse_single_turn_directive"),
}


def _load_directive(provider: str, *, synchronous: bool | None) -> str:
    """Import the adapter symbol for *provider* and return its text."""
    import importlib

    try:
        module_name, symbol = _DIRECTIVE_SYMBOLS[provider]
    except KeyError:
        raise ValueError(f"provider {provider!r} has no directive symbol") from None
    module = importlib.import_module(module_name)
    value = getattr(module, symbol)
    if provider == "muse":
        if synchronous is None:
            from sase.llm_provider.muse_provider import (
                muse_synchronous_shell_enabled,
            )

            synchronous = muse_synchronous_shell_enabled()
        return str(value(synchronous=bool(synchronous)))
    if callable(value):
        return str(value())
    return str(value)


def has_provider_directive(provider: str) -> bool:
    """Return whether *provider* delivers a single-turn directive."""
    return provider in _DIRECTIVE_SYMBOLS


def provider_directive(provider: str, *, synchronous: bool | None = None) -> str | None:
    """Return the adapter directive text for *provider*, or null.

    Raises :class:`ValueError` for a provider name no adapter owns; known
    providers without a directive (``fakey``, ``opencode``, ``qwen``) return
    null. ``synchronous`` selects Muse's mode; null resolves it the way the
    Muse adapter does.
    """
    if provider in _DIRECTIVE_SYMBOLS:
        return _load_directive(provider, synchronous=synchronous)
    from sase.instructions.facts import registered_names

    if provider in registered_names():
        return None
    raise ValueError(
        f"unknown provider {provider!r}; "
        f"directives exist for: {', '.join(DIRECTIVE_PROVIDERS)}"
    )


def provider_display_name(provider: str) -> str:
    """Return the heading display name for *provider*."""
    if provider in PROVIDER_DISPLAY_NAMES:
        return PROVIDER_DISPLAY_NAMES[provider]
    return provider.replace("_", " ").title() or provider


def provider_adapter_path(provider: str) -> str:
    """Return the stable repo-relative adapter path recording a directive source."""
    module_name, _symbol = _DIRECTIVE_SYMBOLS[provider]
    return module_name.replace(".", "/") + ".py"


__all__ = [
    "DIRECTIVE_PROVIDERS",
    "PROVIDER_DISPLAY_NAMES",
    "has_provider_directive",
    "provider_adapter_path",
    "provider_directive",
    "provider_display_name",
]

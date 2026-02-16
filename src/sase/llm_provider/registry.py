"""Provider registry for LLM backends."""

import shutil

from .base import LLMProvider
from .config import get_llm_provider_config

_REGISTRY: dict[str, type[LLMProvider]] = {}


def register_provider(name: str, provider_class: type[LLMProvider]) -> None:
    """Register an LLM provider class under a given name.

    Args:
        name: The provider name (e.g., "gemini", "claude").
        provider_class: The provider class to register.
    """
    _REGISTRY[name] = provider_class


def get_provider(name: str | None = None) -> LLMProvider:
    """Get an instantiated LLM provider by name.

    Args:
        name: Provider name. If None, uses the default from config.

    Returns:
        An instance of the requested LLM provider.

    Raises:
        KeyError: If the provider name is not registered.
    """
    if name is None:
        name = _get_default_provider_name()

    if name not in _REGISTRY:
        raise KeyError(
            f"Unknown LLM provider: {name!r}. "
            f"Registered providers: {list(_REGISTRY.keys())}"
        )

    return _REGISTRY[name]()


def _get_default_provider_name() -> str:
    """Get the default provider name from configuration.

    Returns:
        The configured default provider name, or auto-detected provider.
        Prefers claude if available on PATH, falls back to gemini.
    """
    config = get_llm_provider_config()
    provider = config.get("provider")
    if provider:
        return provider
    # Auto-detect: prefer claude if available on PATH
    if shutil.which("claude"):
        return "claude"
    return "gemini"


def _register_builtin_providers() -> None:
    """Register the built-in providers."""
    from .claude import ClaudeCodeProvider
    from .gemini import GeminiProvider

    register_provider("claude", ClaudeCodeProvider)
    register_provider("gemini", GeminiProvider)


# Auto-register built-in providers on module import
_register_builtin_providers()

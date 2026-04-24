"""LLM plugin manager that delegates to pluggy hooks."""

import pluggy

from .base import LLMProvider
from .types import InvokeResult, ModelTier


class LLMPluginManager(LLMProvider):
    """Wraps a :class:`pluggy.PluginManager` while implementing the
    :class:`LLMProvider` interface.

    Each ``LLMProvider`` method delegates to the corresponding
    ``self._pm.hook.llm_*()`` call.  When pluggy returns ``None``
    (no plugin handled the hook), a :class:`NotImplementedError` is raised,
    matching the behaviour of the ABC default methods.
    """

    def __init__(self, pm: pluggy.PluginManager) -> None:
        self._pm = pm

    def invoke(
        self,
        prompt: str,
        *,
        model_tier: ModelTier,
        suppress_output: bool = False,
        model_override: str | None = None,
    ) -> InvokeResult:
        result = self._pm.hook.llm_invoke(
            prompt=prompt,
            model_tier=model_tier,
            suppress_output=suppress_output,
            model_override=model_override,
        )
        if result is None:
            raise NotImplementedError("invoke is not supported by this LLM provider")
        return result  # type: ignore[return-value]

    def resolve_model_name(self, model_tier: ModelTier = "large") -> str:
        result = self._pm.hook.llm_resolve_model_name(model_tier=model_tier)
        if result is None:
            return "unknown"
        return result  # type: ignore[return-value]

    def provider_name(self) -> str:
        result = self._pm.hook.llm_provider_name()
        if result is None:
            raise NotImplementedError(
                "provider_name is not supported by this LLM provider"
            )
        return result  # type: ignore[return-value]

"""Pluggy hook specifications for LLM provider plugins."""

import pluggy

from .types import InvokeResult, ModelTier

hookspec = pluggy.HookspecMarker("sase_llm")
hookimpl = pluggy.HookimplMarker("sase_llm")


class LLMHookSpec:
    """Hook specifications mirroring :class:`LLMProvider` methods.

    Every method uses ``firstresult=True`` so pluggy returns the first
    non-``None`` result from the registered plugins.  Method names are
    prefixed with ``llm_`` to namespace them within the pluggy project.
    """

    # --- Core dispatch ---

    @hookspec(firstresult=True)
    def llm_invoke(
        self,
        prompt: str,
        model_tier: ModelTier,
        suppress_output: bool,
        model_override: str | None,
    ) -> InvokeResult: ...

    @hookspec(firstresult=True)
    def llm_resolve_model_name(self, model_tier: ModelTier) -> str: ...

    # --- Identity ---

    @hookspec(firstresult=True)
    def llm_provider_name(self) -> str: ...

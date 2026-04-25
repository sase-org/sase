"""Pluggy hook specifications for LLM provider plugins."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pluggy

from .types import InvokeResult, ModelTier

if TYPE_CHECKING:
    from .retry_config import ProviderRetryConfig

hookspec = pluggy.HookspecMarker("sase_llm")
hookimpl = pluggy.HookimplMarker("sase_llm")


class LLMHookSpec:
    """Hook specifications mirroring :class:`LLMProvider` methods.

    Every method uses ``firstresult=True`` so pluggy returns the first
    non-``None`` result from the registered plugins.  Method names are
    prefixed with ``llm_`` to namespace them within the pluggy project.

    Metadata hooks (everything below ``--- Identity ---``) are called
    directly on each registered plugin instance by the registry module
    rather than through the pluggy hook-dispatch machinery — aggregating
    across plugins requires knowing which plugin produced each value, so
    callers iterate ``pm.list_name_plugin()`` and call the decorated
    methods on the instance.  The ``@hookspec`` decorator here documents
    the contract; ``@hookimpl`` on providers marks the implementing
    methods.
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

    # --- Metadata ---

    @hookspec(firstresult=True)
    def llm_known_model_names(self) -> list[str]: ...

    @hookspec(firstresult=True)
    def llm_model_short_aliases(self) -> dict[str, str]: ...

    @hookspec(firstresult=True)
    def llm_skill_template_context(self) -> dict[str, str]: ...

    @hookspec(firstresult=True)
    def llm_skill_deploy_subpath(self) -> str | None: ...

    @hookspec(firstresult=True)
    def llm_cli_status_color(self) -> str | None: ...

    @hookspec(firstresult=True)
    def llm_autodetect_priority(self) -> int | None: ...

    @hookspec(firstresult=True)
    def llm_autodetect_cli_name(self) -> str | None: ...

    @hookspec(firstresult=True)
    def llm_default_retry_config(self) -> ProviderRetryConfig | None: ...

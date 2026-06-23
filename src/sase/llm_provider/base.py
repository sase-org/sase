"""Abstract base class for LLM providers."""

from abc import ABC, abstractmethod

from .types import InvokeResult, LLMInvocationOptions, ModelTier


class LLMProvider(ABC):
    """Abstract base class for LLM backend providers.

    Providers receive an already-preprocessed prompt and return raw response
    text. All preprocessing/postprocessing is handled by the shared
    orchestration layer in ``_invoke.py``.
    """

    @abstractmethod
    def invoke(
        self,
        prompt: str,
        *,
        model_tier: ModelTier,
        suppress_output: bool = False,
        model_override: str | None = None,
        options: LLMInvocationOptions | None = None,
    ) -> InvokeResult:
        """Send a preprocessed prompt to the LLM and return the response.

        Args:
            prompt: The preprocessed prompt to send.
            model_tier: Which model tier to use ("large" or "small").
            suppress_output: If True, suppress real-time output to console.
            model_override: If set, use this model name directly instead of
                mapping from ``model_tier``.
            options: Resolved per-invocation options (e.g. reasoning effort).
                Translated into provider CLI args via
                :meth:`invocation_option_args`. ``None`` means no extra options.

        Returns:
            An ``InvokeResult`` with the response text and optional usage data.

        Raises:
            subprocess.CalledProcessError: If the underlying process fails.
        """

    def invocation_option_args(
        self,
        options: LLMInvocationOptions | None,  # noqa: ARG002
    ) -> list[str]:
        """Return per-invocation CLI args for the resolved *options*.

        Default: no extra args. Providers that support reasoning effort
        override this to translate ``options.reasoning_effort`` into their CLI
        flags, honoring the explicit-vs-default contract via
        :func:`sase.llm_provider._effort_args.effort_cli_args`.
        """
        return []

    def resolve_model_name(self, model_tier: ModelTier = "large") -> str:  # noqa: ARG002
        """Return a human-readable model name for the given tier.

        Subclasses should override to return provider-specific names.
        """
        return "unknown"

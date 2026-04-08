"""Abstract base class for LLM providers."""

from abc import ABC, abstractmethod

from .types import InvokeResult, ModelTier


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
    ) -> InvokeResult:
        """Send a preprocessed prompt to the LLM and return the response.

        Args:
            prompt: The preprocessed prompt to send.
            model_tier: Which model tier to use ("large" or "small").
            suppress_output: If True, suppress real-time output to console.
            model_override: If set, use this model name directly instead of
                mapping from ``model_tier``.

        Returns:
            An ``InvokeResult`` with the response text and optional usage data.

        Raises:
            subprocess.CalledProcessError: If the underlying process fails.
        """

    def resolve_model_name(self, model_tier: ModelTier = "large") -> str:  # noqa: ARG002
        """Return a human-readable model name for the given tier.

        Subclasses should override to return provider-specific names.
        """
        return "unknown"

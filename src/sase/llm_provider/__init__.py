"""LLM Provider abstraction layer.

Provides a pluggable interface for LLM backends (Gemini, Claude, etc.)
with shared preprocessing, postprocessing, and orchestration.
"""

from ._invoke import invoke_agent
from ._subprocess import stream_process_output
from .base import LLMProvider
from .postprocessing import log_prompt_and_response, save_prompt_to_file
from .preprocessing import (
    FileRefMode,
    PreprocessResult,
    preprocess_prompt,
    preprocess_prompt_early,
    preprocess_prompt_late,
)
from .registry import get_provider
from .retry_config import (
    ProviderRetryConfig,
    RetryState,
    get_retry_config,
    get_wait_time,
    is_retryable_error,
)
from .temporary_override import (
    TemporaryLLMOverride,
    clear_temporary_override,
    get_active_temporary_override,
    parse_override_duration,
    resolve_effective_default_provider_model,
    set_temporary_override,
)
from .types import LLMInvocationError, LoggingContext, ModelTier

__all__ = [
    "FileRefMode",
    "LLMInvocationError",
    "LLMProvider",
    "LoggingContext",
    "ModelTier",
    "PreprocessResult",
    "ProviderRetryConfig",
    "RetryState",
    "TemporaryLLMOverride",
    "clear_temporary_override",
    "get_active_temporary_override",
    "get_provider",
    "get_retry_config",
    "get_wait_time",
    "invoke_agent",
    "is_retryable_error",
    "log_prompt_and_response",
    "parse_override_duration",
    "preprocess_prompt",
    "preprocess_prompt_early",
    "preprocess_prompt_late",
    "resolve_effective_default_provider_model",
    "save_prompt_to_file",
    "set_temporary_override",
    "stream_process_output",
]

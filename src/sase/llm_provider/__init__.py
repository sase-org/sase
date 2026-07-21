"""LLM Provider abstraction layer.

Provides a pluggable interface for LLM backends (Claude, Antigravity, etc.)
with shared preprocessing, postprocessing, and orchestration.
"""

from ._invoke import invoke_agent
from ._subprocess import stream_process_output
from .alias_view import (
    AliasKind,
    AliasView,
    BUILTIN_MODEL_ALIAS_BUCKET_NAMES,
    BucketView,
    CODERS_BUCKET_DESCRIPTION,
    CODERS_BUCKET_NAME,
    PHASE_WORKER_BUCKET_DESCRIPTION,
    PHASE_WORKER_BUCKET_NAME,
    build_alias_views,
    build_models_panel_rows,
)
from .base import LLMProvider
from .config import (
    ModelAliasConfigSource,
    default_reasoning_effort,
    get_builtin_model_aliases,
    get_custom_model_aliases,
    model_alias_bucket,
    model_alias_bucket_description,
    model_alias_bucket_names,
    model_alias_config_source,
    model_alias_description,
)
from .messages import AIMessage, BaseMessage, HumanMessage, MessageContent
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
    clear_alias_override,
    clear_temporary_override,
    get_active_alias_override,
    get_active_alias_overrides,
    get_active_temporary_override,
    parse_override_duration,
    resolve_effective_default_provider_model,
    set_alias_override,
    set_alias_override_until,
    set_temporary_override,
)
from .types import LLMInvocationError, LoggingContext, ModelTier

__all__ = [
    "AIMessage",
    "AliasKind",
    "AliasView",
    "BUILTIN_MODEL_ALIAS_BUCKET_NAMES",
    "BucketView",
    "CODERS_BUCKET_DESCRIPTION",
    "CODERS_BUCKET_NAME",
    "PHASE_WORKER_BUCKET_DESCRIPTION",
    "PHASE_WORKER_BUCKET_NAME",
    "BaseMessage",
    "FileRefMode",
    "HumanMessage",
    "LLMInvocationError",
    "LLMProvider",
    "LoggingContext",
    "MessageContent",
    "ModelTier",
    "ModelAliasConfigSource",
    "PreprocessResult",
    "ProviderRetryConfig",
    "RetryState",
    "TemporaryLLMOverride",
    "build_alias_views",
    "build_models_panel_rows",
    "clear_alias_override",
    "clear_temporary_override",
    "default_reasoning_effort",
    "get_active_alias_override",
    "get_active_alias_overrides",
    "get_active_temporary_override",
    "get_builtin_model_aliases",
    "get_custom_model_aliases",
    "get_provider",
    "get_retry_config",
    "get_wait_time",
    "invoke_agent",
    "is_retryable_error",
    "log_prompt_and_response",
    "model_alias_config_source",
    "model_alias_bucket",
    "model_alias_bucket_description",
    "model_alias_bucket_names",
    "model_alias_description",
    "parse_override_duration",
    "preprocess_prompt",
    "preprocess_prompt_early",
    "preprocess_prompt_late",
    "resolve_effective_default_provider_model",
    "save_prompt_to_file",
    "set_alias_override",
    "set_alias_override_until",
    "set_temporary_override",
    "stream_process_output",
]

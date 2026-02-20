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
from .registry import get_provider, register_provider
from .types import LoggingContext, ModelTier

__all__ = [
    "FileRefMode",
    "LLMProvider",
    "LoggingContext",
    "ModelTier",
    "PreprocessResult",
    "get_provider",
    "invoke_agent",
    "log_prompt_and_response",
    "preprocess_prompt",
    "preprocess_prompt_early",
    "preprocess_prompt_late",
    "register_provider",
    "save_prompt_to_file",
    "stream_process_output",
]

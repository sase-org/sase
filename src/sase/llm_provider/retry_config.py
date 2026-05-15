"""Retry and fallback configuration for LLM providers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from sase.config import load_merged_config

RETRY_STATE_FILENAME = "retry_state.json"

RetryStatus = Literal["retrying", "running_retry", "running_fallback"]


@dataclass
class ProviderRetryConfig:
    """Per-provider retry configuration."""

    max_retries: int = 0
    error_patterns: list[str] = field(default_factory=list)
    wait_times: list[int] = field(default_factory=lambda: [30])
    fallback_model: str | None = None
    continuation_prompt: str | None = None
    preserve_workspace: bool = False
    # When True, retry by spawning a fresh detached agent (as if `sase run -d`
    # had been invoked) instead of re-running in the same process. The fresh
    # agent inherits the parent's workspace number, chat history, plan file,
    # and continuation nudge via a retry_handoff.json hand-off file.
    spawn_new_agent: bool = False


@dataclass
class RetryState:
    """Retry state written to artifacts dir for TUI consumption."""

    status: RetryStatus
    retry_count: int
    max_retries: int
    next_retry_at_epoch: float | None = None
    wait_seconds: int = 0
    fallback_model: str | None = None
    using_fallback: bool = False
    last_error_snippet: str | None = None

    def write_to(self, artifacts_dir: str) -> None:
        """Write retry_state.json atomically to the artifacts directory."""
        path = Path(artifacts_dir) / RETRY_STATE_FILENAME
        temp_path = path.with_suffix(".tmp")
        try:
            with open(temp_path, "w") as f:
                json.dump(asdict(self), f, indent=2)
            temp_path.rename(path)
        except OSError:
            try:
                temp_path.unlink()
            except OSError:
                pass

    @classmethod
    def read_from(cls, artifacts_dir: str) -> RetryState | None:
        """Read retry_state.json from the artifacts directory."""
        path = Path(artifacts_dir) / RETRY_STATE_FILENAME
        if not path.exists():
            return None
        try:
            with open(path) as f:
                data = json.load(f)
            return cls(**data)
        except (OSError, json.JSONDecodeError, TypeError):
            return None

    @classmethod
    def delete_from(cls, artifacts_dir: str) -> None:
        """Delete retry_state.json from the artifacts directory."""
        path = Path(artifacts_dir) / RETRY_STATE_FILENAME
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def truncate_error_snippet(error: str, max_len: int = 100) -> str:
    """Truncate error string for display in retry state."""
    error = error.strip()
    if len(error) <= max_len:
        return error
    return error[:max_len] + "..."


_CONTEXT_OVERFLOW_NUDGE = (
    "Your previous attempt hit the model's context window limit. Any file "
    "edits, new tests, and other on-disk changes you made are preserved. "
    "Before making additional changes, run `git status` and `git diff` to "
    "see what is already in place, then continue implementing the plan "
    "from wherever you left off. Do not re-apply edits that are already "
    "present."
)


def _built_in_defaults() -> dict[str, ProviderRetryConfig]:
    """Aggregate ``llm_default_retry_config()`` values from registered plugins."""
    from .registry import iter_plugins

    defaults: dict[str, ProviderRetryConfig] = {}
    for name, plugin in iter_plugins():
        method = getattr(plugin, "llm_default_retry_config", None)
        if method is None:
            continue
        try:
            config = method()
        except Exception:
            continue
        if config is not None:
            defaults[name] = config
    return defaults


def _dedup_ordered(items: list[str]) -> list[str]:
    """Return a list with duplicates removed, preserving first-seen order."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _clone_config(cfg: ProviderRetryConfig) -> ProviderRetryConfig:
    """Return a defensive copy so callers can't mutate module-level built-ins."""
    return ProviderRetryConfig(
        max_retries=cfg.max_retries,
        error_patterns=list(cfg.error_patterns),
        wait_times=list(cfg.wait_times),
        fallback_model=cfg.fallback_model,
        continuation_prompt=cfg.continuation_prompt,
        preserve_workspace=cfg.preserve_workspace,
        spawn_new_agent=cfg.spawn_new_agent,
    )


def _load_user_retry_dict(provider_name: str) -> dict[str, Any] | None:
    """Return the raw user-configured retry dict for a provider, or None."""
    try:
        data = load_merged_config()
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    llm_config = data.get("llm_provider", {}) or {}
    retry_section = llm_config.get("retry", {}) or {}
    provider_retry = retry_section.get(provider_name)
    if not provider_retry or not isinstance(provider_retry, dict):
        return None
    return provider_retry


def _config_from_user_dict(user_dict: dict[str, Any]) -> ProviderRetryConfig:
    return ProviderRetryConfig(
        max_retries=user_dict.get("max_retries", 0),
        error_patterns=list(user_dict.get("error_patterns", [])),
        wait_times=list(user_dict.get("wait_times", [30])),
        fallback_model=user_dict.get("fallback_model") or None,
        continuation_prompt=user_dict.get("continuation_prompt") or None,
        preserve_workspace=bool(user_dict.get("preserve_workspace", False)),
        spawn_new_agent=bool(user_dict.get("spawn_new_agent", False)),
    )


def _merge_with_built_in(
    user_dict: dict[str, Any], built_in: ProviderRetryConfig
) -> ProviderRetryConfig:
    # max_retries, continuation_prompt, and preserve_workspace use key-presence
    # checks so that explicit falsy user values (0, "", False) override the
    # built-in defaults.
    max_retries = (
        user_dict["max_retries"] if "max_retries" in user_dict else built_in.max_retries
    )
    continuation_prompt = (
        user_dict["continuation_prompt"]
        if "continuation_prompt" in user_dict
        else built_in.continuation_prompt
    )
    preserve_workspace = (
        bool(user_dict["preserve_workspace"])
        if "preserve_workspace" in user_dict
        else built_in.preserve_workspace
    )
    spawn_new_agent = (
        bool(user_dict["spawn_new_agent"])
        if "spawn_new_agent" in user_dict
        else built_in.spawn_new_agent
    )
    return ProviderRetryConfig(
        max_retries=max_retries,
        error_patterns=_dedup_ordered(
            list(built_in.error_patterns) + list(user_dict.get("error_patterns", []))
        ),
        wait_times=list(user_dict.get("wait_times") or []) or list(built_in.wait_times),
        fallback_model=user_dict.get("fallback_model") or built_in.fallback_model,
        continuation_prompt=continuation_prompt,
        preserve_workspace=preserve_workspace,
        spawn_new_agent=spawn_new_agent,
    )


def get_retry_config(provider_name: str) -> ProviderRetryConfig | None:
    """Load retry config for a specific provider.

    Merges user-configured values (from ``llm_provider.retry.<provider>``) on
    top of module-level built-in defaults. The built-ins cover universal
    failure modes like Claude's ``"Prompt is too long"`` so that recovery
    works out of the box with no user config.

    Returns None if neither a user config nor a built-in exists for the
    provider.
    """
    user_dict = _load_user_retry_dict(provider_name)
    built_in = _built_in_defaults().get(provider_name)

    if user_dict is None and built_in is None:
        return None
    if user_dict is None:
        assert built_in is not None
        return _clone_config(built_in)
    if built_in is None:
        return _config_from_user_dict(user_dict)
    return _merge_with_built_in(user_dict, built_in)


def is_retryable_error(error_output: str, config: ProviderRetryConfig) -> bool:
    """Check if an error matches any configured retry patterns.

    Performs case-insensitive substring matching against the error output.
    """
    if not config.error_patterns:
        return False

    error_lower = error_output.lower()
    return any(pattern.lower() in error_lower for pattern in config.error_patterns)


def find_retry_config_for_error(error_output: str) -> ProviderRetryConfig | None:
    """Find a retry config that matches the error from any provider.

    Iterates user-configured providers first (preserving insertion order),
    then any built-in-only providers. Returns the first merged config whose
    patterns match the error.
    """
    try:
        data = load_merged_config()
        if isinstance(data, dict):
            llm_config = data.get("llm_provider", {}) or {}
            retry_section = llm_config.get("retry", {}) or {}
        else:
            retry_section = {}
    except Exception:
        retry_section = {}

    checked: set[str] = set()
    provider_order = list(retry_section.keys()) + list(_built_in_defaults().keys())
    for provider_name in provider_order:
        if provider_name in checked:
            continue
        checked.add(provider_name)
        try:
            config = get_retry_config(provider_name)
        except Exception:
            continue
        if config and is_retryable_error(error_output, config):
            return config
    return None


def get_wait_time(retry_count: int, config: ProviderRetryConfig) -> int:
    """Return the wait time in seconds for the Nth retry (1-indexed).

    If the wait_times list is shorter than the retry count, the last value
    is reused. If the list is empty, defaults to 30 seconds.
    """
    if not config.wait_times:
        return 30

    idx = min(retry_count - 1, len(config.wait_times) - 1)
    return config.wait_times[idx]

"""Muse transient model-service retry-config tests."""

from __future__ import annotations

from sase.llm_provider._subprocess_muse import MUSE_USAGE_ERROR_NOTE
from sase.llm_provider.muse import MuseProvider
from sase.llm_provider.retry_config import (
    _RETRY_CONTINUATION_NUDGE,
    find_retry_config_for_error,
    get_retry_config,
    is_retryable_error,
)

# Captured live from the 2026-10-01 `bob-cli-31.4` failure
# (Muse 1.4.2-R4684.1): Muse's own turn retry budget was exhausted on
# session-scoped 504s / first-event timeouts and it exited 1.
_MUSE_TRANSIENT_MODEL_SERVICE_ERROR = (
    "Error running LLM provider command (exit code 1)\n"
    "stderr: run ended with Failed: no data is reaching this machine from "
    "the model service \u2014 likely a local network issue; check connectivity "
    "and retry (3 failed attempts (9 provider requests) over 6m9s, "
    "all [model_stream_first_event_timeout])\n"
    "[muse] task rejected: skip_if_running\n"
    "[muse] run terminal failed: no data is reaching this machine from "
    "the model service"
)


def test_muse_retry_config_shape() -> None:
    config = MuseProvider().llm_default_retry_config()
    assert config.max_retries == 3
    assert config.wait_times == [60, 300, 1800]
    assert config.preserve_workspace is True
    assert config.continuation_prompt == _RETRY_CONTINUATION_NUDGE
    assert config.spawn_new_agent is False


def test_muse_retry_config_retries_transient_model_service_failure() -> None:
    config = MuseProvider().llm_default_retry_config()
    assert is_retryable_error(_MUSE_TRANSIENT_MODEL_SERVICE_ERROR, config) is True


def test_muse_transient_error_found_via_cross_provider_lookup() -> None:
    """Guards the lookup path `handle_workflow_error` actually uses."""
    config = get_retry_config("muse")
    assert config is not None
    found = find_retry_config_for_error(_MUSE_TRANSIENT_MODEL_SERVICE_ERROR)
    assert found is not None
    assert is_retryable_error(_MUSE_TRANSIENT_MODEL_SERVICE_ERROR, found) is True


def test_muse_retry_config_ignores_non_transient_failures() -> None:
    config = MuseProvider().llm_default_retry_config()
    assert is_retryable_error(MUSE_USAGE_ERROR_NOTE, config) is False
    assert (
        is_retryable_error(
            "Muse produced a wait-claim reply after 2 continuation(s); "
            "refusing to report it as success.",
            config,
        )
        is False
    )
    assert (
        is_retryable_error(
            "Error running LLM provider command (exit code 1)\n"
            "stderr: usage limit reached, try again tomorrow",
            config,
        )
        is False
    )

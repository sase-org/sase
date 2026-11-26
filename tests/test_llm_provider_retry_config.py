"""Tests for LLM provider retry configuration lookup."""

from pathlib import Path

from unittest.mock import patch

import yaml

from sase.llm_provider.retry_config import (
    ProviderRetryConfig,
    find_retry_config_for_error,
    get_retry_config,
    is_host_finalizer_failure,
    is_host_owned_failure,
)

# Provider name guaranteed to have no built-in or user config — used to
# assert "truly unconfigured" behavior now that some providers ship with
# built-in defaults (e.g. claude's "Prompt is too long" recovery).
_UNCONFIGURED_PROVIDER = "fake-unconfigured-provider"

# --- ProviderRetryConfig tests ---


class TestProviderRetryConfig:
    def test_defaults(self) -> None:
        config = ProviderRetryConfig()
        assert config.max_retries == 0
        assert config.error_patterns == []
        assert config.wait_times == [30]
        assert config.fallback_model is None
        assert config.continuation_prompt is None
        assert config.preserve_workspace is False

    def test_custom_values(self) -> None:
        config = ProviderRetryConfig(
            max_retries=3,
            error_patterns=["rate limit", "503"],
            wait_times=[30, 60, 120],
            fallback_model="gemini-3-flash-preview",
            continuation_prompt="resume where you left off",
            preserve_workspace=True,
        )
        assert config.max_retries == 3
        assert config.error_patterns == ["rate limit", "503"]
        assert config.wait_times == [30, 60, 120]
        assert config.fallback_model == "gemini-3-flash-preview"
        assert config.continuation_prompt == "resume where you left off"
        assert config.preserve_workspace is True


# --- get_retry_config tests ---


class TestGetRetryConfig:
    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_returns_none_with_default_config(self, mock_config: object) -> None:
        mock_config.return_value = {"llm_provider": {"provider": "", "retry": {}}}  # type: ignore[union-attr]
        assert get_retry_config("gemini") is None

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_returns_config_when_set(self, mock_config: object) -> None:
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "gemini": {
                        "max_retries": 3,
                        "error_patterns": ["rate limit", "503"],
                        "wait_times": [30, 60, 120],
                        "fallback_model": "gemini-3-flash-preview",
                    }
                }
            }
        }
        config = get_retry_config("gemini")
        assert config is not None
        assert config.max_retries == 3
        assert config.error_patterns == ["rate limit", "503"]
        assert config.wait_times == [30, 60, 120]
        assert config.fallback_model == "gemini-3-flash-preview"

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_returns_none_for_unconfigured_provider(self, mock_config: object) -> None:
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "gemini": {"max_retries": 3, "error_patterns": ["rate limit"]}
                }
            }
        }
        assert get_retry_config(_UNCONFIGURED_PROVIDER) is None

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_partial_config_uses_defaults(self, mock_config: object) -> None:
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {"gemini": {"max_retries": 2, "error_patterns": ["503"]}}
            }
        }
        config = get_retry_config("gemini")
        assert config is not None
        assert config.max_retries == 2
        assert config.error_patterns == ["503"]
        assert config.wait_times == [30]  # default
        assert config.fallback_model is None  # default

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_returns_none_when_no_llm_provider_section(
        self, mock_config: object
    ) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        assert get_retry_config(_UNCONFIGURED_PROVIDER) is None

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_returns_none_when_retry_section_missing(self, mock_config: object) -> None:
        mock_config.return_value = {"llm_provider": {"provider": "gemini"}}  # type: ignore[union-attr]
        assert get_retry_config(_UNCONFIGURED_PROVIDER) is None

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_returns_none_on_exception(self, mock_config: object) -> None:
        mock_config.side_effect = RuntimeError("config error")  # type: ignore[union-attr]
        assert get_retry_config(_UNCONFIGURED_PROVIDER) is None

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_empty_fallback_model_becomes_none(self, mock_config: object) -> None:
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "gemini": {
                        "max_retries": 1,
                        "error_patterns": ["err"],
                        "fallback_model": "",
                    }
                }
            }
        }
        config = get_retry_config("gemini")
        assert config is not None
        assert config.fallback_model is None


# --- find_retry_config_for_error tests ---


class TestFindRetryConfigForError:
    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_finds_matching_provider(self, mock_config: object) -> None:
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "gemini": {
                        "max_retries": 3,
                        "error_patterns": ["unexpected critical error"],
                        "wait_times": [60],
                    }
                }
            }
        }
        config = find_retry_config_for_error("An unexpected critical error occurred")
        assert config is not None
        assert config.max_retries == 3

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_returns_none_when_no_match(self, mock_config: object) -> None:
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "gemini": {
                        "max_retries": 3,
                        "error_patterns": ["unexpected critical error"],
                    }
                }
            }
        }
        assert find_retry_config_for_error("authentication failed") is None

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_returns_none_with_empty_config(self, mock_config: object) -> None:
        mock_config.return_value = {}  # type: ignore[union-attr]
        assert find_retry_config_for_error("any error") is None

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_checks_multiple_providers(self, mock_config: object) -> None:
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "claude": {
                        "max_retries": 1,
                        "error_patterns": ["overloaded"],
                    },
                    "gemini": {
                        "max_retries": 3,
                        "error_patterns": ["quota exceeded"],
                        "fallback_model": "gemini-flash",
                    },
                }
            }
        }
        # Should match gemini config
        config = find_retry_config_for_error("quota exceeded for project")
        assert config is not None
        assert config.max_retries == 3
        assert config.fallback_model == "gemini-flash"

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_returns_none_on_exception(self, mock_config: object) -> None:
        mock_config.side_effect = RuntimeError("broken")  # type: ignore[union-attr]
        assert find_retry_config_for_error("any error") is None

    def test_default_sdd_version_skew_is_fresh_process_retryable(self) -> None:
        default_config = yaml.safe_load(
            (
                Path(__file__).resolve().parents[1]
                / "src"
                / "sase"
                / "default_config.yml"
            ).read_text(encoding="utf-8")
        )
        error = (
            "SddMaterializationError: SDD store record /repo/.sase/sdd-store.json "
            "uses a format this process does not understand"
        )

        with patch(
            "sase.llm_provider.retry_config.load_merged_config",
            return_value=default_config,
        ):
            config = find_retry_config_for_error(error)

        assert config is not None
        assert config.max_retries == 1
        assert config.wait_times == [0]
        assert config.preserve_workspace is True
        assert config.spawn_new_agent is True


class TestIsHostFinalizerFailure:
    def test_stitch_failure_text_matches(self) -> None:
        assert (
            is_host_finalizer_failure(
                RuntimeError(
                    "Step 'main' failed: Error: sase stitch create --resume failed "
                    "for research: remote: Internal Server Error"
                )
            )
            is True
        )

    def test_finalize_commit_text_matches(self) -> None:
        assert (
            is_host_finalizer_failure(
                RuntimeError(
                    "finalize_commit created local commit 99e35dd but failed "
                    "before publishing it: remote: rate limit exceeded"
                )
            )
            is True
        )

    def test_commit_finalizer_text_matches(self) -> None:
        assert (
            is_host_finalizer_failure(
                RuntimeError("commit finalizer hit a second unresolved conflict")
            )
            is True
        )

    def test_typed_finalizer_error_matches_without_markers(self) -> None:
        from sase.finalizers.commit_types import (
            BuiltinCommitFinalizerError,
            failed_result,
        )

        err = BuiltinCommitFinalizerError(
            "transient boom",
            result=failed_result("instance", "stitch_failed", "boom"),
        )
        assert is_host_finalizer_failure(err) is True

    def test_chained_finalizer_error_matches(self) -> None:
        from sase.finalizers.commit_types import (
            BuiltinCommitFinalizerError,
            failed_result,
        )

        root = BuiltinCommitFinalizerError(
            "transient boom",
            result=failed_result("instance", "stitch_failed", "boom"),
        )
        outer = RuntimeError("Step 'main' failed: boom")
        outer.__cause__ = root
        assert is_host_finalizer_failure(outer) is True

    def test_bare_provider_500_does_not_match(self) -> None:
        assert (
            is_host_finalizer_failure(
                RuntimeError("API Error: 500 Internal server error: overloaded")
            )
            is False
        )

    def test_bare_remote_500_does_not_match(self) -> None:
        # A bare provider-shaped 500 with no host-owned phrases is still
        # retryable; only host finalizer vocabulary suppresses retry.
        assert (
            is_host_finalizer_failure(RuntimeError("remote: Internal Server Error"))
            is False
        )

    def test_bare_rate_limit_does_not_match(self) -> None:
        assert (
            is_host_finalizer_failure(RuntimeError("hit a rate limit, retry later"))
            is False
        )

    def test_plain_error_does_not_match(self) -> None:
        assert is_host_finalizer_failure(RuntimeError("boom")) is False


class TestIsHostOwnedFailure:
    @staticmethod
    def _lookup_error() -> Exception:
        from sase.agent.names._lookup_named import AgentNamedLookupUnavailable

        return AgentNamedLookupUnavailable(
            availability="busy",
            source="artifact_index",
            diagnostic="database is locked",
        )

    def test_direct_and_chained_lookup_errors_are_host_owned(self) -> None:
        root = self._lookup_error()
        assert is_host_owned_failure(root)
        cause_outer = RuntimeError("outer")
        cause_outer.__cause__ = root
        assert is_host_owned_failure(cause_outer)
        context_outer = RuntimeError("outer")
        context_outer.__context__ = root
        assert is_host_owned_failure(context_outer)

    def test_provider_unavailable_text_still_matches_provider_patterns(self) -> None:
        error = RuntimeError("UNAVAILABLE: provider RPC temporarily failed")
        assert not is_host_owned_failure(error)
        assert find_retry_config_for_error(str(error)) is not None

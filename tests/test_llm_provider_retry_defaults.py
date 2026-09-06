"""Tests for built-in LLM provider retry defaults."""

from unittest.mock import patch

from sase.llm_provider.retry_config import (
    find_retry_config_for_error,
    get_retry_config,
    is_retryable_error,
)

_CLAUDE_SOCKET_CLOSE_ERROR = (
    "API Error: The socket connection was closed unexpectedly. For more "
    "information, pass verbose: true in the second argument to fetch()"
)

# The literal terminal output observed for Codex agent `0s`: a websocket 403
# storm that exhausts the CLI's own reconnects and ends in a 429.
_CODEX_TRANSIENT_FAILURE = (
    "ERROR codex_api::endpoint::responses_websocket: failed to connect to "
    "websocket: HTTP error: 403 Forbidden, "
    "url: wss://chatgpt.com/backend-api/codex/responses Reconnecting 5/5\n"
    "[error] exceeded retry limit, last status: 429 Too Many Requests\n"
    "[turn.failed] exceeded retry limit, last status: 429 Too Many Requests"
)

_CODEX_CAPACITY_FAILURE = (
    "[error] Selected model is at capacity. Please try a different model.\n"
    "[turn.failed] Selected model is at capacity. Please try a different model."
)

# A persistent credential/authorization failure with no rate-limit wording —
# must NOT be retried (guards against over-matching a bare 403).
_CODEX_PERSISTENT_AUTH_FAILURE = (
    "ERROR: authentication failed: 403 Forbidden — invalid API credentials"
)

_CODEX_INPUT_TOO_LARGE_FAILURE = (
    "[turn.failed] turn/start failed: JSON-RPC error -32602: "
    "input validation failed; input_error_code=input_too_large; "
    "max_chars=1048576; actual_chars=1913445; "
    "warning: stale rollout path /tmp/codex-rollout"
)


class TestBuiltInDefaults:
    """Built-in retry defaults for universal failure modes."""

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_claude_built_in_returned_without_user_config(
        self, mock_config: object
    ) -> None:
        """claude gets a built-in 'Prompt is too long' recovery config."""
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_retry_config("claude")
        assert config is not None
        assert config.max_retries == 3
        assert "Prompt is too long" in config.error_patterns
        assert "socket connection was closed unexpectedly" in config.error_patterns
        assert "API Error" in config.error_patterns
        assert config.wait_times == [0]
        assert config.continuation_prompt is not None
        assert "context limit" in config.continuation_prompt
        assert "transient provider failure" in config.continuation_prompt
        assert "git status" in config.continuation_prompt
        assert "git diff" in config.continuation_prompt
        assert config.preserve_workspace is True

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_claude_built_in_matches_socket_close_error(
        self, mock_config: object
    ) -> None:
        """Claude's observed socket-close CLI failure is retried by default."""
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_retry_config("claude")
        assert config is not None
        assert is_retryable_error(_CLAUDE_SOCKET_CLOSE_ERROR, config) is True

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_built_in_returned_when_exception(self, mock_config: object) -> None:
        """Even if user config can't be loaded, built-ins still apply."""
        mock_config.side_effect = RuntimeError("broken")  # type: ignore[union-attr]
        config = get_retry_config("claude")
        assert config is not None
        assert config.max_retries == 3

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_user_appends_custom_pattern_to_built_in(self, mock_config: object) -> None:
        """User patterns are unioned with built-in patterns, deduplicated."""
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "claude": {
                        "error_patterns": ["my custom pattern", "Prompt is too long"],
                    }
                }
            }
        }
        config = get_retry_config("claude")
        assert config is not None
        # Built-in pattern appears exactly once (dedup'd) and order preserved:
        # built-in first, then new user patterns.
        assert config.error_patterns == [
            "Prompt is too long",
            "socket connection was closed unexpectedly",
            "API Error",
            "my custom pattern",
        ]

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_user_explicit_max_retries_zero_disables(self, mock_config: object) -> None:
        """User explicitly setting max_retries=0 disables even built-in retries."""
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "claude": {"max_retries": 0},
                }
            }
        }
        config = get_retry_config("claude")
        assert config is not None
        assert config.max_retries == 0  # user's explicit 0 wins over built-in 3

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_user_unset_max_retries_uses_built_in(self, mock_config: object) -> None:
        """When user doesn't set max_retries, the built-in value is used."""
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "claude": {"error_patterns": ["other"]},
                }
            }
        }
        config = get_retry_config("claude")
        assert config is not None
        assert config.max_retries == 3  # from built-in

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_user_empty_continuation_prompt_overrides(
        self, mock_config: object
    ) -> None:
        """User setting continuation_prompt='' disables the built-in nudge."""
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "claude": {"continuation_prompt": ""},
                }
            }
        }
        config = get_retry_config("claude")
        assert config is not None
        assert config.continuation_prompt == ""

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_user_custom_continuation_prompt_wins(self, mock_config: object) -> None:
        """User-set continuation_prompt replaces the built-in nudge."""
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "claude": {"continuation_prompt": "my custom nudge"},
                }
            }
        }
        config = get_retry_config("claude")
        assert config is not None
        assert config.continuation_prompt == "my custom nudge"

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_built_in_clone_is_defensive(self, mock_config: object) -> None:
        """Mutating a returned built-in must not affect later calls."""
        mock_config.return_value = {}  # type: ignore[union-attr]
        first = get_retry_config("claude")
        assert first is not None
        first.error_patterns.append("not really a pattern")

        second = get_retry_config("claude")
        assert second is not None
        assert "not really a pattern" not in second.error_patterns

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_built_in_clone_copies_preserve_workspace(
        self, mock_config: object
    ) -> None:
        """_clone_config defensively copies the preserve_workspace flag."""
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_retry_config("claude")
        assert config is not None
        assert config.preserve_workspace is True

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_user_unset_preserve_workspace_uses_built_in(
        self, mock_config: object
    ) -> None:
        """User config without preserve_workspace inherits built-in True."""
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "claude": {"error_patterns": ["other"]},
                }
            }
        }
        config = get_retry_config("claude")
        assert config is not None
        assert config.preserve_workspace is True

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_user_explicit_preserve_workspace_false_overrides(
        self, mock_config: object
    ) -> None:
        """User explicit preserve_workspace=False overrides built-in True."""
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "claude": {"preserve_workspace": False},
                }
            }
        }
        config = get_retry_config("claude")
        assert config is not None
        assert config.preserve_workspace is False

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_user_only_config_preserve_workspace_defaults_false(
        self, mock_config: object
    ) -> None:
        """User-only provider with no preserve_workspace key defaults to False."""
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "gemini": {"max_retries": 2, "error_patterns": ["503"]},
                }
            }
        }
        config = get_retry_config("gemini")
        assert config is not None
        assert config.preserve_workspace is False

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_user_only_config_preserve_workspace_true(
        self, mock_config: object
    ) -> None:
        """User-only provider can opt in to preserve_workspace=True."""
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "gemini": {
                        "max_retries": 2,
                        "error_patterns": ["503"],
                        "preserve_workspace": True,
                    },
                }
            }
        }
        config = get_retry_config("gemini")
        assert config is not None
        assert config.preserve_workspace is True

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_find_retry_config_picks_up_built_in(self, mock_config: object) -> None:
        """find_retry_config_for_error checks built-in providers too."""
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = find_retry_config_for_error("API Error: 400 - Prompt is too long")
        assert config is not None
        assert config.max_retries == 3
        assert "Prompt is too long" in config.error_patterns


class TestCodexBuiltInDefaults:
    """Built-in retry defaults for the Codex provider (agent `0s` failure)."""

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_codex_built_in_returned_without_user_config(
        self, mock_config: object
    ) -> None:
        """codex ships a built-in transient-failure recovery config."""
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_retry_config("codex")
        assert config is not None
        assert config.max_retries == 3
        assert "exceeded retry limit" in config.error_patterns
        assert "429 Too Many Requests" in config.error_patterns
        assert "failed to connect to websocket" in config.error_patterns
        assert "Selected model is at capacity" in config.error_patterns
        # Rate limits need a real cool-down, unlike Claude's [0] context-limit
        # cadence.
        assert config.wait_times == [60, 300, 1800]
        assert config.continuation_prompt is not None
        assert "git status" in config.continuation_prompt
        assert config.preserve_workspace is True
        # A bare "403 Forbidden" must not be a pattern, so persistent auth
        # failures aren't retried forever.
        assert "403 Forbidden" not in config.error_patterns

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_codex_built_in_matches_observed_failure(self, mock_config: object) -> None:
        """The literal `0s` transient failure text is retried by default."""
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_retry_config("codex")
        assert config is not None
        assert is_retryable_error(_CODEX_TRANSIENT_FAILURE, config) is True

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_codex_observed_failure_discovered_by_finder(
        self, mock_config: object
    ) -> None:
        """find_retry_config_for_error picks up the codex built-in."""
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = find_retry_config_for_error(_CODEX_TRANSIENT_FAILURE)
        assert config is not None
        assert config.max_retries == 3
        assert "exceeded retry limit" in config.error_patterns

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_codex_capacity_failure_matches_built_in(self, mock_config: object) -> None:
        """The observed model-capacity failure is retried by default."""
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_retry_config("codex")
        assert config is not None
        assert is_retryable_error(_CODEX_CAPACITY_FAILURE, config) is True

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_codex_capacity_failure_discovered_by_finder(
        self, mock_config: object
    ) -> None:
        """find_retry_config_for_error recognizes Codex capacity failures."""
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = find_retry_config_for_error(_CODEX_CAPACITY_FAILURE)
        assert config is not None
        assert config.max_retries == 3
        assert "Selected model is at capacity" in config.error_patterns

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_codex_persistent_auth_failure_not_retried(
        self, mock_config: object
    ) -> None:
        """A persistent 403 auth failure without rate-limit wording is terminal."""
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_retry_config("codex")
        assert config is not None
        assert is_retryable_error(_CODEX_PERSISTENT_AUTH_FAILURE, config) is False
        assert find_retry_config_for_error(_CODEX_PERSISTENT_AUTH_FAILURE) is None

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_codex_input_too_large_failure_not_retried(
        self, mock_config: object
    ) -> None:
        """Codex input-size validation failures are terminal, not transient."""
        mock_config.return_value = {}  # type: ignore[union-attr]
        config = get_retry_config("codex")
        assert config is not None
        assert is_retryable_error(_CODEX_INPUT_TOO_LARGE_FAILURE, config) is False
        assert find_retry_config_for_error(_CODEX_INPUT_TOO_LARGE_FAILURE) is None

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_codex_user_config_merges_with_built_in(self, mock_config: object) -> None:
        """User codex patterns union with the built-in set, deduplicated."""
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "codex": {
                        "error_patterns": [
                            "my custom codex pattern",
                            "exceeded retry limit",
                        ],
                    }
                }
            }
        }
        config = get_retry_config("codex")
        assert config is not None
        # Built-in patterns come first (deduped), then new user patterns.
        assert config.error_patterns == [
            "exceeded retry limit",
            "429 Too Many Requests",
            "Too Many Requests",
            "rate limit",
            "failed to connect to websocket",
            "Selected model is at capacity",
            "my custom codex pattern",
        ]
        assert config.max_retries == 3  # inherited from built-in

    @patch("sase.llm_provider.retry_config.load_merged_config")
    def test_codex_user_explicit_max_retries_zero_disables(
        self, mock_config: object
    ) -> None:
        """User max_retries=0 disables even the codex built-in retries."""
        mock_config.return_value = {  # type: ignore[union-attr]
            "llm_provider": {
                "retry": {
                    "codex": {"max_retries": 0},
                }
            }
        }
        config = get_retry_config("codex")
        assert config is not None
        assert config.max_retries == 0

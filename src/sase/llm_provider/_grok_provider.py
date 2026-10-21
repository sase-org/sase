"""Public provider adapter implementation for Grok Build."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.feature_flags import FeatureFlag, current_flags

from ._grok_cli import (
    GROK_CLI_NAME,
    GROK_RULES_ARGV_BYTE_LIMIT,
    resolve_grok_executable,
)
from ._grok_invocation import GrokInvocationMixin
from ._hookspec import hookimpl
from .instruction_delivery import (
    CHANNEL_GROK_ROOT,
    legacy_instruction_delivery,
)
from .model_manifest import provider_model_names, provider_tier_model
from .types import InvokeResult, LLMInvocationOptions, ModelTier

if TYPE_CHECKING:
    from .retry_config import ProviderRetryConfig
    from .usage.types import UsageProbeContext
    from .usage_limit_config import ProviderUsageLimitConfig


class GrokProvider(GrokInvocationMixin):
    """LLM provider that invokes xAI's Grok Build CLI."""

    def resolve_model_name(self, model_tier: ModelTier = "large") -> str:
        """Return the Grok model name for the given tier."""
        return provider_tier_model("grok", model_tier)

    @hookimpl
    def llm_provider_name(self) -> str:
        return "grok"

    @hookimpl
    def llm_provider_short_name(self) -> str:
        return "grk"

    @hookimpl
    def llm_resolve_model_name(self, model_tier: ModelTier) -> str:
        return self.resolve_model_name(model_tier)

    @hookimpl
    def llm_known_model_names(self) -> list[str]:
        return list(provider_model_names("grok"))

    @hookimpl
    def llm_skill_template_context(self) -> dict[str, str]:
        return {
            "provider_name": "Grok",
            "provider_tool_name": "Grok Build",
            "provider_native_ask_tool": "ask_user_question",
        }

    @hookimpl
    def llm_cli_status_color(self) -> str:
        return "#00C8D7"

    @hookimpl
    def llm_autodetect_cli_name(self) -> str:
        return GROK_CLI_NAME

    @hookimpl
    def llm_auth_evidence(self) -> dict[str, list[str]]:
        return {
            "credential_paths": ["~/.grok/auth.json"],
            "api_key_env_vars": ["XAI_API_KEY"],
        }

    @hookimpl
    def llm_install_metadata(self) -> dict[str, object]:
        # @xai-official/grok is an npm trampoline: `npm install -g` places a
        # shim on PATH, but the real Grok Build binary it downloads on first
        # run lives under ~/.grok/bin/, not node_modules.
        return {
            "manager": "npm",
            "package": "@xai-official/grok",
            "scope": "global",
            "display_name": "Grok Build",
            "vendor": "xAI",
            "docs_url": "https://docs.x.ai/build/overview",
            "self_update_argv": ["update"],
            "latest_version_package": "@xai-official/grok",
        }

    @hookimpl
    def llm_interactive_cli(self) -> dict[str, object]:
        return {
            "menu_key": "g",
            "bypass_args": ["--always-approve"],
            "model_args": ["--model", "{model}"],
        }

    @hookimpl
    def llm_default_retry_config(self) -> ProviderRetryConfig:
        from .retry_config import (
            _RETRY_CONTINUATION_NUDGE,
            ProviderRetryConfig,
        )

        # "max_tokens_truncation" / "response truncated by max_tokens" are
        # captured live from a run that died mid-session (2026-09-04,
        # ace(run)-260904_135714, grok-4.6 xhigh, turn 55) when the CLI
        # aborted with exit code 1 and an internal-error JSON payload whose
        # error_kind was "max_tokens_truncation". Both anchors are kept: the
        # machine error_kind key and the prose message, in case a future CLI
        # build drops one but keeps the other.
        return ProviderRetryConfig(
            max_retries=3,
            error_patterns=[
                "xAI API error",
                "xAI rate limit",
                "xAI server error",
                "xAI upstream request failed",
                "max_tokens_truncation",
                "response truncated by max_tokens",
            ],
            wait_times=[60, 300, 1800],
            continuation_prompt=_RETRY_CONTINUATION_NUDGE,
            preserve_workspace=True,
        )

    @hookimpl
    def llm_default_usage_limit_config(self) -> ProviderUsageLimitConfig:
        from .usage_limit_config import ProviderUsageLimitConfig

        # Free-tier patterns verbatim from a captured live failure (epic
        # sase-n4 research); the source uses U+2019 in "You've", which
        # normalize_for_match handles. The next three patterns are the
        # paid credit/balance family, captured live 2026-08-18 from:
        #   API error (status 402 Payment Required): Grok Build usage
        #   balance exhausted
        # ("usage balance exhausted" and "status 402 payment required" are
        # both substrings of that message). The last two ("you've hit the
        # credit limit for your plan", "you hit your weekly limit") are
        # pager billing-panel strings pulled from the shipped grok binary,
        # not yet observed on stderr.
        #
        # Grok Build emits no reset instant in any limit message a full
        # literal scan of the binary can find (no "resets at/in", no
        # Retry-After on the sampling path) — see the plan's "Evidence:
        # Grok Build never reports a reset instant" section. honor_reset_hint
        # is therefore a no-op for grok and parse_reset_hint always returns
        # (None, None) here. disable_seconds below is now the last resort
        # behind the usage-window fallback (a corroborated reset read from
        # the Grok billing-usage collector): it stays load-bearing whenever
        # the collector has no fresh corroborating window (logged-out CLI,
        # API mode, or a stale snapshot).
        #
        # disable_seconds is 172800 (48h), double the global 24h default,
        # because since June 2026 paid Grok meters every product against one
        # shared weekly usage pool (docs.x.ai/grok/faq): an exhausted balance
        # is typically a multi-day condition, not a same-day reset, so 24h
        # would under-shoot it and burn a fresh agent workspace on every
        # re-probe.
        return ProviderUsageLimitConfig(
            patterns=[
                "reached your free grok build usage limit",
                "usage limit for now",
                "get supergrok for much higher limits",
                "usage balance exhausted",
                "status 402 payment required",
                "out of credits or over your spending limit",
                "you've hit the credit limit for your plan",
                "you hit your weekly limit",
                "usage limit reached",
            ],
            disable_seconds=172800,
        )

    @hookimpl
    def llm_usage_capabilities(self) -> dict[str, object]:
        return {
            "probe": True,
            "passive_events": False,
            "min_probe_interval_seconds": 120,
        }

    @hookimpl
    def llm_usage_probe(self, context: UsageProbeContext) -> dict[str, object] | None:
        from .usage.grok import collect_grok_usage

        return collect_grok_usage(
            context, executable=context.executable or resolve_grok_executable()
        )

    def instruction_delivery(self) -> dict[str, object]:
        if not current_flags().enabled(FeatureFlag.grok_explicit_instructions):
            return legacy_instruction_delivery(reason="flag_disabled")
        return {
            "root": {
                "status": "explicit",
                "channel": CHANNEL_GROK_ROOT,
                "max_bytes": GROK_RULES_ARGV_BYTE_LIMIT,
            },
            "subagent": {"status": "none"},
        }

    @hookimpl
    def llm_instruction_delivery(self) -> dict[str, object]:
        return self.instruction_delivery()

    @hookimpl
    def llm_invoke(
        self,
        prompt: str,
        model_tier: ModelTier,
        suppress_output: bool,
        model_override: str | None,
        options: LLMInvocationOptions | None,
    ) -> InvokeResult:
        return self.invoke(
            prompt,
            model_tier=model_tier,
            suppress_output=suppress_output,
            model_override=model_override,
            options=options,
        )

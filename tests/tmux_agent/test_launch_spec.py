"""Tests for tmux Agent launch-spec composition."""

from __future__ import annotations

import pytest

from sase.config.tmux_agent import TmuxAgentConfig, TmuxAgentProviderConfig
from sase.llm_provider.types import LLMInvocationError, LLMInvocationOptions
from sase.tmux_agent.launch_spec import (
    InvocationOptionProvider,
    LaunchSpec,
    resolve_effort_level,
    resolve_launch_argv,
)

_DESCRIPTOR = {
    "argv": ("claude",),
    "args": ("--always-on",),
    "bypass_args": ("--dangerously-skip-permissions",),
    "model_args": ("--model", "{model}"),
    "env": {"FROM_DESCRIPTOR": "1"},
    "menu_key": "c",
    "supported": True,
}


class _FakeProvider:
    def __init__(self, supported: dict[str, list[str]] | None = None) -> None:
        self._supported = supported or {"high": ["--effort", "high"]}

    def invocation_option_args(self, options: LLMInvocationOptions | None) -> list[str]:
        if options is None or not options.reasoning_effort:
            return []
        selected = self._supported.get(options.reasoning_effort)
        if selected is not None:
            return list(selected)
        if options.explicit:
            raise LLMInvocationError(
                f"fake does not support {options.reasoning_effort!r}"
            )
        return []


def _spec(
    *,
    descriptor: dict[str, object] = _DESCRIPTOR,
    provider_config: TmuxAgentProviderConfig | None = None,
    catalog_config: TmuxAgentConfig | None = None,
    effort: str | None = None,
    provider_obj: InvocationOptionProvider | None = None,
    explicit: bool = False,
) -> LaunchSpec:
    return resolve_launch_argv(
        "claude",
        descriptor=descriptor,
        provider_config=provider_config or TmuxAgentProviderConfig(),
        catalog_config=catalog_config or TmuxAgentConfig(),
        effort=effort,
        provider_obj=provider_obj,
        explicit=explicit,
    )


def test_base_argv_and_always_on_args() -> None:
    spec = _spec(provider_config=TmuxAgentProviderConfig(bypass_permissions=False))
    assert spec.argv == ("claude", "--always-on")


def test_bypass_args_appended_when_bypass_on() -> None:
    spec = _spec(catalog_config=TmuxAgentConfig(bypass_permissions=True))
    assert spec.argv == (
        "claude",
        "--always-on",
        "--dangerously-skip-permissions",
    )
    assert spec.bypass is True


def test_bypass_args_omitted_when_bypass_off() -> None:
    spec = _spec(catalog_config=TmuxAgentConfig(bypass_permissions=False))
    assert "--dangerously-skip-permissions" not in spec.argv
    assert spec.bypass is False


def test_provider_bypass_override_wins_over_catalog_default() -> None:
    spec = _spec(
        catalog_config=TmuxAgentConfig(bypass_permissions=True),
        provider_config=TmuxAgentProviderConfig(bypass_permissions=False),
    )
    assert "--dangerously-skip-permissions" not in spec.argv
    assert spec.bypass is False


def test_provider_bypass_absent_inherits_catalog_default() -> None:
    spec = _spec(
        catalog_config=TmuxAgentConfig(bypass_permissions=True),
        provider_config=TmuxAgentProviderConfig(bypass_permissions=None),
    )
    assert "--dangerously-skip-permissions" in spec.argv


def test_model_pin_substitutes_model_args() -> None:
    spec = _spec(
        catalog_config=TmuxAgentConfig(bypass_permissions=False),
        provider_config=TmuxAgentProviderConfig(model="opus"),
    )
    assert spec.argv == ("claude", "--always-on", "--model", "opus")


def test_model_pin_without_model_args_is_dropped_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    descriptor = {**_DESCRIPTOR, "model_args": ()}
    with caplog.at_level("WARNING"):
        spec = _spec(
            descriptor=descriptor,
            catalog_config=TmuxAgentConfig(bypass_permissions=False),
            provider_config=TmuxAgentProviderConfig(model="opus"),
        )
    assert "opus" not in spec.argv
    assert "claude" in caplog.text
    assert "model_args" in caplog.text


def test_effort_args_appended_from_provider_obj() -> None:
    spec = _spec(
        catalog_config=TmuxAgentConfig(bypass_permissions=False),
        effort="high",
        provider_obj=_FakeProvider(),
    )
    assert spec.argv == ("claude", "--always-on", "--effort", "high")
    assert spec.effort == "high"
    assert spec.effort_skipped is None


def test_unsupported_config_effort_is_skipped_not_raised() -> None:
    spec = _spec(
        catalog_config=TmuxAgentConfig(bypass_permissions=False),
        effort="max",
        provider_obj=_FakeProvider(),
        explicit=False,
    )
    assert "max" not in spec.argv
    assert spec.effort is None
    assert spec.effort_skipped == "max"


def test_unsupported_explicit_effort_raises() -> None:
    with pytest.raises(LLMInvocationError):
        _spec(
            catalog_config=TmuxAgentConfig(bypass_permissions=False),
            effort="max",
            provider_obj=_FakeProvider(),
            explicit=True,
        )


def test_no_effort_when_none_resolved() -> None:
    spec = _spec(
        catalog_config=TmuxAgentConfig(bypass_permissions=False),
        effort=None,
        provider_obj=_FakeProvider(),
    )
    assert spec.effort is None
    assert spec.effort_skipped is None


def test_no_effort_when_provider_obj_missing() -> None:
    spec = _spec(
        catalog_config=TmuxAgentConfig(bypass_permissions=False),
        effort="high",
        provider_obj=None,
    )
    assert spec.effort is None
    assert spec.effort_skipped == "high"


def test_provider_config_args_appended_last() -> None:
    spec = _spec(
        catalog_config=TmuxAgentConfig(bypass_permissions=False),
        effort="high",
        provider_obj=_FakeProvider(),
        provider_config=TmuxAgentProviderConfig(args=("--extra", "flag")),
    )
    assert spec.argv == (
        "claude",
        "--always-on",
        "--effort",
        "high",
        "--extra",
        "flag",
    )


def test_env_merge_user_wins_over_descriptor() -> None:
    spec = _spec(
        provider_config=TmuxAgentProviderConfig(
            bypass_permissions=False,
            env={"FROM_DESCRIPTOR": "overridden", "FROM_USER": "1"},
        ),
    )
    assert dict(spec.env) == {"FROM_DESCRIPTOR": "overridden", "FROM_USER": "1"}


def test_env_merge_keeps_descriptor_only_keys() -> None:
    spec = _spec(provider_config=TmuxAgentProviderConfig(bypass_permissions=False))
    assert dict(spec.env) == {"FROM_DESCRIPTOR": "1"}


def test_full_composition_order() -> None:
    spec = _spec(
        catalog_config=TmuxAgentConfig(bypass_permissions=True),
        provider_config=TmuxAgentProviderConfig(
            model="opus",
            args=("--trailing",),
        ),
        effort="high",
        provider_obj=_FakeProvider(),
    )
    assert spec.argv == (
        "claude",
        "--always-on",
        "--dangerously-skip-permissions",
        "--model",
        "opus",
        "--effort",
        "high",
        "--trailing",
    )


# -- resolve_effort_level ----------------------------------------------------


def test_provider_effort_wins_over_catalog_and_default() -> None:
    level = resolve_effort_level(
        provider_effort="low", catalog_effort="high", default_effort="max"
    )
    assert level == "low"


def test_catalog_effort_wins_over_default() -> None:
    level = resolve_effort_level(
        provider_effort="", catalog_effort="high", default_effort="max"
    )
    assert level == "high"


def test_default_effort_used_when_nothing_configured() -> None:
    level = resolve_effort_level(
        provider_effort="", catalog_effort="", default_effort="max"
    )
    assert level == "max"


def test_provider_off_disables_effort_regardless_of_catalog() -> None:
    level = resolve_effort_level(
        provider_effort="off", catalog_effort="high", default_effort="max"
    )
    assert level is None


def test_catalog_off_disables_effort_when_no_provider_override() -> None:
    level = resolve_effort_level(
        provider_effort="", catalog_effort="off", default_effort="max"
    )
    assert level is None


def test_no_effort_anywhere_resolves_to_none() -> None:
    level = resolve_effort_level(
        provider_effort="", catalog_effort="", default_effort=None
    )
    assert level is None

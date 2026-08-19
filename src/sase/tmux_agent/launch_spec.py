"""Compose one provider's fully resolved interactive-launch argv."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import logging
from typing import Any, Protocol

from sase.config.tmux_agent import TmuxAgentConfig, TmuxAgentProviderConfig
from sase.llm_provider.types import LLMInvocationOptions

logger = logging.getLogger(__name__)


class InvocationOptionProvider(Protocol):
    """The slice of ``LLMProvider`` that ``resolve_launch_argv`` needs."""

    def invocation_option_args(
        self, options: LLMInvocationOptions | None
    ) -> list[str]: ...


@dataclass(frozen=True)
class LaunchSpec:
    """Fully resolved interactive-launch argv, env, and effort outcome."""

    argv: tuple[str, ...]
    env: tuple[tuple[str, str], ...]
    effort: str | None
    effort_skipped: str | None
    bypass: bool


def _str_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(str(item) for item in value)


def resolve_effort_level(
    *,
    provider_effort: str,
    catalog_effort: str,
    default_effort: str | None,
) -> str | None:
    """Resolve the effort level to request, honoring ``tmux_agent`` precedence.

    Per-provider ``effort`` wins over ``tmux_agent.effort``, which wins over
    ``llm_provider.default_effort`` (already resolved by the caller through
    ``effective_default_effort_snapshot().effective_effort()``, so an active
    temporary override is honored). ``"off"`` at either level means no effort
    args at all.
    """
    if provider_effort:
        return None if provider_effort == "off" else provider_effort
    if catalog_effort:
        return None if catalog_effort == "off" else catalog_effort
    return default_effort


def resolve_launch_argv(
    provider: str,
    *,
    descriptor: Mapping[str, Any],
    provider_config: TmuxAgentProviderConfig,
    catalog_config: TmuxAgentConfig,
    effort: str | None,
    provider_obj: InvocationOptionProvider | None,
    explicit: bool = False,
) -> LaunchSpec:
    """Compose one provider's fully resolved interactive launch argv.

    Composition order: the descriptor's base ``argv``, its always-on ``args``,
    its ``bypass_args`` when bypass is on, its ``model_args`` with ``{model}``
    substituted when a model is pinned, effort args from
    ``provider_obj.invocation_option_args``, then the user's raw
    ``provider_config.args``.

    *explicit* mirrors ``LLMInvocationOptions.explicit``: ``False`` (the
    default, used for config-derived effort) makes an unsupported *effort*
    log-and-skip, recorded as ``effort_skipped``. ``True`` (an effort passed
    explicitly, e.g. the CLI's ``-e/--effort``) makes an unsupported *effort*
    raise :class:`~sase.llm_provider.types.LLMInvocationError`, matching the
    explicit-vs-default contract in :mod:`sase.llm_provider._effort_args`.
    """
    argv: list[str] = [
        *_str_tuple(descriptor.get("argv")),
        *_str_tuple(descriptor.get("args")),
    ]

    bypass_wanted = (
        catalog_config.bypass_permissions
        if provider_config.bypass_permissions is None
        else provider_config.bypass_permissions
    )
    bypass_args = _str_tuple(descriptor.get("bypass_args")) if bypass_wanted else ()
    argv.extend(bypass_args)

    model_args = _str_tuple(descriptor.get("model_args"))
    if provider_config.model:
        if model_args:
            argv.extend(
                arg.replace("{model}", provider_config.model, 1) for arg in model_args
            )
        else:
            logger.warning(
                "Ignoring tmux_agent.providers.%s.model: %s declares no "
                "model_args, so a model cannot be pinned",
                provider,
                provider,
            )

    effort_args: list[str] = []
    if effort and provider_obj is not None:
        options = LLMInvocationOptions(reasoning_effort=effort, explicit=explicit)
        effort_args = list(provider_obj.invocation_option_args(options))
    argv.extend(effort_args)

    argv.extend(provider_config.args)

    descriptor_env = descriptor.get("env")
    env: dict[str, str] = {
        **(descriptor_env if isinstance(descriptor_env, dict) else {}),
        **provider_config.env,
    }

    return LaunchSpec(
        argv=tuple(argv),
        env=tuple(sorted(env.items())),
        effort=effort if effort_args else None,
        effort_skipped=effort if effort and not effort_args else None,
        bypass=bool(bypass_args),
    )


__all__ = [
    "InvocationOptionProvider",
    "LaunchSpec",
    "resolve_effort_level",
    "resolve_launch_argv",
]

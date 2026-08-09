"""Translate a resolved reasoning effort into per-provider CLI args (Phase 3).

The directive/config layers (epic sase-55 Phases 1-2) resolve an effective
effort level into an :class:`LLMInvocationOptions`; this module turns that level
into the CLI flags a given provider understands, honoring the
explicit-vs-default contract:

- An *explicitly* requested effort (``%effort``/``@effort``) that a provider
  cannot honor raises :class:`LLMInvocationError` — never silently downgrade.
- An effort coming only from ``llm_provider.default_effort`` is best-effort:
  logged and skipped for providers/levels that do not support it, so a global
  default never breaks an ``agy``/``qwen`` run.

Each provider declares the levels it supports (and the argv fragment for each)
and calls :func:`effort_cli_args` from its ``invocation_option_args`` override.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from .types import LLMInvocationError, LLMInvocationOptions

logger = logging.getLogger(__name__)


def effort_cli_args(
    options: LLMInvocationOptions | None,
    *,
    provider_label: str,
    supported: Mapping[str, Sequence[str]],
) -> list[str]:
    """Return the CLI args selecting *options*' effort for one provider.

    ``supported`` maps each effort level the provider can honor to the argv
    fragment that selects it (an empty mapping means the provider supports no
    effort at all). Returns ``[]`` when there is no effort to apply.

    Raises :class:`LLMInvocationError` when an *explicit* effort is unsupported;
    logs a warning and returns ``[]`` when a *config-default* effort is
    unsupported.
    """
    if options is None or not options.reasoning_effort:
        return []

    level = options.reasoning_effort
    selected = supported.get(level)
    if selected is not None:
        return list(selected)

    supported_label = ", ".join(supported) or "(none)"
    detail = (
        f"{provider_label} does not support reasoning-effort level {level!r} "
        f"(supported: {supported_label})."
    )
    if options.explicit:
        raise LLMInvocationError(detail)
    logger.warning("%s Skipping the configured default effort.", detail)
    return []

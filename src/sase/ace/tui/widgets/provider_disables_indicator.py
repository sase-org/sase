"""Temporary provider-disable pill builders for the ACE top bar.

The disable pill now renders inside the merged ``overrides:`` group owned
by :class:`AliasOverridesIndicator`; this module keeps the static pill and
tooltip builders so plain-text tests can keep calling them.
"""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.provider_disable_display import provider_disable_provenance_label
from sase.llm_provider.provider_disable import TemporaryProviderDisable

from ._override_pill import (
    PROVIDER_DISABLE_PALETTE,
    PROVIDER_SOFT_DISABLE_PALETTE,
    build_override_pill,
    format_pill_remaining,
    format_remaining_until,
)
from ._text_signature import text_signature

_ACTIVE_STYLE = PROVIDER_DISABLE_PALETTE.base_style


class ProviderDisablesIndicator:
    """Static builders for the disable pill inside the merged overrides group."""

    @staticmethod
    def _build_content(
        disables: dict[str, TemporaryProviderDisable],
        *,
        now: float | None = None,
    ) -> Text:
        """Build the disable pill."""
        return ProviderDisablesIndicator._build_disable_content(
            disables,
            now=now,
        )

    @staticmethod
    def _build_disable_content(
        disables: dict[str, TemporaryProviderDisable],
        *,
        now: float | None = None,
    ) -> Text:
        """Build the provider-disable portion of the indicator pill."""
        survivors: list[tuple[bool, str, TemporaryProviderDisable, str]] = []
        for provider, disable in disables.items():
            remaining = format_pill_remaining(disable.expires_at, now)
            if remaining is not None:
                survivors.append((disable.is_soft, provider, disable, remaining))
        survivors.sort()

        if not survivors:
            return Text("")

        all_soft = all(
            is_soft for is_soft, _provider, _disable, _remaining in survivors
        )
        palette = (
            PROVIDER_SOFT_DISABLE_PALETTE if all_soft else PROVIDER_DISABLE_PALETTE
        )
        _is_soft, provider, disable, remaining = survivors[0]
        if len(survivors) == 1:
            kind = "soft" if disable.is_soft else "off"
            return build_override_pill(
                subject=provider.upper(),
                effort=None,
                trailing=f"{kind} {remaining}",
                palette=palette,
            )

        return build_override_pill(
            subject=provider.upper(),
            effort=None,
            trailing=f"+{len(survivors) - 1}",
            palette=palette,
        )

    @staticmethod
    def _build_tooltip(
        disables: dict[str, TemporaryProviderDisable],
        *,
        now: float | None = None,
    ) -> str | None:
        """Build sorted long-form details for disabled providers."""
        lines: list[str] = []
        for provider, disable in sorted(disables.items()):
            if format_pill_remaining(disable.expires_at, now) is None:
                continue
            if disable.expires_at is None:
                remaining = "until cleared"
            else:
                remaining = f"{format_remaining_until(disable.expires_at, now)} left"
            provenance = provider_disable_provenance_label(disable)
            mode = "soft" if disable.is_soft else "hard"
            lines.append(f"{provider.upper()} - {mode} · {provenance}, {remaining}")
        if not lines:
            return None
        return "\n".join(
            (
                "Disabled providers:",
                *lines,
                "Hard disables skip the provider on new launches; "
                "running processes continue.",
                "Pools spare a soft provider while another member can cover; "
                "|| fallbacks and explicit %model still use it.",
                "Press ,m for Config > Launch.",
            )
        )


# Tests and older imports still reach the signature helper through this module.
_text_signature = text_signature


__all__ = ["ProviderDisablesIndicator"]

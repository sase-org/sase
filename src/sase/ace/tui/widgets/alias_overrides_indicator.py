"""Non-default temporary-override indicator for sase's TUI top bar.

A concise, uniform sidecar to :class:`LLMOverrideIndicator`. Where that
widget renders the gold launch-default override pill, this one surfaces
temporary launch overrides — non-default alias pills plus provider priority
and provider-disable pills — side by side under one ``overrides:`` label.
The Launch settings (leader ``,m``) remain the authoritative detail view;
these pills are intentionally terse.

Hover reveals the full targets and remaining durations; clicking opens Launch settings.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text

from sase.llm_provider.config import (
    DEFAULT_MODEL_FIELD,
    launch_model_setting_override_key,
)
from sase.llm_provider.provider_priority import ProviderRoutingContext
from sase.llm_provider.provider_priority_peek import peek_provider_routing_context
from sase.llm_provider.temporary_override import (
    TemporaryLLMOverride,
    get_active_alias_overrides,
)

from ._override_pill import (
    ALIAS_LANE_PALETTE,
    build_override_pill,
    format_pill_remaining,
    format_remaining_until,
    format_tooltip_target,
)
from .provider_disables_indicator import ProviderDisablesIndicator
from .provider_priority_indicator import ProviderPriorityIndicator
from .top_bar_group import TopBarGroup

#: Violet pill, parallel to the gold default pill but unmistakably distinct;
#: matches the launch override-chip accent for a uniform override style.
_ACTIVE_STYLE = ALIAS_LANE_PALETTE.base_style

#: Shared tooltip footer; each section builder ends with this line.
_TOOLTIP_FOOTER = "Press ,m for Config > Launch."


class AliasOverridesIndicator(TopBarGroup):
    """Shows terse pills for alias, priority, and disable launch overrides."""

    GROUP_LABEL = "overrides"
    CLICK_ACTION = "open_models_panel"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        overrides = self._active_non_default_overrides()
        context = peek_provider_routing_context()
        self._set_body(self._build_combined_content(overrides, context))
        self.tooltip = self._build_combined_tooltip(overrides, context)

    def on_mount(self) -> None:
        """Poll on the same cadence as the default-override pill."""
        self._apply_content()
        self.set_interval(30.0, self.refresh)

    def refresh(self, *args: Any, **kwargs: Any) -> Any:
        """Rebuild content on a bare refresh, preserving Widget.refresh kwargs."""
        if args or kwargs:
            return super().refresh(*args, **kwargs)
        self._apply_content()
        return super().refresh()

    def _build_initial_content(self, *, now: float | None = None) -> Text:
        """Render the merged pills from the current override and routing state."""
        overrides = self._active_non_default_overrides()
        context = peek_provider_routing_context(now)
        return self._build_combined_content(overrides, context, now=now)

    def _apply_content(self, *, now: float | None = None) -> None:
        """Update content and tooltip from one current snapshot."""
        overrides = self._active_non_default_overrides()
        context = peek_provider_routing_context(now)
        self._set_body(self._build_combined_content(overrides, context, now=now))
        tooltip = self._build_combined_tooltip(overrides, context, now=now)
        if self.tooltip != tooltip:
            self.tooltip = tooltip

    @staticmethod
    def _active_non_default_overrides() -> dict[str, TemporaryLLMOverride]:
        """Return active overrides, excluding the default-launch setting."""
        overrides = dict(get_active_alias_overrides())
        overrides.pop(launch_model_setting_override_key(DEFAULT_MODEL_FIELD), None)
        return overrides

    @staticmethod
    def _build_content(
        overrides: dict[str, TemporaryLLMOverride],
        *,
        now: float | None = None,
    ) -> Text:
        """Build the alias pill text for the given non-default override map.

        Empty (zero-width) when nothing is overridden; a single
        ``@alias[@effort] <remaining>`` pill for one alias; an
        ``@first +N`` summary for several.
        """
        survivors: list[tuple[str, TemporaryLLMOverride, str]] = []
        for alias, override in sorted(overrides.items()):
            remaining = format_pill_remaining(override.expires_at, now)
            if remaining is not None:
                survivors.append((alias, override, remaining))

        if not survivors:
            return Text("")

        alias, override, remaining = survivors[0]
        if len(survivors) == 1:
            return build_override_pill(
                subject=_override_subject(alias),
                effort=override.effort,
                trailing=remaining,
                palette=ALIAS_LANE_PALETTE,
            )

        return build_override_pill(
            subject=_override_subject(alias),
            effort=None,
            trailing=f"+{len(survivors) - 1}",
            palette=ALIAS_LANE_PALETTE,
        )

    @staticmethod
    def _build_combined_content(
        overrides: dict[str, TemporaryLLMOverride],
        context: ProviderRoutingContext,
        *,
        now: float | None = None,
    ) -> Text:
        """Build the merged alias + priority + disable pill body.

        Each pill is built exactly as its original indicator built it; empty
        pills are omitted so a missing fact leaves no hole. Non-empty pills
        are joined with ``Text.append_text`` and no extra characters.
        """
        alias_pill = AliasOverridesIndicator._build_content(overrides, now=now)
        availability = ProviderPriorityIndicator._priority_availability(context)
        priority_pill = ProviderPriorityIndicator._build_content(
            context.priority,
            priority_availability=availability,
            now=now,
        )
        disable_pill = ProviderDisablesIndicator._build_content(
            context.provider_disables,
            now=now,
        )
        body = Text("")
        for pill in (alias_pill, priority_pill, disable_pill):
            if pill.plain != "":
                body.append_text(pill)
        return body

    @staticmethod
    def _build_tooltip(
        overrides: dict[str, TemporaryLLMOverride],
        *,
        now: float | None = None,
    ) -> str | None:
        """Build sorted long-form details for active alias overrides."""
        lines: list[str] = []
        for alias, override in sorted(overrides.items()):
            if format_pill_remaining(override.expires_at, now) is None:
                continue
            remaining = format_remaining_until(override.expires_at, now)
            if override.expires_at is not None:
                remaining = f"{remaining} left"
            lines.append(
                f"{_override_subject(alias)} -> "
                f"{format_tooltip_target(override)} - {remaining}"
            )
        if not lines:
            return None
        return "\n".join(
            (
                "Temporary model overrides:",
                *lines,
                _TOOLTIP_FOOTER,
            )
        )

    @staticmethod
    def _build_combined_tooltip(
        overrides: dict[str, TemporaryLLMOverride],
        context: ProviderRoutingContext,
        *,
        now: float | None = None,
    ) -> str | None:
        """Build the merged tooltip from the three section builders.

        Each active section contributes its builder output minus the shared
        trailing footer; sections are joined with one blank line and the
        footer is appended once. A single active fact matches that fact's
        original tooltip exactly.
        """
        availability = ProviderPriorityIndicator._priority_availability(context)
        sections: list[str] = []
        for section in (
            AliasOverridesIndicator._build_tooltip(overrides, now=now),
            ProviderPriorityIndicator._build_tooltip(
                context.priority,
                priority_availability=availability,
                now=now,
            ),
            ProviderDisablesIndicator._build_tooltip(
                context.provider_disables,
                now=now,
            ),
        ):
            if section is None:
                continue
            sections.append(_strip_tooltip_footer(section))
        if not sections:
            return None
        return "\n\n".join(sections) + f"\n{_TOOLTIP_FOOTER}"


def _strip_tooltip_footer(section: str) -> str:
    """Remove the shared trailing footer from one tooltip section."""
    suffix = f"\n{_TOOLTIP_FOOTER}"
    if section.endswith(suffix):
        return section[: -len(suffix)]
    if section == _TOOLTIP_FOOTER:
        return ""
    return section


def _override_subject(key: str) -> str:
    if key == "setting:epic_lander_model":
        return "epic lander"
    if key == "setting:big_epic_lander_model":
        return "big epic lander"
    return f"@{key}"

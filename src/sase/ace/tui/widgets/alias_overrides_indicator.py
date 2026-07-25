"""Non-default temporary-override indicator for the ace TUI top bar.

A concise, uniform sidecar to :class:`LLMOverrideIndicator`. Where that
widget renders the gold ``default`` override pill (the no-``%model`` launch
default), this one surfaces temporary overrides on *every other* alias
(``coder`` / ``<size>_phase_worker`` / ``<provider>_coder`` / user aliases) in a single
violet pill, visually parallel to but clearly distinct from the gold default
pill. The Models panel (leader ``,m``) remains the authoritative detail view;
this pill is intentionally terse:

* no non-``default`` override active → empty (the pill collapses to zero width);
* exactly one → ``@<alias>[@<effort>] <remaining>``;
* several → ``@<alphabetically-first-alias> +<remaining-count>``.

It reads :func:`get_active_alias_overrides` (minus ``default``) on each refresh;
that read self-cleans expired entries, so the pill never shows a stale override.
Hover reveals the full targets and remaining durations; clicking opens the
Models panel.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Static

from sase.llm_provider.config import DEFAULT_MODEL_ALIAS_NAME
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

#: Violet pill, parallel to the gold ``default`` pill but unmistakably distinct;
#: matches the Models-panel override-chip accent for a uniform override style.
_ACTIVE_STYLE = ALIAS_LANE_PALETTE.base_style


class AliasOverridesIndicator(Static):
    """Shows a terse pill whenever a non-``default`` alias is overridden."""

    def __init__(self, **kwargs: Any) -> None:
        overrides = self._active_non_default_overrides()
        super().__init__(self._build_content(overrides), **kwargs)
        self.tooltip = self._build_tooltip(overrides)

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

    async def on_click(self) -> None:
        """Open the Models panel."""
        await self.app.run_action("open_models_panel")

    def _build_initial_content(self, *, now: float | None = None) -> Text:
        """Render the pill from the current non-``default`` override map."""
        return self._build_content(self._active_non_default_overrides(), now=now)

    def _apply_content(self, *, now: float | None = None) -> None:
        """Update content and tooltip from one current override snapshot."""
        overrides = self._active_non_default_overrides()
        self.update(self._build_content(overrides, now=now))
        self.tooltip = self._build_tooltip(overrides, now=now)

    @staticmethod
    def _active_non_default_overrides() -> dict[str, TemporaryLLMOverride]:
        """Return active overrides keyed by alias, excluding ``default``."""
        overrides = dict(get_active_alias_overrides())
        overrides.pop(DEFAULT_MODEL_ALIAS_NAME, None)
        return overrides

    @staticmethod
    def _build_content(
        overrides: dict[str, TemporaryLLMOverride],
        *,
        now: float | None = None,
    ) -> Text:
        """Build the pill text for the given non-``default`` override map.

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
                subject=f"@{alias}",
                effort=override.effort,
                trailing=remaining,
                palette=ALIAS_LANE_PALETTE,
            )

        return build_override_pill(
            subject=f"@{alias}",
            effort=None,
            trailing=f"+{len(survivors) - 1}",
            palette=ALIAS_LANE_PALETTE,
        )

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
            lines.append(f"@{alias} -> {format_tooltip_target(override)} - {remaining}")
        if not lines:
            return None
        return "\n".join(
            (
                "Temporary alias overrides:",
                *lines,
                "Press ,m for the Models panel.",
            )
        )

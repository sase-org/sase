"""Non-default temporary-override indicator for the ace TUI top bar.

A concise, uniform sidecar to :class:`LLMOverrideIndicator`. Where that
widget renders the gold ``default`` override pill (the no-``%model`` launch
default), this one surfaces temporary overrides on *every other* alias
(``coder`` / ``<size>_phase_worker`` / ``<provider>_coder`` / user aliases) in a single
violet pill, visually parallel to but clearly distinct from the gold default
pill. The Models panel (leader ``,m``) remains the authoritative detail view;
this pill is intentionally terse:

* no non-``default`` override active → empty (the pill collapses to zero width);
* exactly one → ``Override @<alias> <remaining>`` (alias name + countdown);
* several → ``Overrides ×<count>`` (just a count, so the bar never bloats).

It reads :func:`get_active_alias_overrides` (minus ``default``) on each refresh;
that read self-cleans expired entries, so the pill never shows a stale override.
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

from .llm_override_indicator import format_remaining_until

#: Violet pill, parallel to the gold ``default`` pill but unmistakably distinct;
#: matches the Models-panel override-chip accent for a uniform override style.
_ACTIVE_STYLE = "bold #1a1a1a on #AF87FF"


class AliasOverridesIndicator(Static):
    """Shows a terse pill whenever a non-``default`` alias is overridden."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(self._build_initial_content(), **kwargs)

    def on_mount(self) -> None:
        """Poll on the same cadence as the default-override pill."""
        self.set_interval(30.0, self.refresh)

    def refresh(self, *args: Any, **kwargs: Any) -> Any:
        """Rebuild content on a bare refresh, preserving Widget.refresh kwargs."""
        if args or kwargs:
            return super().refresh(*args, **kwargs)
        self.update(self._build_initial_content())
        return super().refresh()

    def _build_initial_content(self, *, now: float | None = None) -> Text:
        """Render the pill from the current non-``default`` override map."""
        return self._build_content(self._active_non_default_overrides(), now=now)

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
        ``Override @alias <remaining>`` pill for one alias; a terse
        ``Overrides ×N`` count for several.
        """
        if not overrides:
            return Text("")

        if len(overrides) == 1:
            alias, override = next(iter(overrides.items()))
            remaining = format_remaining_until(override.expires_at, now)
            if not remaining:
                # Expired entries are pruned by ``get_active_alias_overrides``;
                # guard the direct-call path so a lapsed entry shows nothing.
                return Text("")
            return Text(f" Override @{alias} {remaining} ", style=_ACTIVE_STYLE)

        return Text(f" Overrides ×{len(overrides)} ", style=_ACTIVE_STYLE)

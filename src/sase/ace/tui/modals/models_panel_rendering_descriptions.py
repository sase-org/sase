"""Description-strip rendering for Models panel rows."""

from __future__ import annotations

from collections.abc import Iterable

from rich.text import Text

from sase.ace.tui.model_alias_styles import append_pool_weight
from sase.llm_provider import AliasView, BucketView

from .models_panel_rendering_layout import (
    _DESCRIPTION_MISSING_STYLE,
    _DESCRIPTION_STYLE,
    _PAUSED_OVERRIDE_TAG_STYLE,
    _POOL_AVAILABLE_STYLE,
    _POOL_UNAVAILABLE_STYLE,
    _WARNING_STYLE,
)
from .models_panel_rows import (
    BigEpicPhaseThresholdSettingRow,
    DefaultEffortSettingRow,
    LaunchModelSettingRow,
    ModelsPanelDisplayRow,
    RunnerLimitSettingRow,
)

_POOL_SOFT_STYLE = "bold #FFD75F"

_CUSTOM_ALIASES_PATH = "llm_provider.model_aliases.custom"
_BUILTIN_ALIASES_PATH = "llm_provider.model_aliases.builtin"


def custom_builtin_shadow_warning_message(names: Iterable[str]) -> str:
    """Return actionable opening-toast text for misplaced builtin aliases."""
    aliases = tuple(f"@{name}" for name in sorted(names))
    if len(aliases) == 1:
        return (
            f"Builtin alias {aliases[0]} is configured under {_CUSTOM_ALIASES_PATH}. "
            f"Move its model value from {_CUSTOM_ALIASES_PATH} to "
            f"{_BUILTIN_ALIASES_PATH}."
        )
    return (
        f"Builtin aliases {', '.join(aliases)} are configured under "
        f"{_CUSTOM_ALIASES_PATH}. Move each custom entry's model value from "
        f"{_CUSTOM_ALIASES_PATH} to {_BUILTIN_ALIASES_PATH}."
    )


def _custom_builtin_shadow_description(names: Iterable[str]) -> Text:
    """Return the two-line persistent warning for highlighted problem rows."""
    aliases = tuple(f"@{name}" for name in sorted(names))
    noun = "alias" if len(aliases) == 1 else "aliases"
    pronoun = "its model value" if len(aliases) == 1 else "their model values"
    text = Text(style=_WARNING_STYLE, no_wrap=True, overflow="ellipsis")
    text.append(f"! Misplaced builtin {noun}: {', '.join(aliases)}")
    text.append(
        f"\nMove {pronoun} from {_CUSTOM_ALIASES_PATH} to {_BUILTIN_ALIASES_PATH}."
    )
    return text


def _format_provider_model(provider: str | None, model: str, effort: str | None) -> str:
    label = f"{provider.upper()}({model})" if provider else model
    return f"{label} @ {effort}" if effort else label


def _description_text_for_launch_setting(row: LaunchModelSettingRow) -> Text:
    snapshot = row.snapshot
    text = Text()
    if row.is_override_paused:
        disable = snapshot.override_paused_by_provider_disable
        assert disable is not None
        text.append(
            f"Stored override is paused because {disable.provider.upper()} is disabled.",
            style=_PAUSED_OVERRIDE_TAG_STYLE,
        )
        text.append(
            f"\nConfigured {snapshot.config_path}: {snapshot.raw_value}", style="dim"
        )
        return text
    text.append(row.detail, style=_DESCRIPTION_STYLE)
    text.append("\n")
    text.append(f"{snapshot.config_path}: {snapshot.raw_value}", style="dim")
    text.append(" · effective ", style="dim")
    text.append(
        _format_provider_model(snapshot.provider, snapshot.model, snapshot.effort),
        style="dim",
    )
    if snapshot.override is not None:
        text.append(" · temporary override active", style="bold #AF87FF")
    return text


def _description_text_for_default_effort(
    row: DefaultEffortSettingRow,
    *,
    now: float,
) -> Text:
    text = Text()
    override = row.snapshot.active_override(now)
    if override is not None:
        text.append(
            "Temporary launch-default effort override.", style=_DESCRIPTION_STYLE
        )
        text.append("\nconfigured: ", style="dim")
        text.append(row.snapshot.configured_effort or "provider default", style="dim")
        return text
    text.append(
        "Default reasoning effort for launches without explicit effort.",
        style=_DESCRIPTION_STYLE,
    )
    text.append("\nconfigured: ", style="dim")
    text.append(row.snapshot.configured_effort or "provider default", style="dim")
    return text


def _description_text_for_runner_limit(
    row: RunnerLimitSettingRow,
    *,
    now: float,
) -> Text:
    text = Text()
    override = row.snapshot.active_override(now)
    if override is not None:
        text.append("Temporary maximum running-agent limit.", style=_DESCRIPTION_STYLE)
        text.append(f"\nconfigured: {row.snapshot.configured_limit}", style="dim")
        return text
    text.append(
        "Maximum number of agents admitted to run at once.", style=_DESCRIPTION_STYLE
    )
    text.append(f"\nconfigured: {row.snapshot.configured_limit}", style="dim")
    return text


def _description_text_for_threshold(row: BigEpicPhaseThresholdSettingRow) -> Text:
    text = Text()
    text.append(
        "Epics with "
        f"{row.threshold} or more authored phases use the big epic lander; "
        "smaller epics use the regular epic lander.",
        style=_DESCRIPTION_STYLE,
    )
    text.append(f"\n{row.config_path}: {row.threshold}", style="dim")
    return text


def description_text_for_view(
    view: AliasView | None,
    default_effort: str | None = None,
) -> Text:
    """Return the two-line description strip content for *view*."""
    if view is None:
        return Text("", style=_DESCRIPTION_STYLE)
    if view.is_custom_builtin_shadow:
        return _custom_builtin_shadow_description((view.name,))
    text = Text()
    if view.is_override_paused:
        disable = view.override_paused_by_provider_disable
        assert disable is not None
        provider = disable.provider.upper()
        if view.override is not None:
            target = f"{view.override.provider}/{view.override.model}"
            if view.override.effort:
                target = f"{target}@{view.override.effort}"
        else:
            target = provider
        text.append(
            f"Stored override {target} is paused because {provider} is disabled.",
            style=_PAUSED_OVERRIDE_TAG_STYLE,
        )
        if disable.expires_at is None:
            text.append("\nIt resumes when the provider is enabled.", style="dim")
        else:
            text.append(
                "\nIt resumes when the provider disable expires or is cleared.",
                style="dim",
            )
    elif view.description:
        text.append(view.description, style=_DESCRIPTION_STYLE)
    elif view.kind == "user":
        text.append(
            "no description - set "
            f"llm_provider.model_aliases.custom.{view.name}.description",
            style=_DESCRIPTION_MISSING_STYLE,
        )
    if view.selector_members:
        if text:
            text.append("\n")
        label = "pool" if view.selector_mode == "round_robin" else "fallback"
        suspended = view.is_overridden
        if suspended:
            label = f"{label} (suspended by override)"
        text.append(f"{label}: ", style="dim")
        for index, member in enumerate(view.selector_members):
            if index:
                text.append(" · ", style="dim")
            if member.selected and not suspended:
                arrow_style = (
                    "bold #FFD75F"
                    if not member.valid
                    else f"bold {'#87D787' if member.available else '#D78787'}"
                )
                text.append("→ ", style=arrow_style)
            if member.valid:
                marker = "✓" if member.available else "×"
                target = member.target
                if member.effort:
                    target = f"{target}@{member.effort}"
                color = (
                    _POOL_AVAILABLE_STYLE
                    if member.available
                    else _POOL_UNAVAILABLE_STYLE
                )
                dimmed = suspended or not member.selected
                style = f"dim {color}" if dimmed else color
                text.append(f"{marker} {target}", style=style)
                if member.sparing:
                    text.append(" soft", style=_POOL_SOFT_STYLE)
            else:
                style = (
                    "dim #FFD75F"
                    if suspended or not member.selected
                    else _WARNING_STYLE
                )
                text.append(f"! {member.value}", style=style)
            append_pool_weight(text, member.weight)
    elif view.effort:
        if text:
            text.append("\n")
        text.append(f"effort: {view.effort}", style="dim")
        if view.override is None and view.reference_effort is not None:
            reference = view.references or view.implicit_fallback
            if reference is not None:
                text.append(
                    f" (via @{reference}@{view.reference_effort})",
                    style="dim",
                )
        if default_effort is None:
            text.append(" · no default configured", style="dim")
        elif view.effort == default_effort:
            text.append(" · matches default", style="dim")
        else:
            text.append(
                f" · overrides default {default_effort}",
                style="dim",
            )
    return text


def _description_text_for_bucket(bucket: BucketView) -> Text:
    """Return the two-line description and effective-model mix for *bucket*."""
    if bucket.custom_builtin_shadow_names:
        return _custom_builtin_shadow_description(bucket.custom_builtin_shadow_names)
    text = Text()
    if bucket.description:
        text.append(bucket.description, style=_DESCRIPTION_STYLE)
    else:
        text.append(
            "no description - set "
            f"llm_provider.model_aliases.buckets.{bucket.name}.description",
            style=_DESCRIPTION_MISSING_STYLE,
        )
    text.append("\n")
    text.append(
        " · ".join(f"{model} ×{count}" for model, count in bucket.model_counts),
        style="dim",
    )
    return text


def description_text_for_row(
    row: ModelsPanelDisplayRow | None,
    default_effort: str | None = None,
    *,
    now: float = 0.0,
) -> Text:
    """Dispatch Models-panel description rendering by row type."""
    if isinstance(row, LaunchModelSettingRow):
        return _description_text_for_launch_setting(row)
    if isinstance(row, DefaultEffortSettingRow):
        return _description_text_for_default_effort(row, now=now)
    if isinstance(row, RunnerLimitSettingRow):
        return _description_text_for_runner_limit(row, now=now)
    if isinstance(row, BigEpicPhaseThresholdSettingRow):
        return _description_text_for_threshold(row)
    if isinstance(row, BucketView):
        return _description_text_for_bucket(row)
    return description_text_for_view(row, default_effort)

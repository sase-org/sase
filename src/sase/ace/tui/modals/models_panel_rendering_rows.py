"""Data-row rendering for the Models panel."""

from __future__ import annotations

from collections.abc import Iterable

from rich.text import Text

from sase.ace.tui.model_alias_styles import (
    MODEL_ALIAS_KIND_STYLES,
    alias_kind_label,
    alias_state_text,
    append_alias_reference,
    append_effort_suffix,
    append_pool_chip,
    provider_model_text,
)
from sase.llm_provider import AliasView, BucketView
from sase.llm_provider.temporary_override import TemporaryLLMOverride

from .models_panel_duration import format_remaining
from .models_panel_rendering_layout import (
    PROVIDER_MODEL_CELL_MAX,
    _BUCKET_DIM_STYLE,
    _BUCKET_STYLE,
    _IMPLICIT_TAG_STYLE,
    _NAME_CELL,
    _OVERRIDE_TAG_STYLE,
    _OWNERSHIP_STYLE,
    _PAUSED_OVERRIDE_TAG_STYLE,
    _STATE_GAP,
    _WARNING_STYLE,
    append_ownership_gutter,
    count_label,
    pad_to_width,
)
from .models_panel_rows import (
    BigEpicPhaseThresholdSettingRow,
    DefaultEffortSettingRow,
    LaunchModelSettingRow,
    ModelsPanelDisplayRow,
    RunnerLimitSettingRow,
)


def kind_label(view: AliasView) -> str:
    """Return the small kind badge text for *view*."""
    # Keep the Models panel's established ``user`` label while the denser
    # completion table uses the clearer shared ``custom`` vocabulary.
    if view.kind == "user":
        return "user"
    return alias_kind_label(view.kind)


def _override_chip(override: TemporaryLLMOverride, now: float) -> str:
    """Render the active-override state chip (``override · 15m left``)."""
    if override.expires_at is None:
        return "override · until cleared"
    return f"override · {format_remaining(override.expires_at - now)} left"


def state_tag(view: AliasView, now: float) -> Text:
    """Return the styled provenance / override state column for *view*."""
    if view.is_override_paused:
        disable = view.override_paused_by_provider_disable
        assert disable is not None
        provider = disable.provider.upper()
        return Text(
            f"override paused · {provider} disabled",
            style=_PAUSED_OVERRIDE_TAG_STYLE,
        )
    if view.override is not None:
        return Text(_override_chip(view.override, now), style=_OVERRIDE_TAG_STYLE)
    reference = ""
    if view.configured and view.references is not None:
        reference = view.references
    elif not view.configured and view.implicit_fallback is not None:
        reference = view.implicit_fallback
    members = (
        tuple(member for member in view.selector_members if not member.last_resort)
        if view.selector_mode == "round_robin"
        else ()
    )
    text = alias_state_text("configured" if view.configured else "implicit")
    if members:
        append_pool_chip(
            text,
            sum(member.available for member in members),
            len(members),
        )
    elif reference:
        append_alias_reference(text, reference, view.reference_effort or "")
    return text


def _provider_model_text(view: AliasView) -> Text:
    """Build the shared provider/model badge for one alias view."""
    text = provider_model_text(view.provider, view.model)
    append_effort_suffix(text, view.effort or "")
    return text


def _provider_model_text_for_values(
    provider: str | None,
    model: str,
    effort: str | None,
) -> Text:
    """Build a provider/model badge from explicit fields."""
    text = provider_model_text(provider, model)
    append_effort_suffix(text, effort or "")
    return text


def _launch_value_text(row: LaunchModelSettingRow) -> Text:
    """Return the raw-expression-to-effective value for a launch setting."""
    snapshot = row.snapshot
    text = Text(no_wrap=True, overflow="ellipsis")
    raw = snapshot.raw_value
    raw_style = "#87D7FF" if raw.startswith("@") else "bold"
    text.append(raw, style=raw_style)
    text.append(" → ", style="dim")
    text.append_text(
        _provider_model_text_for_values(
            snapshot.provider,
            snapshot.model,
            snapshot.effort,
        )
    )
    return text


def _effort_label(effort: str | None) -> Text:
    text = Text(no_wrap=True, overflow="ellipsis")
    if effort is None:
        text.append("provider default", style="dim")
        return text
    text.append("@ ", style="dim")
    text.append(effort, style="bold #AF87FF")
    return text


def _default_effort_value_text(row: DefaultEffortSettingRow, *, now: float) -> Text:
    return _effort_label(row.snapshot.effective_effort(now))


def _runner_limit_value_text(row: RunnerLimitSettingRow, *, now: float) -> Text:
    text = Text(no_wrap=True, overflow="ellipsis")
    text.append(str(row.snapshot.effective_limit(now)), style="bold cyan")
    return text


def format_phase_threshold(threshold: int) -> str:
    """Return the visible threshold value with correct singularization."""
    noun = "phase" if threshold == 1 else "phases"
    return f"{threshold} {noun}"


def _threshold_value_text(row: BigEpicPhaseThresholdSettingRow) -> Text:
    text = Text(no_wrap=True, overflow="ellipsis")
    text.append(format_phase_threshold(row.threshold), style="bold cyan")
    return text


def _row_value_text(row: ModelsPanelDisplayRow, *, now: float) -> Text:
    """Return the aligned value-column text for any data row."""
    if isinstance(row, LaunchModelSettingRow):
        return _launch_value_text(row)
    if isinstance(row, DefaultEffortSettingRow):
        return _default_effort_value_text(row, now=now)
    if isinstance(row, RunnerLimitSettingRow):
        return _runner_limit_value_text(row, now=now)
    if isinstance(row, BigEpicPhaseThresholdSettingRow):
        return _threshold_value_text(row)
    if isinstance(row, BucketView):
        return Text(count_label(row.alias_count, "alias"), style="dim")
    return _provider_model_text(row)


def provider_model_column_width(
    views: Iterable[AliasView], *, cap: int = PROVIDER_MODEL_CELL_MAX
) -> int:
    """Return the provider/model column width (in cells) for *views*.

    Sized to the widest badge currently visible, capped by *cap* (normally
    :data:`PROVIDER_MODEL_CELL_MAX`, shrunk by the jump-mode gutter width
    while hints are painted) so the state tag stays on-screen. Rich cell
    widths are used (not ``len``) so wide glyphs and future badges are measured
    correctly. Collapses to ``0`` when no row has a badge.
    """
    widest = 0
    for view in views:
        widest = max(widest, _provider_model_text(view).cell_len)
    return min(widest, cap)


def panel_value_column_width(
    rows: Iterable[ModelsPanelDisplayRow],
    *,
    now: float,
    cap: int = PROVIDER_MODEL_CELL_MAX,
) -> int:
    """Return the shared value-column width for visible panel rows.

    *cap* is normally :data:`PROVIDER_MODEL_CELL_MAX`; callers shrink it by
    the jump-mode gutter width while hints are painted so the reserved gutter
    does not push the state tag past the modal budget.
    """
    widest = 0
    for row in rows:
        widest = max(widest, _row_value_text(row, now=now).cell_len)
    return min(widest, cap)


def render_alias_row(view: AliasView, *, now: float, provider_model_width: int) -> Text:
    """Render one alias row as a single-line Rich ``Text``.

    Layout: ``<ownership> <name> <PROVIDER(model)> <state>``.
    The provider/model badge is fitted to *provider_model_width* - padded when
    short and ellipsized when it exceeds the cap - so the rightmost state tag
    starts at the same cell across every row. Building a ``Text`` (rather than
    a markup string) keeps alias/model values literal so a stray bracket in a
    config value can never break rendering.
    """
    text = Text(no_wrap=True, overflow="ellipsis")
    append_ownership_gutter(text, user_owned=view.is_user_owned)
    name = view.name
    if view.is_custom_builtin_shadow:
        text.append(pad_to_width(f"! {name}", _NAME_CELL), style=_WARNING_STYLE)
    else:
        name_style = MODEL_ALIAS_KIND_STYLES.get(view.kind, "bold")
        text.append(
            pad_to_width(name, _NAME_CELL),
            style=name_style,
        )
    text.append(" ")
    badge = _provider_model_text(view)
    badge.truncate(provider_model_width, overflow="ellipsis", pad=True)
    text.append_text(badge)
    text.append(_STATE_GAP)
    text.append_text(state_tag(view, now))
    return text


def _launch_setting_state_tag(row: LaunchModelSettingRow, now: float) -> Text:
    """Return the provenance/override state for one launch-setting row."""
    snapshot = row.snapshot
    if row.is_override_paused:
        disable = snapshot.override_paused_by_provider_disable
        assert disable is not None
        return Text(
            f"override paused · {disable.provider.upper()} disabled",
            style=_PAUSED_OVERRIDE_TAG_STYLE,
        )
    if snapshot.override is not None:
        return Text(_override_chip(snapshot.override, now), style=_OVERRIDE_TAG_STYLE)
    return Text(snapshot.provenance.replace("_", " "), style="dim #9E9E9E")


def _default_effort_state_tag(row: DefaultEffortSettingRow, now: float) -> Text:
    override = row.snapshot.active_override(now)
    if override is not None:
        if override.expires_at is None:
            label = "override · until cleared"
        else:
            label = f"override · {format_remaining(override.expires_at - now)} left"
        return Text(label, style=_OVERRIDE_TAG_STYLE)
    if row.snapshot.configured_effort is None:
        return Text("provider default", style="dim #9E9E9E")
    return Text("configured", style="dim #9E9E9E")


def _runner_limit_state_tag(row: RunnerLimitSettingRow, now: float) -> Text:
    override = row.snapshot.active_override(now)
    if override is not None:
        if override.expires_at is None:
            label = "override · until cleared"
        else:
            label = f"override · {format_remaining(override.expires_at - now)} left"
        return Text(label, style=_OVERRIDE_TAG_STYLE)
    return Text("configured", style="dim #9E9E9E")


def _threshold_state_tag(_row: BigEpicPhaseThresholdSettingRow) -> Text:
    return Text("configured", style="dim #9E9E9E")


def _render_setting_row(
    *,
    name: str,
    value: Text,
    state: Text,
    value_width: int,
) -> Text:
    text = Text(no_wrap=True, overflow="ellipsis")
    append_ownership_gutter(text, user_owned=False)
    text.append(pad_to_width(name, _NAME_CELL), style="bold")
    text.append(" ")
    value.truncate(value_width, overflow="ellipsis", pad=True)
    text.append_text(value)
    text.append(_STATE_GAP)
    text.append_text(state)
    return text


def _render_launch_setting_row(
    row: LaunchModelSettingRow,
    *,
    now: float,
    value_width: int,
) -> Text:
    """Render one launch model-setting row."""
    return _render_setting_row(
        name=row.label,
        value=_launch_value_text(row),
        state=_launch_setting_state_tag(row, now),
        value_width=value_width,
    )


def _render_default_effort_row(
    row: DefaultEffortSettingRow,
    *,
    now: float,
    value_width: int,
) -> Text:
    """Render the default-effort row."""
    return _render_setting_row(
        name=row.label,
        value=_default_effort_value_text(row, now=now),
        state=_default_effort_state_tag(row, now),
        value_width=value_width,
    )


def _render_runner_limit_row(
    row: RunnerLimitSettingRow,
    *,
    now: float,
    value_width: int,
) -> Text:
    """Render the running-agents row."""
    return _render_setting_row(
        name=row.label,
        value=_runner_limit_value_text(row, now=now),
        state=_runner_limit_state_tag(row, now),
        value_width=value_width,
    )


def _render_threshold_row(
    row: BigEpicPhaseThresholdSettingRow,
    *,
    value_width: int,
) -> Text:
    """Render the big-epic threshold row."""
    return _render_setting_row(
        name=row.label,
        value=_threshold_value_text(row),
        state=_threshold_state_tag(row),
        value_width=value_width,
    )


def render_panel_row(
    row: ModelsPanelDisplayRow,
    *,
    now: float,
    value_width: int,
) -> Text:
    """Render any data row in the Models panel."""
    if isinstance(row, LaunchModelSettingRow):
        return _render_launch_setting_row(row, now=now, value_width=value_width)
    if isinstance(row, DefaultEffortSettingRow):
        return _render_default_effort_row(row, now=now, value_width=value_width)
    if isinstance(row, RunnerLimitSettingRow):
        return _render_runner_limit_row(row, now=now, value_width=value_width)
    if isinstance(row, BigEpicPhaseThresholdSettingRow):
        return _render_threshold_row(row, value_width=value_width)
    if isinstance(row, BucketView):
        return render_bucket_row(row, provider_model_width=value_width)
    return render_alias_row(row, now=now, provider_model_width=value_width)


def render_bucket_row(bucket: BucketView, *, provider_model_width: int) -> Text:
    """Render one collapsed bucket using the alias-row column skeleton."""
    text = Text(no_wrap=True, overflow="ellipsis")
    append_ownership_gutter(text, user_owned=bucket.is_user_owned)
    bucket_label = f"▸ {bucket.name}"
    if bucket.custom_builtin_shadow_count:
        bucket_label = f"▸ ! {bucket.name}"
    bucket_style = (
        _WARNING_STYLE
        if bucket.custom_builtin_shadow_count
        else _OWNERSHIP_STYLE
        if bucket.is_user_owned
        else _BUCKET_STYLE
    )
    text.append(pad_to_width(bucket_label, _NAME_CELL), style=bucket_style)
    text.append(" ")
    alias_count = count_label(bucket.alias_count, "alias")
    text.append(pad_to_width(alias_count, provider_model_width), style="dim")
    text.append(_STATE_GAP)
    if bucket.custom_builtin_shadow_count:
        text.append(
            f"! {bucket.custom_builtin_shadow_count} misplaced", style=_WARNING_STYLE
        )
        if bucket.override_count:
            text.append(
                f" · {bucket.override_count} override",
                style=_OVERRIDE_TAG_STYLE,
            )
        if bucket.paused_override_count:
            text.append(
                f" · {bucket.paused_override_count} paused",
                style=_PAUSED_OVERRIDE_TAG_STYLE,
            )
    elif bucket.override_count:
        text.append(
            f"override · {bucket.override_count} active", style=_OVERRIDE_TAG_STYLE
        )
        if bucket.paused_override_count:
            text.append(
                f" · {bucket.paused_override_count} paused",
                style=_PAUSED_OVERRIDE_TAG_STYLE,
            )
    elif bucket.paused_override_count:
        text.append(
            f"override paused · {bucket.paused_override_count}",
            style=_PAUSED_OVERRIDE_TAG_STYLE,
        )
    else:
        bucket_state_style = (
            _OWNERSHIP_STYLE if bucket.is_user_owned else _BUCKET_DIM_STYLE
        )
        text.append("bucket", style=bucket_state_style)
    if not bucket.is_user_owned and bucket.user_member_count:
        text.append(" · ", style=_IMPLICIT_TAG_STYLE)
        text.append(
            f"{bucket.user_member_count} custom",
            style=_OWNERSHIP_STYLE,
        )
    return text

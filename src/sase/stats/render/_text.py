"""Shared number, date, and model-row helpers for Rich and Markdown."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sase.integrations.provider_badges import provider_emoji_badge
from sase.integrations.provider_palette import provider_bar_style, provider_name_style
from sase.project_accents import project_accent
from sase.stats.project.models import ProjectStatsModel
from sase.stats.project.view import ProjectStatsView
from sase.stats.render.context import RenderContext
from sase.stats.render.primitives import (
    format_compact,
    format_count,
    format_duration,
    format_relative_age,
)

DASH = "—"
STATS_ACCENT = "#FF87D7"
UNKNOWN_STYLE = "dim #D7AF5F"
NO_AGENT_STYLE = "dim #808080"
GREEN = "#5FD75F"
RED = "#FF5F5F"
CYAN = "#87D7FF"
DIM = "dim"
_UNKNOWN_REASON_LABELS = {
    "page_unpublished": "agent page not published",
    "page_metadata_empty": "agent page has no model",
    "session_ambiguous": "session members disagree on model",
    "malformed_model_tag": "malformed model tag",
}
_NOT_COUNTED_LABELS = {
    "user_linked": "user-linked",
    "external": "external",
}
_MAX_MODELS_PER_PROVIDER = 3


def maybe_int(value: int | float | None, *, compact: bool = False) -> str:
    """Format a measured integer, or an em dash when the source is missing."""
    if value is None:
        return DASH
    return format_compact(value) if compact else format_count(value)


def maybe_percent(value: float | None) -> str:
    """Format a 0–1 share as a whole-number percent."""
    if value is None:
        return DASH
    return f"{round(value * 100)}%"


def share_of(part: int | None, whole: int | None) -> str:
    if part is None or not whole:
        return DASH if whole is None else "0%"
    return f"{round(part * 100 / whole)}%"


def format_age_days(days: int | None, *, prose: bool = False) -> str:
    if days is None:
        return DASH
    if days < 45:
        unit = "days" if prose else "d"
        return f"{days} {unit}" if prose else f"{days} d"
    months = int(days / 30.4375)
    if months < 18:
        if prose:
            return "1 month" if months == 1 else f"{months} months"
        return f"{months} mo"
    years = max(1, int(round(months / 12)))
    if prose:
        return "1 year" if years == 1 else f"{years} years"
    return f"{years} yr"


def format_agent_time(seconds: float | None) -> str:
    if seconds is None:
        return DASH
    if seconds >= 3600:
        hours = seconds / 3600
        rendered = (
            f"{hours:.0f}" if hours >= 10 else f"{hours:.1f}".rstrip("0").rstrip(".")
        )
        return f"{rendered} h"
    return format_duration(seconds)


def _aware_dt(ts: int | float | None, ctx: RenderContext) -> datetime | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=UTC).astimezone(ctx.timezone)
    except (OSError, OverflowError, ValueError):
        return None


def format_ts(ts: int | float | None, ctx: RenderContext, fmt: str) -> str:
    parsed = _aware_dt(ts, ctx)
    return parsed.strftime(fmt) if parsed is not None else DASH


def relative_ts(ts: int | float | None, ctx: RenderContext) -> str:
    parsed = _aware_dt(ts, ctx)
    if parsed is None:
        return DASH
    now = (
        ctx.now if ctx.now.tzinfo is not None else ctx.now.replace(tzinfo=ctx.timezone)
    )
    delta = (now.astimezone(ctx.timezone) - parsed).total_seconds()
    if delta < 0:
        return format_ts(ts, ctx, "%b %d %H:%M")
    return format_relative_age(delta)


def range_heading(view: ProjectStatsView) -> str:
    span = view.query.range
    label = span.display_label
    absolute = span.label
    if label and absolute and label != absolute:
        return f"{label} · {absolute}"
    return absolute or label or "range"


def unknown_reason_label(reason: str) -> str:
    return _UNKNOWN_REASON_LABELS.get(reason, reason.replace("_", " "))


def not_counted_label(reason: str) -> str:
    return _NOT_COUNTED_LABELS.get(reason, reason.replace("_", " "))


def project_border_style(view: ProjectStatsView) -> str:
    if len(view.projects) == 1:
        keys = tuple(project.key for project in view.projects)
        return project_accent(view.projects[0].key, among=keys)
    return STATS_ACCENT


def square_glyph(ctx: RenderContext) -> str:
    return "■" if ctx.unicode else "*"


def sentinel_name(kind: str) -> str:
    return "?  model not recorded" if kind == "unknown" else "∅  no agent footer"


def sentinel_style(kind: str) -> str:
    return UNKNOWN_STYLE if kind == "unknown" else NO_AGENT_STYLE


def _provider_badge(provider: str | None, ctx: RenderContext) -> str:
    if not ctx.unicode or not provider:
        return ""
    badge = provider_emoji_badge(provider)
    return f"{badge} " if badge else ""


def provider_plain(provider: str | None, ctx: RenderContext) -> str:
    if not provider:
        return ""
    return f"{_provider_badge(provider, ctx)}{provider}"


def provider_style(provider: str | None) -> str:
    return provider_name_style(provider)


def bar_style_for(kind: str, provider: str | None) -> str:
    if kind == "unknown":
        return UNKNOWN_STYLE
    if kind == "no_agent":
        return NO_AGENT_STYLE
    return provider_bar_style(provider)


def _ensure_sentinel_models(
    rows: Sequence[ProjectStatsModel],
) -> tuple[ProjectStatsModel, ...]:
    kinds = {row.kind for row in rows}
    extra: list[ProjectStatsModel] = []
    if "unknown" not in kinds:
        extra.append(ProjectStatsModel(kind="unknown"))
    if "no_agent" not in kinds:
        extra.append(ProjectStatsModel(kind="no_agent"))
    return tuple(rows) + tuple(extra)


def _sum_models(
    rows: Sequence[ProjectStatsModel],
    *,
    kind: str,
    provider: str | None,
) -> ProjectStatsModel:
    def _add(values: Sequence[int | None]) -> int | None:
        known = [value for value in values if value is not None]
        return sum(known) if known else None

    return ProjectStatsModel(
        kind=kind,
        provider=provider,
        commits=sum(row.commits for row in rows),
        plans=_add([row.plans for row in rows]),
        plans_epic=_add([row.plans_epic for row in rows]),
        plans_tale=_add([row.plans_tale for row in rows]),
        unknown_reasons=tuple(
            sorted({reason for row in rows for reason in row.unknown_reasons})
        ),
    )


@dataclass(frozen=True, slots=True)
class ModelGroup:
    """One provider subtotal plus its model rows, or a ?/∅ sentinel."""

    kind: str
    provider: str | None
    total: ProjectStatsModel
    models: tuple[ProjectStatsModel, ...]

    @property
    def collapsed(self) -> bool:
        return self.kind == "resolved" and len(self.models) == 1

    @property
    def visible_models(self) -> tuple[ProjectStatsModel, ...]:
        if self.kind != "resolved" or self.collapsed:
            return ()
        return self.models[:_MAX_MODELS_PER_PROVIDER]

    @property
    def hidden_model_count(self) -> int:
        if self.kind != "resolved" or self.collapsed:
            return 0
        return max(0, len(self.models) - _MAX_MODELS_PER_PROVIDER)


def group_models(rows: Sequence[ProjectStatsModel]) -> tuple[ModelGroup, ...]:
    """Group resolved models by provider; keep ? and ∅ as trailing rows."""
    rows = _ensure_sentinel_models(rows)
    grouped: dict[str, list[ProjectStatsModel]] = {}
    unknown: list[ProjectStatsModel] = []
    none: list[ProjectStatsModel] = []
    for row in rows:
        if row.kind == "unknown":
            unknown.append(row)
        elif row.kind == "no_agent":
            none.append(row)
        else:
            grouped.setdefault(row.provider or "?", []).append(row)
    result: list[ModelGroup] = []
    for provider, models in grouped.items():
        ordered = tuple(
            sorted(models, key=lambda row: (-row.commits, row.model or "", row.kind))
        )
        result.append(
            ModelGroup(
                kind="resolved",
                provider=provider,
                total=_sum_models(ordered, kind="resolved", provider=provider),
                models=ordered,
            )
        )
    result.sort(key=lambda group: (-group.total.commits, group.provider or ""))
    result.append(
        ModelGroup(
            kind="unknown",
            provider=None,
            total=_sum_models(unknown, kind="unknown", provider=None),
            models=tuple(unknown),
        )
    )
    result.append(
        ModelGroup(
            kind="no_agent",
            provider=None,
            total=_sum_models(none, kind="no_agent", provider=None),
            models=tuple(none),
        )
    )
    return tuple(result)


def display_models(view: ProjectStatsView) -> tuple[ProjectStatsModel, ...]:
    if len(view.projects) == 1:
        return view.projects[0].models
    return view.models


def fetched_at(view: ProjectStatsView) -> int | None:
    stamps = [
        repo.ref.fetched_at
        for project in view.projects
        for repo in project.repos
        if repo.ref is not None and repo.ref.fetched_at is not None
    ]
    return max(stamps) if stamps else None

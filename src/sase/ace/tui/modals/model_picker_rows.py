"""Typed rows and catalog construction for the model picker."""

from dataclasses import dataclass
from typing import Literal

from rich.text import Text

from sase.ace.tui.provider_styles import provider_model_badge_markup
from sase.llm_provider import AliasView
from sase.llm_provider.config import normalize_model_alias_reference

# Sentinel returned when user selects "Custom..."
CUSTOM_SENTINEL = "__custom__"
# Sentinel returned when the user selects "Pool / fallback..." — only offered
# when the caller opts in with ``include_selector_option`` (the persistent
# Edit path). Selectors are config-only, so the Override picker never sets it.
SELECTOR_SENTINEL = "__selector__"
# Returned when the user selects "Follow-up default" and the caller opted
# into ``distinct_default``. By default this row dismisses with ``None`` (the
# same as cancel); callers that need to tell "use the follow-up default" apart
# from a cancel pass ``distinct_default=True`` to receive this sentinel.
DEFAULT_SENTINEL = "__default__"
_EMPTY_SENTINEL = "__empty__"

AliasSelectionOperation = Literal["persistent", "temporary", "member"]
_RowKind = Literal[
    "alias_header",
    "alias",
    "default",
    "provider",
    "model",
    "custom",
    "selector",
    "empty",
]

_ALIAS_HEADER_SENTINEL = "__header_aliases__"
_ALIAS_NAME_CELL = 22
_ALIAS_TARGET_CELL = 27


@dataclass(frozen=True)
class AliasSelectionContext:
    """Opt-in alias catalog and safety semantics for a Models-panel picker."""

    views: tuple[AliasView, ...]
    target_alias: str
    operation: AliasSelectionOperation


@dataclass(frozen=True)
class ModelPickerRow:
    kind: _RowKind
    label: str
    option_id: str
    provider: str | None = None
    model_id: str | None = None
    alias: str | None = None
    model_count: int | None = None
    alias_name: str | None = None
    alias_kind: str | None = None
    description: str | None = None
    disabled_reason: str | None = None
    rendered_label: Text | None = None
    advisory_label: str | None = None
    advisory_severity: str | None = None

    @property
    def disabled(self) -> bool:
        return self.kind in {"alias_header", "provider", "empty"} or (
            self.disabled_reason is not None
        )

    @property
    def is_model(self) -> bool:
        return self.kind == "model"

    @property
    def is_target(self) -> bool:
        return self.kind in {"alias", "model"}

    @property
    def search_terms(self) -> tuple[str, ...]:
        return tuple(
            part.lower()
            for part in (
                self.provider,
                self.provider.upper() if self.provider else None,
                self.model_id,
                self.label,
                self.alias,
                self.alias_name,
                f"@{self.alias_name}" if self.alias_name else None,
                self.alias_kind,
                self.description,
                self.rendered_label.plain if self.rendered_label else None,
                self.disabled_reason,
                self.advisory_label,
            )
            if part
        )


def _alias_dependencies(views: tuple[AliasView, ...]) -> dict[str, str]:
    """Return the immediate known dependency edge for each alias snapshot row."""
    known = {view.name for view in views}
    dependencies: dict[str, str] = {}
    for view in views:
        dependency = view.references or view.implicit_fallback
        if dependency in known:
            dependencies[view.name] = dependency
    return dependencies


def _selector_reach_reason(view: AliasView) -> str | None:
    """Return why *view* is unsafe as a selector member, or ``None``."""
    if view.selector_mode is None:
        return None
    return (
        "reaches a pool"
        if view.selector_mode == "round_robin"
        else "reaches a fallback"
    )


def _alias_disabled_reason(
    context: AliasSelectionContext,
    candidate: str,
) -> str | None:
    """Classify whether selecting *candidate* is unsafe for this operation."""
    target = context.target_alias.strip()
    if candidate == target:
        return "current alias"
    if context.operation == "temporary":
        return None

    views_by_name = {view.name: view for view in context.views}
    dependencies = _alias_dependencies(context.views)
    current = candidate
    visited: set[str] = set()
    # There can be at most one useful visit per known alias. The explicit
    # bound makes malformed snapshots safe even if this helper changes later.
    for _ in range(len(context.views) + 1):
        if current == target:
            return "would create a cycle"
        if current in visited:
            return "would create a cycle"
        visited.add(current)
        if context.operation == "member":
            view = views_by_name.get(current)
            if view is not None:
                reason = _selector_reach_reason(view)
                if reason is not None:
                    return reason
        dependency = dependencies.get(current)
        if dependency is None:
            return None
        current = dependency
    return "would create a cycle"


def alias_reference_rejection(
    context: AliasSelectionContext | None,
    value: str,
) -> str | None:
    """Return a concise rejection reason for a free-form ``@alias`` value."""
    cleaned = value.strip()
    if context is None or not cleaned.startswith("@"):
        return None
    alias, _ = normalize_model_alias_reference(cleaned)
    known = {view.name for view in context.views}
    if not alias or alias not in known:
        return "unknown alias"
    return _alias_disabled_reason(context, alias)


def _alias_row_text(
    view: AliasView,
    *,
    operation: AliasSelectionOperation,
    disabled_reason: str | None,
) -> Text:
    """Build the immutable styled body for one alias option row."""
    text = Text(no_wrap=True, overflow="ellipsis")
    alias_token = f"@{view.name}"
    if len(alias_token) > _ALIAS_NAME_CELL:
        alias_token = alias_token[: _ALIAS_NAME_CELL - 1] + "…"
    text.append(alias_token.ljust(_ALIAS_NAME_CELL), style="bold #87D7FF")
    text.append("  →  ", style="dim #5F8787")
    badge = Text.from_markup(provider_model_badge_markup(view.provider, view.model))
    badge.truncate(_ALIAS_TARGET_CELL, overflow="ellipsis", pad=True)
    text.append_text(badge)
    text.append("  ")
    if disabled_reason is not None:
        text.append(disabled_reason, style="bold #FF875F")
    else:
        semantic = "snapshot" if operation == "temporary" else "dynamic ref"
        if view.override is not None:
            semantic = f"override now · {semantic}"
        text.append(semantic, style="dim #A8A8A8")
    return text


def _build_alias_rows(context: AliasSelectionContext) -> list[ModelPickerRow]:
    """Build alias rows once from the Models panel's in-memory snapshot."""
    if not context.views:
        return []
    rows = [
        ModelPickerRow(
            kind="alias_header",
            label=f"  ALIASES  {len(context.views)} aliases",
            option_id=_ALIAS_HEADER_SENTINEL,
            model_count=len(context.views),
        )
    ]
    for view in context.views:
        disabled_reason = _alias_disabled_reason(context, view.name)
        rows.append(
            ModelPickerRow(
                kind="alias",
                label=f"@{view.name}",
                option_id=f"@{view.name}",
                provider=view.provider,
                model_id=view.model,
                alias_name=view.name,
                alias_kind=view.kind,
                description=view.description,
                disabled_reason=disabled_reason,
                rendered_label=_alias_row_text(
                    view,
                    operation=context.operation,
                    disabled_reason=disabled_reason,
                ),
            )
        )
    return rows


def build_model_rows(
    *,
    include_default_option: bool = True,
    alias_context: AliasSelectionContext | None = None,
    include_selector_option: bool = False,
) -> list[ModelPickerRow]:
    """Build typed model-picker rows grouped by provider."""
    from sase.llm_provider.registry import (
        model_advisory_map,
        model_advisory_marker,
        model_picker_hidden_provider_names,
        model_short_alias_map,
        model_to_provider_map,
    )

    aliases = model_short_alias_map()
    advisories = model_advisory_map()
    hidden_providers = model_picker_hidden_provider_names()
    provider_models: dict[str, list[str]] = {}
    for model, provider in model_to_provider_map().items():
        if provider in hidden_providers:
            continue
        provider_models.setdefault(provider, []).append(model)

    rows: list[ModelPickerRow] = []
    if include_default_option:
        rows.append(
            ModelPickerRow(
                kind="default",
                label="Follow-up default",
                option_id=DEFAULT_SENTINEL,
            )
        )

    for provider, models in provider_models.items():
        rows.append(
            ModelPickerRow(
                kind="provider",
                label=f"  {provider.upper()}  {len(models)} models",
                option_id=f"__header_{provider}__",
                provider=provider,
                model_count=len(models),
            )
        )
        for model in models:
            alias = aliases.get(model)
            label = f"    {model}"
            if alias:
                label = f"{label}  ({alias})"
            # This is where somebody actually chooses a model, so an advisory
            # rides on the row itself and its full sentence becomes the row's
            # secondary text (which also makes it searchable).
            advisory = advisories.get(model) or {}
            advisory_label = advisory.get("label") or None
            if advisory_label:
                marker = model_advisory_marker(advisory.get("severity"))
                label = f"{label}  {marker} {advisory_label}"
            rows.append(
                ModelPickerRow(
                    kind="model",
                    label=label,
                    option_id=model,
                    provider=provider,
                    model_id=model,
                    alias=alias,
                    description=advisory.get("detail") or None,
                    advisory_label=advisory_label,
                    advisory_severity=(
                        advisory.get("severity") if advisory_label else None
                    ),
                )
            )

    if alias_context is not None:
        rows.extend(_build_alias_rows(alias_context))

    if include_selector_option:
        rows.append(
            ModelPickerRow(
                kind="selector",
                label="  Pool / fallback...",
                option_id=SELECTOR_SENTINEL,
            )
        )
    rows.append(
        ModelPickerRow(
            kind="custom",
            label="  Custom...",
            option_id=CUSTOM_SENTINEL,
        )
    )
    return rows

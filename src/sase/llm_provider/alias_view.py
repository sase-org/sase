"""Aggregated, display-ready view of every model alias.

A small, pure helper that flattens the model-alias policy
(:mod:`sase.llm_provider.config`), the live alias resolution
(:func:`resolve_model_alias` / :func:`resolve_model_provider`), and the active
per-alias temporary overrides (:mod:`sase.llm_provider.temporary_override`) into
one deterministically-ordered list of :class:`AliasView` rows.

This is the data layer behind the ace **Models** panel (leader ``,m``): it knows
nothing about Textual or rendering, so it is cheaply unit-testable and reusable
by any future (CLI/web) surface. Each row carries the alias name, its kind
(``role`` / ``user``), whether it is
explicitly configured (vs. an implicit special), the raw configured value if
any, the *currently effective* provider/model (an active temporary override
wins), and the active override itself when present.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal, cast

from .config import (
    LARGE_MODEL_ALIAS_NAME,
    MEDIUM_MODEL_ALIAS_NAME,
    SMALL_MODEL_ALIAS_NAME,
    XLARGE_MODEL_ALIAS_NAME,
    XSMALL_MODEL_ALIAS_NAME,
    ModelAliasSelectorMember,
    get_model_aliases,
    implicit_model_alias_fallback,
    implicit_model_alias_fallback_effort,
    implicit_model_alias_value,
    model_alias_bucket,
    model_alias_bucket_description,
    model_alias_config_source,
    model_alias_description,
    model_alias_kind,
    model_alias_names,
    model_alias_selector_details,
    normalize_model_alias_reference,
)
from .load_balancing import ModelAliasSelectorMode
from .provider_disable import TemporaryProviderDisable
from .temporary_override import TemporaryLLMOverride, get_active_alias_overrides

#: The kind of an alias, used for badge styling and grouping.
AliasKind = Literal["role", "user"]

#: Canonical display order for built-in size aliases.
_ROLE_ALIAS_ORDER: tuple[str, ...] = (
    XSMALL_MODEL_ALIAS_NAME,
    SMALL_MODEL_ALIAS_NAME,
    MEDIUM_MODEL_ALIAS_NAME,
    LARGE_MODEL_ALIAS_NAME,
    XLARGE_MODEL_ALIAS_NAME,
)

#: There are no built-in Launch Control buckets in the compact alias contract.
BUILTIN_MODEL_ALIAS_BUCKET_NAMES: frozenset[str] = frozenset()


@dataclass(frozen=True)
class AliasView:
    """A single display-ready model-alias row.

    Attributes:
        name: The bare alias name (no ``@`` marker).
        kind: ``role`` / ``user``.
        configured: ``True`` when ``name`` is an explicit
            ``llm_provider.model_aliases.builtin`` or
            ``llm_provider.model_aliases.custom`` entry (vs. an implicit
            special).
        configured_value: The raw configured target string, or ``None`` for an
            implicit alias.
        configured_source: The config map providing ``configured_value``, or
            ``None`` for an implicit alias.
        description: The fixed builtin or user-configured alias description, if
            one is known.
        provider: The currently-effective provider name, or ``None`` when the
            target is a bare/unknown model that runs on the default provider.
        model: The currently-effective model name.
        effort: The alias-borne reasoning effort, or ``None`` when the alias
            does not override the configured/provider default.
        override: The active temporary override for this alias, or ``None``.
        bucket: The optional Launch Control bucket for a custom alias.
        reference_effort: Effort overlay carried by the row's immediate
            ``@name`` reference, or ``None`` for a concrete pinned target.
        implicit_value: Raw concrete/selector value supplied by an implicit alias.
        selector_mode: ``round_robin`` or ``fallback`` when the alias owns a
            selector expression.
        selector_members: Parsed/resolved member, availability, and selection
            details for an owned selector expression.
    """

    name: str
    kind: AliasKind
    configured: bool
    configured_value: str | None
    provider: str | None
    model: str
    override: TemporaryLLMOverride | None
    configured_source: str | None = None
    description: str | None = None
    bucket: str | None = None
    implicit_value: str | None = None
    selector_mode: ModelAliasSelectorMode | None = None
    selector_members: tuple[ModelAliasSelectorMember, ...] = ()
    effort: str | None = None
    override_paused_by_provider_disable: TemporaryProviderDisable | None = None

    @property
    def is_overridden(self) -> bool:
        """Whether a temporary override is currently shaping this alias."""
        return self.override is not None and not self.is_override_paused

    @property
    def is_override_paused(self) -> bool:
        """Whether a stored override is suspended by provider-disable state."""
        return self.override_paused_by_provider_disable is not None

    @property
    def is_custom_builtin_shadow(self) -> bool:
        """Whether a custom entry is shadowing this builtin alias.

        Alias kind is the centralized builtin classification used throughout
        the model-alias policy.  Keeping the predicate on the display snapshot
        lets presentation surfaces warn without re-reading configuration or
        maintaining a second list of builtin names.
        """
        return self.configured_source == "custom" and self.kind != "user"

    @property
    def is_user_owned(self) -> bool:
        """Whether this alias exists because the user defined it."""
        return is_user_owned(self)

    @property
    def references(self) -> str | None:
        """Return the immediate alias referenced by the configured value."""
        if self.configured_value is None:
            return None
        alias, _ = normalize_model_alias_reference(self.configured_value)
        return alias

    @property
    def raw_value(self) -> str | None:
        """Return the configured or implicit raw alias target value."""
        return self.configured_value or self.implicit_value

    @property
    def implicit_fallback(self) -> str | None:
        """Return the immediate fallback for an unconfigured implicit alias."""
        if self.configured:
            return None
        return implicit_model_alias_fallback(self.name)

    @property
    def reference_effort(self) -> str | None:
        """Return the effort overlay carried by the immediate alias reference."""
        if self.configured:
            if self.configured_value is None:
                return None
            alias, effort = normalize_model_alias_reference(self.configured_value)
            return effort if alias is not None else None
        return implicit_model_alias_fallback_effort(self.name)


@dataclass(frozen=True)
class BucketView:
    """A collapsed Launch Control bucket containing builtin and/or custom rows."""

    name: str
    description: str | None
    members: tuple[AliasView, ...]

    @property
    def alias_count(self) -> int:
        """Return the number of member aliases."""
        return len(self.members)

    @property
    def is_user_owned(self) -> bool:
        """Whether this bucket exists because the user defined it."""
        return is_user_owned(self)

    @property
    def user_member_count(self) -> int:
        """Return the number of user-owned aliases folded into this bucket."""
        return sum(member.is_user_owned for member in self.members)

    @property
    def override_count(self) -> int:
        """Return the number of members with an active temporary override."""
        return sum(member.is_overridden for member in self.members)

    @property
    def paused_override_count(self) -> int:
        """Return the number of members with a suspended temporary override."""
        return sum(member.is_override_paused for member in self.members)

    @property
    def custom_builtin_shadow_names(self) -> tuple[str, ...]:
        """Return member names whose custom entries shadow builtin aliases."""
        return tuple(
            member.name for member in self.members if member.is_custom_builtin_shadow
        )

    @property
    def custom_builtin_shadow_count(self) -> int:
        """Return the number of misplaced builtin aliases in this bucket."""
        return len(self.custom_builtin_shadow_names)

    @staticmethod
    def _model_label(member: AliasView) -> str:
        label = f"{member.provider}/{member.model}" if member.provider else member.model
        return f"{label}@{member.effort}" if member.effort else label

    @property
    def model_counts(self) -> tuple[tuple[str, int], ...]:
        """Return distinct effective models ordered by count, then name."""
        counts = Counter(self._model_label(member) for member in self.members)
        return tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))

    @property
    def model_summary(self) -> str:
        """Return the dominant effective model plus the other-distinct count."""
        if not self.model_counts:
            return ""
        dominant = self.model_counts[0][0]
        other_count = len(self.model_counts) - 1
        return f"{dominant} +{other_count}" if other_count else dominant


ModelsPanelRow = AliasView | BucketView
ModelsPanelOwnership = Literal["builtin", "user"]


@dataclass(frozen=True)
class ModelsPanelSection:
    """One ownership section in an ordered Launch Control row partition."""

    ownership: ModelsPanelOwnership
    rows: tuple[ModelsPanelRow, ...]
    alias_count: int
    bucket_count: int

    @property
    def is_user_owned(self) -> bool:
        """Whether this is the user-owned section."""
        return self.ownership == "user"


def is_user_owned(row: ModelsPanelRow) -> bool:
    """Return the centralized Launch Control ownership classification for *row*.

    Alias ownership follows the semantic alias kind, never its config-map
    location. Bucket ownership follows whether the bucket name is part of the
    built-in display contract.
    """
    if isinstance(row, AliasView):
        return row.kind == "user"
    return row.name not in BUILTIN_MODEL_ALIAS_BUCKET_NAMES


def _section(
    ownership: ModelsPanelOwnership,
    rows: Iterable[ModelsPanelRow],
) -> ModelsPanelSection:
    """Build count metadata for one already-partitioned row sequence."""
    ordered = tuple(rows)
    return ModelsPanelSection(
        ownership=ownership,
        rows=ordered,
        alias_count=sum(
            row.alias_count if isinstance(row, BucketView) else 1 for row in ordered
        ),
        bucket_count=sum(isinstance(row, BucketView) for row in ordered),
    )


def split_models_panel_rows(
    rows: Iterable[ModelsPanelRow],
) -> tuple[ModelsPanelSection, ModelsPanelSection]:
    """Partition ordered panel rows into built-in and user-owned sections.

    Relative order is preserved within both sections. The current Launch Control
    order already places user-owned rows last, so concatenating the returned
    row tuples reproduces the input exactly.
    """
    builtin: list[ModelsPanelRow] = []
    user: list[ModelsPanelRow] = []
    for row in rows:
        (user if is_user_owned(row) else builtin).append(row)
    return _section("builtin", builtin), _section("user", user)


def split_bucket_members(
    bucket: BucketView,
) -> tuple[ModelsPanelSection, ModelsPanelSection]:
    """Return the ownership split for the ordered members of *bucket*."""
    return split_models_panel_rows(bucket.members)


def _alias_kind(name: str) -> AliasKind:
    """Classify *name* into its display kind (see :func:`model_alias_kind`)."""
    return cast("AliasKind", model_alias_kind(name))


def _sort_key(view: AliasView) -> tuple[int, int, str]:
    """Deterministic ordering: built-in size aliases, then user aliases.

    Built-in aliases follow :data:`_ROLE_ALIAS_ORDER`; user aliases sort
    alphabetically by name.
    """
    if view.kind == "role":
        try:
            role_index = _ROLE_ALIAS_ORDER.index(view.name)
        except ValueError:
            role_index = len(_ROLE_ALIAS_ORDER)
        return (0, role_index, view.name)
    return (1, 0, view.name)


def _effective_provider_model(
    name: str,
    override: TemporaryLLMOverride | None,
    provider_disables: Mapping[str, TemporaryProviderDisable],
) -> tuple[str | None, str, str | None]:
    """Return the currently-effective provider, model, and effort for *name*.

    An active temporary override always wins (this is what the panel and the
    top-bar pill show); otherwise the configured/implicit alias chain is
    resolved and split into a provider/model pair. Only a *hard* disable on
    the override's provider bypasses it — a soft disable keeps the override
    applying.
    """
    override_disable = (
        provider_disables.get(override.provider) if override is not None else None
    )
    if override is not None and (override_disable is None or override_disable.is_soft):
        return override.provider, override.model, override.effort

    # Lazy import to avoid an import cycle: registry imports this package's
    # config at import time.
    from .registry import resolve_model_provider_with_effort

    return resolve_model_provider_with_effort(
        name,
        provider_disables=provider_disables,
    )


def selector_member_provider_model_effort(
    member: ModelAliasSelectorMember,
) -> tuple[str | None, str, str | None]:
    """Return display fields derived from one already-resolved selector member."""
    model = member.target
    if member.provider is not None:
        prefix = f"{member.provider}/"
        if model.startswith(prefix):
            model = model[len(prefix) :]
    return member.provider, model, member.effort


def build_alias_views(
    now: float | None = None,
    *,
    overrides: Mapping[str, TemporaryLLMOverride] | None = None,
    provider_disables: Mapping[str, TemporaryProviderDisable] | None = None,
) -> list[AliasView]:
    """Aggregate every model alias into ordered, display-ready rows.

    Combines the alias policy (:func:`model_alias_names`,
    :func:`get_model_aliases`), live resolution (:func:`resolve_model_alias` /
    ``resolve_model_provider``), and active temporary overrides
    (:func:`get_active_alias_overrides`). The result is sorted with the five
    built-in size aliases first, then user-defined aliases alphabetically.

    Args:
        now: Optional fixed timestamp forwarded to the override loader (lets
            tests pin expiry); ``None`` uses the wall clock.
        overrides: Optional already-loaded temporary overrides. ``None`` keeps
            the authoritative self-cleaning load used by Launch Control;
            an explicit mapping, including ``{}``, is consumed verbatim.
    """
    names = model_alias_names()
    configured = get_model_aliases()
    active_overrides = (
        get_active_alias_overrides(now) if overrides is None else overrides
    )
    active_provider_disables: Mapping[str, TemporaryProviderDisable]
    if provider_disables is None:
        from .provider_disable import get_active_provider_disables

        active_provider_disables = get_active_provider_disables(now)
    else:
        active_provider_disables = provider_disables

    views: list[AliasView] = []
    for name in names:
        override = active_overrides.get(name)
        selector = model_alias_selector_details(
            name,
            provider_disables=active_provider_disables,
        )
        selected_member = (
            next((member for member in selector.members if member.selected), None)
            if selector is not None
            else None
        )
        if override is None and selected_member is not None:
            provider, model, effort = selector_member_provider_model_effort(
                selected_member
            )
        else:
            provider, model, effort = _effective_provider_model(
                name,
                override,
                active_provider_disables,
            )
        paused_disable = (
            active_provider_disables.get(override.provider)
            if override is not None
            else None
        )
        if paused_disable is not None and paused_disable.is_soft:
            paused_disable = None
        views.append(
            AliasView(
                name=name,
                kind=_alias_kind(name),
                configured=name in configured,
                configured_value=configured.get(name),
                provider=provider,
                model=model,
                override=override,
                configured_source=model_alias_config_source(name),
                description=model_alias_description(name),
                bucket=model_alias_bucket(name),
                implicit_value=implicit_model_alias_value(name),
                selector_mode=selector.mode if selector is not None else None,
                selector_members=selector.members if selector is not None else (),
                effort=effort,
                override_paused_by_provider_disable=paused_disable,
            )
        )

    views.sort(key=_sort_key)
    return views


def build_models_panel_rows(
    views: list[AliasView] | None = None,
) -> list[AliasView | BucketView]:
    """Fold user-owned aliases into custom bucket rows."""
    source = sorted(build_alias_views() if views is None else views, key=_sort_key)
    top_rows: list[AliasView | BucketView] = [
        view for view in source if view.kind != "user"
    ]

    user = [view for view in source if view.kind == "user"]

    members_by_bucket: dict[str, list[AliasView]] = {}
    ungrouped: list[AliasView] = []
    for view in user:
        if view.bucket:
            members_by_bucket.setdefault(view.bucket, []).append(view)
        else:
            ungrouped.append(view)

    buckets = [
        BucketView(
            name=name,
            description=model_alias_bucket_description(name),
            members=tuple(sorted(members, key=lambda member: member.name)),
        )
        for name, members in sorted(members_by_bucket.items())
    ]
    return [
        *top_rows,
        *buckets,
        *sorted(ungrouped, key=lambda view: view.name),
    ]


__all__ = [
    "AliasKind",
    "AliasView",
    "BUILTIN_MODEL_ALIAS_BUCKET_NAMES",
    "BucketView",
    "ModelsPanelOwnership",
    "ModelsPanelRow",
    "ModelsPanelSection",
    "build_alias_views",
    "build_models_panel_rows",
    "is_user_owned",
    "selector_member_provider_model_effort",
    "split_bucket_members",
    "split_models_panel_rows",
]

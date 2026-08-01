"""Aggregated, display-ready view of every model alias.

A small, pure helper that flattens the model-alias policy
(:mod:`sase.llm_provider.config`), the live alias resolution
(:func:`resolve_model_alias` / :func:`resolve_model_provider`), and the active
per-alias temporary overrides (:mod:`sase.llm_provider.temporary_override`) into
one deterministically-ordered list of :class:`AliasView` rows.

This is the data layer behind the ace **Models** panel (leader ``,m``): it knows
nothing about Textual or rendering, so it is cheaply unit-testable and reusable
by any future (CLI/web) surface. Each row carries the alias name, its kind
(``default`` / ``role`` / ``provider_coder`` / ``user``), whether it is
explicitly configured (vs. an implicit special), the raw configured value if
any, the *currently effective* provider/model (an active temporary override
wins), and the active override itself when present.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Literal, cast

from .config import (
    BIG_EPIC_LANDER_MODEL_ALIAS_NAME,
    CHEAP_MODEL_ALIAS_NAME,
    CHEAPER_MODEL_ALIAS_NAME,
    CHEAPEST_MODEL_ALIAS_NAME,
    CODER_MODEL_ALIAS_NAME,
    DEFAULT_MODEL_ALIAS_NAME,
    EPIC_LANDER_MODEL_ALIAS_NAME,
    LARGE_PHASE_WORKER_MODEL_ALIAS_NAME,
    MEDIUM_PHASE_WORKER_MODEL_ALIAS_NAME,
    SMALL_PHASE_WORKER_MODEL_ALIAS_NAME,
    SMART_MODEL_ALIAS_NAME,
    SMARTEST_MODEL_ALIAS_NAME,
    XLARGE_PHASE_WORKER_MODEL_ALIAS_NAME,
    XSMALL_PHASE_WORKER_MODEL_ALIAS_NAME,
    ModelAliasSelectorMember,
    coder_model_alias_for_provider,
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
from .temporary_override import TemporaryLLMOverride, get_active_alias_overrides

#: The kind of an alias, used for badge styling and grouping.
AliasKind = Literal["default", "role", "provider_coder", "user"]

#: Canonical display order for the implicit role aliases (after ``default``).
_ROLE_ALIAS_ORDER: tuple[str, ...] = (
    CODER_MODEL_ALIAS_NAME,
    EPIC_LANDER_MODEL_ALIAS_NAME,
    BIG_EPIC_LANDER_MODEL_ALIAS_NAME,
    XSMALL_PHASE_WORKER_MODEL_ALIAS_NAME,
    SMALL_PHASE_WORKER_MODEL_ALIAS_NAME,
    MEDIUM_PHASE_WORKER_MODEL_ALIAS_NAME,
    LARGE_PHASE_WORKER_MODEL_ALIAS_NAME,
    XLARGE_PHASE_WORKER_MODEL_ALIAS_NAME,
    SMARTEST_MODEL_ALIAS_NAME,
    SMART_MODEL_ALIAS_NAME,
    CHEAP_MODEL_ALIAS_NAME,
    CHEAPER_MODEL_ALIAS_NAME,
    CHEAPEST_MODEL_ALIAS_NAME,
)

#: Built-in Models-panel bucket for the generic and provider-specific coder roles.
CODERS_BUCKET_NAME = "coders"

#: Description used when config does not provide metadata for :data:`CODERS_BUCKET_NAME`.
CODERS_BUCKET_DESCRIPTION = (
    "Generic coder default and planner-provider-specific coder follow-up aliases."
)

#: Built-in Models-panel bucket for the five size-specific phase roles.
PHASE_WORKER_BUCKET_NAME = "phase_worker"

#: Description used when config does not override the phase-worker bucket.
PHASE_WORKER_BUCKET_DESCRIPTION = "Size-specific phase-agent aliases."

#: Built-in bucket names accepted by doctor even without custom members.
BUILTIN_MODEL_ALIAS_BUCKET_NAMES = frozenset(
    {CODERS_BUCKET_NAME, PHASE_WORKER_BUCKET_NAME}
)


@dataclass(frozen=True)
class _BuiltinBucketSpec:
    """Display policy for one always-present Models-panel bucket."""

    name: str
    description: str
    fixed_members: tuple[str, ...]


_BUILTIN_BUCKET_SPECS: tuple[_BuiltinBucketSpec, ...] = (
    _BuiltinBucketSpec(
        name=CODERS_BUCKET_NAME,
        description=CODERS_BUCKET_DESCRIPTION,
        fixed_members=(CODER_MODEL_ALIAS_NAME,),
    ),
    _BuiltinBucketSpec(
        name=PHASE_WORKER_BUCKET_NAME,
        description=PHASE_WORKER_BUCKET_DESCRIPTION,
        fixed_members=(
            XSMALL_PHASE_WORKER_MODEL_ALIAS_NAME,
            SMALL_PHASE_WORKER_MODEL_ALIAS_NAME,
            MEDIUM_PHASE_WORKER_MODEL_ALIAS_NAME,
            LARGE_PHASE_WORKER_MODEL_ALIAS_NAME,
            XLARGE_PHASE_WORKER_MODEL_ALIAS_NAME,
        ),
    ),
)


@dataclass(frozen=True)
class AliasView:
    """A single display-ready model-alias row.

    Attributes:
        name: The bare alias name (no ``@`` marker).
        kind: ``default`` / ``role`` / ``provider_coder`` / ``user``.
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
        bucket: The optional Models-panel bucket for a custom alias.
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

    @property
    def is_overridden(self) -> bool:
        """Whether a temporary override is currently shaping this alias."""
        return self.override is not None

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
    """A collapsed Models-panel bucket containing builtin and/or custom rows."""

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
    """One ownership section in an ordered Models-panel row partition."""

    ownership: ModelsPanelOwnership
    rows: tuple[ModelsPanelRow, ...]
    alias_count: int
    bucket_count: int

    @property
    def is_user_owned(self) -> bool:
        """Whether this is the user-owned section."""
        return self.ownership == "user"


def is_user_owned(row: ModelsPanelRow) -> bool:
    """Return the centralized Models-panel ownership classification for *row*.

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

    Relative order is preserved within both sections. The current Models-panel
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
    """Deterministic ordering: default, role, ``<provider>_coder``, then user.

    Role aliases follow :data:`_ROLE_ALIAS_ORDER`; the other groups sort
    alphabetically by name.
    """
    if view.kind == "default":
        return (0, 0, "")
    if view.kind == "role":
        try:
            role_index = _ROLE_ALIAS_ORDER.index(view.name)
        except ValueError:
            role_index = len(_ROLE_ALIAS_ORDER)
        return (1, role_index, view.name)
    if view.kind == "provider_coder":
        return (2, 0, view.name)
    return (3, 0, view.name)


def _effective_provider_model(
    name: str,
    override: TemporaryLLMOverride | None,
) -> tuple[str | None, str, str | None]:
    """Return the currently-effective provider, model, and effort for *name*.

    An active temporary override always wins (this is what the panel and the
    top-bar pill show); otherwise the configured/implicit alias chain is
    resolved and split into a provider/model pair.
    """
    if override is not None:
        return override.provider, override.model, override.effort

    # Lazy import to avoid an import cycle: registry imports this package's
    # config at import time.
    from .registry import resolve_model_provider_with_effort

    return resolve_model_provider_with_effort(name)


def _selector_member_provider_model_effort(
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
) -> list[AliasView]:
    """Aggregate every model alias into ordered, display-ready rows.

    Combines the alias policy (:func:`model_alias_names`,
    :func:`get_model_aliases`), live resolution (:func:`resolve_model_alias` /
    ``resolve_model_provider``), and active temporary overrides
    (:func:`get_active_alias_overrides`). The result is sorted with ``default``
    first, then the other role aliases, then ``<provider>_coder`` aliases, then
    user-defined aliases alphabetically.

    Args:
        now: Optional fixed timestamp forwarded to the override loader (lets
            tests pin expiry); ``None`` uses the wall clock.
        overrides: Optional already-loaded temporary overrides. ``None`` keeps
            the authoritative self-cleaning load used by the Models panel;
            an explicit mapping, including ``{}``, is consumed verbatim.
    """
    names = model_alias_names()
    configured = get_model_aliases()
    active_overrides = (
        get_active_alias_overrides(now) if overrides is None else overrides
    )

    # Lazy import to avoid an import cycle: registry imports this package's
    # config at import time.
    from .registry import model_picker_hidden_provider_names

    hidden_provider_coder_aliases = {
        coder_model_alias_for_provider(provider)
        for provider in model_picker_hidden_provider_names()
    }

    views: list[AliasView] = []
    for name in names:
        if name in hidden_provider_coder_aliases and name not in configured:
            continue
        override = active_overrides.get(name)
        selector = model_alias_selector_details(name)
        selected_member = (
            next((member for member in selector.members if member.selected), None)
            if selector is not None
            else None
        )
        if override is None and selected_member is not None:
            provider, model, effort = _selector_member_provider_model_effort(
                selected_member
            )
        else:
            provider, model, effort = _effective_provider_model(name, override)
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
            )
        )

    views.sort(key=_sort_key)
    return views


def build_models_panel_rows(
    views: list[AliasView] | None = None,
) -> list[AliasView | BucketView]:
    """Fold related aliases into top-level Models-panel bucket rows.

    Built-in role families form always-present ``coders`` and ``phase_worker``
    buckets, with custom aliases that name either bucket coalesced after the
    built-in members. Other custom bucket rows come first alphabetically in the
    user region, followed by ungrouped aliases alphabetically. Bucket metadata
    without any member aliases intentionally produces no row.
    """
    source = sorted(build_alias_views() if views is None else views, key=_sort_key)
    specs_by_name = {spec.name: spec for spec in _BUILTIN_BUCKET_SPECS}

    def builtin_bucket_for_alias(view: AliasView) -> str | None:
        if view.name == CODER_MODEL_ALIAS_NAME or view.kind == "provider_coder":
            return CODERS_BUCKET_NAME
        if view.name in specs_by_name[PHASE_WORKER_BUCKET_NAME].fixed_members:
            return PHASE_WORKER_BUCKET_NAME
        return None

    builtin_members: dict[str, list[AliasView]] = {
        spec.name: [] for spec in _BUILTIN_BUCKET_SPECS
    }
    for view in source:
        bucket_name = builtin_bucket_for_alias(view)
        if bucket_name is None and view.kind == "user":
            bucket_name = view.bucket
        if bucket_name in BUILTIN_MODEL_ALIAS_BUCKET_NAMES:
            builtin_members[bucket_name].append(view)

    def builtin_member_sort_key(
        bucket_name: str, view: AliasView
    ) -> tuple[int, int, str]:
        spec = specs_by_name[bucket_name]
        try:
            return (0, spec.fixed_members.index(view.name), view.name)
        except ValueError:
            if bucket_name == CODERS_BUCKET_NAME and view.kind == "provider_coder":
                return (1, 0, view.name)
            return (2, 0, view.name)

    builtin_buckets = {
        spec.name: BucketView(
            name=spec.name,
            description=(model_alias_bucket_description(spec.name) or spec.description),
            members=tuple(
                sorted(
                    builtin_members[spec.name],
                    key=partial(builtin_member_sort_key, spec.name),
                )
            ),
        )
        for spec in _BUILTIN_BUCKET_SPECS
    }

    top_rows: list[AliasView | BucketView] = []
    emitted_builtin_buckets: set[str] = set()
    for view in source:
        bucket_name = builtin_bucket_for_alias(view)
        if bucket_name is not None:
            if bucket_name not in emitted_builtin_buckets:
                top_rows.append(builtin_buckets[bucket_name])
                emitted_builtin_buckets.add(bucket_name)
            continue
        if view.kind != "user":
            top_rows.append(view)

    user = [
        view
        for view in source
        if view.kind == "user" and view.bucket not in BUILTIN_MODEL_ALIAS_BUCKET_NAMES
    ]

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

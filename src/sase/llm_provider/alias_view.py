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
from dataclasses import dataclass
from typing import Literal, cast

from .config import (
    CODER_MODEL_ALIAS_NAME,
    EPIC_CREATOR_MODEL_ALIAS_NAME,
    EPIC_LANDER_MODEL_ALIAS_NAME,
    PHASE_WORKER_MODEL_ALIAS_NAME,
    get_model_aliases,
    model_alias_bucket,
    model_alias_bucket_description,
    model_alias_config_source,
    model_alias_description,
    model_alias_kind,
    model_alias_names,
    resolve_model_alias,
)
from .temporary_override import TemporaryLLMOverride, get_active_alias_overrides

#: The kind of an alias, used for badge styling and grouping.
AliasKind = Literal["default", "role", "provider_coder", "user"]

#: Canonical display order for the implicit role aliases (after ``default``).
_ROLE_ALIAS_ORDER: tuple[str, ...] = (
    CODER_MODEL_ALIAS_NAME,
    EPIC_CREATOR_MODEL_ALIAS_NAME,
    EPIC_LANDER_MODEL_ALIAS_NAME,
    PHASE_WORKER_MODEL_ALIAS_NAME,
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
        override: The active temporary override for this alias, or ``None``.
        bucket: The optional Models-panel bucket for a custom alias.
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

    @property
    def is_overridden(self) -> bool:
        """Whether a temporary override is currently shaping this alias."""
        return self.override is not None


@dataclass(frozen=True)
class BucketView:
    """A collapsed Models-panel bucket containing custom alias rows."""

    name: str
    description: str | None
    members: tuple[AliasView, ...]

    @property
    def alias_count(self) -> int:
        """Return the number of member aliases."""
        return len(self.members)

    @property
    def override_count(self) -> int:
        """Return the number of members with an active temporary override."""
        return sum(member.is_overridden for member in self.members)

    @staticmethod
    def _model_label(member: AliasView) -> str:
        return f"{member.provider}/{member.model}" if member.provider else member.model

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
) -> tuple[str | None, str]:
    """Return the currently-effective ``(provider, model)`` for *name*.

    An active temporary override always wins (this is what the panel and the
    top-bar pill show); otherwise the configured/implicit alias chain is
    resolved and split into a provider/model pair.
    """
    if override is not None:
        return override.provider, override.model

    # Lazy import to avoid an import cycle: registry imports this package's
    # config at import time.
    from .registry import resolve_model_provider

    target = resolve_model_alias(name)
    return resolve_model_provider(target)


def build_alias_views(now: float | None = None) -> list[AliasView]:
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
    """
    names = model_alias_names()
    configured = get_model_aliases()
    overrides = get_active_alias_overrides(now)

    views: list[AliasView] = []
    for name in names:
        override = overrides.get(name)
        provider, model = _effective_provider_model(name, override)
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
            )
        )

    views.sort(key=_sort_key)
    return views


def build_models_panel_rows(
    views: list[AliasView] | None = None,
) -> list[AliasView | BucketView]:
    """Fold bucketed custom aliases into top-level Models-panel rows.

    Non-user aliases retain their canonical order. In the user region, bucket
    rows come first alphabetically, followed by ungrouped aliases alphabetically.
    Bucket metadata without any member aliases intentionally produces no row.
    """
    source = build_alias_views() if views is None else list(views)
    non_user = sorted((view for view in source if view.kind != "user"), key=_sort_key)
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
    return [*non_user, *buckets, *sorted(ungrouped, key=lambda view: view.name)]

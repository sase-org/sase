"""Deterministic model views shared by Models-panel PNG snapshot tests."""

from __future__ import annotations

from datetime import datetime, tzinfo
from zoneinfo import ZoneInfo

from sase.llm_provider import (
    AliasView,
    EffectiveDefaultEffortSnapshot,
    ProviderRoutingStatus,
    TemporaryEffortOverride,
    TemporaryLLMOverride,
    TemporaryProviderDisable,
)
from sase.llm_provider.config import ModelAliasSelectorMember
from sase.llm_provider.load_balancing import ModelAliasSelectorMode
from sase.llm_provider.provider_disable import PROVIDER_DISABLE_WIRE_SCHEMA_VERSION
from sase.config import EffectiveRunnerLimitSnapshot, TemporaryRunnerLimitOverride


# Frozen clocks keep override countdowns and time previews deterministic.
FROZEN_NOW = 1000.0
EASTERN = ZoneInfo("America/New_York")
_TIME_MODAL_NOW = datetime(2026, 7, 10, 14, 42, tzinfo=EASTERN)


def time_modal_clock(_timezone: tzinfo) -> datetime:
    return _TIME_MODAL_NOW


def effort_snapshot() -> EffectiveDefaultEffortSnapshot:
    return EffectiveDefaultEffortSnapshot(
        configured_effort="xhigh",
        temporary_override=TemporaryEffortOverride(
            version=1,
            effort="medium",
            created_at=FROZEN_NOW,
            expires_at=FROZEN_NOW + 42 * 60,
            source="visual",
        ),
        captured_at=FROZEN_NOW,
    )


def runner_limit_snapshot() -> EffectiveRunnerLimitSnapshot:
    return EffectiveRunnerLimitSnapshot(
        configured_limit=10,
        temporary_override=TemporaryRunnerLimitOverride(
            version=1,
            limit=4,
            created_at=FROZEN_NOW,
            expires_at=FROZEN_NOW + 42 * 60,
            source="visual",
        ),
        captured_at=FROZEN_NOW,
    )


def _view(
    name: str,
    kind: str,
    *,
    configured: bool = False,
    configured_value: str | None = None,
    provider: str | None = "claude",
    model: str = "opus",
    override: TemporaryLLMOverride | None = None,
    configured_source: str | None = None,
    description: str | None = None,
    bucket: str | None = None,
    selector_mode: ModelAliasSelectorMode | None = None,
    selector_members: tuple[ModelAliasSelectorMember, ...] = (),
    effort: str | None = None,
    override_paused_by_provider_disable: TemporaryProviderDisable | None = None,
) -> AliasView:
    return AliasView(
        name=name,
        kind=kind,  # type: ignore[arg-type]
        configured=configured,
        configured_value=configured_value,
        provider=provider,
        model=model,
        override=override,
        configured_source=configured_source,
        description=description,
        bucket=bucket,
        selector_mode=selector_mode,
        selector_members=selector_members,
        effort=effort,
        override_paused_by_provider_disable=override_paused_by_provider_disable,
    )


def provider_disable(
    provider: str,
    *,
    expires_at: float | None = None,
    source: str = "ace",
    mode: str = "hard",
) -> TemporaryProviderDisable:
    return TemporaryProviderDisable(
        version=PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
        provider=provider,
        created_at=FROZEN_NOW,
        expires_at=expires_at,
        source=source,
        mode=mode,
    )


def provider_status(
    provider: str,
    *,
    model_count: int,
    cli_available: bool = True,
    active_disable: TemporaryProviderDisable | None = None,
    affected_aliases: tuple[str, ...] = (),
) -> ProviderRoutingStatus:
    return ProviderRoutingStatus(
        provider=provider,
        model_count=model_count,
        cli_available=cli_available,
        active_disable=active_disable,
        hidden_from_model_pickers=False,
        affected_aliases=affected_aliases,
    )


def calm_views() -> list[AliasView]:
    """The five built-in size aliases plus two custom aliases.

    Each size alias demonstrates a distinct state the Models panel must
    render: ``xsmall`` a load-balanced pool/selector, ``small`` a plain
    effort-suffixed target, ``medium`` a plain implicit target, ``large`` an
    explicit configured-override target, and ``xlarge`` a max-effort target.
    """
    return [
        _view(
            "xsmall",
            "role",
            provider="claude",
            model="haiku",
            description=(
                "Extra-small, lowest-cost alias load-balanced across a "
                "fallback pool for the simplest direct tasks."
            ),
            selector_mode="round_robin",
            selector_members=(
                ModelAliasSelectorMember(
                    value="claude/haiku",
                    target="claude/haiku",
                    effort=None,
                    provider="claude",
                    available=True,
                    selected=True,
                ),
                ModelAliasSelectorMember(
                    value="codex/gpt-5.3-codex-spark",
                    target="codex/gpt-5.3-codex-spark",
                    effort=None,
                    provider="codex",
                    available=True,
                ),
            ),
        ),
        _view(
            "small",
            "role",
            provider="claude",
            model="sonnet",
            effort="xhigh",
            description="Small phases that implement directly.",
        ),
        _view(
            "medium",
            "role",
            provider="claude",
            model="claude-fable-4-10",
            description="Medium phases that implement directly.",
        ),
        _view(
            "large",
            "role",
            configured=True,
            configured_value="claude/opus",
            provider="claude",
            model="opus",
            description="Large phases that plan before implementation.",
        ),
        _view(
            "xlarge",
            "role",
            provider="claude",
            model="opus",
            effort="max",
            description="Extra-large phases that author an epic plan.",
        ),
        _view(
            "fast",
            "user",
            configured=True,
            configured_value="claude/haiku",
            provider="claude",
            model="haiku",
            configured_source="custom",
            description="Quick low-cost follow-up agents.",
        ),
        _view(
            "legacy_blog",
            "user",
            configured=True,
            configured_value="codex/o3",
            provider="codex",
            model="o3",
            configured_source="builtin",
        ),
    ]


def override_views() -> list[AliasView]:
    """calm_views() with an active temporary override on the "medium" role."""
    worker_override = TemporaryLLMOverride(
        provider="codex",
        model="gpt-5.6-sol",
        raw_model="codex/gpt-5.6-sol",
        created_at=FROZEN_NOW,
        expires_at=None,
        source="ace",
    )
    return [
        _view(
            "medium",
            "role",
            configured=True,
            configured_value="codex/o3",
            provider="codex",
            model="gpt-5.6-sol",
            override=worker_override,
        )
        if row.name == "medium"
        else row
        for row in calm_views()
    ]


def provider_disabled_views() -> list[AliasView]:
    disable = provider_disable(
        "codex", expires_at=FROZEN_NOW + 2_520.0, source="visual"
    )
    paused_override = TemporaryLLMOverride(
        provider="codex",
        model="o3",
        raw_model="codex/o3",
        created_at=FROZEN_NOW,
        expires_at=None,
        source="ace",
    )
    return [
        _view(
            "medium",
            "role",
            configured=True,
            configured_value="@large@high",
            provider="claude",
            model="claude-fable-4-10",
            override=paused_override,
            override_paused_by_provider_disable=disable,
            description="Medium phases that implement directly.",
            effort="high",
        )
        if row.name == "medium"
        else row
        for row in calm_views()
    ]


def custom_builtin_warning_views() -> list[AliasView]:
    return [
        _view(
            "small",
            "role",
            configured=True,
            configured_value="codex/o3",
            provider="codex",
            model="o3",
            configured_source="custom",
            description="Misplaced builtin phase-worker alias.",
        )
        if row.name == "small"
        else row
        for row in calm_views()
    ]


def bucket_views() -> list[AliasView]:
    """The five built-in size aliases plus a research bucket and one lone alias."""
    base = calm_views()
    fast = next(view for view in base if view.name == "fast")
    return [
        *(view for view in base if view.kind == "role"),
        _view(
            "research_a",
            "user",
            configured=True,
            configured_value="codex/gpt-5.6-sol",
            provider="codex",
            model="gpt-5.6-sol",
            configured_source="custom",
            description="Lead researcher and consolidator.",
            bucket="research",
        ),
        _view(
            "research_b",
            "user",
            configured=True,
            configured_value="claude/opus",
            provider="claude",
            model="opus",
            configured_source="custom",
            description="Second-opinion researcher.",
            bucket="research",
        ),
        _view(
            "research_c",
            "user",
            configured=True,
            configured_value="codex/gpt-5.6-sol",
            provider="codex",
            model="gpt-5.6-sol",
            configured_source="custom",
            description="Extra researcher lane.",
            bucket="research",
        ),
        fast,
    ]


def ownership_views() -> list[AliasView]:
    """Views covering a user bucket, user row, and mixed built-in bucket."""
    return [
        *bucket_views(),
        _view(
            "pair_programmer",
            "user",
            configured=True,
            configured_value="claude/opus",
            provider="claude",
            model="opus",
            configured_source="custom",
            description="Custom phase-worker bucket member.",
            bucket="worker",
        ),
    ]


LONG_POOL_DESCRIPTION = (
    "Round-robins across four heterogeneous workers so batch drafting keeps "
    "flowing even when a single provider is degraded or rate-limited."
)

LONG_POOL_MEMBERS = (
    ModelAliasSelectorMember(
        value="claude/opus@medium",
        target="claude/opus",
        effort="medium",
        provider="claude",
        available=True,
        selected=True,
    ),
    ModelAliasSelectorMember(
        value="codex/gpt-5.5",
        target="codex/gpt-5.5",
        effort=None,
        provider="codex",
        available=True,
    ),
    ModelAliasSelectorMember(
        value="claude/sonnet@high",
        target="claude/sonnet",
        effort="high",
        provider="claude",
        available=True,
    ),
    ModelAliasSelectorMember(
        value="codex/gpt-5.5-mini",
        target="codex/gpt-5.5-mini",
        effort=None,
        provider="codex",
        available=True,
    ),
)


def long_pool_views() -> list[AliasView]:
    """calm_views() with "xsmall" wired to a 4-member pool that wraps 3+ rows."""
    return [
        _view(
            "xsmall",
            "role",
            configured=True,
            configured_value=(
                "claude/opus@medium | codex/gpt-5.5 | claude/sonnet@high | "
                "codex/gpt-5.5-mini"
            ),
            provider="codex",
            model="gpt-5.5",
            configured_source="builtin",
            description=LONG_POOL_DESCRIPTION,
            selector_mode="round_robin",
            selector_members=LONG_POOL_MEMBERS,
        )
        if row.name == "xsmall"
        else row
        for row in calm_views()
    ]


def builtin_only_views() -> list[AliasView]:
    """Built-in rows used to exercise the empty Custom section."""
    return [view for view in calm_views() if view.kind != "user"]


def pool_effort_views(*, suspended: bool = False) -> list[AliasView]:
    pool_members = (
        ModelAliasSelectorMember(
            value="claude/opus@medium",
            target="claude/opus",
            effort="medium",
            provider="claude",
            available=False,
        ),
        ModelAliasSelectorMember(
            value="codex/gpt-5.5@high",
            target="codex/gpt-5.5",
            effort="high",
            provider="codex",
            available=True,
            selected=True,
        ),
    )
    pool_override = (
        TemporaryLLMOverride(
            provider="claude",
            model="sonnet",
            raw_model="claude/sonnet",
            created_at=FROZEN_NOW,
            expires_at=None,
            source="ace",
        )
        if suspended
        else None
    )
    rows = [
        _view(
            "xsmall",
            "role",
            configured=True,
            configured_value="claude/opus@medium | codex/gpt-5.5@high",
            provider="claude" if suspended else "codex",
            model="sonnet" if suspended else "gpt-5.5",
            override=pool_override,
            configured_source="builtin",
            description="Cheap load-balanced pool for high-volume agents.",
            selector_mode="round_robin",
            selector_members=pool_members,
            effort=None if suspended else "high",
        )
        if row.name == "xsmall"
        else row
        for row in calm_views()
    ]
    rows.append(
        _view(
            "focused",
            "user",
            configured=True,
            configured_value="claude/opus@medium",
            provider="claude",
            model="opus",
            configured_source="custom",
            description="Focused analysis with a pinned effort.",
            effort="medium",
        )
    )
    return rows

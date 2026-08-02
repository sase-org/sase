"""Deterministic model views shared by Models-panel PNG snapshot tests."""

from __future__ import annotations

from datetime import datetime, tzinfo
from zoneinfo import ZoneInfo

from sase.llm_provider import (
    AliasView,
    EffectiveDefaultEffortSnapshot,
    TemporaryEffortOverride,
    TemporaryLLMOverride,
)
from sase.llm_provider.config import ModelAliasSelectorMember
from sase.llm_provider.load_balancing import ModelAliasSelectorMode
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
    )


def calm_views() -> list[AliasView]:
    return [
        _view(
            "default",
            "default",
            provider="claude",
            model="claude-fable-4-10",
            description=(
                "Model used when a prompt has no %model directive; every other "
                "alias ultimately falls back to it."
            ),
        ),
        _view(
            "coder",
            "role",
            provider="claude",
            model="claude-fable-4-10",
        ),
        _view("epic_lander", "role", provider="claude", model="opus"),
        _view(
            "big_epic_lander",
            "role",
            provider="claude",
            model="opus",
            effort="max",
            description=(
                "Epic land agents selected for plans at or above the configured "
                "phase-count threshold."
            ),
        ),
        _view(
            "xsmall_phase_worker",
            "role",
            provider="claude",
            model="sonnet",
            effort="medium",
            description="Extra-small phases that implement the simplest tasks.",
        ),
        _view(
            "small_phase_worker",
            "role",
            provider="claude",
            model="sonnet",
            effort="xhigh",
            description="Small phases that implement directly.",
        ),
        _view(
            "medium_phase_worker",
            "role",
            provider="claude",
            model="claude-fable-4-10",
            effort="high",
            description="Medium phases that implement directly.",
        ),
        _view(
            "large_phase_worker",
            "role",
            configured=True,
            configured_value="claude/opus",
            provider="claude",
            model="opus",
            description="Large phases that plan before implementation.",
        ),
        _view(
            "xlarge_phase_worker",
            "role",
            provider="claude",
            model="opus",
            effort="max",
            description="Extra-large phases that author an epic plan.",
        ),
        _view(
            "smartest",
            "role",
            provider="claude",
            model="opus",
            effort="max",
            description="Highest-capability alias for explicit use.",
        ),
        _view(
            "smart",
            "role",
            provider="claude",
            model="claude-fable-4-10",
            description="High-capability alias used automatically by large phases.",
        ),
        _view(
            "cheap",
            "role",
            provider="claude",
            model="sonnet",
            effort="xhigh",
            description="Load-balanced pool used automatically by small phases.",
        ),
        _view(
            "cheaper",
            "role",
            provider="codex",
            model="gpt-5.5",
            effort="medium",
            description="Lower-cost pool used automatically by extra-small phases.",
        ),
        _view(
            "cheapest",
            "role",
            provider="claude",
            model="haiku",
            description="Lowest-cost load-balanced pool for explicit use.",
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
        _view("claude_coder", "provider_coder", provider="claude", model="sonnet"),
        _view(
            "codex_coder",
            "provider_coder",
            provider="codex",
            model="gpt-5.5",
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
    default_override = TemporaryLLMOverride(
        provider="codex",
        model="o3",
        raw_model="codex/o3",
        created_at=FROZEN_NOW,
        expires_at=FROZEN_NOW + 3600.0,
        source="ace",
    )
    coder_override = TemporaryLLMOverride(
        provider="codex",
        model="gpt-5.6-sol",
        raw_model="codex/gpt-5.6-sol",
        created_at=FROZEN_NOW,
        expires_at=None,
        source="ace",
    )
    return [
        _view(
            "default",
            "default",
            provider="codex",
            model="o3",
            override=default_override,
        )
        if row.name == "default"
        else _view(
            "codex_coder",
            "provider_coder",
            configured=True,
            configured_value="codex/o3",
            provider="codex",
            model="gpt-5.6-sol",
            override=coder_override,
        )
        if row.name == "codex_coder"
        else row
        for row in calm_views()
    ]


def custom_builtin_warning_views() -> list[AliasView]:
    return [
        _view(
            "codex_coder",
            "provider_coder",
            configured=True,
            configured_value="codex/o3",
            provider="codex",
            model="o3",
            configured_source="custom",
            description="Misplaced builtin coder alias.",
        )
        if row.name == "codex_coder"
        else row
        for row in calm_views()
    ]


def bucket_views() -> list[AliasView]:
    return [
        _view(
            "default",
            "default",
            provider="claude",
            model="opus",
            description=(
                "Model used when a prompt has no %model directive; every other "
                "alias ultimately falls back to it."
            ),
        ),
        _view("coder", "role", provider="claude", model="opus"),
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
            description="Custom coder-bucket member.",
            bucket="coders",
        ),
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
            "cheaper",
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
        if row.name == "cheaper"
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

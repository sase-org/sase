"""Shared row builders and fixture data for `%model`/`=`/`==` completion PNG snapshots.

Provider and model values are fixed fakes (as the Models-panel fixtures do) so the
goldens never depend on installed provider CLIs.
"""

from __future__ import annotations

from sase.ace.tui.widgets.directive_completion import ModelCompletionMetadata
from sase.ace.tui.widgets.file_completion import CompletionCandidate


def model_row(
    value: str,
    *,
    provider: str,
    provider_display: str,
    short_alias: str = "",
    description: str | None = None,
    bucket: str = "",
    advisory_label: str = "",
    advisory_severity: str = "",
) -> CompletionCandidate:
    return candidate(
        ModelCompletionMetadata(
            value=value,
            kind="model",
            provider=provider,
            provider_display=provider_display,
            short_alias=short_alias,
            description=description or f"{provider_display} ({short_alias or value})",
            bucket=bucket,
            advisory_label=advisory_label,
            advisory_severity=advisory_severity,
        )
    )


def alias_row(
    value: str,
    *,
    kind: str,
    alias_kind: str,
    target_provider: str,
    target_model: str,
    target_effort: str = "",
    provenance: str = "implicit",
    reference: str = "",
    reference_effort: str = "",
    pool_available: int = 0,
    pool_total: int = 0,
    description: str = "",
    config_source: str = "",
) -> CompletionCandidate:
    return candidate(
        ModelCompletionMetadata(
            value=value,
            kind=kind,
            alias_kind=alias_kind,
            target_provider=target_provider,
            target_model=target_model,
            target_effort=target_effort,
            provenance=provenance,
            reference=reference,
            reference_effort=reference_effort,
            pool_available=pool_available,
            pool_total=pool_total,
            description=description,
            config_source=config_source,
        )
    )


def candidate(metadata: ModelCompletionMetadata) -> CompletionCandidate:
    return CompletionCandidate(
        display=metadata.value,
        insertion=metadata.value,
        is_dir=False,
        name=metadata.value,
        metadata=metadata,
    )


MODEL_ROWS = [
    model_row(
        "claude-fable-5",
        provider="claude",
        provider_display="Claude",
        short_alias="fable",
    ),
    model_row("claude-opus-5", provider="claude", provider_display="Claude"),
    model_row("gpt-5.6-sol", provider="codex", provider_display="Codex"),
]

ALIAS_ROWS = [
    alias_row(
        "@large",
        kind="implicit_alias",
        alias_kind="role",
        target_provider="claude",
        target_model="opus",
        target_effort="high",
        description="Large launch alias for planning-heavy work and default launches.",
    ),
    alias_row(
        "@medium",
        kind="implicit_alias",
        alias_kind="role",
        target_provider="codex",
        target_model="gpt-5.6-sol",
        provenance="configured",
        config_source="builtin",
        description="Default model used for medium tale follow-ups.",
    ),
    alias_row(
        "@small",
        kind="implicit_alias",
        alias_kind="role",
        target_provider="claude",
        target_model="sonnet",
        target_effort="xhigh",
        description="Default model used for small tale follow-ups.",
    ),
    alias_row(
        "@scout",
        kind="user_alias",
        alias_kind="user",
        target_provider="claude",
        target_model="sonnet-4-5",
        provenance="configured",
        config_source="custom",
        pool_available=2,
        pool_total=3,
        description="Cheap scouting model for read-only sweeps.",
    ),
    alias_row(
        "@xlarge",
        kind="implicit_alias",
        alias_kind="role",
        target_provider="codex",
        target_model="o3-pro",
        target_effort="xhigh",
        provenance="override",
        description="Highest-capability model available.",
    ),
]

SCOPED_CLAUDE_ROWS = [
    model_row(
        "claude/opus",
        provider="claude",
        provider_display="Claude",
        description="Claude",
    ),
    model_row(
        "claude/sonnet",
        provider="claude",
        provider_display="Claude",
        description="Claude",
    ),
    model_row(
        "claude/claude-fable-5",
        provider="claude",
        provider_display="Claude",
        short_alias="fable",
        description="Claude (fable)",
    ),
]

LONG_ALIAS_ROWS = [
    alias_row(
        "@observability_super_router_alias_with_extra_segments",
        kind="user_alias",
        alias_kind="user",
        target_provider="codex",
        target_model="gpt-5.6-sol",
        provenance="configured",
        pool_available=2,
        pool_total=4,
        description=("Long operational routing alias for incident sweeps and traces."),
    ),
    alias_row(
        "@observability_backup",
        kind="user_alias",
        alias_kind="user",
        target_provider="claude",
        target_model="opus",
        target_effort="high",
        provenance="backup",
        description="Fallback alias with a shorter target.",
    ),
]

LONG_EXPLICIT_MODEL_ROWS = [
    model_row(
        "anthropic/claude-ultra-long-context-beta-preview-2026-09",
        provider="opencode",
        provider_display="OpenCode Anthropic",
        short_alias="long-preview",
        description="OpenCode Anthropic (long-preview)",
    ),
    model_row(
        "anthropic/claude-ultra-long-context-stable",
        provider="opencode",
        provider_display="OpenCode Anthropic",
        short_alias="long-stable",
        description="OpenCode Anthropic (long-stable)",
    ),
]

ADVISORY_MODEL_ROWS = [
    model_row(
        "muse-contributor-1.1",
        provider="muse",
        provider_display="Muse",
        short_alias="contrib",
        description="Muse (contrib) — ⚠ trains on your data",
        bucket="external",
        advisory_label="trains on your data",
        advisory_severity="warn",
    ),
    model_row(
        "muse-spark-1.2",
        provider="muse",
        provider_display="Muse",
        short_alias="spark",
        description="Muse (spark)",
    ),
]

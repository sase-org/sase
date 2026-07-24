"""Shared helpers for Models panel tests."""

from pathlib import Path

from textual.app import App, ComposeResult

import sase.ace.tui.modals.models_panel as models_panel
from sase.llm_provider import AliasKind, AliasView, TemporaryLLMOverride
from sase.llm_provider.config import ModelAliasSelectorMember
from sase.llm_provider.load_balancing import ModelAliasSelectorMode

_ROOT = Path(__file__).resolve().parents[1]


class ModelsPanelTestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


class StyledModelsPanelTestApp(ModelsPanelTestApp):
    """Test app that loads production styles for geometry assertions."""

    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"


def make_alias_view(
    name: str,
    kind: AliasKind,
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
        kind=kind,
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


def make_override(expires_at: float | None = 3600.0) -> TemporaryLLMOverride:
    return TemporaryLLMOverride(
        provider="codex",
        model="o3",
        raw_model="codex/o3",
        created_at=0.0,
        expires_at=expires_at,
        source="test",
    )


def make_pool_members(
    availability: tuple[bool, ...] = (True, True),
    *,
    next_index: int = 0,
) -> tuple[ModelAliasSelectorMember, ...]:
    values = ("claude/opus@medium", "codex/gpt-5.5")
    targets = ("claude/opus", "codex/gpt-5.5")
    efforts = ("medium", None)
    providers = ("claude", "codex")
    return tuple(
        ModelAliasSelectorMember(
            value=value,
            target=targets[index],
            effort=efforts[index],
            provider=providers[index],
            available=available,
            selected=index == next_index,
        )
        for index, (value, available) in enumerate(
            zip(values, availability, strict=True)
        )
    )


def patch_alias_views(
    monkeypatch,
    views: list[AliasView],
    *,
    bucket_descriptions: dict[str, str] | None = None,
) -> None:
    monkeypatch.setattr(models_panel, "build_alias_views", lambda *a, **k: views)
    monkeypatch.setattr(
        "sase.llm_provider.alias_view.model_alias_bucket_description",
        lambda name: (bucket_descriptions or {}).get(name),
    )
    monkeypatch.setattr(models_panel, "_now", lambda: 0.0)


def make_bucketed_views() -> list[AliasView]:
    return [
        make_alias_view("default", "default"),
        make_alias_view("coder", "role"),
        make_alias_view(
            "research_a",
            "user",
            configured=True,
            configured_source="custom",
            provider="codex",
            model="gpt-5.6-sol",
            description="Lead researcher.",
            bucket="research",
        ),
        make_alias_view(
            "research_b",
            "user",
            configured=True,
            configured_source="custom",
            provider="claude",
            model="opus",
            description="Second-opinion researcher.",
            bucket="research",
        ),
        make_alias_view(
            "plain",
            "user",
            configured=True,
            configured_source="custom",
            description="Ungrouped alias.",
        ),
    ]


def make_coder_bucket_views() -> list[AliasView]:
    return [
        make_alias_view("default", "default", description="Default model."),
        make_alias_view("codex_coder", "provider_coder", provider="codex", model="o3"),
        make_alias_view("coder", "role", provider="claude", model="opus"),
        make_alias_view(
            "claude_coder", "provider_coder", provider="claude", model="opus"
        ),
    ]


def make_phase_worker_bucket_views() -> list[AliasView]:
    return [
        make_alias_view("default", "default", description="Default model."),
        make_alias_view("coder", "role", provider="claude", model="opus"),
        make_alias_view(
            "xsmall_phase_worker", "role", provider="claude", model="sonnet"
        ),
        make_alias_view("small_phase_worker", "role", provider="claude", model="opus"),
        make_alias_view(
            "medium_phase_worker", "role", provider="codex", model="gpt-5.6-sol"
        ),
        make_alias_view("large_phase_worker", "role", provider="claude", model="opus"),
        make_alias_view(
            "xlarge_phase_worker",
            "role",
            provider="claude",
            model="claude-fable-5",
        ),
        make_alias_view("smartest", "role", provider="claude", model="claude-fable-5"),
        make_alias_view("smart", "role", provider="claude", model="opus"),
        make_alias_view("cheap", "role", provider="claude", model="opus"),
        make_alias_view("cheaper", "role", provider="claude", model="sonnet"),
        make_alias_view("cheapest", "role", provider="claude", model="haiku"),
    ]

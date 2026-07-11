"""Shared helpers for Models panel tests."""

from pathlib import Path

from textual.app import App, ComposeResult

import sase.ace.tui.modals.models_panel as models_panel
from sase.llm_provider import AliasKind, AliasView, TemporaryLLMOverride

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
        make_alias_view("epic_creator", "role"),
        make_alias_view(
            "claude_coder", "provider_coder", provider="claude", model="opus"
        ),
    ]

"""Shared helpers for Models panel tests."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.widgets import OptionList

import sase.ace.tui.modals.models_panel as models_panel
import sase.ace.tui.modals.models_panel_provider_state as models_panel_provider_state
from sase.ace.testing import wait_for as wait_for_pilot
from sase.ace.tui.modals.models_panel import ModelsPanel
from sase.config.edit import ConfigEffectivePreview, ConfigWritePlan, EditPlanResult
from sase.config.inventory import ConfigDiagnostic
from sase.llm_provider import (
    AliasKind,
    AliasView,
    TemporaryLLMOverride,
    TemporaryProviderDisable,
)
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
    override_paused_by_provider_disable: TemporaryProviderDisable | None = None,
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
        override_paused_by_provider_disable=override_paused_by_provider_disable,
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


LONG_POOL_DESCRIPTION = (
    "Round-robins across four heterogeneous workers so batch drafting keeps "
    "flowing even when a single provider is degraded or rate-limited."
)


def make_long_pool_members() -> tuple[ModelAliasSelectorMember, ...]:
    """Four-member pool whose rendered summary wraps to 3+ rows at 110 width."""
    values = (
        "claude/opus@medium",
        "codex/gpt-5.5",
        "claude/sonnet@high",
        "codex/gpt-5.5-mini",
    )
    targets = ("claude/opus", "codex/gpt-5.5", "claude/sonnet", "codex/gpt-5.5-mini")
    efforts = ("medium", None, "high", None)
    providers = ("claude", "codex", "claude", "codex")
    return tuple(
        ModelAliasSelectorMember(
            value=value,
            target=target,
            effort=effort,
            provider=provider,
            available=True,
            selected=index == 0,
        )
        for index, (value, target, effort, provider) in enumerate(
            zip(values, targets, efforts, providers, strict=True)
        )
    )


def make_long_pool_views() -> list[AliasView]:
    """A saturated, production-style alias list plus a long-wrapping pool.

    Matches the shape of a real Launch Control view (many built-in aliases,
    at or beyond the option list's 22-row cap) so geometry tests exercise the
    same list/description budget contention production hits.
    """
    views = [
        make_alias_view(f"worker_{index}", "role", description=f"Worker tier {index}.")
        for index in range(14)
    ]
    views.append(
        make_alias_view(
            "cheaper",
            "role",
            configured=True,
            configured_value=(
                "claude/opus@medium | codex/gpt-5.5 | claude/sonnet@high | "
                "codex/gpt-5.5-mini"
            ),
            description=LONG_POOL_DESCRIPTION,
            selector_mode="round_robin",
            selector_members=make_long_pool_members(),
        )
    )
    return views


def patch_alias_views(
    monkeypatch,
    views: list[AliasView],
    *,
    bucket_descriptions: dict[str, str] | None = None,
) -> None:
    monkeypatch.setattr(models_panel, "build_alias_views", lambda *a, **k: views)
    monkeypatch.setattr(
        models_panel_provider_state, "build_alias_views", lambda *a, **k: views
    )
    monkeypatch.setattr(
        "sase.llm_provider.alias_view.model_alias_bucket_description",
        lambda name: (bucket_descriptions or {}).get(name),
    )
    monkeypatch.setattr(models_panel, "_now", lambda: 0.0)
    monkeypatch.setattr(models_panel_provider_state, "_now", lambda: 0.0)


def make_edit_plan(
    *,
    op: str = "set",
    value: str | None = "opus",
    target_path: str = "/tmp/sase.yml",
    diff: str = ("@@ -1 +1 @@\n-medium: old\n+medium: opus\n"),
    valid: bool = True,
    used_chezmoi: bool = False,
) -> EditPlanResult:
    write_plan = ConfigWritePlan(
        file=target_path,
        layer="user",
        key_path=("llm_provider", "model_aliases", "builtin", "medium"),
        op=op,
        has_value=op == "set",
        new_value=value if op == "set" else None,
    )
    preview = ConfigEffectivePreview(
        path="llm_provider.model_aliases.builtin.medium",
        has_before=True,
        before="old",
        has_after=op == "set",
        after=value if op == "set" else None,
        changed=True,
    )
    validation: tuple[ConfigDiagnostic, ...] = ()
    if not valid:
        validation = (
            ConfigDiagnostic(
                severity="error",
                code="bad",
                message="bad value",
                path="llm_provider.model_aliases.builtin.medium",
                layer="user",
            ),
        )
    return EditPlanResult(
        schema_version=1,
        write_plan=write_plan,
        candidate_config={},
        effective_preview=preview,
        validation=validation,
        diagnostics=(),
        target_path=target_path,
        used_chezmoi=used_chezmoi,
        current_text="medium: old\n",
        new_text="medium: opus\n" if op == "set" else "",
        text_diff=diff,
    )


async def wait_for(
    pilot: Any, predicate: Callable[[], bool], *, timeout: float = 5.0
) -> None:
    await wait_for_pilot(pilot, predicate, timeout=timeout)


def highlight_row(panel: ModelsPanel, row_id: str) -> None:
    """Move the mounted panel's highlight to ``row_id`` and refresh its context."""
    option_list = panel.query_one("#models-panel-list", OptionList)
    panel._set_highlighted_index(option_list, option_list.get_option_index(row_id))
    panel._update_context()


def make_bucketed_views() -> list[AliasView]:
    return [
        make_alias_view("large", "role"),
        make_alias_view("medium", "role"),
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


def make_worker_bucket_views() -> list[AliasView]:
    return [
        make_alias_view("xsmall", "role", provider="claude", model="sonnet"),
        make_alias_view("small", "role", provider="claude", model="opus"),
        make_alias_view(
            "medium",
            "role",
            provider="claude",
            model="opus",
            effort="high",
        ),
        make_alias_view("large", "role", provider="claude", model="opus"),
        make_alias_view(
            "xlarge",
            "role",
            provider="claude",
            model="claude-fable-5",
        ),
    ]

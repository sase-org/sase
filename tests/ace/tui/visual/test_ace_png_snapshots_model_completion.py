"""ACE PNG visual snapshots for the enriched ``%model`` completion menu (sase-ao.5).

Pins how ``PromptInputBar`` renders the four-column ``%model`` grid: concrete
model rows above alias rows, each alias showing its kind badge, resolved
``PROVIDER(model)`` target, and provenance state, plus the contextual panel
title/subtitle. Provider and model values are fixed fakes (as the Models-panel
fixtures do) so the goldens never depend on installed provider CLIs. Goldens live
in ``tests/ace/tui/visual/snapshots/png/``.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui import AceApp
from sase.ace.tui.widgets.directive_completion import ModelCompletionMetadata
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _patch_prompt_catalog_rebuild(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable startup prompt-catalog work; these tests inject rows directly."""
    monkeypatch.setattr(
        AceApp,
        "_schedule_prompt_catalog_rebuild",
        lambda *_args, **_kwargs: None,
    )


def _model_row(
    value: str,
    *,
    provider: str,
    provider_display: str,
    short_alias: str = "",
) -> CompletionCandidate:
    return _candidate(
        ModelCompletionMetadata(
            value=value,
            kind="model",
            provider=provider,
            provider_display=provider_display,
            short_alias=short_alias,
            description=f"{provider_display} ({short_alias or value})",
        )
    )


def _alias_row(
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
    return _candidate(
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


def _candidate(metadata: ModelCompletionMetadata) -> CompletionCandidate:
    return CompletionCandidate(
        display=metadata.value,
        insertion=metadata.value,
        is_dir=False,
        name=metadata.value,
        metadata=metadata,
    )


_MODEL_ROWS = [
    _model_row(
        "claude-fable-5",
        provider="claude",
        provider_display="Claude",
        short_alias="fable",
    ),
    _model_row("claude-opus-5", provider="claude", provider_display="Claude"),
    _model_row("gpt-5.6-sol", provider="codex", provider_display="Codex"),
]

_ALIAS_ROWS = [
    _alias_row(
        "@default",
        kind="implicit_alias",
        alias_kind="default",
        target_provider="claude",
        target_model="opus",
        target_effort="high",
        description="Model used when a prompt has no %model directive.",
    ),
    _alias_row(
        "@medium_phase_worker",
        kind="implicit_alias",
        alias_kind="role",
        target_provider="codex",
        target_model="gpt-5.6-sol",
        provenance="configured",
        config_source="builtin",
        description="Default model used for medium tale follow-ups.",
    ),
    _alias_row(
        "@small_phase_worker",
        kind="implicit_alias",
        alias_kind="role",
        target_provider="claude",
        target_model="sonnet",
        target_effort="xhigh",
        description="Default model used for small tale follow-ups.",
    ),
    _alias_row(
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
    _alias_row(
        "@smartest",
        kind="implicit_alias",
        alias_kind="role",
        target_provider="codex",
        target_model="o3-pro",
        target_effort="xhigh",
        provenance="override",
        description="Highest-capability model available.",
    ),
]


async def _mount_prompt_bar(page: AcePage, initial_value: str) -> PromptInputBar:
    await page.app.mount(
        PromptInputBar(initial_value=initial_value, id="prompt-input-bar")
    )
    bar = page.app.query_one("#prompt-input-bar", PromptInputBar)
    await wait_for_state(
        page,
        lambda: bar.active_text_area().has_focus,
        description="model-completion prompt-bar focus",
    )
    await wait_for_visual_idle(page)
    return bar


async def test_model_completion_mixed_menu_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_prompt_catalog_rebuild(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "patches")
        bar = await _mount_prompt_bar(page, "%model:")

        # A model row is highlighted so the `[@] model aliases` gate hint shows.
        bar.show_file_completions(
            "",
            [*_MODEL_ROWS, *_ALIAS_ROWS],
            selected_index=0,
            completion_kind="directive_arg",
        )
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="model completion visibility",
        )
        await wait_for_svg_contains(page, "@small_phase_worker")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_model_completion_mixed_120x40",
            title="ACE prompt input — %model values with alias rows",
        )


async def test_model_completion_alias_only_menu_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_prompt_catalog_rebuild(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "patches")
        bar = await _mount_prompt_bar(page, "%model:@")

        # An alias row is highlighted so its description subtitle shows.
        bar.show_file_completions(
            "@",
            _ALIAS_ROWS,
            selected_index=3,
            completion_kind="directive_arg",
        )
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="alias-only completion visibility",
        )
        await wait_for_svg_contains(page, "@scout")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_model_completion_aliases_120x40",
            title="ACE prompt input — %model alias-only menu",
        )

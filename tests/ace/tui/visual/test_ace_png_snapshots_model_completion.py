"""ACE PNG visual snapshots for enriched model completion menus.

Pins how ``PromptInputBar`` renders the four-column ``%model`` grid: concrete
model rows above alias rows, each alias showing its kind badge, resolved
``PROVIDER(model)`` target, and provenance state, plus the ``*alias`` and
``**model`` shortcut panels. Provider and model values are fixed fakes (as the
Models-panel fixtures do) so the goldens never depend on installed provider CLIs.
Goldens live in ``tests/ace/tui/visual/snapshots/png/``.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.directive_completion import ModelCompletionMetadata
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.model_alias_completion import MODEL_ALIAS_COMPLETION_KIND
from sase.ace.tui.widgets.model_explicit_completion import (
    MODEL_EXPLICIT_COMPLETION_KIND,
    build_loading_model_explicit_placeholder,
    build_unavailable_model_explicit_placeholder,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._ace_prompt_png_snapshot_helpers import mount_prompt_bar
from tests.ace.tui.visual._ace_prompt_png_snapshot_prompts import TWO_PANE_PROMPT
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _model_row(
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
    return _candidate(
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
        "@large",
        kind="implicit_alias",
        alias_kind="role",
        target_provider="claude",
        target_model="opus",
        target_effort="high",
        description="Large launch alias for planning-heavy work and default launches.",
    ),
    _alias_row(
        "@medium",
        kind="implicit_alias",
        alias_kind="role",
        target_provider="codex",
        target_model="gpt-5.6-sol",
        provenance="configured",
        config_source="builtin",
        description="Default model used for medium tale follow-ups.",
    ),
    _alias_row(
        "@small",
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

_SCOPED_CLAUDE_ROWS = [
    _model_row(
        "claude/opus",
        provider="claude",
        provider_display="Claude",
        description="Claude",
    ),
    _model_row(
        "claude/sonnet",
        provider="claude",
        provider_display="Claude",
        description="Claude",
    ),
    _model_row(
        "claude/claude-fable-5",
        provider="claude",
        provider_display="Claude",
        short_alias="fable",
        description="Claude (fable)",
    ),
]

_LONG_ALIAS_ROWS = [
    _alias_row(
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
    _alias_row(
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

_LONG_EXPLICIT_MODEL_ROWS = [
    _model_row(
        "anthropic/claude-ultra-long-context-beta-preview-2026-09",
        provider="opencode",
        provider_display="OpenCode Anthropic",
        short_alias="long-preview",
        description="OpenCode Anthropic (long-preview)",
    ),
    _model_row(
        "anthropic/claude-ultra-long-context-stable",
        provider="opencode",
        provider_display="OpenCode Anthropic",
        short_alias="long-stable",
        description="OpenCode Anthropic (long-stable)",
    ),
]

_ADVISORY_MODEL_ROWS = [
    _model_row(
        "muse-contributor-1.1",
        provider="muse",
        provider_display="Muse",
        short_alias="contrib",
        description="Muse (contrib) — ⚠ trains on your data",
        bucket="external",
        advisory_label="trains on your data",
        advisory_severity="warn",
    ),
    _model_row(
        "muse-spark-1.2",
        provider="muse",
        provider_display="Muse",
        short_alias="spark",
        description="Muse (spark)",
    ),
]


async def test_model_completion_mixed_menu_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, "%model:")

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
        await wait_for_svg_contains(page, "@small")
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

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, "%model:@")

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


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "prompt_model_alias_completion_full_dark_120x40",
            "ACE prompt input — star alias completion full menu, dark theme",
        ),
        (
            "textual-light",
            "prompt_model_alias_completion_full_light_120x40",
            "ACE prompt input — star alias completion full menu, light theme",
        ),
    ],
)
async def test_model_alias_completion_full_menu_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = theme
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, "*")

        bar.show_file_completions(
            "",
            _ALIAS_ROWS,
            selected_index=0,
            completion_kind=MODEL_ALIAS_COMPLETION_KIND,
        )
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="star alias completion full-menu visibility",
        )
        await wait_for_svg_contains(page, "Enter → %m:@large")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        pytest.param(
            "textual-dark",
            "prompt_model_explicit_completion_full_dark_120x40",
            "ACE prompt input — double-star model completion, dark theme",
            id="dark",
        ),
        pytest.param(
            "textual-light",
            "prompt_model_explicit_completion_full_light_120x40",
            "ACE prompt input — double-star model completion, light theme",
            id="light",
        ),
    ],
)
async def test_model_explicit_completion_full_menu_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = theme
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, "**")

        bar.show_file_completions(
            "",
            _MODEL_ROWS,
            selected_index=0,
            completion_kind=MODEL_EXPLICIT_COMPLETION_KIND,
        )
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="explicit model shortcut completion visibility",
        )
        await wait_for_svg_contains(page, "Enter → %m:claude-fable-5")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            snapshot_name,
            title=title,
        )


async def test_model_explicit_completion_filtered_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = "textual-light"
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, "Route **fa")

        bar.show_file_completions(
            "fa",
            [_MODEL_ROWS[0]],
            selected_index=0,
            completion_kind=MODEL_EXPLICIT_COMPLETION_KIND,
        )
        await wait_for_svg_contains(page, "Enter → %m:claude-fable-5")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_model_explicit_completion_filtered_light_120x40",
            title="ACE prompt input — filtered double-star model completion",
        )


async def test_model_explicit_completion_narrow_scoped_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches(), size=(70, 24)) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, "Try **anthropic/claude")

        bar.show_file_completions(
            "anthropic/claude",
            _LONG_EXPLICIT_MODEL_ROWS,
            selected_index=0,
            completion_kind=MODEL_EXPLICIT_COMPLETION_KIND,
        )
        await wait_for_svg_contains(page, "Enter → %m:anthropic/claude")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_model_explicit_completion_scoped_narrow_70x24",
            title="ACE prompt input — narrow provider-scoped double-star model completion",
        )


async def test_model_explicit_completion_stacked_pane_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = "textual-light"
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, TWO_PANE_PROMPT)

        bar.show_file_completions(
            "gp",
            [_MODEL_ROWS[2]],
            selected_index=0,
            completion_kind=MODEL_EXPLICIT_COMPLETION_KIND,
        )
        await wait_for_svg_contains(page, "Enter → %m:gpt-5.6-sol")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_model_explicit_completion_stack_light_120x40",
            title="ACE prompt stack — double-star model completion, light theme",
        )


async def test_model_explicit_completion_advisory_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = "textual-light"
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, "**contrib")

        bar.show_file_completions(
            "contrib",
            _ADVISORY_MODEL_ROWS,
            selected_index=0,
            completion_kind=MODEL_EXPLICIT_COMPLETION_KIND,
        )
        await wait_for_svg_contains(page, "trains on your data")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_model_explicit_completion_advisory_light_120x40",
            title="ACE prompt input — advisory double-star model completion",
        )


@pytest.mark.parametrize(
    ("candidate", "snapshot_name", "title", "expected"),
    [
        pytest.param(
            build_loading_model_explicit_placeholder(),
            "prompt_model_explicit_completion_loading_120x40",
            "ACE prompt input — loading double-star model completion",
            "Loading models",
            id="loading",
        ),
        pytest.param(
            build_unavailable_model_explicit_placeholder(),
            "prompt_model_explicit_completion_unavailable_120x40",
            "ACE prompt input — unavailable double-star model completion",
            "Models unavailable",
            id="unavailable",
        ),
    ],
)
async def test_model_explicit_completion_status_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    candidate: CompletionCandidate,
    snapshot_name: str,
    title: str,
    expected: str,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, "**")

        bar.show_file_completions(
            "",
            [candidate],
            selected_index=0,
            completion_kind=MODEL_EXPLICIT_COMPLETION_KIND,
        )
        await wait_for_svg_contains(page, expected)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


async def test_model_alias_completion_filtered_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = "textual-light"
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, "Route *sc")

        bar.show_file_completions(
            "sc",
            [_ALIAS_ROWS[3]],
            selected_index=0,
            completion_kind=MODEL_ALIAS_COMPLETION_KIND,
        )
        await wait_for_svg_contains(page, "@scout")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_model_alias_completion_filtered_light_120x40",
            title="ACE prompt input — filtered star alias completion, light theme",
        )


async def test_model_alias_completion_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches(), size=(70, 24)) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, "Explain *observability")

        bar.show_file_completions(
            "observability",
            _LONG_ALIAS_ROWS,
            selected_index=0,
            completion_kind=MODEL_ALIAS_COMPLETION_KIND,
        )
        await wait_for_svg_contains(page, "Enter → %m:@observability")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_model_alias_completion_narrow_70x24",
            title="ACE prompt input — narrow star alias completion",
        )


async def test_model_alias_completion_stacked_pane_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = "textual-light"
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, TWO_PANE_PROMPT)

        bar.show_file_completions(
            "la",
            [_ALIAS_ROWS[0]],
            selected_index=0,
            completion_kind=MODEL_ALIAS_COMPLETION_KIND,
        )
        await wait_for_svg_contains(page, "Enter → %m:@large")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_model_alias_completion_stack_light_120x40",
            title="ACE prompt stack — star alias completion, light theme",
        )


async def test_model_completion_provider_scoped_menu_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, "%model:claude/")

        bar.show_file_completions(
            "claude/",
            _SCOPED_CLAUDE_ROWS,
            selected_index=0,
            completion_kind="directive_arg",
        )
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="provider-scoped model completion visibility",
        )
        await wait_for_svg_contains(page, "claude/sonnet")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_model_completion_provider_scoped_120x40",
            title="ACE prompt input — provider-scoped %model values",
        )

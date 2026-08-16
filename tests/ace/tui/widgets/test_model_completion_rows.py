"""Rich-row tests for the ``%model`` completion grid."""

from __future__ import annotations

import pytest
from rich.text import Text

from sase.ace.tui.widgets._prompt_input_bar_completion_rows import (
    append_model_completion_row,
    model_completion_column_widths,
)
from sase.ace.tui.provider_styles import provider_name_style
from sase.ace.tui.widgets.directive_completion import ModelCompletionMetadata
from sase.ace.tui.widgets.file_completion import CompletionCandidate


def _candidate(
    value: str,
    *,
    kind: str = "implicit_alias",
    alias_kind: str = "role",
    provider: str = "",
    provider_display: str = "",
    short_alias: str = "",
    target_provider: str = "claude",
    target_model: str = "opus",
    target_effort: str = "",
    provenance: str = "implicit",
    reference: str = "",
    reference_effort: str = "",
    pool_available: int = 0,
    pool_total: int = 0,
    description: str = "",
    config_source: str = "",
    provider_model_count: int = 0,
) -> CompletionCandidate:
    return CompletionCandidate(
        display=value,
        insertion=value,
        is_dir=False,
        name=value,
        metadata=ModelCompletionMetadata(
            value=value,
            kind=kind,
            alias_kind=alias_kind,
            provider=provider,
            provider_display=provider_display,
            short_alias=short_alias,
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
            provider_model_count=provider_model_count,
        ),
    )


def _render(
    candidate: CompletionCandidate,
    *,
    selected: bool = False,
    widths: tuple[int, int] | None = None,
) -> Text:
    text = Text()
    append_model_completion_row(
        text,
        candidate,
        selected,
        widths or model_completion_column_widths([candidate]),
    )
    return text


def test_model_completion_row_uses_model_columns_and_styles() -> None:
    candidate = _candidate(
        "claude-fable-5",
        kind="model",
        alias_kind="",
        provider="claude",
        provider_display="Claude",
        short_alias="fable",
        target_provider="",
        target_model="",
        provenance="",
    )

    text = _render(candidate, selected=True)

    assert text.plain.split() == ["claude-fable-5", "model", "Claude", "fable"]
    assert text.spans[0].start == 0
    assert "bold magenta" in str(text.spans[0].style).lower()


def test_provider_completion_row_uses_model_grid_and_provider_style() -> None:
    candidate = _candidate(
        "claude/",
        kind="provider",
        alias_kind="",
        provider="claude",
        provider_display="Claude",
        target_provider="",
        target_model="",
        provenance="",
        description="Claude",
        provider_model_count=2,
    )

    text = _render(candidate, selected=True)
    widths = model_completion_column_widths([candidate])

    assert "claude/" in text.plain
    assert "models" in text.plain
    assert "Claude (2 models)" in text.plain
    assert len("models") <= 7
    assert widths[1] == Text("Claude (2 models)").cell_len
    provider_color = provider_name_style("claude").split()[-1].lower()
    assert provider_color in str(text.spans[0].style).lower()


@pytest.mark.parametrize(
    ("candidate", "kind_label", "state"),
    [
        (
            _candidate(
                "@medium",
                reference="large",
                reference_effort="high",
            ),
            "role",
            "implicit → @large @ high",
        ),
        (
            _candidate(
                "@medium",
                provenance="configured",
                reference="large",
            ),
            "role",
            "configured → @large",
        ),
        (
            _candidate(
                "@scout",
                alias_kind="user",
                provenance="configured",
                pool_available=2,
                pool_total=3,
            ),
            "custom",
            "configured · pool 2/3",
        ),
        (
            _candidate(
                "@medium",
                target_provider="codex",
                target_model="gpt-5.6-sol",
                provenance="override",
            ),
            "role",
            "override",
        ),
    ],
)
def test_alias_completion_rows_show_kind_target_and_state(
    candidate: CompletionCandidate,
    kind_label: str,
    state: str,
) -> None:
    text = _render(candidate)

    assert kind_label in text.plain
    assert "CLAUDE(opus)" in text.plain or "CODEX(gpt-5.6-sol)" in text.plain
    assert state in text.plain


def test_model_completion_rows_align_state_across_mixed_window() -> None:
    model = _candidate(
        "fable",
        kind="model",
        alias_kind="",
        provider="claude",
        provider_display="Claude",
        short_alias="short",
        target_provider="",
        target_model="",
        provenance="",
    )
    alias = _candidate(
        "@medium",
        target_provider="codex",
        target_model="gpt-5.6-sol",
    )
    widths = model_completion_column_widths([model, alias])

    model_text = _render(model, widths=widths).plain
    alias_text = _render(alias, widths=widths).plain

    assert model_text.index("short") == alias_text.index("implicit")


def test_model_completion_row_ellipsizes_overlong_name() -> None:
    candidate = _candidate("@" + ("very_long_alias_" * 3), alias_kind="user")

    text = _render(candidate)

    assert "…" in text.plain[:30]
    assert "custom" in text.plain

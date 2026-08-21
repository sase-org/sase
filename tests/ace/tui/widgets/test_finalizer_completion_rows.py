"""Rich-row tests for the ``%final`` completion grid."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.widgets._prompt_input_bar_completion_rows import (
    append_finalizer_completion_row,
    finalizer_completion_column_widths,
)
from sase.ace.tui.widgets.directive_completion import FinalizerCompletionMetadata
from sase.ace.tui.widgets.file_completion import CompletionCandidate


def _candidate(
    value: str,
    *,
    kind: str = "finalizer",
    status: str = "optional",
    provider: str = "builtin@command",
    documentation: str = "",
) -> CompletionCandidate:
    return CompletionCandidate(
        display=value,
        insertion=value,
        is_dir=False,
        name=value,
        metadata=FinalizerCompletionMetadata(
            value=value,
            kind=kind,
            status=status,
            provider=provider,
            documentation=documentation,
        ),
    )


def _render(
    candidate: CompletionCandidate,
    *,
    selected: bool = False,
    widths: tuple[int, int] | None = None,
) -> Text:
    text = Text()
    append_finalizer_completion_row(
        text,
        candidate,
        selected,
        widths or finalizer_completion_column_widths([candidate]),
    )
    return text


def test_finalizer_row_shows_selector_state_and_provider() -> None:
    candidate = _candidate("commit", status="required", provider="builtin@commit")

    text = _render(candidate, selected=True)

    assert "commit" in text.plain
    assert "required" in text.plain
    assert "builtin@commit" in text.plain
    assert "bold magenta" in str(text.spans[0].style).lower()


def test_remove_row_labels_the_operation_without_relying_on_color() -> None:
    candidate = _candidate(
        "!lint",
        kind="finalizer_remove",
        status="default",
        provider="builtin@command",
    )

    text = _render(candidate)

    assert "!lint" in text.plain
    assert "remove" in text.plain
    assert "required" not in text.plain


def test_clear_row_is_labeled_clear() -> None:
    candidate = _candidate(
        "none",
        kind="finalizer_clear",
        status="clear",
        provider="",
    )

    text = _render(candidate)

    assert "none" in text.plain
    assert "clear" in text.plain


def test_metadata_fallback_still_renders_the_selector() -> None:
    candidate = CompletionCandidate(
        display="zoom",
        insertion="zoom",
        is_dir=False,
        name="zoom",
        metadata=FinalizerCompletionMetadata(value="zoom", kind="finalizer"),
    )

    text = _render(candidate)

    assert "zoom" in text.plain
    assert "optional" in text.plain


def test_finalizer_rows_align_state_across_mixed_window() -> None:
    required = _candidate("commit", status="required", provider="builtin@commit")
    optional = _candidate("zoom", status="optional", provider="plugin@zoom")
    widths = finalizer_completion_column_widths([required, optional])

    required_text = _render(required, widths=widths).plain
    optional_text = _render(optional, widths=widths).plain

    assert required_text.index("required") == optional_text.index("optional")


def test_finalizer_row_ellipsizes_overlong_selector_and_provider() -> None:
    candidate = _candidate(
        "very_long_finalizer_instance_name",
        provider="plugin@an_extremely_long_provider_reference",
    )

    text = _render(candidate, widths=(12, 10))

    assert "…" in text.plain
    assert "optional" in text.plain

"""State precedence and shared renderers for the Artifacts pane shell."""

from __future__ import annotations

import pytest

from sase.ace.tui._artifact_tab_contract import compile_builtin_contract
from sase.ace.tui.widgets.artifacts.shell import (
    ArtifactsPaneState,
    ArtifactsShellState,
    build_degraded_card,
    build_empty_card,
    build_footer_hints,
    build_reveal_chip,
    build_shell_scope,
    build_state_badge,
    resolve_pane_state,
)
from sase.ace.tui.widgets.artifacts.types import ArtifactsPaneContract


def _contract(pane_id: str = "beads", accent: str = "#D787FF") -> ArtifactsPaneContract:
    labels = {"beads": "Bead", "stitches": "Stitch", "files": "File"}
    icons = {"beads": "◈", "stitches": "◉", "files": "▤"}
    return compile_builtin_contract(
        pane_id,
        label=labels[pane_id],
        icon=icons[pane_id],
        accent=accent,
    )


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        # Degraded always wins, regardless of other flags.
        (
            ArtifactsShellState(
                is_degraded=True,
                is_loading=True,
                has_error=True,
                has_content=True,
                row_count=5,
            ),
            ArtifactsPaneState.DEGRADED,
        ),
        # A first-load failure with no cached content is degraded.
        (
            ArtifactsShellState(has_error=True, has_content=False),
            ArtifactsPaneState.DEGRADED,
        ),
        # First load in flight, nothing cached yet.
        (
            ArtifactsShellState(is_loading=True, has_content=False),
            ArtifactsPaneState.LOADING,
        ),
        # A refresh in flight with cached content is stale, not loading.
        (
            ArtifactsShellState(is_loading=True, has_content=True, row_count=3),
            ArtifactsPaneState.STALE,
        ),
        # A runtime error with cached content preserves that content as stale.
        (
            ArtifactsShellState(has_error=True, has_content=True, row_count=3),
            ArtifactsPaneState.STALE,
        ),
        # Successful load, zero rows, no active filter: empty inventory.
        (
            ArtifactsShellState(has_content=True, row_count=0),
            ArtifactsPaneState.EMPTY,
        ),
        # Successful load, zero rows, active filter: still the empty bucket;
        # the pane distinguishes inventory vs no-match copy separately.
        (
            ArtifactsShellState(
                has_content=True,
                row_count=0,
                has_active_filter=True,
            ),
            ArtifactsPaneState.EMPTY,
        ),
        # Settled, populated content.
        (
            ArtifactsShellState(has_content=True, row_count=7),
            ArtifactsPaneState.RESULTS,
        ),
        # No content, not loading, not erroring, zero rows: empty.
        (
            ArtifactsShellState(),
            ArtifactsPaneState.EMPTY,
        ),
    ],
)
def test_resolve_pane_state_precedence(
    state: ArtifactsShellState,
    expected: ArtifactsPaneState,
) -> None:
    assert resolve_pane_state(state) == expected


def test_state_enum_declares_precedence_order() -> None:
    assert [member.value for member in ArtifactsPaneState] == [
        "degraded",
        "loading",
        "stale",
        "empty",
        "results",
    ]


def test_build_shell_scope_uses_contract_identity_and_accent() -> None:
    contract = _contract("beads", accent="#D787FF")
    text = build_shell_scope(
        label=contract.label,
        accent=contract.accent,
        scope_label="All projects",
        change_hint="p change",
    )
    assert "Bead" in text.plain
    assert "All projects" in text.plain
    assert "p change" in text.plain
    styles = {span.style for span in text.spans}
    assert any("#D787FF" in str(style) for style in styles)


def test_build_shell_scope_uses_non_plan_provider_accent() -> None:
    contract = compile_builtin_contract(
        "beads",
        label="Research",
        icon="R",
        accent="#5FAFFF",
    )
    text = build_shell_scope(
        label=contract.label,
        accent=contract.accent,
        scope_label="All projects",
    )
    styles = {span.style for span in text.spans}
    assert any("#5FAFFF" in str(style) for style in styles)
    assert "#AF87FF" not in text.plain
    assert not any("#AF87FF" in str(style) for style in styles)


def test_build_reveal_chip_names_relation_and_return_key() -> None:
    text = build_reveal_chip(label="Ancestors", accent="#87D7FF", return_hint="^")
    assert "Ancestors" in text.plain
    assert "^" in text.plain
    assert "to return" in text.plain
    styles = {str(span.style) for span in text.spans}
    assert any("#87D7FF" in style for style in styles)


@pytest.mark.parametrize(
    ("state", "error_message", "expected_fragment"),
    [
        (ArtifactsPaneState.LOADING, None, "Loading…"),
        (ArtifactsPaneState.STALE, None, "Refreshing"),
        (ArtifactsPaneState.STALE, "boom", "boom"),
        (ArtifactsPaneState.RESULTS, None, ""),
        (ArtifactsPaneState.EMPTY, None, ""),
    ],
)
def test_build_state_badge(
    state: ArtifactsPaneState,
    error_message: str | None,
    expected_fragment: str,
) -> None:
    text = build_state_badge(state, error_message=error_message)
    if expected_fragment:
        assert expected_fragment in text.plain
    else:
        assert text.plain == ""


def test_build_empty_card_distinguishes_inventory_from_no_match() -> None:
    contract = _contract("beads")
    inventory = build_empty_card(contract, has_active_filter=False)
    assert inventory.plain.startswith(contract.empty_state.title)
    assert contract.empty_state.body in inventory.plain

    no_match = build_empty_card(
        contract,
        has_active_filter=True,
        clear_filter_hint="Press f to clear it.",
    )
    assert "No matches" in no_match.plain
    assert "bead" in no_match.plain.lower()
    assert "Press f to clear it." in no_match.plain
    assert no_match.plain != inventory.plain


def test_build_degraded_card_carries_diagnostics() -> None:
    hero, card = build_degraded_card(
        provider_kind="research",
        provider_label="Research",
        error="ref.inventory is missing a root",
        error_code="ref_inventory_missing_root",
        error_source="sidecar.yml",
    )
    assert "Research" in hero.plain
    assert "research" in hero.plain
    assert "ref_inventory_missing_root" in card.plain
    assert "ref.inventory is missing a root" in card.plain
    assert "sidecar.yml" in card.plain


def test_build_footer_hints_marks_disabled_labels() -> None:
    text = build_footer_hints(
        (("n", "next"), ("a", "agent")),
        accent="#FFAF5F",
        disabled_labels=frozenset({"agent"}),
    )
    assert "next" in text.plain
    assert "agent" in text.plain
    styles = [str(span.style) for span in text.spans]
    assert any("#FFAF5F" in style for style in styles)
    assert any(style == "dim" for style in styles)

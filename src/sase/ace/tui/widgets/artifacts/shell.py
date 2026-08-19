"""Contract-driven visual shell: state resolution and shared Rich renderers.

Every configured Artifacts pane, including Patch and degraded third-party
panes, composes through this shared visual grammar so loading, empty,
results, stale, and degraded states are deterministic and theme-legible
regardless of provider. Renderers here are pure: they consume an
:class:`ArtifactsPaneContract` (or already-computed presentation values)
and never look up a pane id in ``ARTIFACTS_ACCENTS``, invoke provider code,
resolve providers, touch the filesystem, or perform data-scaled work.

See ``docs/artifacts_pane_visual_grammar.md`` for the full state precedence
table, layout order, and extension checklist.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from rich.text import Text

from .types import ArtifactsPaneContract

_LOADING_BADGE_STYLE = "bold #FFD700"
_STALE_BADGE_STYLE = "bold #FFD700"
_ERROR_BADGE_STYLE = "bold #FF5F5F"
_SEPARATOR = "  ·  "


class ArtifactsPaneState(StrEnum):
    """Closed vocabulary of Artifacts pane visual states.

    Members are declared in the shell's precedence order: a state earlier
    in this enum always wins over a state later in it.
    """

    DEGRADED = "degraded"
    LOADING = "loading"
    STALE = "stale"
    EMPTY = "empty"
    RESULTS = "results"


@dataclass(frozen=True, slots=True)
class ArtifactsShellState:
    """Immutable, purely presentational state input for one pane render.

    Every field must already be computed by the pane before calling
    :func:`resolve_pane_state`; this record never touches the filesystem,
    invokes provider code, or resolves providers.
    """

    is_degraded: bool = False
    is_loading: bool = False
    has_error: bool = False
    has_content: bool = False
    row_count: int = 0
    has_active_filter: bool = False


def resolve_pane_state(state: ArtifactsShellState) -> ArtifactsPaneState:
    """Resolve one closed visual state from *state* by fixed precedence.

    - ``degraded``: a contract/discovery failure, or an initial load
      failure with no usable content.
    - ``loading``: first load for the current scope, with no cached
      content.
    - ``stale``: usable content from the current scope remains while a
      refresh is running, or while a runtime error has occurred; either
      way the existing content is preserved rather than cleared.
    - ``empty``: the current scope loaded successfully but has no rows.
    - ``results``: usable rows are present and no refresh is in flight.
    """

    if state.is_degraded or (state.has_error and not state.has_content):
        return ArtifactsPaneState.DEGRADED
    if state.is_loading and not state.has_content:
        return ArtifactsPaneState.LOADING
    if state.has_content and (state.is_loading or state.has_error):
        return ArtifactsPaneState.STALE
    if state.row_count == 0:
        return ArtifactsPaneState.EMPTY
    return ArtifactsPaneState.RESULTS


def build_shell_scope(
    *,
    label: str,
    accent: str,
    scope_label: str,
    change_hint: str | None = None,
) -> Text:
    """Build the shared identity/scope header line.

    Every pane's header opens with the same contract-driven identity chip
    (*label* on *accent*), followed by project scope. *label*/*accent* must
    come from the pane's resolved ``ArtifactsPaneContract`` — never a
    pane-id lookup into ``ARTIFACTS_ACCENTS``. Bespoke per-pane information
    does not belong here; it belongs in the state/count lane or the pane's
    own rows. The active query lives solely in that pane's persistent
    ``FilterBar`` — it is not echoed here.
    """

    text = Text()
    text.append(f" {label} ", style=f"bold #1a1a1a on {accent}")
    text.append("  Project scope  ", style="dim")
    text.append(f" {scope_label} ", style=f"bold {accent}")
    if change_hint:
        text.append(_SEPARATOR, style="dim")
        text.append(change_hint, style="dim")
    return text


def build_reveal_chip(
    *,
    label: str,
    accent: str,
    return_hint: str,
) -> Text:
    """Build the reversible relation-reveal lens chip.

    Shown only while a pane's live query is exactly the rewrite a relation
    jump produced (:func:`sase.ace.relation_reveal.is_relation_reveal_active`
    decides that, not this renderer). Names the relation that caused the
    rewrite and the existing key that returns to the composed query the
    jump left behind -- no new binding, this reuses `prev_query`.
    """

    text = Text()
    text.append(f" ↩ {label} ", style=f"bold #1a1a1a on {accent}")
    text.append(f"  {return_hint} to return", style="dim")
    return text


def build_state_badge(
    pane_state: ArtifactsPaneState,
    *,
    error_message: str | None = None,
) -> Text:
    """Build the compact badge shown in the state/count lane.

    Returns empty text for ``results`` and ``empty``; those states are
    conveyed by the pane's own count text rather than a badge. ``degraded``
    is normally rendered as a full-surface card rather than a lane badge,
    but a caller may still ask for its badge form (e.g. a diagnostics
    summary).
    """

    text = Text()
    if pane_state is ArtifactsPaneState.LOADING:
        text.append("Loading…", style=_LOADING_BADGE_STYLE)
    elif pane_state is ArtifactsPaneState.STALE:
        if error_message:
            text.append(f"⚠ {error_message}", style=_ERROR_BADGE_STYLE)
        else:
            text.append("↻ Refreshing", style=_STALE_BADGE_STYLE)
    elif pane_state is ArtifactsPaneState.DEGRADED and error_message:
        text.append(error_message, style=_ERROR_BADGE_STYLE)
    return text


def build_empty_card(
    contract: ArtifactsPaneContract,
    *,
    has_active_filter: bool,
    clear_filter_hint: str | None = None,
) -> Text:
    """Build the empty-inventory or no-match card body.

    An empty inventory (no rows exist at all) uses the contract's declared
    empty-state copy. A no-match card (rows exist but the active filter
    excludes all of them) names the filter and, when supplied, the key that
    edits or clears it.
    """

    text = Text()
    if has_active_filter:
        text.append("No matches", style="bold")
        text.append(f" under the active {contract.label.lower()} filter.")
        if clear_filter_hint:
            text.append(f" {clear_filter_hint}", style="dim")
        return text
    if contract.empty_state.title:
        text.append(contract.empty_state.title, style="bold")
        if contract.empty_state.body:
            text.append("\n\n")
            text.append(contract.empty_state.body)
        return text
    text.append(f"No {contract.label.lower()} entries yet.", style="dim")
    return text


def build_degraded_card(
    *,
    provider_kind: str,
    provider_label: str,
    error: str,
    error_code: str | None = None,
    error_source: str | None = None,
) -> tuple[Text, Text]:
    """Build the ``(hero, card)`` pair for a degraded pane's failure surface.

    The hero names the provider kind and label so the tab stays identified
    even though it failed; the card carries the stable diagnostic code when
    available, the validation problem, and its configuration source.
    """

    hero = Text()
    hero.append(provider_label, style="bold")
    hero.append(f"  ({provider_kind})", style="dim")

    card = Text()
    if error_code:
        card.append(f"{error_code}\n", style="bold")
    card.append(error)
    if error_source:
        card.append("\n")
        card.append(f"source: {error_source}", style="dim")
    return hero, card


def build_footer_hints(
    entries: tuple[tuple[str, str], ...],
    *,
    accent: str,
    disabled_labels: frozenset[str] = frozenset(),
) -> Text:
    """Build the shared footer-hint lane from configured ``(key, label)`` pairs.

    Every pane mounts its hints in the same position with the same
    separator, accent treatment for enabled keys, and dim treatment for
    disabled ones.
    """

    text = Text(justify="center")
    for index, (key, label) in enumerate(entries):
        if index:
            text.append(_SEPARATOR, style="dim")
        disabled = label in disabled_labels
        text.append(key, style="dim" if disabled else f"bold {accent}")
        text.append(f" {label}", style="dim")
    return text


__all__ = [
    "ArtifactsPaneState",
    "ArtifactsShellState",
    "build_degraded_card",
    "build_empty_card",
    "build_footer_hints",
    "build_reveal_chip",
    "build_shell_scope",
    "build_state_badge",
    "resolve_pane_state",
]

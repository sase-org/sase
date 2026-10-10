"""Cell-aware compact and expanded rendering of recorded session models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.provider_styles import provider_text_palette

if TYPE_CHECKING:
    from sase.core.agent_models import AgentModelIdentity, AgentModelSummary

_LABEL = "Models: "
_LABEL_STYLE = "bold #87D7FF"
_SEPARATOR = " · "
_SEPARATOR_STYLE = "dim"
_INDENT = " " * len(_LABEL)
_UNKNOWN_STYLE = "dim"


@dataclass(frozen=True, slots=True)
class SessionModelStripFit:
    """A compact fit and the known model identities it omits."""

    text: Text
    rows: int
    omitted_count: int


def fit_session_model_strip(
    summary: AgentModelSummary,
    *,
    width: int,
    max_rows: int,
) -> SessionModelStripFit:
    """Fit whole provider-colored model tokens into one or two terminal rows."""
    width = max(1, int(width))
    max_rows = min(2, max(1, int(max_rows)))
    identities = summary.models
    if not identities:
        unknown = _styled("unknown", _UNKNOWN_STYLE)
        fitted = _pack((unknown,), width=width, max_rows=1)
        if fitted is not None:
            return SessionModelStripFit(fitted, 1, 0)
        return SessionModelStripFit(_count_only(0, width, 0), 1, 0)

    labels = _model_labels(identities)
    extras = _unknown_marker(summary.unknown_turn_count)
    full = _pack((*labels, *extras), width=width, max_rows=max_rows)
    if full is not None:
        return SessionModelStripFit(full, _line_count(full), 0)

    latest_index = (
        identities.index(summary.latest) if summary.latest in identities else 0
    )
    priority = (
        latest_index,
        *(index for index in range(len(identities)) if index != latest_index),
    )
    for keep_count in range(len(identities) - 1, 0, -1):
        kept_indexes = sorted(priority[:keep_count])
        omitted = len(identities) - keep_count
        tokens = tuple(labels[index] for index in kept_indexes)
        overflow = _styled(f"+{omitted} more", _UNKNOWN_STYLE)
        fitted = _pack((*tokens, *extras, overflow), width=width, max_rows=max_rows)
        if fitted is not None:
            return SessionModelStripFit(fitted, _line_count(fitted), omitted)

    # Keep the latest known identity even when its full token is wider than the
    # available strip. Disambiguating provider text is retained whenever the
    # width allows the complete prefix plus the ellipsis.
    keep_latest = labels[latest_index]
    omitted = len(identities) - 1
    overflow_tokens: tuple[Text, ...] = (
        (_styled(f"+{omitted} more", _UNKNOWN_STYLE),) if omitted else ()
    )
    for budget in range(width, 0, -1):
        shortened = _shorten_identity(
            identities[latest_index], keep_latest.plain, budget
        )
        if shortened is None:
            continue
        tokens = (
            _styled(shortened, _model_style(identities[latest_index])),
            *extras,
            *overflow_tokens,
        )
        fitted = _pack(tokens, width=width, max_rows=max_rows)
        if fitted is not None:
            return SessionModelStripFit(fitted, _line_count(fitted), omitted)

    return SessionModelStripFit(
        _count_only(len(identities), width, summary.unknown_turn_count),
        1,
        len(identities),
    )


def expanded_session_model_summary(summary: AgentModelSummary) -> Text:
    """Render the uncapped full model list for expanded session identity fields."""
    text = Text()
    text.append(_LABEL, style=_LABEL_STYLE)
    if summary.models:
        for index, identity in enumerate(summary.models):
            if index:
                text.append(_SEPARATOR, style=_SEPARATOR_STYLE)
            _append_full_identity(text, identity)
    else:
        text.append("unknown", style=_UNKNOWN_STYLE)
    text.append("\n")
    if summary.unknown_turn_count:
        count = summary.unknown_turn_count
        noun = "turn has" if count == 1 else "turns have"
        text.append(f"{count} {noun} no recorded model\n", style=_UNKNOWN_STYLE)
    return text


def _model_labels(identities: tuple[AgentModelIdentity, ...]) -> tuple[Text, ...]:
    providers_by_model: dict[str, set[str | None]] = {}
    for identity in identities:
        providers_by_model.setdefault(identity.model, set()).add(identity.provider)
    labels: list[Text] = []
    for identity in identities:
        collision = len(providers_by_model[identity.model]) > 1
        label = _styled(
            _identity_label(identity, qualify=collision), _model_style(identity)
        )
        labels.append(label)
    return tuple(labels)


def _identity_label(identity: AgentModelIdentity, *, qualify: bool) -> str:
    if qualify and identity.provider:
        return f"{identity.provider}/{identity.model}"
    return identity.model


def _model_style(identity: AgentModelIdentity) -> str:
    return provider_text_palette(identity.provider).subject_style


def _append_full_identity(text: Text, identity: AgentModelIdentity) -> None:
    style = _model_style(identity)
    if identity.provider:
        text.append(f"{identity.provider}/", style=style)
    text.append(identity.model, style=style)


def _unknown_marker(count: int) -> tuple[Text, ...]:
    if count <= 0:
        return ()
    return (_styled(f"{count} unknown", _UNKNOWN_STYLE),)


def _styled(value: str, style: str) -> Text:
    return Text(value, style=style)


def _pack(tokens: tuple[Text, ...], *, width: int, max_rows: int) -> Text | None:
    rows = [Text(_LABEL, style=_LABEL_STYLE)]
    row_has_token = [False]
    for source in tokens:
        token = source.copy()
        row_index = len(rows) - 1
        separator = _SEPARATOR if row_has_token[row_index] else ""
        if (
            cell_len(rows[row_index].plain)
            + cell_len(separator)
            + cell_len(token.plain)
            > width
        ):
            if len(rows) >= max_rows:
                return None
            rows.append(Text(_INDENT))
            row_has_token.append(False)
            row_index += 1
            separator = ""
        if (
            cell_len(rows[row_index].plain)
            + cell_len(separator)
            + cell_len(token.plain)
            > width
        ):
            return None
        if separator:
            rows[row_index].append(separator, style=_SEPARATOR_STYLE)
        rows[row_index].append_text(token)
        row_has_token[row_index] = True
    result = Text()
    for index, row in enumerate(rows):
        if index:
            result.append("\n")
        result.append_text(row)
    return result


def _shorten_identity(
    identity: AgentModelIdentity,
    full_label: str,
    width: int,
) -> str | None:
    prefix = (
        f"{identity.provider}/"
        if full_label.startswith(f"{identity.provider}/") and identity.provider
        else ""
    )
    model = identity.model
    if prefix and cell_len(prefix) + cell_len("…") > width:
        return None
    model_width = width - cell_len(prefix)
    if cell_len(model) <= model_width:
        return full_label
    if model_width < 1:
        return None
    if model_width == 1:
        shortened = "…"
    else:
        remaining = model_width - cell_len("…")
        left_budget = (remaining + 1) // 2
        right_budget = remaining - left_budget
        left = _take_cells_from_start(model, left_budget)
        right = _take_cells_from_end(model[len(left) :], right_budget)
        shortened = f"{left}…{right}"
    return f"{prefix}{shortened}"


def _take_cells_from_start(value: str, budget: int) -> str:
    result = ""
    for character in value:
        if cell_len(result + character) > budget:
            break
        result += character
    return result


def _take_cells_from_end(value: str, budget: int) -> str:
    result = ""
    for character in reversed(value):
        if cell_len(character + result) > budget:
            break
        result = character + result
    return result


def _count_only(model_count: int, width: int, unknown_count: int) -> Text:
    if model_count <= 0:
        label = "Models: unknown"
    else:
        label = f"Models: +{model_count} more"
    if unknown_count and model_count:
        label += f" · {unknown_count} unknown"
    if cell_len(label) > width:
        label = f"M+{model_count}"
    if cell_len(label) > width:
        label = f"+{model_count}"
    if cell_len(label) > width:
        label = str(model_count % (10 ** max(width, 1)))
    if cell_len(label) > width:
        label = "…"
    result = Text(label, style=_UNKNOWN_STYLE)
    return result


def _line_count(text: Text) -> int:
    return text.plain.count("\n") + 1


__all__ = [
    "SessionModelStripFit",
    "expanded_session_model_summary",
    "fit_session_model_strip",
]

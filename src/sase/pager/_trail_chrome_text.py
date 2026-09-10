"""Cell-width text wrapping and truncation helpers for the trail chrome."""

from __future__ import annotations

from collections.abc import Iterable
import unicodedata

from rich.cells import cell_len

_ELLIPSIS = "…"


def wrap_cells(text: str, width: int) -> tuple[str, ...]:
    width = max(1, width)
    words = safe_label(text).split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        if not word:
            continue
        if not current:
            if cell_len(word) <= width:
                current = word
            else:
                lines.extend(_hard_wrap(word, width))
            continue
        candidate = f"{current} {word}"
        if cell_len(candidate) <= width:
            current = candidate
        else:
            lines.append(current)
            if cell_len(word) <= width:
                current = word
            else:
                wrapped = list(_hard_wrap(word, width))
                lines.extend(wrapped[:-1])
                current = wrapped[-1] if wrapped else ""
    if current:
        lines.append(current)
    return tuple(lines or ("",))


def _hard_wrap(text: str, width: int) -> tuple[str, ...]:
    clusters = list(_clusters(text))
    lines: list[str] = []
    current: list[str] = []
    used = 0
    for cluster in clusters:
        cluster_width = cell_len(cluster)
        if current and used + cluster_width > width:
            lines.append("".join(current))
            current = []
            used = 0
        if cluster_width > width:
            continue
        current.append(cluster)
        used += cluster_width
    if current:
        lines.append("".join(current))
    return tuple(lines or ("",))


def fit_label(label: str, budget: int) -> str:
    budget = max(0, int(budget))
    label = safe_label(label)
    if budget <= 0:
        return ""
    if cell_len(label) <= budget:
        return label
    if budget <= cell_len(_ELLIPSIS):
        return _ELLIPSIS

    ellipsis_width = cell_len(_ELLIPSIS)
    available = budget - ellipsis_width
    suffix_hint = _suffix_hint_width(label)
    suffix_budget = min(available, max(1, available // 2, suffix_hint))
    prefix_budget = available - suffix_budget
    if prefix_budget <= 0:
        return _ELLIPSIS + _take_suffix(label, available)
    return (
        _take_prefix(label, prefix_budget)
        + _ELLIPSIS
        + _take_suffix(label, suffix_budget)
    )


def fit_text(text: str, budget: int) -> str:
    budget = max(0, int(budget))
    text = safe_label(text)
    if budget <= 0:
        return ""
    if cell_len(text) <= budget:
        return text
    if budget <= cell_len(_ELLIPSIS):
        return _ELLIPSIS
    return _take_prefix(text, budget - cell_len(_ELLIPSIS)) + _ELLIPSIS


def _suffix_hint_width(label: str) -> int:
    basename = label.rsplit("/", 1)[-1]
    if "." not in basename:
        return 0
    dot = basename.rfind(".")
    if dot <= 0:
        return 0
    return min(cell_len(basename[dot:]) + 2, 12)


def _take_prefix(text: str, budget: int) -> str:
    kept: list[str] = []
    used = 0
    for cluster in _clusters(text):
        width = cell_len(cluster)
        if used + width > budget:
            break
        kept.append(cluster)
        used += width
    return "".join(kept)


def _take_suffix(text: str, budget: int) -> str:
    kept: list[str] = []
    used = 0
    for cluster in reversed(tuple(_clusters(text))):
        width = cell_len(cluster)
        if used + width > budget:
            break
        kept.append(cluster)
        used += width
    return "".join(reversed(kept))


def _clusters(text: str) -> Iterable[str]:
    current = ""
    for character in text:
        if unicodedata.combining(character) and current:
            current += character
            continue
        if current:
            yield current
        current = character
    if current:
        yield current


def safe_label(value: str) -> str:
    safe = safe_optional(value)
    return safe or "untitled"


def safe_optional(value: str) -> str:
    characters = []
    for character in value:
        category = unicodedata.category(character)
        if character in {"\n", "\r", "\t"} or category.startswith("C"):
            characters.append(" ")
        else:
            characters.append(character)
    return " ".join("".join(characters).split())

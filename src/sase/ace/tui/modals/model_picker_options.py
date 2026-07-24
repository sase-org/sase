"""Filtering and Textual option rendering for model-picker rows."""

from dataclasses import replace

from rich.text import Text
from textual.widgets._option_list import Option

from sase.ace.tui.provider_styles import model_option_text, provider_header_text

from .model_picker_rows import (
    DEFAULT_SENTINEL,
    ModelPickerRow,
    _EMPTY_SENTINEL,
    _RowKind,
    build_model_rows,
)


def _row_matches(row: ModelPickerRow, query: str) -> bool:
    if not query:
        return True
    return any(query in term for term in row.search_terms)


def filter_model_rows(
    rows: list[ModelPickerRow],
    query: str,
) -> list[ModelPickerRow]:
    """Return rows matching the filter while keeping provider groups coherent."""
    query = query.strip().lower()
    if not query:
        return rows

    special_rows = [row for row in rows if row.kind in {"default", "custom"}]
    filtered: list[ModelPickerRow] = []
    matched_targets = 0
    index = 0
    while index < len(rows):
        row = rows[index]
        if row.kind == "alias_header":
            alias_header = row
            aliases: list[ModelPickerRow] = []
            index += 1
            while index < len(rows) and rows[index].kind == "alias":
                aliases.append(rows[index])
                index += 1
            header_matches = _row_matches(alias_header, query)
            matching_aliases = (
                aliases
                if header_matches
                else [alias for alias in aliases if _row_matches(alias, query)]
            )
            if matching_aliases:
                filtered.append(
                    replace(alias_header, model_count=len(matching_aliases))
                )
                filtered.extend(matching_aliases)
                matched_targets += len(matching_aliases)
            continue
        if row.kind == "default":
            filtered.append(row)
            index += 1
            continue
        if row.kind != "provider":
            index += 1
            continue

        provider_row = row
        provider_models: list[ModelPickerRow] = []
        index += 1
        while index < len(rows) and rows[index].kind == "model":
            provider_models.append(rows[index])
            index += 1

        provider_matches = _row_matches(provider_row, query)
        matching_models = (
            provider_models
            if provider_matches
            else [model for model in provider_models if _row_matches(model, query)]
        )
        if matching_models:
            filtered.append(provider_row)
            filtered.extend(matching_models)
            matched_targets += len(matching_models)

    if matched_targets == 0:
        has_aliases = any(row.kind == "alias" for row in rows)
        filtered.append(
            ModelPickerRow(
                kind="empty",
                label=(
                    "  No matching aliases or models"
                    if has_aliases
                    else "  No matching models"
                ),
                option_id=_EMPTY_SENTINEL,
            )
        )
    filtered.extend(row for row in special_rows if row.kind == "custom")
    return filtered


def rows_to_options(
    rows: list[ModelPickerRow],
    *,
    jump_hints: dict[str, str] | None = None,
) -> list[Option | None]:
    """Render typed rows into Textual OptionList content."""
    items: list[Option | None] = []
    previous_kind: _RowKind | None = None
    for row in rows:
        if items and (
            row.kind in {"provider", "alias_header"}
            or row.kind == "custom"
            or previous_kind == "default"
        ):
            items.append(None)
        label: str | Text
        if row.kind == "alias_header":
            count = row.model_count or 0
            noun = "alias" if count == 1 else "aliases"
            label = Text("  ")
            label.append("━ ALIASES", style="bold #5FD7D7")
            label.append(f"  {count} {noun}", style="dim #87D7D7")
        elif row.kind == "alias" and row.rendered_label is not None:
            label = Text()
            hint = jump_hints.get(row.option_id) if jump_hints else None
            if hint is not None:
                label.append(f"{hint:>2} ", style="bold #87D7FF")
            else:
                label.append("   ")
            label.append_text(row.rendered_label.copy())
            label.no_wrap = True
            label.overflow = "ellipsis"
        elif row.kind == "provider" and row.provider is not None:
            label = provider_header_text(row.provider, row.model_count or 0)
        elif row.kind == "model" and row.model_id is not None:
            label = model_option_text(
                provider=row.provider,
                model_id=row.model_id,
                alias=row.alias,
                hint=jump_hints.get(row.option_id) if jump_hints else None,
            )
        elif jump_hints is not None and not row.disabled:
            hint = jump_hints.get(row.option_id)
            label = Text()
            if hint is not None:
                label.append(f"{hint:>2} ", style="bold #87D7FF")
            else:
                label.append("   ")
            label.append(row.label)
        else:
            label = row.label
        items.append(Option(label, id=row.option_id, disabled=row.disabled))
        previous_kind = row.kind
    return items


def build_model_options(*, include_default_option: bool = True) -> list[Option | None]:
    """Build the option list items grouped by provider.

    Args:
        include_default_option: If True (default), prepend the
            ``"Follow-up default"`` option that returns ``None``.
            Callers like the temporary-override modal that have no
            "use follow-up default" semantics pass ``False`` to omit it.
    """
    return rows_to_options(
        build_model_rows(include_default_option=include_default_option)
    )

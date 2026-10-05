"""Shared lossless choices-text helper for inline enum authoring."""

from __future__ import annotations

from sase.macro.models import InputChoice, MacroValidationError

__all__ = ["format_choices_text", "parse_choices_text"]


def parse_choices_text(text: str, *, name: str) -> tuple[InputChoice, ...]:
    """Parse YAML choices text into validated :class:`InputChoice` values.

    Accepts a block list or a single-line flow list such as
    ``[wip, draft, {value: ready, label: Ready}]``. Every Rust
    ``validate_enum_choices`` error surfaces as :class:`MacroValidationError`;
    nothing is silently dropped, de-duplicated, or coerced.
    """
    import yaml  # type: ignore[import-untyped]

    try:
        raw = yaml.safe_load(text) if text.strip() else None
    except yaml.YAMLError as exc:
        raise MacroValidationError(f"choices are not valid YAML: {exc}") from None
    if raw is None:
        raise MacroValidationError("enum requires at least one choice")
    if not isinstance(raw, list):
        raise MacroValidationError("choices must be a YAML list")
    if not raw:
        raise MacroValidationError("enum requires at least one choice")
    from sase.core.rust import require_rust_binding

    try:
        result = require_rust_binding("validate_enum_choices")({"items": raw})
    except ValueError as exc:
        raise MacroValidationError(str(exc)) from None
    issues = result.get("issues", [])
    errors = [
        str(issue.get("message", "invalid choice"))
        for issue in issues
        if issue.get("severity") == "error"
    ]
    if errors:
        raise MacroValidationError("; ".join(errors))
    return tuple(
        InputChoice(
            value=str(item["value"]),
            label=None if item.get("label") is None else str(item["label"]),
            description=(
                None if item.get("description") is None else str(item["description"])
            ),
        )
        for item in result.get("choices", [])
    )


def format_choices_text(choices: tuple[InputChoice, ...], *, flow: bool) -> str:
    """Serialize choices to YAML text that :func:`parse_choices_text` reads back."""
    import yaml  # type: ignore[import-untyped]

    items: list[object] = []
    for choice in choices:
        if choice.label is None and choice.description is None:
            items.append(choice.value)
        else:
            mapping: dict[str, str] = {"value": choice.value}
            if choice.label is not None:
                mapping["label"] = choice.label
            if choice.description is not None:
                mapping["description"] = choice.description
            items.append(mapping)
    text = yaml.safe_dump(
        items,
        default_flow_style=flow,
        sort_keys=False,
        allow_unicode=True,
    )
    return text.strip()

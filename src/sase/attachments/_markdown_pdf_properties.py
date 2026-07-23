"""Frontmatter preprocessing for Markdown PDF rendering."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from html import escape
from pathlib import Path
import re
import tempfile
from typing import Any

from sase.sdd.frontmatter import parse_frontmatter
from sase.sdd.plan_properties import (
    ordered_plan_property_items,
    plan_property_label,
    render_plan_value_lines,
)


def preprocess_markdown_source(
    source: Path,
    directory: Path,
    *,
    include_properties: bool,
    properties_card_markup: Callable[[Mapping[str, Any]], str],
) -> tuple[Path, str, Path | None]:
    """Replace YAML frontmatter with a rendered Properties card when enabled."""
    title = source.stem
    if not include_properties:
        return source, title, None

    content = source.read_text(encoding="utf-8")
    frontmatter, body, had_frontmatter = parse_frontmatter(content)
    if not had_frontmatter or not frontmatter:
        return source, title, None

    if "title" in frontmatter:
        title = str(frontmatter["title"])
    card = properties_card_markup(frontmatter)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{source.stem}.properties.",
            suffix=source.suffix,
            dir=directory,
            mode="w",
            encoding="utf-8",
            delete=False,
        ) as tmp:
            temporary_path = Path(tmp.name)
            tmp.write(f"{card}\n\n{body}")
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
    return temporary_path, title, temporary_path


def properties_card_markup(frontmatter: Mapping[str, Any]) -> str:
    """Render a self-contained, HTML-safe frontmatter Properties card."""
    rows = [
        (plan_property_label(key), render_plan_value_lines(value))
        for key, value in ordered_plan_property_items(frontmatter)
    ]
    container_style = (
        "background:#f6f8fa;border:1px solid #d8dee4;border-radius:4px;"
        "box-sizing:border-box;margin:0 0 1em;overflow:hidden;padding:0;"
    )
    heading_style = (
        "background:#eef1f4;border-bottom:1px solid #d8dee4;color:#111827;"
        "font-size:0.95em;font-weight:700;letter-spacing:0.01em;"
        "padding:0.5em 0.65em;"
    )
    table_style = (
        "border:0;border-collapse:collapse;margin:0;table-layout:fixed;width:100%;"
    )
    label_style = (
        "border:0;color:#57606a;font-size:0.82em;font-weight:600;"
        "padding:0.42em 0.65em;text-align:left;vertical-align:top;width:28%;"
    )
    value_style = "border:0;color:#1f2328;padding:0.42em 0.65em;vertical-align:top;"
    line_style = "line-height:1.3;margin:0;white-space:pre-wrap;"
    row_style = "border-top:1px solid #d8dee4;break-inside:avoid;"

    html_markup = [
        (
            '<div class="sase-properties" aria-label="Properties" '
            f'style="{container_style}">'
        ),
        (
            '<div class="sase-properties__heading" '
            f'style="{heading_style}">Properties</div>'
        ),
        f'<table class="sase-properties__table" style="{table_style}">',
        "<tbody>",
    ]
    for label, value_lines in rows:
        html_markup.extend(
            [
                f'<tr class="sase-properties__row" style="{row_style}">',
                (
                    '<th class="sase-properties__label" scope="row" '
                    f'style="{label_style}">{escape(label, quote=True)}</th>'
                ),
                (f'<td class="sase-properties__value" style="{value_style}">'),
            ]
        )
        for line in value_lines:
            escaped_line = escape(line, quote=True) or "&#160;"
            html_markup.append(
                '<div class="sase-properties__value-line" '
                f'style="{line_style}">{escaped_line}</div>'
            )
        html_markup.extend(["</td>", "</tr>"])
    html_markup.extend(["</tbody>", "</table>", "</div>"])

    fallback_markup = [
        '::: {.sase-properties-fallback style="display:none;"}',
        "",
        "**Properties**",
        "",
    ]
    for label, value_lines in rows:
        fallback_markup.append(f"**{escape_markdown_text(label)}:**  ")
        rendered_value = False
        for line in value_lines:
            for physical_line in plain_text_lines(line):
                physical_line = physical_line.lstrip()
                if not physical_line:
                    continue
                fallback_markup.append(f"{escape_markdown_text(physical_line)}  ")
                rendered_value = True
        if not rendered_value:
            fallback_markup.append("—  ")
        fallback_markup.append("")
    fallback_markup.append(":::")
    return "\n".join(
        [
            "```{=html}",
            *html_markup,
            "```",
            "",
            *fallback_markup,
        ]
    )


def plain_text_lines(value: str) -> list[str]:
    """Split arbitrary property text into safe physical fallback lines."""
    return value.splitlines() or [""]


def escape_markdown_text(value: str) -> str:
    """Escape arbitrary property text for the native Markdown fallback."""
    return re.sub(r"""([!"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])""", r"\\\1", value)

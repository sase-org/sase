"""Parity checks for heading ids on moved documentation pages."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from docs_moves import (  # noqa: E402
    GENERATED_FILE_RE,
    _heading_anchors,
    page_anchors,
    slugify_heading,
)


def test_heading_slug_uses_rendered_text_and_toc_normalization() -> None:
    assert slugify_heading("**Name** -r why") == "name-r-why"
    assert slugify_heading("`ace.agent_decks`") == "aceagent_decks"
    assert (
        slugify_heading("[Heading text](https://example.test/path)") == "heading-text"
    )
    assert slugify_heading("<span>Heading</span>") == "heading"
    assert slugify_heading("Caf&eacute; &amp; tea") == "cafe-tea"
    assert slugify_heading("Heading {#stable-id}") == "stable-id"


def test_heading_anchors_use_toc_unique_suffixes() -> None:
    text = (
        "## Repeat\n"
        "## Repeat\n"
        "## Repeat_1\n"
        "## Repeat_1\n"
        "## Custom {#stable-id}\n"
        "## Custom {#stable-id}\n"
    )

    assert page_anchors(text) == [
        "repeat",
        "repeat_1",
        "repeat_2",
        "repeat_3",
        "stable-id",
        "stable-id_1",
    ]


def _toc_ids(tokens: list[dict[str, object]]) -> list[str]:
    ids: list[str] = []
    for token in tokens:
        anchor = token.get("id")
        if isinstance(anchor, str):
            ids.append(anchor)
        children = token.get("children")
        if isinstance(children, list):
            ids.extend(_toc_ids(children))
    return ids


def _without_frontmatter(text: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    end = next(
        (index for index in range(1, len(lines)) if lines[index].strip() == "---"),
        None,
    )
    return "\n".join(lines[end + 1 :]) if end is not None else text


def test_page_heading_ids_match_python_markdown_toc() -> None:
    markdown = pytest.importorskip("markdown")
    config = yaml.safe_load((ROOT / "mkdocs.yml").read_text(encoding="utf-8"))
    extension_names: list[str] = []
    extension_configs: dict[str, dict[str, object]] = {}
    for extension in config["markdown_extensions"]:
        if isinstance(extension, str):
            extension_names.append(extension)
        elif isinstance(extension, dict):
            name, settings = next(iter(extension.items()))
            extension_names.append(name)
            extension_configs[name] = settings or {}

    for path in sorted(DOCS.rglob("*.md")):
        relative = path.relative_to(DOCS)
        if relative.parts[0] in {"_meta", "_templates", "_includes"}:
            continue
        text = path.read_text(encoding="utf-8")
        if GENERATED_FILE_RE.search(text):
            continue
        parser = markdown.Markdown(
            extensions=extension_names,
            extension_configs=extension_configs,
        )
        parser.convert(_without_frontmatter(text))
        expected = _toc_ids(parser.toc_tokens)
        actual = _heading_anchors(text)
        assert actual == expected, f"docs/{relative}: expected {expected}, got {actual}"

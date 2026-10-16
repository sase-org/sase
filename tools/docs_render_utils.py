"""Shared helpers for generated documentation sources."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]


def replace_generated_block(
    text: str,
    name: str,
    body: str,
    *,
    prefix: str = "<!--",
    suffix: str = "-->",
    insert_before: str | None = None,
) -> str:
    """Replace one generated block, inserting it if the file has no markers yet."""
    begin = f"{prefix} BEGIN GENERATED: {name}"
    end = f"{prefix} END GENERATED: {name}"
    if suffix:
        begin += f" {suffix}"
        end += f" {suffix}"
    if text.count(begin) != text.count(end):
        raise ValueError(f"unbalanced generated markers for {name}")
    if text.count(begin) > 1:
        raise ValueError(f"duplicate generated markers for {name}")

    replacement = f"{begin}\n{body.rstrip()}\n{end}"
    if begin in text:
        start = text.index(begin)
        finish = text.index(end, start) + len(end)
        return text[:start] + replacement + text[finish:]

    if insert_before is not None:
        match = re.search(insert_before, text, flags=re.MULTILINE)
        if match is None:
            raise ValueError(f"cannot find insertion point for generated block {name}")
        insertion = f"{replacement}\n\n"
        return text[: match.start()] + insertion + text[match.start() :]

    separator = "" if not text or text.endswith("\n\n") else "\n"
    if text and not text.endswith("\n"):
        separator = "\n\n"
    elif text and not text.endswith("\n\n"):
        separator = "\n"
    return f"{text}{separator}{replacement}\n"


def replace_generated_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return parsed YAML frontmatter and the remaining Markdown body."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    raw = text[4:end]
    metadata = yaml.safe_load(raw) or {}
    if not isinstance(metadata, dict):
        return {}, text
    return metadata, text[end + 5 :]


def markdown_title_and_description(path: Path, text: str) -> tuple[str, str]:
    """Read the title and explicit description, or derive a legacy summary."""
    metadata, body = parse_frontmatter(text)
    title_value = metadata.get("title")
    title = title_value.strip() if isinstance(title_value, str) else ""
    if not title:
        for line in body.splitlines():
            match = re.match(r"^#\s+(.+?)\s*#*\s*$", line)
            if match:
                title = match.group(1).strip()
                break
    if not title:
        title = path.stem.replace("-", " ").replace("_", " ").title()

    description = metadata.get("description")
    if isinstance(description, str) and description.strip():
        return title, " ".join(description.split())

    paragraph: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            if paragraph:
                break
            continue
        if stripped.startswith(
            ("#", "```", "~~~", "|", "<!--", ">", "- ", "<")
        ):
            if paragraph:
                if not stripped.startswith("<"):
                    break
                continue
            continue
        paragraph.append(stripped)
    sentence = " ".join(paragraph)
    code_spans: dict[str, str] = {}

    def preserve_code(match: re.Match[str]) -> str:
        token = f"DOCSCODE{len(code_spans)}TOKEN"
        code_spans[token] = match.group(1)
        return token

    sentence = re.sub(r"`([^`]+)`", preserve_code, sentence)
    sentence = re.sub(r"<[^>]*>", "", sentence)
    sentence = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", sentence)
    sentence = re.sub(r"[*_]", "", sentence)
    for token, content in code_spans.items():
        sentence = sentence.replace(token, content)
    if sentence:
        match = re.search(r"[.!?](?:\s|$)", sentence)
        if match:
            sentence = sentence[: match.end()].strip()
        return title, f"{title} — {sentence}"
    return title, title

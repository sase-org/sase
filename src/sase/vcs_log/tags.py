"""Display helpers for trailing ``SASE_*`` commit footer tags."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sase.core.vcs_log_wire import VcsCommitWire

_TAG_LINE_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
_COMMIT_TAG_PREFIX = "SASE_"


@dataclass(frozen=True)
class _SaseCommitTagView:
    """Parsed SASE-tag display data for one commit."""

    tags: tuple[tuple[str, str], ...]
    body: str


def commit_tag_view(commit: VcsCommitWire) -> _SaseCommitTagView:
    """Return stripped trailing ``SASE_*`` tags and body without that footer."""
    message = _commit_message(commit)
    body_message, footer_tags = _split_trailing_tag_block(message)
    display_tags: dict[str, str] = {}
    for key, value in footer_tags:
        if key.startswith(_COMMIT_TAG_PREFIX):
            display_tags[key[len(_COMMIT_TAG_PREFIX) :]] = value

    if not display_tags:
        return _SaseCommitTagView(tags=(), body=commit.body)

    return _SaseCommitTagView(
        tags=tuple(display_tags.items()),
        body=_body_from_message(commit, body_message),
    )


def _commit_message(commit: VcsCommitWire) -> str:
    if commit.body:
        return f"{commit.subject}\n\n{commit.body}"
    return commit.subject


def _body_from_message(commit: VcsCommitWire, message: str) -> str:
    prefix = f"{commit.subject}\n\n"
    if message.startswith(prefix):
        return message[len(prefix) :]
    if message == commit.subject:
        return ""
    return message


def _split_trailing_tag_block(message: str) -> tuple[str, list[tuple[str, str]]]:
    lines = message.split("\n")

    last_non_blank = len(lines) - 1
    while last_non_blank >= 0 and lines[last_non_blank].strip() == "":
        last_non_blank -= 1

    if last_non_blank < 0:
        return "", []

    tags_start_idx = last_non_blank + 1
    for idx in range(last_non_blank, -1, -1):
        stripped = lines[idx].strip()
        if _TAG_LINE_RE.match(stripped):
            tags_start_idx = idx
        elif stripped == "":
            continue
        else:
            break

    if tags_start_idx > last_non_blank:
        return message.rstrip(), []

    tags: list[tuple[str, str]] = []
    for line in lines[tags_start_idx : last_non_blank + 1]:
        stripped = line.strip()
        match = _TAG_LINE_RE.match(stripped)
        if match:
            tags.append((match.group(1), match.group(2)))

    body = "\n".join(lines[:tags_start_idx]).rstrip()
    return body, tags


__all__ = ["commit_tag_view"]

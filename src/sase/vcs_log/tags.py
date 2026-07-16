"""Display helpers for trailing ``SASE_*`` commit footer tags."""

from __future__ import annotations

from dataclasses import dataclass

from sase.core.commit_footer_facade import parse_commit_footer
from sase.core.vcs_log_wire import VcsCommitWire

_COMMIT_TAG_PREFIX = "SASE_"


@dataclass(frozen=True)
class _SaseCommitTagView:
    """Parsed SASE-tag display data for one commit."""

    tags: tuple[tuple[str, str], ...]
    body: str


def commit_tag_view(commit: VcsCommitWire) -> _SaseCommitTagView:
    """Return stripped trailing ``SASE_*`` tags and body without that footer."""
    message = _commit_message(commit)
    footer = parse_commit_footer(message)
    display_tags: dict[str, str] = {}
    for tag in footer.tags:
        if tag.raw_key.startswith(_COMMIT_TAG_PREFIX):
            display_tags[tag.key] = tag.label

    if not display_tags:
        return _SaseCommitTagView(tags=(), body=commit.body)

    return _SaseCommitTagView(
        tags=tuple(display_tags.items()),
        body=_body_from_message(commit, footer.body),
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


__all__ = ["commit_tag_view"]

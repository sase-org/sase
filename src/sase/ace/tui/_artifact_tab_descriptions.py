"""Resolve Artifacts pane descriptions from config, providers, and fallbacks."""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
import re
from typing import Any, Literal
import unicodedata

from sase.config import load_merged_config
from sase.config.core import current_config_token

from ._artifact_tab_model import PaneDescription

DescriptionSource = Literal["config", "provider", "builtin", "fallback"]

MAX_PANE_DESCRIPTION_SUMMARY_CHARS = 240
MAX_PANE_DESCRIPTION_BODY_CHARS = 600

BUILTIN_PANE_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "agents": (
        (
            "Every SASE agent that has run, with the prompt it was given and the work "
            "it left behind."
        ),
        (
            "Rows are agent runs, families and their shells, scoped to the selected "
            "project. Selecting one shows its identity, lifecycle, provenance, and "
            "prompt preview, and the relation panel links it to the beads it worked "
            "and the stitches it landed. Live agents belong to the Agents tab; this "
            "pane is the durable record you can query."
        ),
    ),
    "stitches": (
        "Commits landed through SASE, each one a stitch inside the Patch that carries it.",
        (
            "Rows are VCS commits across your enabled projects, narrowed by the query "
            "bar and the project scope. Selecting one shows its message, diff, and "
            "repository context, and the relation panel walks its parents, its "
            "children, and the Patch it belongs to."
        ),
    ),
    "patches": (
        (
            "SASE's unit of change: one Patch per change, with or without a PR behind "
            "it yet."
        ),
        (
            "A Patch carries a change's name, description, stitches, hooks, review "
            "comments, and mentors. Its status runs WIP, Draft, Ready, Mailed, "
            "Submitted, and a terminal Patch moves to the project archive. Selecting "
            "one shows the full spec beside its commits."
        ),
    ),
    "beads": (
        (
            "The work SASE tracks: plan and epic beads, the phases beneath them, and "
            "standalone task beads."
        ),
        (
            "Rows come from the current project's bead store, grouped by hierarchy: a "
            "plan bead owns its phase beads, and typed task beads capture follow-up "
            "work agents discovered along the way. Selecting one shows its status, "
            "size, dependencies, append-only notes, and the artifacts it references."
        ),
    ),
    "files": (
        (
            "Indexed artifact files: the snapshots agents registered, plus automatic "
            "captures from their runs."
        ),
        (
            "This is the artifact index, not every file in your repos. Explicit "
            "snapshots an agent registered are immutable and permanent, while "
            "automatic captures may be reclaimed as verified VCS locators or pruned "
            "by retention. Selecting one shows its metadata, its versions, and the "
            "agent that produced it."
        ),
    ),
    "ref:plan": (
        (
            "Plan documents from each project's plans sidecar, from proposed through "
            "approved and archived."
        ),
        (
            "Selecting a plan shows its body and its approval state. Approving one "
            "launches the epic that implements it, and the relation panel links a "
            "plan to the bead that tracks that work."
        ),
    ),
}


def resolve_pane_description(
    pane_id: str,
    *,
    label: str,
    provider_summary: object,
    provider_body: object,
) -> PaneDescription:
    """Return the resolved pane summary/body and the source rung for each."""

    configured = _configured_pane_descriptions().get(pane_id, _ConfiguredDescription())
    builtin_summary, builtin_body = BUILTIN_PANE_DESCRIPTIONS.get(pane_id, ("", ""))
    summary, summary_source = _resolve_field(
        configured.summary,
        provider_summary,
        builtin_summary,
        _fallback_summary(label),
        max_len=MAX_PANE_DESCRIPTION_SUMMARY_CHARS,
        preserve_paragraphs=False,
    )
    body, body_source = _resolve_field(
        configured.body,
        provider_body,
        builtin_body,
        "",
        max_len=MAX_PANE_DESCRIPTION_BODY_CHARS,
        preserve_paragraphs=True,
    )
    return PaneDescription(
        summary=summary,
        body=body,
        summary_source=summary_source,
        body_source=body_source,
    )


def sanitize_description(
    raw: object,
    *,
    max_len: int,
    preserve_paragraphs: bool = False,
) -> str:
    """Return terminal-safe description text, or ``""`` for unusable input."""

    if not isinstance(raw, str):
        return ""
    if preserve_paragraphs:
        text = _sanitize_body(raw)
    else:
        text = _sanitize_summary(raw)
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text


class _ConfiguredDescription:
    __slots__ = ("summary", "body")

    def __init__(self, summary: str = "", body: str = "") -> None:
        self.summary = summary
        self.body = body


def _configured_pane_descriptions() -> dict[str, _ConfiguredDescription]:
    return _configured_pane_descriptions_for_token(current_config_token())


@lru_cache(maxsize=1)
def _configured_pane_descriptions_for_token(
    _token: tuple[Any, ...],
) -> dict[str, _ConfiguredDescription]:
    try:
        config = load_merged_config()
    except Exception:
        return {}
    if not isinstance(config, Mapping):
        return {}
    ace = config.get("ace", {})
    if not isinstance(ace, Mapping):
        return {}
    artifacts = ace.get("artifacts", {})
    if not isinstance(artifacts, Mapping):
        return {}
    panes = artifacts.get("panes", {})
    if not isinstance(panes, Mapping):
        return {}

    descriptions: dict[str, _ConfiguredDescription] = {}
    for pane_id, raw in panes.items():
        if not isinstance(pane_id, str) or not isinstance(raw, Mapping):
            continue
        summary = sanitize_description(
            raw.get("description"),
            max_len=MAX_PANE_DESCRIPTION_SUMMARY_CHARS,
        )
        body = sanitize_description(
            raw.get("description_body"),
            max_len=MAX_PANE_DESCRIPTION_BODY_CHARS,
            preserve_paragraphs=True,
        )
        if summary or body:
            descriptions[pane_id] = _ConfiguredDescription(summary, body)
    return descriptions


def _resolve_field(
    config_value: str,
    provider_value: object,
    builtin_value: str,
    fallback_value: str,
    *,
    max_len: int,
    preserve_paragraphs: bool,
) -> tuple[str, DescriptionSource]:
    candidates: tuple[tuple[object, DescriptionSource], ...] = (
        (config_value, "config"),
        (provider_value, "provider"),
        (builtin_value, "builtin"),
        (fallback_value, "fallback"),
    )
    for value, source in candidates:
        text = sanitize_description(
            value,
            max_len=max_len,
            preserve_paragraphs=preserve_paragraphs,
        )
        if text:
            return text, source
    return "", "fallback"


def _fallback_summary(label: str) -> str:
    safe_label = sanitize_description(
        label,
        max_len=80,
    )
    if not safe_label:
        safe_label = "Document"
    return f"{safe_label} documents contributed by this project's sidecar repos."


def _sanitize_summary(raw: str) -> str:
    collapsed = re.sub(r"\s+", " ", raw)
    return _strip_control_characters(collapsed).strip()


def _sanitize_body(raw: str) -> str:
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = []
    for paragraph in re.split(r"\n[ \t]*\n+", normalized):
        text = _strip_control_characters(re.sub(r"\s+", " ", paragraph)).strip()
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def _strip_control_characters(value: str) -> str:
    return "".join(char for char in value if unicodedata.category(char) != "Cc")


__all__ = [
    "BUILTIN_PANE_DESCRIPTIONS",
    "MAX_PANE_DESCRIPTION_BODY_CHARS",
    "MAX_PANE_DESCRIPTION_SUMMARY_CHARS",
    "resolve_pane_description",
    "sanitize_description",
]

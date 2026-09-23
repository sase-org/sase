"""Prompt digests and grouping for tribe PROMPTS sections.

Worker-side, pure presentation logic over already-loaded rows and existing
artifact files: every digest is computed off the Textual event loop and cached
by raw-text hash, so the renderer only appends precomputed strings and replays
precomputed style spans.
"""

from __future__ import annotations

import re
import threading
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import blake2b
from typing import TYPE_CHECKING

from sase.history.prompt_metadata import summarize_prompt_for_list
from sase.xprompt import extract_project_from_vcs_tag, extract_vcs_workflow_tag

from ..._agent_completion_prompt import split_prompt_preamble
from ...util.xprompt_syntax import xprompt_overlay_spans
from ._agent_display_clan_sections_common import humanize_prompt_body

if TYPE_CHECKING:
    from ...models.agent import Agent
    from ._agent_tribe_aggregation import TribeUnitSource

from ...models._agent_clan_sections import (
    ClanAgentIdentity,
    ClanDiskMemberSnapshot,
    first_meaningful_line,
)

type StyleSpan = tuple[str, int, int]  # (rich style, start, end) relative to one string

_HEADLINE_MAX_CHARS = 120
_DIGEST_CACHE_MAX_ENTRIES = 1024
_HEADING_MARKER_RE = re.compile(r"#{1,6}\s+")
_FENCE_LINE_PREFIX = "```"


@dataclass(frozen=True, slots=True)
class PromptDigest:
    """Content-only digest of one raw prompt text; cached by raw-text hash."""

    group_key: str  # 12-hex blake2b of f"{project}\0{collapsed body}"
    headline: str  # humanized, <=120 chars
    headline_spans: tuple[StyleSpan, ...]
    body: str  # humanized, preamble-stripped, rstripped; line structure preserved
    body_spans: tuple[StyleSpan, ...]
    body_line_count: int
    launch: str  # humanized, whitespace-collapsed preamble (no frontmatter)
    launch_spans: tuple[StyleSpan, ...]
    xprompts: tuple[str, ...]  # <=3 xprompt chips from the body
    project: str | None  # short display name of the prompt's VCS/project target


@dataclass(frozen=True, slots=True)
class TribePromptMember:
    """One roster row attributed to a prompt group."""

    unit_identity: ClanAgentIdentity
    unit_label: str
    member_identity: ClanAgentIdentity
    member_label: str  # source.labels value: unit label for the unit root

    @property
    def is_unit_root(self) -> bool:
        """Return whether this member is its unit's roster root."""
        return self.member_identity == self.unit_identity


@dataclass(frozen=True, slots=True)
class TribePromptGroup:
    """One distinct prompt plus every roster row that launched it."""

    digest: PromptDigest  # the representative (first) member's digest
    members: tuple[TribePromptMember, ...]


@dataclass(frozen=True, slots=True)
class TribePromptsSnapshot:
    """Renderer-facing prompt groups for one tribe panel."""

    groups: tuple[TribePromptGroup, ...]
    agent_count: int  # members across all groups
    multi_project: bool  # >1 distinct non-None project across groups


_digest_cache: OrderedDict[tuple[str, object], PromptDigest] = OrderedDict()
_digest_cache_lock = threading.Lock()


def build_tribe_prompts(
    sources: Sequence[TribeUnitSource],
    member_snapshots: Mapping[ClanAgentIdentity, ClanDiskMemberSnapshot],
) -> TribePromptsSnapshot:
    """Group roster rows by distinct prompt body in first-appearance order.

    Identical prompt bodies (same project, same text once the launch preamble
    is stripped and whitespace is collapsed) are listed once; the first member
    is the representative whose digest renders.
    """
    ordered: dict[str, tuple[PromptDigest, list[TribePromptMember]]] = {}
    for source in sources:
        for row in source.rows:
            if row.is_monitor or row.is_gate or row.is_proc_shell:
                continue
            snapshot = member_snapshots.get(row.identity)
            if snapshot is None:
                continue
            raw = _select_member_raw(row, snapshot)
            if not raw:
                continue
            digest = _digest_for_raw(raw)
            member = TribePromptMember(
                unit_identity=source.unit_identity,
                unit_label=source.unit_label,
                member_identity=row.identity,
                member_label=source.labels.get(row.identity, snapshot.member_label),
            )
            existing = ordered.get(digest.group_key)
            if existing is None:
                ordered[digest.group_key] = (digest, [member])
            else:
                existing[1].append(member)
    groups = tuple(
        TribePromptGroup(digest=digest, members=tuple(members))
        for digest, members in ordered.values()
    )
    projects = {
        group.digest.project for group in groups if group.digest.project is not None
    }
    return TribePromptsSnapshot(
        groups=groups,
        agent_count=sum(len(group.members) for group in groups),
        multi_project=len(projects) > 1,
    )


def _select_member_raw(
    row: Agent,
    snapshot: ClanDiskMemberSnapshot,
) -> str | None:
    """Return the raw prompt text that represents *row*, if any."""
    bodies: dict[str, str] = {}
    for entry in snapshot.prompts:
        bodies.setdefault(entry.kind, entry.body)
    if row.is_workflow_step_child:
        # A step's shared raw_xprompt.md belongs to the parent workflow, so a
        # step only ever contributes its own step prompt.
        if row.step_type != "agent":
            return None
        return bodies.get("AGENT PROMPT") or None
    # Every other row prefers the authored xprompt, falling back to the
    # selected prompt file only for historical rows without one.
    return bodies.get("AGENT XPROMPT") or bodies.get("AGENT PROMPT") or None


def _digest_for_raw(raw: str) -> PromptDigest:
    """Return the cached digest for one raw prompt text."""
    key = (_raw_digest_key(raw), _catalog_signature())
    with _digest_cache_lock:
        cached = _digest_cache.get(key)
        if cached is not None:
            _digest_cache.move_to_end(key)
            return cached
    try:
        digest = _build_digest(raw)
    except Exception:
        digest = _fallback_digest(raw)
    with _digest_cache_lock:
        _digest_cache[key] = digest
        _digest_cache.move_to_end(key)
        while len(_digest_cache) > _DIGEST_CACHE_MAX_ENTRIES:
            _digest_cache.popitem(last=False)
    return digest


def _raw_digest_key(raw: str) -> str:
    return blake2b(raw.encode("utf-8", errors="replace"), digest_size=16).hexdigest()


def _catalog_signature() -> object:
    """Return the warm tag-catalog signature, or ``None`` when cold."""
    try:
        from sase.project_tags.catalog import peek_project_tag_catalog_signature

        return peek_project_tag_catalog_signature()
    except Exception:
        return None


def _build_digest(raw: str) -> PromptDigest:
    preamble, raw_body = split_prompt_preamble(raw)
    stripped_body = raw_body.strip()
    collapsed_preamble = " ".join(preamble.split())
    project = _digest_project(raw)
    headline = _truncate_headline(
        _first_paragraph_headline(stripped_body)
        or collapsed_preamble
        or first_meaningful_line(raw)
    )
    humanized_headline = humanize_prompt_body(headline)
    humanized_body = humanize_prompt_body(stripped_body)
    humanized_launch = humanize_prompt_body(collapsed_preamble) if preamble else ""
    chips = _digest_chips(stripped_body, humanized_headline)
    collapsed = " ".join(stripped_body.split())
    group_key = blake2b(
        f"{project or ''}\0{collapsed}".encode("utf-8", errors="replace"),
        digest_size=6,
    ).hexdigest()
    return PromptDigest(
        group_key=group_key,
        headline=humanized_headline,
        headline_spans=tuple(xprompt_overlay_spans(humanized_headline)),
        body=humanized_body,
        body_spans=tuple(xprompt_overlay_spans(humanized_body)),
        body_line_count=humanized_body.count("\n") + 1 if humanized_body else 0,
        launch=humanized_launch,
        launch_spans=tuple(xprompt_overlay_spans(humanized_launch)),
        xprompts=chips,
        project=project,
    )


def _fallback_digest(raw: str) -> PromptDigest:
    """Return a plain digest so one malformed prompt never fails the worker."""
    try:
        collapsed = " ".join(raw.split())
        group_key = blake2b(
            f"\0{collapsed}".encode("utf-8", errors="replace"), digest_size=6
        ).hexdigest()
    except Exception:
        group_key = "fallback"
    return PromptDigest(
        group_key=group_key,
        headline=first_meaningful_line(raw),
        headline_spans=(),
        body=raw,
        body_spans=(),
        body_line_count=raw.count("\n") + 1 if raw else 0,
        launch="",
        launch_spans=(),
        xprompts=(),
        project=None,
    )


def _digest_project(raw: str) -> str | None:
    """Return the display project for one raw prompt, failing open.

    Only catalog-known targets count (D5): Patch refs, ``owner/repo``
    refs, and unknown names return ``None`` so they never gain a
    made-up ``+`` chip and never flip ``multi_project``. A known
    ``+<project>`` tag returns its bare name; a known but untaggable
    name returns its ``#<workflow>:`` spelling. A cold catalog returns
    ``None``.
    """
    try:
        tag = extract_vcs_workflow_tag(raw)
    except Exception:
        return None
    if not tag:
        return None
    try:
        ref = extract_project_from_vcs_tag(tag)
    except Exception:
        return None
    if not ref:
        return None
    try:
        from sase.project_tags import known_project_tag_for
        from sase.project_tags.catalog import peek_project_tag_catalog

        catalog = peek_project_tag_catalog()
    except Exception:
        return None
    if catalog is None:
        return None
    try:
        spelling = known_project_tag_for(catalog, ref)
    except Exception:
        return None
    if not spelling:
        return None
    if spelling.startswith("+"):
        return spelling[1:] or None
    return spelling


def _first_paragraph_headline(body: str) -> str:
    """Return the whitespace-collapsed first paragraph of *body*.

    Leading blank lines are skipped; the paragraph ends at the first blank
    line or fence line. An xprompt-only body therefore keeps its invocation
    with arguments, and a leading Markdown heading marker is stripped.
    """
    lines = body.splitlines()
    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1
    parts: list[str] = []
    while index < len(lines):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith(_FENCE_LINE_PREFIX):
            break
        parts.append(line.strip())
        index += 1
    headline = " ".join(" ".join(parts).split())
    return _HEADING_MARKER_RE.sub("", headline, count=1)


def _truncate_headline(headline: str, *, max_chars: int = _HEADLINE_MAX_CHARS) -> str:
    """Truncate *headline* to *max_chars* at a word boundary with ``…``."""
    if len(headline) <= max_chars:
        return headline
    cut = headline[: max_chars - 1].rsplit(" ", 1)[0].rstrip()
    if not cut:
        cut = headline[: max_chars - 1].rstrip()
    return cut + "…"


def _digest_chips(body: str, headline: str) -> tuple[str, ...]:
    """Return up to 3 xprompt chips from *body*, excluding headline text.

    Chips come from the preamble-stripped body so directive-argument
    false positives (such as Rich color markup) can never appear.
    """
    try:
        chips = summarize_prompt_for_list(body).xprompts
    except Exception:
        return ()
    return tuple(chip for chip in chips if chip not in headline)[:3]


__all__ = [
    "PromptDigest",
    "StyleSpan",
    "TribePromptGroup",
    "TribePromptMember",
    "TribePromptsSnapshot",
    "build_tribe_prompts",
]

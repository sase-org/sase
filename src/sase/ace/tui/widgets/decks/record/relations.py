"""Record Relations and Links cards (epic sase-1jm.4.2)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from rich.text import Text

from sase.ace.dismissed_bundle_index import query_summaries
from sase.ace.tui.relations.artifact_links import load_artifact_links_snapshot
from sase.ace.tui.relations.link_index import LinkChip, link_index_for_snapshot
from sase.artifact_ref_entries import reference_for_agent_name

from ..card_part import CardPart
from .model import RecordSubject


@dataclass(frozen=True)
class ArtifactLinkGroup:
    """Links to neighbors with the same direction and relation."""

    direction: Literal["outgoing", "incoming", "related"]
    relation: str
    label: str
    neighbor_refs: tuple[str, ...]


@dataclass(frozen=True)
class RelationsExtras:
    """Off-thread Relations/Links inputs."""

    resolved_refs: tuple[tuple[str, str], ...] = ()
    link_groups: tuple[ArtifactLinkGroup, ...] = ()
    snapshot_source_key: tuple[object, ...] | None = None
    snapshot_error: str | None = None


_RELATION_SUFFIXES = (
    ("parent", "parent_timestamp"),
    ("retry_of", "retry_of_timestamp"),
    ("retried_as", "retried_as_timestamp"),
)
_LINK_GROUP_LIMIT = 3
_DIRECTION_ORDER: dict[str, int] = {"outgoing": 0, "incoming": 1, "related": 2}


def _copyable_agent_ref(name: str | None) -> str | None:
    """Return the durable, paste-ready agent reference for ``name``."""

    if not name:
        return None
    value = name.strip()
    if not value:
        return None
    if value.startswith("@agent:"):
        return value
    if value.startswith("agent:"):
        return f"@{value}"
    try:
        reference = reference_for_agent_name(value)
    except Exception:  # noqa: BLE001 - a stale identity snapshot degrades to the name.
        reference = None
    return f"@{reference}" if reference else f"@agent:{value}"


def _summary_name(summary: object) -> str | None:
    """Get a durable name from one archive summary, tolerating old rows."""

    name = getattr(summary, "agent_name", None) or getattr(summary, "cl_name", None)
    return name if isinstance(name, str) and name else None


def _resolve_related_names(subject: RecordSubject) -> dict[str, str]:
    """Resolve parent/retry suffixes from live rows, then the archive index."""

    suffix_by_relation = {
        relation: getattr(subject, field_name)
        for relation, field_name in _RELATION_SUFFIXES
        if getattr(subject, field_name)
    }
    if not suffix_by_relation:
        return {}

    live_names: dict[str, str] = {}
    for suffix, name in subject.related_live_names:
        live_names.setdefault(suffix, name)

    suffixes = set(suffix_by_relation.values())
    resolved_names = dict(live_names)
    missing_suffixes = suffixes - live_names.keys()
    if missing_suffixes:
        try:
            from sase.ace.dismissed_agents import dismissed_bundles_dir

            summaries = query_summaries(
                dismissed_bundles_dir(),
                suffixes=missing_suffixes,
                visibility=None,
            )
        except Exception:  # noqa: BLE001 - missing archive index keeps raw suffixes.
            summaries = None
        if summaries:
            preferred: dict[str, tuple[bool, str]] = {}
            for summary in summaries:
                summary_suffix = getattr(summary, "raw_suffix", None)
                summary_name = _summary_name(summary)
                if (
                    not isinstance(summary_suffix, str)
                    or summary_suffix not in missing_suffixes
                    or not summary_name
                ):
                    continue
                is_child = bool(getattr(summary, "is_workflow_child", False))
                current = preferred.get(summary_suffix)
                if current is None or (current[0] and not is_child):
                    preferred[summary_suffix] = (is_child, summary_name)
            resolved_names.update(
                (suffix, selected[1]) for suffix, selected in preferred.items()
            )

    resolved_refs: dict[str, str] = {}
    for relation, suffix in suffix_by_relation.items():
        resolved_name = resolved_names.get(suffix)
        reference = _copyable_agent_ref(resolved_name)
        if reference:
            resolved_refs[relation] = reference
    return resolved_refs


def _link_groups(chips: tuple[LinkChip, ...]) -> tuple[ArtifactLinkGroup, ...]:
    grouped: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for chip in chips:
        direction: Literal["outgoing", "incoming", "related"]
        if not chip.directed:
            direction = "related"
        elif chip.this_is_source:
            direction = "outgoing"
        else:
            direction = "incoming"
        grouped[(direction, chip.relation, chip.label)].append(chip.neighbor_ref)

    groups = [
        ArtifactLinkGroup(
            direction=direction,  # type: ignore[arg-type]
            relation=relation,
            label=label,
            neighbor_refs=tuple(dict.fromkeys(refs)),
        )
        for (direction, relation, label), refs in grouped.items()
    ]
    return tuple(
        sorted(
            groups,
            key=lambda group: (
                _DIRECTION_ORDER[group.direction],
                group.label.casefold(),
                group.relation,
            ),
        )
    )


def load_relations_extras(subject: RecordSubject) -> RelationsExtras:
    """Resolve relation references and links on the Record worker thread."""

    resolved_refs = _resolve_related_names(subject)
    for key, name in (
        ("session", subject.presented_session_name or subject.agent_session),
        ("clan", subject.presented_clan_name or subject.agent_clan),
        ("workflow", subject.parent_workflow),
    ):
        reference = _copyable_agent_ref(name)
        if reference:
            resolved_refs[key] = reference

    source_key: tuple[object, ...] | None = None
    snapshot_error: str | None = None
    groups: tuple[ArtifactLinkGroup, ...] = ()
    try:
        snapshot = load_artifact_links_snapshot(None)
        source_key = tuple(snapshot.source_key)
        if snapshot.errors:
            snapshot_error = "; ".join(snapshot.errors[:2])
        if subject.agent_name:
            reference = reference_for_agent_name(subject.agent_name)
            if reference:
                chips = link_index_for_snapshot(snapshot).chips_for(reference)
                groups = _link_groups(chips)
    except Exception as exc:  # noqa: BLE001 - links degrade without breaking the card.
        snapshot_error = str(exc) or exc.__class__.__name__

    return RelationsExtras(
        resolved_refs=tuple(sorted(resolved_refs.items())),
        link_groups=groups,
        snapshot_source_key=source_key,
        snapshot_error=snapshot_error,
    )


def _append_ref(text: Text, reference: str | None, fallback: str | None) -> None:
    if reference:
        text.append(reference, style="bold #87D7FF")
    elif fallback:
        raw = fallback if fallback.startswith("@agent:") else f"@agent:{fallback}"
        text.append(raw, style="dim")
    else:
        text.append("—", style="dim")


def relations_card(subject: RecordSubject, extras: RelationsExtras) -> CardPart:
    """Build the Relations card from pump-captured facts and worker extras."""

    refs = dict(extras.resolved_refs)
    text = Text()
    rows = 0

    if subject.agent_session or subject.presented_session_name:
        text.append("Session: ", style="bold")
        _append_ref(
            text,
            refs.get("session"),
            subject.presented_session_name or subject.agent_session,
        )
        if subject.agent_session_role:
            text.append(f" · {subject.agent_session_role}", style="dim")
        text.append("\n")
        rows += 1

    if subject.agent_clan or subject.presented_clan_name:
        text.append("Clan: ", style="bold")
        _append_ref(
            text,
            refs.get("clan"),
            subject.presented_clan_name or subject.agent_clan,
        )
        if subject.agent_clan_generation:
            text.append(f" · generation {subject.agent_clan_generation}", style="dim")
        text.append("\n")
        rows += 1

    if subject.parent_timestamp:
        text.append("Parent: ", style="bold")
        _append_ref(text, refs.get("parent"), subject.parent_timestamp)
        text.append("\n")
        rows += 1

    if subject.parent_workflow:
        text.append("Workflow: ", style="bold")
        _append_ref(text, refs.get("workflow"), subject.parent_workflow)
        text.append("\n")
        rows += 1

    retry_of = bool(subject.retry_of_timestamp)
    retried_as = bool(subject.retried_as_timestamp)
    if retry_of or retried_as:
        text.append("Retry: ", style="bold")
        if retry_of:
            _append_ref(text, refs.get("retry_of"), subject.retry_of_timestamp)
        if retry_of and retried_as:
            text.append(" → ", style="dim")
        if retried_as:
            _append_ref(text, refs.get("retried_as"), subject.retried_as_timestamp)
        if subject.retry_attempt > 0:
            text.append(f" · attempt {subject.retry_attempt}", style="dim")
        text.append("\n")
        rows += 1

    if not rows:
        text.append("No relations", style="dim italic")
    elif text.plain.endswith("\n"):
        text.rstrip()
    return CardPart("relations", "Relations", text)


def links_card(subject: RecordSubject, extras: RelationsExtras) -> CardPart:
    """Build grouped, direction-aware artifact link chips."""

    del subject
    text = Text()
    for group in extras.link_groups:
        direction = {
            "outgoing": "Outgoing",
            "incoming": "Incoming",
            "related": "Related",
        }[group.direction]
        text.append(f"{direction} · {group.label}\n", style="bold")
        visible = group.neighbor_refs[:_LINK_GROUP_LIMIT]
        for reference in visible:
            text.append("  ")
            text.append(reference, style="bold #87D7FF")
            text.append("\n")
        remaining = len(group.neighbor_refs) - len(visible)
        if remaining:
            text.append(f"  +{remaining} more\n", style="dim")

    if not extras.link_groups:
        text.append("No artifact links", style="dim italic")
    elif text.plain.endswith("\n"):
        text.rstrip()
    if extras.snapshot_error:
        if text.plain:
            text.append("\n")
        text.append(f"Link index unavailable: {extras.snapshot_error}", style="dim")
    return CardPart("links", "Links", text)


__all__ = [
    "ArtifactLinkGroup",
    "RelationsExtras",
    "links_card",
    "load_relations_extras",
    "relations_card",
]

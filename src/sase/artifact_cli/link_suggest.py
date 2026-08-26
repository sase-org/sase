"""Ephemeral hard-evidence suggestions for ``sase artifact link``."""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from itertools import combinations
import json
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sase.artifact_links.derive import DerivableDocument, derive_research_swarm_lineage
from sase.artifact_links.read_candidates import rank_read_citation_candidates
from sase.artifact_read_log import ArtifactReadEvent, read_artifact_read_events
from sase.sdd._artifact_link_store_support import store_backed_rows
from sase.sdd.artifact_link_store import (
    ArtifactLinkStore,
    canonicalize_artifact_link_ref,
    resolve_artifact_link_store,
)
from sase.sdd.referenced_by_index import REFERENCED_BY_LINKS_DIR


_SIGNAL_ORDER = {
    "filename-lineage": 0,
    "shared-bead": 1,
    "shared-epic": 2,
    "overlapping-reads": 3,
    "read-log": 4,
}


@dataclass(frozen=True, slots=True)
class _ArtifactLinkSuggestion:
    """One write-free link suggestion plus the hard evidence behind it."""

    source_ref: str
    relation: str
    target_ref: str
    description: str
    signal: str
    evidence: tuple[str, ...]


def handle_link_suggest(args: argparse.Namespace) -> int:
    """Print hard-evidence link suggestions without mutating the store."""

    try:
        store = resolve_artifact_link_store()
        suggestions = _suggest_artifact_links(
            store,
            reference=getattr(args, "reference", None),
            limit=getattr(args, "limit", 50),
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if bool(getattr(args, "json", False)):
        json.dump(
            [asdict(suggestion) for suggestion in suggestions], sys.stdout, indent=2
        )
        sys.stdout.write("\n")
        return 0

    _print_suggestions(suggestions, reference=getattr(args, "reference", None))
    return 0


def _suggest_artifact_links(
    store: ArtifactLinkStore,
    *,
    reference: str | None = None,
    limit: int = 50,
) -> tuple[_ArtifactLinkSuggestion, ...]:
    """Return missing suggestions from hard evidence only.

    The function writes nothing. Existing persisted links are exclusions, with
    ``related`` treated as undirected to avoid reporting the inverse of a stored row.
    """

    canonical_reference = (
        None if reference is None else canonicalize_artifact_link_ref(reference)
    )
    rows = tuple(store_backed_rows(store.load_aggregate().get("rows", [])))
    collector = _SuggestionCollector(rows, reference=canonical_reference)
    _collect_filename_lineage(collector, store)
    _collect_shared_bead_and_epic(collector, rows)
    events = _read_events(store)
    _collect_overlapping_read_sets(collector, events)
    _collect_read_log_candidates(collector, events)
    suggestions = sorted(collector.suggestions(), key=_suggestion_sort_key)
    if limit > 0:
        suggestions = suggestions[:limit]
    return tuple(suggestions)


class _SuggestionCollector:
    def __init__(
        self,
        rows: Iterable[Mapping[str, Any]],
        *,
        reference: str | None,
    ) -> None:
        self._reference = reference
        self._existing = _existing_link_keys(rows)
        self._suggestions: dict[tuple[str, str, str], _ArtifactLinkSuggestion] = {}

    def add(
        self,
        *,
        source_ref: str,
        relation: str,
        target_ref: str,
        description: str,
        signal: str,
        evidence: Iterable[str],
    ) -> None:
        source = canonicalize_artifact_link_ref(source_ref)
        target = canonicalize_artifact_link_ref(target_ref)
        if source == target:
            return
        if self._reference is not None and self._reference not in {source, target}:
            return
        if _link_exists(self._existing, source, relation, target):
            return
        key = _suggestion_key(source, relation, target)
        new_evidence = tuple(item for item in evidence if item)
        if not new_evidence:
            return
        current = self._suggestions.get(key)
        if current is None:
            self._suggestions[key] = _ArtifactLinkSuggestion(
                source_ref=key[0],
                relation=key[1],
                target_ref=key[2],
                description=_one_line(description),
                signal=signal,
                evidence=new_evidence,
            )
            return
        merged_evidence = tuple(dict.fromkeys((*current.evidence, *new_evidence)))
        self._suggestions[key] = _ArtifactLinkSuggestion(
            source_ref=current.source_ref,
            relation=current.relation,
            target_ref=current.target_ref,
            description=current.description,
            signal=current.signal,
            evidence=merged_evidence,
        )

    def suggestions(self) -> tuple[_ArtifactLinkSuggestion, ...]:
        return tuple(self._suggestions.values())


def _existing_link_keys(
    rows: Iterable[Mapping[str, Any]],
) -> frozenset[tuple[str, str, str]]:
    keys: set[tuple[str, str, str]] = set()
    for row in rows:
        source = str(row.get("source_ref") or "")
        relation = str(row.get("relation") or "")
        target = str(row.get("target_ref") or "")
        if source and relation and target:
            keys.add(_suggestion_key(source, relation, target))
    return frozenset(keys)


def _link_exists(
    existing: frozenset[tuple[str, str, str]],
    source: str,
    relation: str,
    target: str,
) -> bool:
    return _suggestion_key(source, relation, target) in existing


def _suggestion_key(source: str, relation: str, target: str) -> tuple[str, str, str]:
    if relation == "related" and target < source:
        return (target, relation, source)
    return (source, relation, target)


def _collect_filename_lineage(
    collector: _SuggestionCollector,
    store: ArtifactLinkStore,
) -> None:
    root = store.sidecar_roots.get("research")
    if root is None or not root.is_dir():
        return
    resolved_root = root.expanduser().resolve(strict=False)
    for path in sorted(resolved_root.rglob("*.md")):
        relative = path.relative_to(resolved_root)
        if relative.parts[:1] == (REFERENCED_BY_LINKS_DIR,):
            continue
        ref = canonicalize_artifact_link_ref(f"research:{relative.as_posix()}")
        for candidate in derive_research_swarm_lineage(
            DerivableDocument(ref=ref, path=path)
        ):
            collector.add(
                source_ref=candidate.source_ref,
                relation=candidate.relation,
                target_ref=candidate.target_ref,
                description=candidate.description,
                signal="filename-lineage",
                evidence=(f"{Path(candidate.target_ref).name} is a sibling source",),
            )


def _collect_shared_bead_and_epic(
    collector: _SuggestionCollector,
    rows: Iterable[Mapping[str, Any]],
) -> None:
    bead_to_refs: dict[str, set[str]] = defaultdict(set)
    ref_to_beads: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        source = str(row.get("source_ref") or "")
        target = str(row.get("target_ref") or "")
        if source.startswith("bead:") and target and not target.startswith("bead:"):
            bead_to_refs[source].add(target)
            ref_to_beads[target].add(source)
        if target.startswith("bead:") and source and not source.startswith("bead:"):
            bead_to_refs[target].add(source)
            ref_to_beads[source].add(target)

    for bead, refs in sorted(bead_to_refs.items()):
        for left, right in combinations(sorted(refs), 2):
            collector.add(
                source_ref=left,
                relation="related",
                target_ref=right,
                description=f"both artifacts are linked to {bead}",
                signal="shared-bead",
                evidence=(f"shared bead {bead}",),
            )

    epic_to_refs: dict[str, set[str]] = defaultdict(set)
    for ref, beads in ref_to_beads.items():
        for bead in beads:
            epic_to_refs[_epic_ref_for_bead(bead)].add(ref)
    for epic_ref, refs in sorted(epic_to_refs.items()):
        for left, right in combinations(sorted(refs), 2):
            left_beads = ", ".join(sorted(ref_to_beads[left])[:3])
            right_beads = ", ".join(sorted(ref_to_beads[right])[:3])
            collector.add(
                source_ref=left,
                relation="related",
                target_ref=right,
                description=f"both artifacts are linked to beads under {epic_ref}",
                signal="shared-epic",
                evidence=(f"{left_beads} and {right_beads} share {epic_ref}",),
            )


def _epic_ref_for_bead(bead_ref: str) -> str:
    bead_id = bead_ref.removeprefix("bead:")
    return f"bead:{bead_id.split('.', 1)[0]}"


def _read_events(store: ArtifactLinkStore) -> tuple[ArtifactReadEvent, ...]:
    try:
        return read_artifact_read_events(project=store.project_key)
    except Exception:  # noqa: BLE001 - suggestions are best-effort diagnostics.
        return ()


def _collect_read_log_candidates(
    collector: _SuggestionCollector,
    events: tuple[ArtifactReadEvent, ...],
) -> None:
    for candidate in rank_read_citation_candidates(events):
        collector.add(
            source_ref=f"agent:{candidate.agent_name}",
            relation="read",
            target_ref=candidate.ref,
            description=candidate.reason,
            signal="read-log",
            evidence=(
                f"audited read recorded {candidate.reads} time(s)",
                f"latest read {candidate.latest_timestamp}",
                f"reason: {candidate.reason}",
            ),
        )


def _collect_overlapping_read_sets(
    collector: _SuggestionCollector,
    events: tuple[ArtifactReadEvent, ...],
) -> None:
    refs_by_agent: dict[str, set[str]] = defaultdict(set)
    latest_reason: dict[tuple[str, str], ArtifactReadEvent] = {}
    for event in events:
        ref = canonicalize_artifact_link_ref(event.ref)
        refs_by_agent[event.agent_name].add(ref)
        key = (event.agent_name, ref)
        current = latest_reason.get(key)
        if current is None or event.timestamp >= current.timestamp:
            latest_reason[key] = event

    evidence_by_pair: dict[tuple[str, str], list[str]] = defaultdict(list)
    for agent, refs in sorted(refs_by_agent.items()):
        for left, right in combinations(sorted(refs), 2):
            reason_left = latest_reason[(agent, left)].reason
            reason_right = latest_reason[(agent, right)].reason
            evidence_by_pair[(left, right)].append(
                f"{agent} read both ({reason_left}; {reason_right})"
            )

    for (left, right), evidence in sorted(evidence_by_pair.items()):
        collector.add(
            source_ref=left,
            relation="related",
            target_ref=right,
            description=f"{len(evidence)} agent(s) read both artifacts",
            signal="overlapping-reads",
            evidence=tuple(evidence[:5]),
        )


def _suggestion_sort_key(
    suggestion: _ArtifactLinkSuggestion,
) -> tuple[int, int, str, str, str]:
    return (
        -len(suggestion.evidence),
        _SIGNAL_ORDER.get(suggestion.signal, 99),
        suggestion.source_ref,
        suggestion.relation,
        suggestion.target_ref,
    )


def _one_line(value: str) -> str:
    return " ".join(value.strip().splitlines())[:240]


def _print_suggestions(
    suggestions: tuple[_ArtifactLinkSuggestion, ...],
    *,
    reference: str | None,
) -> None:
    title = (
        f"Artifact link suggestions for {reference} ({len(suggestions)})"
        if reference
        else f"Artifact link suggestions ({len(suggestions)})"
    )
    console = Console()
    if not suggestions:
        console.print(
            Panel(
                "[dim]No hard-evidence link suggestions found.[/dim]",
                title=title,
                border_style="cyan",
            )
        )
        return

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("SIGNAL", no_wrap=True)
    table.add_column("RELATION", no_wrap=True)
    table.add_column("SOURCE", style="bold")
    table.add_column("TARGET", style="bold")
    table.add_column("EVIDENCE")
    table.add_column("WHY")
    for suggestion in suggestions:
        table.add_row(
            suggestion.signal,
            suggestion.relation,
            suggestion.source_ref,
            suggestion.target_ref,
            " · ".join(suggestion.evidence),
            suggestion.description or "-",
        )
    console.print(Panel(table, title=title, border_style="cyan"))


__all__ = [
    "handle_link_suggest",
]

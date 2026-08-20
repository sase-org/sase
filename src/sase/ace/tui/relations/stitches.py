"""Stitches relation source: commit parents and SASE_PATCH links."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sase.ace.tui._artifact_tab_model import ArtifactsPaneContract
from sase.ace.tui.relations.artifact_links import (
    ArtifactLinksSnapshot,
    artifact_link_edges,
)
from sase.ace.tui.relations._support import decls_by_name, emit_edge
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relations import (
    RelationEdge,
    RelationIndex,
    RelationSource,
    build_relation_index,
)
from sase.core.vcs_log_wire import AggregatedCommitWire
from sase.vcs_log.tags import commit_tag_view


def build_stitches_relation_index(
    entries: Sequence[AggregatedCommitWire],
    *,
    contract: ArtifactsPaneContract,
    project_keys_by_repo: Mapping[str, str],
    artifact_links: ArtifactLinksSnapshot | None = None,
) -> RelationIndex:
    """Build the host-owned Stitches relation index for *entries*."""
    source = _StitchesRelationSource(entries, contract, project_keys_by_repo)
    known = source.known_targets()
    project_hint = next(iter(project_keys_by_repo.values()), None)
    return build_relation_index(
        pane_id=source.pane_id,
        relations=source.relations(),
        edges=(
            *source.raw_edges(),
            *artifact_link_edges(
                artifact_links,
                contract=contract,
                known_targets=known,
                project_hint=project_hint,
            ),
        ),
        known_targets=known,
    )


def _commit_target(repo: str, full_id: str) -> ArtifactEntryTarget:
    return ArtifactEntryTarget(pane_id="stitches", parts=(repo, full_id))


class _StitchesRelationSource(RelationSource):
    def __init__(
        self,
        entries: Sequence[AggregatedCommitWire],
        contract: ArtifactsPaneContract,
        project_keys_by_repo: Mapping[str, str],
    ) -> None:
        self._entries = tuple(entries)
        self._contract = contract
        self._decls = decls_by_name(contract)
        self._project_keys = project_keys_by_repo

    @property
    def pane_id(self) -> str:
        return self._contract.id

    def relations(self) -> tuple:
        return self._contract.relations

    def known_targets(self) -> frozenset[ArtifactEntryTarget]:
        return frozenset(
            _commit_target(entry.repo, entry.commit.full_id) for entry in self._entries
        )

    def raw_edges(self) -> tuple[RelationEdge, ...]:
        edges: list[RelationEdge] = []
        parents = self._decls.get("parents")
        patches = self._decls.get("patches")
        for entry in self._entries:
            source = _commit_target(entry.repo, entry.commit.full_id)
            if parents is not None:
                for parent_id in entry.commit.parent_ids:
                    edges.append(
                        emit_edge(
                            parents,
                            source,
                            _commit_target(entry.repo, parent_id),
                        )
                    )
            if patches is None:
                continue
            patch_name = _sase_patch_name(entry)
            if not patch_name:
                continue
            project_key = self._project_keys.get(entry.repo) or entry.repo
            edges.append(
                emit_edge(
                    patches,
                    source,
                    ArtifactEntryTarget(
                        pane_id="patches",
                        parts=(project_key, patch_name),
                    ),
                )
            )
        return tuple(edges)


def _sase_patch_name(entry: AggregatedCommitWire) -> str | None:
    for key, label in commit_tag_view(entry.commit).tags:
        if key in {"PATCH", "SASE_PATCH"} and label.strip():
            return label.strip()
    return None

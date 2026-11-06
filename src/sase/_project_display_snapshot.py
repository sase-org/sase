"""Immutable project identity-to-display snapshot types."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from sase.core.project_lifecycle_wire import (
    ProjectRecordWire,
    effective_project_name,
)
from sase.project_alias_records import project_alias_map_from_records


@dataclass(frozen=True, slots=True)
class ProjectDisplayProjection:
    """Paired canonical identity and human-facing label for one project."""

    project_key: str
    project_label: str

    @property
    def sort_key(self) -> tuple[str, str]:
        """Return the visible-label/canonical-key presentation sort key."""
        return (self.project_label.casefold(), self.project_key)


@dataclass(frozen=True, slots=True)
class ProjectDisplaySnapshot(Mapping[str, str]):
    """Immutable batch projection from canonical project keys to labels.

    Duplicate labels remain distinct entries because canonical keys own
    identity. Unknown or deleted keys resolve to themselves through
    :meth:`label_for` and :meth:`projection_for`.
    """

    labels_by_key: Mapping[str, str] = field(default_factory=dict, repr=False)
    projections: tuple[ProjectDisplayProjection, ...] = field(init=False)
    signature: tuple[tuple[str, str], ...] = field(init=False)

    def __post_init__(self) -> None:
        labels = MappingProxyType(dict(self.labels_by_key))
        projections = tuple(
            sorted(
                (
                    ProjectDisplayProjection(project_key, project_label)
                    for project_key, project_label in labels.items()
                ),
                key=lambda projection: projection.sort_key,
            )
        )
        object.__setattr__(self, "labels_by_key", labels)
        object.__setattr__(self, "projections", projections)
        object.__setattr__(self, "signature", tuple(sorted(labels.items())))

    @classmethod
    def from_records(
        cls,
        records: Iterable[ProjectRecordWire],
    ) -> ProjectDisplaySnapshot:
        """Build one immutable snapshot from one lifecycle-record batch."""
        return cls(
            {record.project_name: effective_project_name(record) for record in records}
        )

    def __getitem__(self, project_key: str) -> str:
        return self.labels_by_key[project_key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.labels_by_key)

    def __len__(self) -> int:
        return len(self.labels_by_key)

    def label_for(self, project_key: str) -> str:
        """Resolve *project_key* to its label, falling back to the key."""
        return self.labels_by_key.get(project_key, project_key)

    def projection_for(self, project_key: str) -> ProjectDisplayProjection:
        """Return a paired identity/label projection for *project_key*."""
        return ProjectDisplayProjection(project_key, self.label_for(project_key))


def project_display_name_for_ref(
    project_ref: str | None,
    display_snapshot: ProjectDisplaySnapshot,
    aliases: Mapping[str, str],
) -> str | None:
    """Project one known key, alias, or label to its configured label.

    Unknown refs stay unchanged so ad-hoc namespaces remain usable. Keys and
    aliases use their canonical spelling; configured labels also match
    case-insensitively because they are already presentation values.
    """
    if not project_ref:
        return None
    if project_ref in display_snapshot:
        return display_snapshot[project_ref]

    project_key = aliases.get(project_ref)
    if project_key is not None and project_key in display_snapshot:
        return display_snapshot[project_key]

    folded = project_ref.casefold()
    for projection in display_snapshot.projections:
        if projection.project_label.casefold() == folded:
            return projection.project_label
    return project_ref


def _unambiguous_folded_refs(
    refs: Iterable[tuple[str, str]],
) -> Mapping[str, str]:
    """Return casefolded refs whose canonical owner is unambiguous."""
    owners: dict[str, str] = {}
    conflicts: set[str] = set()
    for ref, project_key in refs:
        folded = ref.casefold()
        existing = owners.get(folded)
        if existing is not None and existing != project_key:
            owners.pop(folded, None)
            conflicts.add(folded)
        elif folded not in conflicts:
            owners[folded] = project_key
    return MappingProxyType(owners)


@dataclass(frozen=True, slots=True)
class ProjectRefDisplaySnapshot:
    """Immutable project-ref projection built from one lifecycle inventory."""

    display_snapshot: ProjectDisplaySnapshot = field(
        default_factory=ProjectDisplaySnapshot
    )
    aliases: Mapping[str, str] = field(default_factory=dict, repr=False)
    _project_keys_by_folded_ref: Mapping[str, str] = field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        aliases = MappingProxyType(dict(self.aliases))
        refs = [(project_key, project_key) for project_key in self.display_snapshot]
        refs.extend(aliases.items())
        refs.extend(
            (projection.project_label, projection.project_key)
            for projection in self.display_snapshot.projections
        )
        object.__setattr__(self, "aliases", aliases)
        object.__setattr__(
            self,
            "_project_keys_by_folded_ref",
            _unambiguous_folded_refs(refs),
        )

    @classmethod
    def from_records(
        cls,
        records: Iterable[ProjectRecordWire],
    ) -> ProjectRefDisplaySnapshot:
        """Build key, label, and alias projections from one record batch."""
        record_batch = list(records)
        return cls(
            display_snapshot=ProjectDisplaySnapshot.from_records(record_batch),
            aliases=project_alias_map_from_records(record_batch, strict=False),
        )

    def label_for_ref(self, project_ref: str | None) -> str | None:
        """Return the configured label for one known ref."""
        return project_display_name_for_ref(
            project_ref,
            self.display_snapshot,
            self.aliases,
        )

    def project_key_for_ref(self, project_ref: str | None) -> str | None:
        """Resolve a key, alias, or label to canonical identity for selection."""
        if not project_ref:
            return None
        return self._project_keys_by_folded_ref.get(project_ref.casefold())

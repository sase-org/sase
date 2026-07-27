"""Pure lane-kinship projection and Markdown rendering."""

from __future__ import annotations

from dataclasses import dataclass

from sase.agents_sync.rendering_markdown import (
    md_cell,
    md_escape,
    relative_page_url,
    state_counts,
)
from sase.agents_sync.v2_models import (
    V2ContainerRecord,
    V2HoodSnapshot,
    V2RunRecord,
)
from sase.core.agent_identity_facade import (
    agent_link_target,
    agent_name_ancestors,
)

NEIGHBOR_GROUP_LIMIT = 50


@dataclass(frozen=True, slots=True)
class _LaneKinshipRow:
    """One related lane on a published agent or family page."""

    lane_name: str
    relation: str
    page_path: str
    state: str
    is_family: bool
    member_count: int


@dataclass(frozen=True, slots=True)
class _LaneKinshipGroup:
    """One bounded relation group in projection order."""

    relation: str
    rows: tuple[_LaneKinshipRow, ...]
    overflow_count: int = 0


@dataclass(frozen=True, slots=True)
class _LaneKinshipProjection:
    """The ordered neighbor groups for one lane."""

    lane_name: str
    groups: tuple[_LaneKinshipGroup, ...]

    @property
    def rows(self) -> tuple[_LaneKinshipRow, ...]:
        """Return the visible rows flattened in rendered order."""

        return tuple(row for group in self.groups for row in group.rows)


@dataclass(frozen=True, slots=True)
class HoodKinshipProjection:
    """All name-derived lane projections for one hood snapshot."""

    lanes: tuple[_LaneKinshipProjection, ...]
    source_lanes: tuple[tuple[str, str], ...]
    hood_page_path: str

    def for_lane(self, lane_name: str) -> _LaneKinshipProjection:
        """Return a lane projection, including an empty compatibility fallback."""

        for projection in self.lanes:
            if projection.lane_name == lane_name:
                return projection
        return _LaneKinshipProjection(lane_name, ())

    def lane_for_source(self, source_run_id: str) -> str:
        """Return the authoritative family-or-solo lane for a source run."""

        for candidate_id, lane_name in self.source_lanes:
            if candidate_id == source_run_id:
                return lane_name
        raise KeyError(source_run_id)


@dataclass(frozen=True, slots=True)
class _Lane:
    name: str
    page_path: str
    runs: tuple[V2RunRecord, ...]
    is_family: bool
    chain: tuple[str, ...]

    def row(self, relation: str) -> _LaneKinshipRow:
        state = state_counts(self.runs) if self.is_family else self.runs[0].state
        return _LaneKinshipRow(
            lane_name=self.name,
            relation=relation,
            page_path=self.page_path,
            state=state,
            is_family=self.is_family,
            member_count=len(self.runs),
        )


def build_hood_kinship(snapshot: V2HoodSnapshot) -> HoodKinshipProjection:
    """Build every lane-relative kinship roster for one hood snapshot."""

    by_id = {run.source_run_id: run for run in snapshot.runs}
    family_by_member: dict[str, V2ContainerRecord] = {}
    lanes: list[_Lane] = []
    owner_prefix = f"{snapshot.owner.username}.{snapshot.owner.machine_name}."

    for container in snapshot.containers:
        if container.kind != "family":
            continue
        members = tuple(
            by_id[source_id] for source_id in container.member_source_run_ids
        )
        lane_name = container.global_name.removeprefix(owner_prefix)
        lanes.append(
            _Lane(
                name=lane_name,
                page_path=f"families/{container.global_name}.md",
                runs=members,
                is_family=True,
                chain=agent_name_ancestors(lane_name),
            )
        )
        for source_id in container.member_source_run_ids:
            family_by_member[source_id] = container

    for run in snapshot.runs:
        if run.source_run_id in family_by_member:
            continue
        target = agent_link_target(run.local_name, snapshot.owner)
        page_path = target.path
        if not page_path.startswith("agents/"):
            page_path = f"agents/{run.global_name}/README.md"
        lanes.append(
            _Lane(
                name=run.local_name,
                page_path=page_path,
                runs=(run,),
                is_family=False,
                chain=agent_name_ancestors(run.local_name),
            )
        )

    ordered_lanes = tuple(sorted(lanes, key=_lane_sort_key))
    by_name = {lane.name: lane for lane in ordered_lanes}
    projections = tuple(
        _lane_projection(lane, ordered_lanes, by_name) for lane in ordered_lanes
    )
    family_lane_names = {
        source_id: container.global_name.removeprefix(owner_prefix)
        for source_id, container in family_by_member.items()
    }
    source_lanes = tuple(
        (run.source_run_id, family_lane_names.get(run.source_run_id, run.local_name))
        for run in snapshot.runs
    )
    hood_page_path = (
        f"users/{snapshot.owner.username}/machines/{snapshot.owner.machine_name}"
        f"/hoods/{snapshot.local_hood}/README.md"
    )
    return HoodKinshipProjection(projections, source_lanes, hood_page_path)


def render_neighbors_section(
    kinship: HoodKinshipProjection,
    *,
    lane_name: str,
    source_path: str,
) -> list[str]:
    """Render the shared Neighbors section for an agent or family page."""

    projection = kinship.for_lane(lane_name)
    if not projection.groups:
        return []
    lines = [
        "## Neighbors",
        "",
        "| Agent | Relation | State |",
        "|---|---|---|",
    ]
    roster_url = relative_page_url(source_path, kinship.hood_page_path)
    for group in projection.groups:
        for row in group.rows:
            label = f"[{md_escape(row.lane_name)}]("
            label += relative_page_url(source_path, row.page_path) + ")"
            if row.is_family:
                label += f" (family · {row.member_count})"
            lines.append(
                f"| {label} | {md_cell(row.relation)} | {md_cell(row.state)} |"
            )
        if group.overflow_count:
            lines.append(
                f"| … and {group.overflow_count} more in the "
                f"[hood roster]({roster_url}) | {md_cell(group.relation)} | — |"
            )
    lines.append("")
    return lines


def _lane_projection(
    lane: _Lane,
    lanes: tuple[_Lane, ...],
    by_name: dict[str, _Lane],
) -> _LaneKinshipProjection:
    assigned = {lane.name}
    groups: list[_LaneKinshipGroup] = []

    ancestors = [
        by_name[name]
        for name in reversed(lane.chain[:-1])
        if name in by_name and name not in assigned
    ]
    if ancestors:
        groups.append(_bounded_group("ancestor", ancestors))
        assigned.update(item.name for item in ancestors)

    descendants = sorted(
        (
            candidate
            for candidate in lanes
            if lane.name in candidate.chain[:-1] and candidate.name not in assigned
        ),
        key=_lane_sort_key,
    )
    if descendants:
        groups.append(_bounded_group("descendant", descendants))
        assigned.update(item.name for item in descendants)

    for hood in reversed(lane.chain):
        neighbors = sorted(
            (
                candidate
                for candidate in lanes
                if hood in candidate.chain and candidate.name not in assigned
            ),
            key=_lane_sort_key,
        )
        if not neighbors:
            continue
        relation = f"{hood} hood"
        groups.append(_bounded_group(relation, neighbors))
        assigned.update(item.name for item in neighbors)

    return _LaneKinshipProjection(lane.name, tuple(groups))


def _bounded_group(relation: str, lanes: list[_Lane]) -> _LaneKinshipGroup:
    visible = lanes[:NEIGHBOR_GROUP_LIMIT]
    return _LaneKinshipGroup(
        relation=relation,
        rows=tuple(lane.row(relation) for lane in visible),
        overflow_count=len(lanes) - len(visible),
    )


def _lane_sort_key(lane: _Lane) -> tuple[str, str]:
    return lane.name.casefold(), lane.name


__all__ = [
    "HoodKinshipProjection",
    "NEIGHBOR_GROUP_LIMIT",
    "build_hood_kinship",
    "render_neighbors_section",
]

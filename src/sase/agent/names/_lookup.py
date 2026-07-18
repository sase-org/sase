"""Find named agents and inspect workflow completion status.

:func:`find_named_agent` consumes the agent-artifact snapshot produced
by :func:`sase.core.agent_scan_facade.scan_agent_artifacts` so name
lookup benefits from a single Rust filesystem walk of
``~/.sase/projects/*/artifacts/ace-run/*`` rather than independently
re-walking the tree per call.

:func:`is_workflow_complete` deliberately does NOT use the snapshot
facade. The snapshot path would materialize wire records for every
artifact in the tree before any predicate can run, which previously
measured as a ~3× regression on this hot path. Instead it does a
targeted direct-walk that only loads ``agent_meta.json`` files matching
``workflow_name == name``.

Process liveness, dismissed-bundle fallback, and dismissal-prefix
semantics stay in Python.

Name lookup and completion checks intentionally scan agent artifacts across
all project lifecycle states. A disabled project's historical artifacts can
still own names or complete workflows referenced by prompts, repeat launches,
and diagnostics.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sase.agent.names._common import (
    NamedAgent,
    is_dismissed_prefixed,
    is_process_alive,
)
from sase.agent.names._templates import resolve_agent_name_template_reference
from sase.plan_chain import (
    AGENT_FAMILY_FIELD,
    agent_family_base,
    is_agent_family_member,
    is_plan_chain_artifact_meta,
)
from sase.core.paths import sase_projects_dir

if TYPE_CHECKING:
    from sase.core.agent_scan_wire import AgentArtifactRecordWire

_SUCCESS_OUTCOME = "completed"


@dataclass(frozen=True)
class AgentFamilyMember:
    """One artifact member of a plan-chain agent family."""

    name: str
    artifacts_dir: Path
    timestamp: str
    outcome: str | None
    parent_timestamp: str | None

    @property
    def is_done(self) -> bool:
        return self.outcome is not None


@dataclass(frozen=True)
class AgentFamily:
    """Newest known generation of a plan-chain agent family."""

    base_name: str
    root: AgentFamilyMember | None
    members: tuple[AgentFamilyMember, ...]

    @property
    def timestamp(self) -> str:
        if self.root is not None:
            return self.root.timestamp
        return max((member.timestamp for member in self.members), default="")

    @property
    def newest_member_timestamp(self) -> str:
        return max(
            (member.timestamp for member in self.members), default=self.timestamp
        )


@dataclass(frozen=True)
class AgentClanMember:
    """One artifact member of an agent clan."""

    name: str
    artifacts_dir: Path
    timestamp: str
    outcome: str | None
    generation: str

    @property
    def is_done(self) -> bool:
        return self.outcome is not None


@dataclass(frozen=True)
class AgentClan:
    """Newest known generation of a rootless agent clan."""

    name: str
    generation: str
    members: tuple[AgentClanMember, ...]

    @property
    def newest_member_timestamp(self) -> str:
        return max((member.timestamp for member in self.members), default="")

    @property
    def is_complete(self) -> bool:
        return bool(self.members) and all(
            member.outcome == _SUCCESS_OUTCOME for member in self.members
        )


def _ace_run_scan_options() -> Any:
    """Return the scan-facade options for ace-run-only name lookups.

    Imported lazily to avoid the agent-scan facade pulling in the TUI
    loader package at ``sase.agent`` import time (the loader package
    transitively depends back on ``sase.agent.names``).
    """
    from sase.core.agent_scan_wire import AgentArtifactScanOptionsWire

    return AgentArtifactScanOptionsWire(
        only_workflow_dirs=("ace-run",),
        include_prompt_step_markers=False,
        include_raw_prompt_snippets=False,
    )


def _projects_root() -> Path:
    return sase_projects_dir()


def _iter_ace_run_artifact_dirs(*, newest_first: bool = False) -> Iterator[Path]:
    projects_dir = _projects_root()
    if not projects_dir.exists():
        return
    from sase.core.agent_artifact_paths import iter_agent_artifact_dirs

    try:
        project_iter = projects_dir.iterdir()
    except OSError:
        return
    for project_dir in project_iter:
        if not project_dir.is_dir():
            continue
        yield from iter_agent_artifact_dirs(
            project_dir.name,
            "ace-run",
            projects_root=projects_dir,
            newest_first=newest_first,
        )


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _done_outcome(artifact_dir: Path) -> str | None:
    done_data = _read_json_dict(artifact_dir / "done.json")
    if done_data is None:
        return None
    outcome = done_data.get("outcome")
    return outcome if isinstance(outcome, str) else None


def _meta_parent_timestamp(meta: dict[str, Any]) -> str | None:
    value = meta.get("parent_timestamp")
    return value if isinstance(value, str) and value else None


def _family_base_from_meta(meta: dict[str, Any]) -> str | None:
    family = meta.get(AGENT_FAMILY_FIELD)
    if isinstance(family, str) and family:
        return family

    workflow_name = meta.get("workflow_name")
    if not isinstance(workflow_name, str) or not workflow_name:
        return None

    if is_plan_chain_artifact_meta(meta):
        return workflow_name

    name = meta.get("name")
    if isinstance(name, str) and agent_family_base(name) == workflow_name:
        return workflow_name

    return None


def _iter_family_members(base_name: str) -> list[AgentFamilyMember]:
    members: list[AgentFamilyMember] = []
    for artifact_dir in _iter_ace_run_artifact_dirs():
        meta = _read_json_dict(artifact_dir / "agent_meta.json")
        if meta is None or _family_base_from_meta(meta) != base_name:
            continue

        name_value = meta.get("name")
        name = name_value if isinstance(name_value, str) else base_name
        members.append(
            AgentFamilyMember(
                name=name,
                artifacts_dir=artifact_dir,
                timestamp=artifact_dir.name,
                outcome=_done_outcome(artifact_dir),
                parent_timestamp=_meta_parent_timestamp(meta),
            )
        )

    return members


def _clan_identity_from_meta(
    meta: dict[str, Any], artifact_dir: Path
) -> tuple[str, str] | None:
    clan = meta.get("agent_clan")
    legacy_parallel = meta.get("agent_family_parallel") is True
    if not isinstance(clan, str) or not clan:
        legacy_family = meta.get(AGENT_FAMILY_FIELD)
        if (
            not legacy_parallel
            or not isinstance(legacy_family, str)
            or not legacy_family
        ):
            return None
        clan = legacy_family

    generation = meta.get("agent_clan_generation")
    if not isinstance(generation, str) or not generation:
        parent_timestamp = _meta_parent_timestamp(meta)
        generation = parent_timestamp or artifact_dir.name
    return clan, generation


def _iter_clan_members(clan_name: str) -> list[AgentClanMember]:
    members: list[AgentClanMember] = []
    for artifact_dir in _iter_ace_run_artifact_dirs():
        meta = _read_json_dict(artifact_dir / "agent_meta.json")
        if meta is None:
            continue
        identity = _clan_identity_from_meta(meta, artifact_dir)
        if identity is None or identity[0] != clan_name:
            continue
        name = meta.get("name")
        if not isinstance(name, str) or not name:
            continue
        members.append(
            AgentClanMember(
                name=name,
                artifacts_dir=artifact_dir,
                timestamp=artifact_dir.name,
                outcome=_done_outcome(artifact_dir),
                generation=identity[1],
            )
        )
    return members


def find_agent_clan(clan_name: str) -> AgentClan | None:
    """Return the newest known generation of *clan_name*."""
    members = _iter_clan_members(clan_name)
    if not members:
        return None
    generation = max(member.generation for member in members)
    generation_members = tuple(
        sorted(
            (member for member in members if member.generation == generation),
            key=lambda member: member.timestamp,
        )
    )
    return AgentClan(
        name=clan_name,
        generation=generation,
        members=generation_members,
    )


def is_agent_clan_complete(clan_name: str) -> bool | None:
    """Return whether every member of the newest clan generation completed."""
    clan = find_agent_clan(clan_name)
    return None if clan is None else clan.is_complete


def most_recent_completed_clan_member(clan_name: str) -> NamedAgent | None:
    """Return the newest successful member once the whole clan is complete."""
    clan = find_agent_clan(clan_name)
    if clan is None or not clan.is_complete:
        return None
    member = max(clan.members, key=lambda item: item.timestamp)
    return NamedAgent(
        name=member.name,
        artifacts_dir=str(member.artifacts_dir),
        is_done=True,
        outcome=member.outcome,
    )


def find_agent_family(base_name: str) -> AgentFamily | None:
    """Return the newest known generation for *base_name*.

    Only plan-chain/family metadata is considered. Plain exact agents named
    ``base_name`` are intentionally excluded so legacy exact-name lookups keep
    their existing behavior when no family members exist.
    """
    if not base_name or is_agent_family_member(base_name):
        return None

    members = _iter_family_members(base_name)
    if not members:
        return None

    roots = [member for member in members if member.parent_timestamp is None]
    if roots:
        root = max(roots, key=lambda member: member.timestamp)
        generation_members = [root]
        generation_timestamps = {root.timestamp}
        remaining = [member for member in members if member is not root]
        while remaining:
            attached = [
                member
                for member in remaining
                if member.parent_timestamp in generation_timestamps
            ]
            if not attached:
                break
            generation_members.extend(attached)
            generation_timestamps.update(member.timestamp for member in attached)
            remaining = [member for member in remaining if member not in attached]
        generation = tuple(
            sorted(generation_members, key=lambda member: member.timestamp)
        )
        return AgentFamily(base_name=base_name, root=root, members=generation)

    # Legacy recovery path: if only child artifacts remain, treat all known
    # family members as one generation and let timestamp ordering choose the
    # newest completed handoff member.
    return AgentFamily(
        base_name=base_name,
        root=None,
        members=tuple(sorted(members, key=lambda member: member.timestamp)),
    )


def is_agent_family_complete(base_name: str) -> bool | None:
    """Return whether the newest *base_name* family generation completed."""
    family = find_agent_family(base_name)
    if family is None:
        return None
    if not family.members:
        return False
    return all(member.outcome == _SUCCESS_OUTCOME for member in family.members)


def most_recent_completed_family_member(base_name: str) -> NamedAgent | None:
    """Return the newest successful member of the newest *base_name* family."""
    family = find_agent_family(base_name)
    if family is None:
        return None

    completed = [
        member for member in family.members if member.outcome == _SUCCESS_OUTCOME
    ]
    if not completed:
        return None

    member = max(completed, key=lambda item: item.timestamp)
    return NamedAgent(
        name=member.name,
        artifacts_dir=str(member.artifacts_dir),
        is_done=True,
        outcome=member.outcome,
    )


def _self_parallel_family_root(
    base_name: str,
) -> tuple[bool, NamedAgent | None]:
    """Return this member's generation-pinned root for a base-name reference."""
    artifacts_value = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_value:
        return False, None
    artifacts_dir = Path(artifacts_value)
    meta = _read_json_dict(artifacts_dir / "agent_meta.json")
    if meta is None:
        return False, None
    if meta.get("agent_family_parallel") is not True:
        return False, None
    if meta.get(AGENT_FAMILY_FIELD) != base_name:
        return False, None
    parent_timestamp = _meta_parent_timestamp(meta)
    if parent_timestamp is None:
        return False, None

    family = find_agent_family(base_name)
    if (
        family is not None
        and family.root is not None
        and family.root.timestamp == parent_timestamp
    ):
        root = family.root
        return True, NamedAgent(
            name=root.name,
            artifacts_dir=str(root.artifacts_dir),
            is_done=root.is_done,
            outcome=root.outcome,
        )

    # Exact-name recovery covers a plain pre-existing root that acquired a
    # late parallel member but does not itself carry family metadata.
    exact = find_named_agent(base_name)
    if exact is not None and Path(exact.artifacts_dir).name == parent_timestamp:
        return True, exact
    return True, None


def resolve_resume_agent_name(name: str) -> NamedAgent | None:
    """Resolve a ``#fork`` target to the artifact that should provide chat.

    Direct child references such as ``foo-code`` and legacy ``foo.code`` remain
    exact lookups. A root family reference such as ``foo`` resolves to the most
    recent successful member of the newest family generation, falling back to
    exact-name behavior when no family exists.
    """
    name = resolve_agent_name_template_reference(name)
    clan_member = most_recent_completed_clan_member(name)
    if clan_member is not None:
        return clan_member
    is_self_family, self_root = _self_parallel_family_root(name)
    if is_self_family:
        if (
            self_root is not None
            and self_root.is_done
            and self_root.outcome == _SUCCESS_OUTCOME
        ):
            return self_root
        return None
    if not is_agent_family_member(name):
        family_member = most_recent_completed_family_member(name)
        if family_member is not None:
            return family_member
    return find_named_agent(name, only_done=True)


def resolve_wait_dependency(name: str) -> bool:
    """Return whether a wait dependency has completed successfully.

    Tribe waits require the waiting artifact's launch cutoff and therefore
    resolve only through ``WaitDependencyIndex`` runner callers.
    """
    from sase.core.agent_tribe import InvalidTagError, parse_tribe_reference

    try:
        if parse_tribe_reference(name) is not None:
            return False
    except InvalidTagError:
        return False
    clan_complete = is_agent_clan_complete(name)
    if clan_complete is not None:
        return clan_complete
    is_self_family, self_root = _self_parallel_family_root(name)
    if is_self_family:
        return bool(
            self_root is not None
            and self_root.is_done
            and self_root.outcome == _SUCCESS_OUTCOME
        )
    complete = is_agent_family_complete(name)
    if complete is not None:
        return complete

    agent = find_named_agent(name, only_done=True)
    return agent is not None and agent.outcome == _SUCCESS_OUTCOME


def _meta_dict(record: AgentArtifactRecordWire) -> dict[str, Any]:
    """Project the record's ``agent_meta`` fields needed by ``is_process_alive``.

    ``is_process_alive`` only reads ``pid`` and ``stopped_at``; the wire
    carries both. Returning a dict keeps the helper untouched and avoids
    re-reading ``agent_meta.json`` from disk.
    """
    meta = record.agent_meta
    if meta is None:
        return {}
    out: dict[str, Any] = {}
    if meta.pid is not None:
        out["pid"] = meta.pid
    if meta.stopped_at is not None:
        out["stopped_at"] = meta.stopped_at
    return out


def find_named_agent(name: str, *, only_done: bool = False) -> NamedAgent | None:
    """Find a named agent by scanning all project artifacts.

    Consults the snapshot returned by
    :func:`sase.core.agent_scan_facade.scan_agent_artifacts` for every
    ``~/.sase/projects/*/artifacts/ace-run/*/agent_meta.json`` whose
    ``"name"`` or ``"workflow_name"`` field matches *name*.

    Prefers running (non-done) agents over completed ones.  Exact ``name``
    matches take priority over ``workflow_name`` matches.  Among workflow
    matches, the most recent (by timestamp) is preferred.

    Args:
        name: The agent name to search for.
        only_done: When True, ignore running candidates and return only
            historical/done matches.

    Returns:
        A NamedAgent if found, or None.
    """
    projects_dir = _projects_root()
    if not projects_dir.exists():
        # Fall through to dismissed-bundle fallback below.
        return _find_named_dismissed_bundle(name)

    from sase.core.agent_scan_facade import scan_agent_artifacts

    snapshot = scan_agent_artifacts(projects_dir, _ace_run_scan_options())

    best_match: NamedAgent | None = None
    best_priority: tuple[int, str] = (0, "")

    for record in snapshot.records:
        if record.workflow_dir_name != "ace-run":
            continue
        meta = record.agent_meta
        if meta is None:
            continue

        exact = meta.name == name
        workflow = meta.workflow_name == name
        if not exact and not workflow:
            continue

        artifact_dir = Path(record.artifact_dir)
        is_done = False
        outcome: str | None = None
        if record.has_done_marker:
            is_done = True
            if record.done is not None:
                outcome = record.done.outcome
        elif is_dismissed_prefixed(name):
            # Dismissal removes done.json but preserves the prefixed
            # agent_meta.json. Treat such artifacts as historical so
            # `%w:260428.foo` and `#fork:260428.foo` still resolve.
            is_done = True
            outcome = "dismissed"

        agent = NamedAgent(
            name=name,
            artifacts_dir=str(artifact_dir),
            is_done=is_done,
            outcome=outcome,
        )

        # Running agents take priority — return immediately,
        # but only if the process is actually alive.  Parent-phase
        # artifacts (e.g. .plan) share the agent name yet never
        # write done.json; without a liveness check we'd return
        # them as "running" and block wait resolution forever.
        # For workflow matches, only return the root agent
        # (no parent_timestamp) to avoid matching intermediate steps.
        if not is_done:
            if not only_done and is_process_alive(_meta_dict(record), artifact_dir):
                if exact or not meta.parent_timestamp:
                    return agent
            continue

        # Done agent — prefer exact matches over workflow matches,
        # and most recent timestamp within each category.
        priority = (1 if exact else 0, record.timestamp)
        if priority > best_priority:
            best_match = agent
            best_priority = priority

    if best_match is None:
        # Fall back to dismissed bundles. After dismissal the artifact
        # directory may be partially or fully gone, but the bundle still
        # carries the prefixed agent_name and cl_name for historical
        # reference.
        bundle_match = _find_named_dismissed_bundle(name)
        if bundle_match is not None:
            return bundle_match

    return best_match


def _find_named_dismissed_bundle(name: str) -> NamedAgent | None:
    """Return a dismissed-bundle match for *name*, or ``None``.

    Scans ``~/.sase/dismissed_bundles`` for a bundle whose ``agent_name``
    or ``workflow_name`` equals *name*. Used as a fallback when artifact
    directories no longer carry the metadata (e.g. dismissed agents whose
    artifact dir was cleaned up).
    """
    try:
        from sase.ace import dismissed_agents
    except Exception:
        return None

    bundles_dir = dismissed_agents.dismissed_bundles_dir()
    if not bundles_dir.is_dir():
        return None

    best: NamedAgent | None = None
    best_ts = ""
    try:
        candidates = list(bundles_dir.rglob("*.json"))
    except OSError:
        return None

    for filepath in candidates:
        if not filepath.is_file():
            continue
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue

        if data.get("agent_name") != name and data.get("workflow_name") != name:
            continue

        raw_suffix = data.get("raw_suffix")
        ts = raw_suffix if isinstance(raw_suffix, str) else filepath.stem
        if ts <= best_ts:
            continue
        artifacts_dir = data.get("artifacts_dir")
        best = NamedAgent(
            name=name,
            artifacts_dir=str(artifacts_dir) if artifacts_dir else str(filepath.parent),
            is_done=True,
            outcome="dismissed",
        )
        best_ts = ts

    return best


def is_workflow_complete(name: str) -> bool | None:
    """Check whether all agents in a multi-agent workflow have completed.

    Walks ``~/.sase/projects/*/artifacts/ace-run/*/agent_meta.json``
    directly and only loads files whose ``workflow_name`` matches *name*.
    Bypasses :func:`sase.core.agent_scan_facade.scan_agent_artifacts` on
    purpose: the snapshot facade has to materialize wire records for every
    artifact in the tree before any predicate can run, which previously
    measured as a ~3× regression for this hot path against the
    short-circuiting walk.

    Returns:
        ``True`` — root has ``done.json`` and no child is still alive without one.
        ``False`` — workflow exists but isn't fully complete.
        ``None`` — no agents with ``workflow_name == name`` found (not a workflow).
    """
    projects_dir = _projects_root()
    if not projects_dir.exists():
        return None

    # (artifact_dir, agent_meta dict)
    workflow_agents: list[tuple[Path, dict[str, Any]]] = []
    for artifact_dir in _iter_ace_run_artifact_dirs():
        meta_path = artifact_dir / "agent_meta.json"
        if not meta_path.exists():
            continue

        try:
            with open(meta_path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        if not isinstance(data, dict):
            continue

        if data.get("workflow_name") != name:
            continue

        workflow_agents.append((artifact_dir, data))

    if not workflow_agents:
        return None

    # Find the root agent (no parent_timestamp).
    root: tuple[Path, dict[str, Any]] | None = None
    children: list[tuple[Path, dict[str, Any]]] = []
    for artifact_dir, meta in workflow_agents:
        if meta.get("parent_timestamp"):
            children.append((artifact_dir, meta))
        else:
            root = (artifact_dir, meta)

    if root is None:
        # No root found — the root's workflow_name may have been
        # stripped by claim_agent_name (it only preserves names on
        # artifacts with done.json, and the root may lack one).
        # Return None so the caller falls through to name-based
        # resolution via find_named_agent.
        return None

    root_dir, root_meta = root
    root_done = (root_dir / "done.json").exists()

    if not root_done:
        if is_process_alive(root_meta, root_dir):
            # Root still running — may write done.json later
            return False
        # Root is dead without done.json (crashed/killed between
        # workflow_state.json write and done.json write).  Fall through
        # to check children so the workflow can still resolve as complete
        # when all children are done/dead.
        if not children:
            return False

    # Root is done (or dead without done.json) — check all children
    for child_dir, child_meta in children:
        if (child_dir / "done.json").exists():
            continue
        if is_process_alive(child_meta, child_dir):
            # Child is still alive and hasn't finished
            return False

    return True


def get_most_recent_agent_name(
    *, exclude_artifacts_dir: str | Path | None = None
) -> str | None:
    """Return the name of the most recently created named agent.

    Scans ``~/.sase/projects/*/artifacts/ace-run/*/agent_meta.json``
    for agents with a name, ordered by artifact directory timestamp
    (directory names are timestamps).

    Args:
        exclude_artifacts_dir: Optional artifact directory to ignore. Used by
            bare ``#fork`` resolution so a workflow does not select its own
            just-written metadata as the most recent agent.

    Returns the name of the most recently created one, or ``None`` if no named
    agents exist.
    """
    projects_dir = sase_projects_dir()
    if not projects_dir.exists():
        return None

    excluded: Path | None = None
    if exclude_artifacts_dir:
        excluded = Path(exclude_artifacts_dir).expanduser().resolve(strict=False)

    candidates: list[tuple[str, str]] = []  # (dir_name, agent_name)
    for artifact_dir in _iter_ace_run_artifact_dirs():
        if excluded is not None:
            candidate_dir = artifact_dir.expanduser().resolve(strict=False)
            if candidate_dir == excluded:
                continue

        meta_path = artifact_dir / "agent_meta.json"
        if not meta_path.exists():
            continue

        try:
            with open(meta_path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        if not isinstance(data, dict):
            continue

        name = data.get("name")
        if not name:
            continue

        # Bare ``%wait`` should never resolve to a dismissed historical
        # agent. Dismissal-prefixed names (``YYmmdd.foo``) are reserved
        # for explicit references (``%w:260428.foo``); skip them so the
        # bare-wait path stays anchored on visible/active agents.
        if isinstance(name, str) and is_dismissed_prefixed(name):
            continue

        candidates.append((artifact_dir.name, name))

    if not candidates:
        return None

    # Sort by directory name descending — most recent first
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]

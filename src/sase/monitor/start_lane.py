"""Lane, parent, and workspace resolution for monitor starts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.plan_chain import agent_family_base
from sase.workspace_provider import resolve_workspace_owner_for_path
from sase.workspace_provider.utils import parse_workspace_dir

from . import store_lane
from .models import MonitorLaneError
from .request import StartMonitorRequest
from .start_metadata import read_start_meta


@dataclass(frozen=True)
class LaneStart:
    """The lane state a start resolves before it creates anything.

    ``workspace_num`` is the workspace identity for the directory the monitored
    command runs in. ``transfer_from_pid`` is set only when that identity is the
    starter runner's own live claim row and should move to the supervisor.
    """

    project_file: str
    member_meta: dict[str, Any]
    durable_lane: str
    cl_name: str | None
    prev_timestamp: str
    workspace_num: int
    transfer_from_pid: int | None
    starter_agent: str | None


@dataclass(frozen=True)
class StartIdentity:
    """How a start chose its parent artifact and durable family lane.

    ``target`` is the resolved parent's own agent name for an implicit
    start, or the explicit ``--agent`` / lane string. ``context`` is the
    already-resolved artifact for an implicit start, reused by
    ``resolve_lane_start()`` instead of re-resolving; it is ``None`` for
    an explicit start, which still resolves via ``store_lane.resolve_lane()``.
    ``lock_lane`` is the durable family used for the start lock, replay,
    conflict detection, and request fingerprint.
    """

    target: str
    context: store_lane.LaneContext | None
    lock_lane: str


def resolve_start_identity(request: StartMonitorRequest) -> StartIdentity:
    """Return the parent identity and durable lock lane for *request*."""
    if request.lane:
        return StartIdentity(target=request.lane, context=None, lock_lane=request.lane)
    caller = store_lane.default_caller()
    if not caller:
        raise MonitorLaneError(
            "no lane given and SASE_AGENT_NAME is unset; pass an explicit lane"
        )
    ctx = store_lane.resolve_caller_agent(
        request.project_name, caller, artifacts_dir=store_lane.caller_artifacts_dir()
    )
    meta = ctx.record.agent_meta
    target = meta.name if meta is not None and meta.name else caller
    lock_lane = store_lane.durable_lane_for_record(ctx.record, fallback=target)
    return StartIdentity(target=target, context=ctx, lock_lane=lock_lane)


def resolve_lane_start(
    request: StartMonitorRequest, identity: StartIdentity
) -> LaneStart:
    """Read the selected parent artifact and decide what the monitor inherits."""
    lane_ctx = (
        identity.context
        if identity.context is not None
        else store_lane.resolve_lane(request.project_name, identity.target)
    )
    selected = lane_ctx.record
    raw_meta = read_start_meta(selected.artifact_dir)

    durable_lane = str(raw_meta.get("agent_family") or "").strip()
    if not durable_lane:
        from sase.agent._family_promotion import promote_agent_to_family

        promoted_name = promote_agent_to_family(selected.artifact_dir, identity.target)
        durable_lane = agent_family_base(promoted_name) or identity.target
        raw_meta = read_start_meta(selected.artifact_dir)

    workspace_dir = raw_meta.get("workspace_dir")
    raw_lane_workspace_num = raw_meta.get("workspace_num")
    raw_runner_pid = raw_meta.get("pid")
    lane_workspace_num = _optional_int(raw_lane_workspace_num)
    runner_pid = _optional_int(raw_runner_pid)
    lane_workspace_dir = str(workspace_dir) if workspace_dir else ""
    cwd_matches_lane = bool(lane_workspace_dir) and (
        _same_path(request.cwd, lane_workspace_dir)
        or _path_contains(lane_workspace_dir, request.cwd)
    )

    resolved_workspace_num, member_workspace_dir = _resolve_monitor_workspace(
        selected.project_file,
        request.cwd,
        cwd_matches_lane=cwd_matches_lane,
        lane_workspace_num=lane_workspace_num,
        lane_workspace_dir=lane_workspace_dir,
    )
    transfer_from_pid: int | None = None
    starter_agent: str | None = None
    if request.transfer_claim_from_pid is not None:
        transfer_from_pid = request.transfer_claim_from_pid
    elif (
        request.inherit_lane_workspace_claim
        and cwd_matches_lane
        and resolved_workspace_num != 0
        and runner_pid is not None
    ):
        transfer_from_pid = runner_pid
        raw_name = raw_meta.get("name")
        starter_agent = raw_name if isinstance(raw_name, str) and raw_name else None

    member_meta = dict(raw_meta)
    member_meta["workspace_dir"] = member_workspace_dir
    member_meta["workspace_num"] = resolved_workspace_num

    cl_name = raw_meta.get("cl_name")
    return LaneStart(
        project_file=selected.project_file,
        member_meta=member_meta,
        durable_lane=durable_lane,
        cl_name=cl_name if isinstance(cl_name, str) else None,
        prev_timestamp=selected.timestamp,
        workspace_num=resolved_workspace_num,
        transfer_from_pid=transfer_from_pid,
        starter_agent=starter_agent,
    )


def _resolve_monitor_workspace(
    project_file: str,
    cwd: str,
    *,
    cwd_matches_lane: bool,
    lane_workspace_num: int | None,
    lane_workspace_dir: str,
) -> tuple[int, str]:
    """Return the workspace number and owning checkout root for the command cwd.

    A cwd that matches (or is nested within) its lane's own workspace
    reuses the lane's already-known number and directory without a
    registry round-trip. Otherwise *cwd* is resolved against the
    workspace registry by containment, so a cwd nested inside some
    managed checkout -- not just an exact checkout root -- still resolves
    to its owning workspace.
    """
    if cwd_matches_lane and lane_workspace_num is not None and lane_workspace_num != 0:
        return lane_workspace_num, lane_workspace_dir

    owner = _lookup_workspace_owner_for_dir(project_file, cwd)
    if owner is not None:
        return owner

    if cwd_matches_lane and lane_workspace_num is not None:
        return lane_workspace_num, cwd

    return 0, cwd


def _lookup_workspace_owner_for_dir(
    project_file: str, directory: str
) -> tuple[int, str] | None:
    primary_workspace_dir = parse_workspace_dir(project_file)
    if not primary_workspace_dir:
        return None
    return resolve_workspace_owner_for_path(primary_workspace_dir, directory)


def _same_path(left: str, right: str) -> bool:
    try:
        return Path(left).expanduser().resolve() == Path(right).expanduser().resolve()
    except OSError:
        return left == right


def _path_contains(root: str, path: str) -> bool:
    try:
        root_resolved = Path(root).expanduser().resolve()
        path_resolved = Path(path).expanduser().resolve()
    except OSError:
        return False
    try:
        path_resolved.relative_to(root_resolved)
    except ValueError:
        return False
    return True


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int | str):
        return None
    try:
        return int(value)
    except ValueError:
        return None


__all__ = [
    "LaneStart",
    "StartIdentity",
    "resolve_lane_start",
    "resolve_start_identity",
]

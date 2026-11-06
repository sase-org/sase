"""Stale RUNNING entry cleanup utilities for the axe scheduler."""

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sase.core.paths import sase_projects_dir
from sase.core.time import local_now
from sase.running_field import (
    WorkspaceClaim,
    get_claimed_workspaces,
    get_workspace_directory_for_num,
    release_workspace,
)
from sase.workspace_provider.occupant import clear_owned_occupant_record

from ..hooks.processes import is_process_running

_CLAIM_TIMESTAMP_FORMATS = ("%Y%m%d%H%M%S", "%Y%m%d_%H%M%S", "%y%m%d_%H%M%S")
_DEFAULT_HELD_CLAIM_TTL_DAYS = 14


def _held_agent_artifacts_exist(project_file: str, artifacts_timestamp: str) -> bool:
    """Conservatively check whether a held agent still has artifacts."""
    try:
        from sase.core.agent_artifact_paths import (
            ACE_RUN_WORKFLOW_DIR,
            resolve_agent_artifact_timestamp_path,
        )

        project_name = Path(project_file).parent.name
        return resolve_agent_artifact_timestamp_path(
            project_name,
            ACE_RUN_WORKFLOW_DIR,
            artifacts_timestamp,
        ).is_dir()
    except Exception:
        return True


def _held_done_marker_exists(project_file: str, artifacts_timestamp: str) -> bool:
    """Conservatively check whether a held agent has a dismissible done marker.

    Read failures fail closed (assume a marker exists) so a transient path
    error cannot reap a claim that ACE could still surface.
    """
    try:
        from sase.core.agent_artifact_paths import (
            ACE_RUN_WORKFLOW_DIR,
            resolve_agent_artifact_timestamp_path,
        )

        project_name = Path(project_file).parent.name
        artifacts_dir = resolve_agent_artifact_timestamp_path(
            project_name,
            ACE_RUN_WORKFLOW_DIR,
            artifacts_timestamp,
        )
        return (artifacts_dir / "done.json").is_file()
    except Exception:
        return True


def _held_claim_ttl_days() -> int:
    """Return ``workspace.held_claim_ttl_days``, defaulting to 14 on error."""
    try:
        from sase.config import load_merged_config
        from sase.workspace_provider.store import held_claim_ttl_days_from_config

        return held_claim_ttl_days_from_config(load_merged_config())
    except Exception:
        return _DEFAULT_HELD_CLAIM_TTL_DAYS


def _parse_claim_timestamp(artifacts_timestamp: str) -> datetime | None:
    """Parse a RUNNING-field artifacts timestamp, or None if unparseable."""
    for fmt in _CLAIM_TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(artifacts_timestamp, fmt)
        except ValueError:
            continue
    return None


def _now() -> datetime:
    return local_now()


def _held_claim_exceeds_ttl(
    artifacts_timestamp: str,
    ttl_days: int,
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether a pinned claim's launch stamp is older than the TTL.

    ``ttl_days <= 0`` disables age-based release. Unparseable stamps keep
    today's never-release behavior.
    """
    if ttl_days <= 0:
        return False
    parsed = _parse_claim_timestamp(artifacts_timestamp)
    if parsed is None:
        return False
    current = _now() if now is None else now
    return current - parsed > timedelta(days=ttl_days)


def _monitor_claim_is_releasable(project_file: str, claim: WorkspaceClaim) -> bool:
    """Return whether a dead-pid monitor workspace claim is safe to release.

    A monitor owns its workspace for the length of its command, and a dead
    supervisor pid alone is exactly the state a not-yet-reconciled monitor is
    in. Only release once the owning monitor member's own markers say it is
    terminal; any failure to read that state fails closed (not releasable),
    matching the conservative pinned-artifacts check above.
    """
    if not claim.artifacts_timestamp:
        return True
    try:
        from sase.core.agent_artifact_paths import (
            ACE_RUN_WORKFLOW_DIR,
            resolve_agent_artifact_timestamp_path,
        )
        from sase.monitor.store import read_monitor_marker

        project_name = Path(project_file).parent.name
        artifacts_dir = resolve_agent_artifact_timestamp_path(
            project_name, ACE_RUN_WORKFLOW_DIR, claim.artifacts_timestamp
        )
        record = read_monitor_marker(project_name, str(artifacts_dir))
    except Exception:
        return False
    return record is None or record.is_terminal


def _gate_claim_exceeds_held_ttl(
    project_file: str,
    claim: WorkspaceClaim,
    held_ttl_days: int,
) -> bool:
    """Return whether a dead-pid non-terminal gate claim outlived the held TTL.

    A gate whose settler died mid-``settling`` — no ``done.json`` and no
    decision record — never reaches a terminal marker, so the plain
    ``gate_claim_is_releasable`` rule would hold its workspace forever. Once
    the claim stamp is older than the held-claim TTL the workspace releases
    while the gate record itself is left untouched. Every unreadable or
    ambiguous state fails closed.
    """
    if not claim.artifacts_timestamp:
        return False
    if is_process_running(claim.pid):
        return False
    try:
        from sase.core.agent_artifact_paths import (
            ACE_RUN_WORKFLOW_DIR,
            resolve_agent_artifact_timestamp_path,
        )
        from sase.gate_turn.store import read_gate_turn_marker

        project_name = Path(project_file).parent.name
        artifacts_dir = resolve_agent_artifact_timestamp_path(
            project_name, ACE_RUN_WORKFLOW_DIR, claim.artifacts_timestamp
        )
        record = read_gate_turn_marker(project_name, str(artifacts_dir))
    except Exception:
        return False
    if record is None or record.is_terminal:
        return False
    return _held_claim_exceeds_ttl(claim.artifacts_timestamp, held_ttl_days)


def _repair_leaked_monitor_claim(
    project_file: str,
    claim: WorkspaceClaim,
    *,
    log_fn: Callable[[str, str | None], None] | None,
) -> bool:
    """Publish stray sheets and re-settle one leaked epic-launch monitor claim.

    Already-leaked claims are pinned ``ace-monitor`` claims with a dead pid
    whose terminal retention record probed paths outside the claimed checkout
    (foreign starter evidence). The stray decision sheet is published through
    the SDD plans-store commit API, then settlement re-runs with the
    corrected starter-evidence scope: a clean result releases the claim, and
    other dirt keeps retaining with a working notification.

    Returns True when the claim released and the caller should count it.
    Never raises: every failure returns False so the normal pinned-hold path
    keeps the claim.
    """
    try:
        return _repair_leaked_monitor_claim_inner(project_file, claim, log_fn=log_fn)
    except Exception as exc:  # noqa: BLE001 - repair must never break the sweep
        if log_fn:
            log_fn(
                f"Leaked monitor claim for workspace #{claim.workspace_num} "
                f"kept: {exc}",
                "yellow",
            )
        return False


def _repair_leaked_monitor_claim_inner(
    project_file: str,
    claim: WorkspaceClaim,
    *,
    log_fn: Callable[[str, str | None], None] | None,
) -> bool:
    import json as _json

    from sase.workspace_provider.retention_record import (
        read_workspace_retention_record,
    )

    from sase.core.workspace_retention import DISPOSITION_RETAIN

    if not claim.artifacts_timestamp:
        return False
    project_name = Path(project_file).parent.name
    try:
        from sase.core.agent_artifact_paths import (
            ACE_RUN_WORKFLOW_DIR,
            resolve_agent_artifact_timestamp_path,
        )

        artifacts_dir = resolve_agent_artifact_timestamp_path(
            project_name, ACE_RUN_WORKFLOW_DIR, claim.artifacts_timestamp
        )
    except Exception:
        return False
    if not artifacts_dir.is_dir():
        return False
    try:
        from sase.monitor.store import read_monitor_marker

        member = read_monitor_marker(project_name, str(artifacts_dir))
    except Exception:
        return False
    if member is None or not member.is_terminal:
        return False
    try:
        retention = read_workspace_retention_record(artifacts_dir)
    except Exception:
        return False
    if (
        retention is None
        or not retention.terminal
        or retention.disposition != DISPOSITION_RETAIN
        or not retention.unresolved
    ):
        return False
    try:
        meta = _json.loads(
            (artifacts_dir / "agent_meta.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return False
    if not isinstance(meta, dict):
        return False
    starter = meta.get("monitor_starter_artifacts_dir")
    if not (isinstance(starter, str) and starter.strip()):
        return False
    try:
        checkout_dir, _ = get_workspace_directory_for_num(
            claim.workspace_num, project_name, clean=False
        )
    except Exception:
        return False
    try:
        from sase.monitor.settlement_fresh_owner import starter_same_workspace

        if starter_same_workspace(meta, starter, checkout_dir):
            return False
    except Exception:
        return False
    if _staged_origin_retains_claim(project_file, claim):
        return False
    if _pending_retention_retains_claim(project_file, claim):
        return False
    published = _publish_stray_decision_sheets(
        project_file, claim, checkout_dir, log_fn=log_fn
    )
    try:
        from sase.monitor._settlement_retention import release_monitor_claim

        error = release_monitor_claim(
            meta,
            project_name=project_name,
            artifacts_dir=str(artifacts_dir),
        )
    except Exception as exc:  # noqa: BLE001 - custody outranks repair
        if log_fn:
            log_fn(
                f"Leaked monitor claim for workspace #{claim.workspace_num} "
                f"kept: settlement failed ({exc})",
                "yellow",
            )
        return False
    if error is not None:
        if log_fn:
            log_fn(
                f"Leaked monitor claim for workspace #{claim.workspace_num} "
                f"kept: settlement failed ({error})",
                "yellow",
            )
        return False
    if _claim_still_held(project_file, claim):
        if log_fn:
            log_fn(
                f"Leaked monitor claim for workspace #{claim.workspace_num} "
                f"retained with other dirt (published {published} "
                f"decision sheet{'s' if published != 1 else ''})",
                "yellow",
            )
        return False
    _settle_stale_retention_record(project_file, claim)
    _clear_stale_occupant_record(project_file, claim)
    if log_fn:
        log_fn(
            f"Released leaked monitor workspace #{claim.workspace_num} "
            f"({claim.workflow}) - re-settled after publishing {published} "
            f"decision sheet{'s' if published != 1 else ''}",
            "cyan",
        )
    return True


def _claim_still_held(project_file: str, claim: WorkspaceClaim) -> bool:
    """Return whether the exact claim row still pins its workspace.

    Read failures fail closed (assume held) so a transient read error
    cannot double-count a release the settlement already performed.
    """
    try:
        claims = get_claimed_workspaces(project_file)
    except Exception:
        return True
    for current in claims:
        if (
            current.workspace_num == claim.workspace_num
            and current.workflow == claim.workflow
            and (current.cl_name or "") == (claim.cl_name or "")
            and (current.artifacts_timestamp or "") == (claim.artifacts_timestamp or "")
            and current.pid == claim.pid
        ):
            return True
    return False


def _publish_stray_decision_sheets(
    project_file: str,
    claim: WorkspaceClaim,
    checkout_dir: str,
    *,
    log_fn: Callable[[str, str | None], None] | None,
) -> int:
    """Commit untracked decision sheets whose sibling plan is committed.

    Scans the claimed checkout's plans repo for untracked
    ``<YYYYMM>/<plan>.plan-decisions.json`` files and publishes each one
    whose sibling plan is already committed, through the same SDD
    plans-store commit API the bead-work launch path uses. The committed
    bytes are verified against the stray copy, and nothing is ever deleted:
    a sheet that cannot be verified stays untracked for the next sweep.
    Returns the number of sheets published. Never raises.
    """
    try:
        return _publish_stray_decision_sheets_inner(
            project_file, claim, checkout_dir, log_fn=log_fn
        )
    except Exception as exc:  # noqa: BLE001 - publishing is best effort
        if log_fn:
            log_fn(
                f"Stray decision sheets for workspace #{claim.workspace_num} "
                f"kept: {exc}",
                "yellow",
            )
        return 0


def _publish_stray_decision_sheets_inner(
    project_file: str,
    claim: WorkspaceClaim,
    checkout_dir: str,
    *,
    log_fn: Callable[[str, str | None], None] | None,
) -> int:
    from sase.sdd.plan_decision_freeze import SUFFIX
    from sase.sdd.store import resolve_sdd_store

    checkout = Path(checkout_dir)
    try:
        store = resolve_sdd_store(checkout, claim.workspace_num)
        plans_root = Path(store.kind_root("plans"))
    except Exception:
        return 0
    try:
        inside = plans_root.resolve(strict=False).is_relative_to(
            checkout.resolve(strict=False)
        )
    except Exception:
        return 0
    if not inside or not plans_root.is_dir():
        return 0
    changed = _sdd_changed_files(plans_root)
    if not changed:
        return 0
    from sase.sdd.files import commit_sdd_store_files

    published = 0
    for rel in sorted(changed):
        candidate = Path(rel)
        if candidate.suffix != ".json" or not candidate.name.endswith(SUFFIX):
            continue
        if len(candidate.parts) != 2:
            continue
        if not (len(candidate.parent.name) == 6 and candidate.parent.name.isdigit()):
            continue
        try:
            if _sdd_path_committed(plans_root, rel):
                continue
            plan_abs = _sibling_plan_path(plans_root, candidate, SUFFIX)
            if plan_abs is None:
                continue
            plan_rel = plan_abs.relative_to(plans_root).as_posix()
            if not _sdd_path_committed(plans_root, plan_rel):
                if log_fn:
                    log_fn(
                        f"Stray decision sheet {rel} for workspace "
                        f"#{claim.workspace_num} kept: sibling plan is not "
                        "committed to the plans store",
                        "yellow",
                    )
                continue
            raw = (plans_root / candidate).read_bytes()
        except OSError:
            continue
        try:
            result = commit_sdd_store_files(
                store,
                f"Publish stray decision sheet {rel}",
                paths=[plan_abs, plans_root / candidate],
                push_after_commit=False,
            )
        except Exception as exc:  # noqa: BLE001 - keep the stray on failure
            if log_fn:
                log_fn(
                    f"Stray decision sheet {rel} for workspace "
                    f"#{claim.workspace_num} kept: commit failed ({exc})",
                    "yellow",
                )
            continue
        if not result.committed:
            continue
        if _sdd_show_head(plans_root, rel) != raw:
            if log_fn:
                log_fn(
                    f"Stray decision sheet {rel} for workspace "
                    f"#{claim.workspace_num} kept: committed bytes differ",
                    "yellow",
                )
            continue
        published += 1
        if log_fn:
            log_fn(
                f"Published stray decision sheet {rel} for workspace "
                f"#{claim.workspace_num}",
                "cyan",
            )
    return published


def _sibling_plan_path(plans_root: Path, stray: Path, suffix: str) -> Path | None:
    """Return the sibling plan file for a stray decisions sheet, if any."""
    base = stray.name[: -len(suffix)]
    parent = plans_root / stray.parent
    exact = parent / base
    try:
        if exact.is_file():
            return exact
        dotted = parent / f"{base}.md"
        if dotted.is_file():
            return dotted
        others = sorted(
            path
            for path in parent.glob(f"{base}.*")
            if path.is_file() and path.name != stray.name
        )
    except OSError:
        return None
    if len(others) == 1:
        return others[0]
    return None


def _sdd_changed_files(plans_root: Path) -> list[str]:
    """List changed files under the plans repo through the SDD git runner."""
    from sase.sdd._git import run_sdd_git

    try:
        result = run_sdd_git(
            [
                "ls-files",
                "--modified",
                "--others",
                "--deleted",
                "--exclude-standard",
                "-z",
                "--",
                ".",
            ],
            cwd=plans_root,
            op="stale_cleanup.stray_sheets",
            check=True,
            capture_output=True,
        )
    except Exception:
        return []
    stdout = result.stdout or b""
    if isinstance(stdout, str):
        return [path for path in stdout.split("\0") if path]
    return [path.decode("utf-8") for path in stdout.split(b"\0") if path]


def _sdd_path_committed(plans_root: Path, rel: str) -> bool:
    """Return whether *rel* is committed to the plans repo HEAD."""
    from sase.sdd._git import run_sdd_git

    try:
        result = run_sdd_git(
            ["cat-file", "-e", f"HEAD:{rel}"],
            cwd=plans_root,
            op="stale_cleanup.stray_sheets",
            check=False,
            capture_output=True,
        )
    except Exception:
        return False
    return result.returncode == 0


def _sdd_show_head(plans_root: Path, rel: str) -> bytes | None:
    """Return the HEAD bytes of *rel*, or None when unreadable."""
    from sase.sdd._git import run_sdd_git

    try:
        result = run_sdd_git(
            ["show", f"HEAD:{rel}"],
            cwd=plans_root,
            op="stale_cleanup.stray_sheets",
            check=True,
            capture_output=True,
        )
    except Exception:
        return None
    stdout = result.stdout or b""
    if isinstance(stdout, str):
        return stdout.encode("utf-8")
    return bytes(stdout)


def cleanup_stale_running_entries(
    log_fn: Callable[[str, str | None], None] | None = None,
    *,
    skip_monitor_claims: bool = False,
) -> int:
    """Release workspace claims for processes that are no longer running.

    Iterates through all project files and checks each RUNNING entry's PID.
    If the process is no longer running, the workspace claim is released.
    Lifecycle filtering is intentionally not applied: stale claims in disabled
    projects (including legacy archived/closed states) still need cleanup.

    Args:
        log_fn: Optional logging function (message, style).
        skip_monitor_claims: When True, leave every monitor-workflow claim
            (``MONITOR_WORKSPACE_CLAIM_WORKFLOW``) untouched this sweep,
            regardless of pid or terminal state. Set by the caller when it
            could not reconcile dead monitor supervisors first, so a live
            lane's workspace is never handed to another agent on the strength
            of stale reconciliation state. The flag also means the monitor
            package may be unimportable; this sweep does not import or
            touch it.

    Returns:
        Number of stale workspace claims released.
    """
    from sase.gate_turn.claims import (
        GATE_WORKSPACE_CLAIM_WORKFLOW,
        gate_claim_is_releasable,
    )

    if skip_monitor_claims:
        # The caller already committed to leaving monitor claims alone, and
        # the monitor package may be unimportable. Identify those claims by
        # the workflow label without importing sase.monitor.start so they
        # cannot fall through to the generic stale-PID release path.
        monitor_workflow = "ace-monitor"
    else:
        from sase.monitor.start import MONITOR_WORKSPACE_CLAIM_WORKFLOW

        monitor_workflow = MONITOR_WORKSPACE_CLAIM_WORKFLOW

    released_count = 0
    held_ttl_days: int | None = None

    for project_file in _get_all_project_files():
        claims = get_claimed_workspaces(project_file)

        for claim in claims:
            # Protect pending adoption independently of reconciliation ordering.
            # Once pinned, the origin follows the normal held-claim lifecycle,
            # including its configured TTL and explicit dismissal.
            if not claim.pinned and _staged_origin_retains_claim(project_file, claim):
                continue
            hijack_record = _matching_hijack_record(project_file, claim)
            if hijack_record is _HIJACK_LOOKUP_FAILED:
                continue
            if isinstance(hijack_record, dict):
                hijack_released, held_ttl_days = _apply_hijack_custody(
                    project_file,
                    claim,
                    hijack_record,
                    held_ttl_days=held_ttl_days,
                    log_fn=log_fn,
                )
                if hijack_released:
                    released_count += 1
                continue
            is_monitor_claim = claim.workflow == monitor_workflow
            is_gate_claim = claim.workflow == GATE_WORKSPACE_CLAIM_WORKFLOW
            if is_monitor_claim and skip_monitor_claims:
                continue

            # Already-leaked epic-launch monitor claims settle before the
            # pinned-hold TTL would release them: publish their stray
            # decision sheets, then re-run retention settlement with the
            # corrected starter-evidence scope. A clean result releases
            # here; other dirt keeps the normal pinned path below.
            if (
                claim.pinned
                and is_monitor_claim
                and claim.artifacts_timestamp
                and not is_process_running(claim.pid)
                and _repair_leaked_monitor_claim(project_file, claim, log_fn=log_fn)
            ):
                released_count += 1
                continue

            if claim.pinned:
                if not claim.artifacts_timestamp:
                    continue
                if is_process_running(claim.pid):
                    continue
                # Terminal holds follow the configured TTL. A staged origin
                # can also be pinned just before its runner crashes without
                # writing done.json; recovery still owns that pending marker
                # and must get a chance to publish terminal evidence.
                if _held_agent_artifacts_exist(
                    project_file, claim.artifacts_timestamp
                ) and (
                    _held_done_marker_exists(project_file, claim.artifacts_timestamp)
                    or _staged_origin_retains_claim(project_file, claim)
                ):
                    if held_ttl_days is None:
                        held_ttl_days = _held_claim_ttl_days()
                    if not _held_claim_exceeds_ttl(
                        claim.artifacts_timestamp, held_ttl_days
                    ):
                        continue
            elif is_process_running(claim.pid):
                continue
            elif is_monitor_claim and not _monitor_claim_is_releasable(
                project_file, claim
            ):
                continue
            elif is_gate_claim and not gate_claim_is_releasable(project_file, claim):
                # A settler that died mid-settling never writes a terminal
                # marker, so the rule above would hold its workspace forever.
                # Bound that hold with the held-claim TTL instead; the gate
                # record itself is left untouched.
                if held_ttl_days is None:
                    held_ttl_days = _held_claim_ttl_days()
                if not _gate_claim_exceeds_held_ttl(project_file, claim, held_ttl_days):
                    continue
            if _pending_retention_retains_claim(project_file, claim):
                continue

            released = release_workspace(
                project_file,
                claim.workspace_num,
                claim.workflow,
                claim.cl_name,
                caller_tag="stale-cleanup",
                expected_pid=claim.pid,
                artifacts_timestamp=claim.artifacts_timestamp,
            )
            if not released.success:
                continue
            _settle_stale_retention_record(project_file, claim)
            _clear_stale_occupant_record(project_file, claim)
            released_count += 1

            if log_fn:
                cl_info = f" for PR {claim.cl_name}" if claim.cl_name else ""
                log_fn(
                    f"Released stale{' held' if claim.pinned else ''} "
                    f"workspace #{claim.workspace_num} "
                    f"({claim.workflow}){cl_info} - PID {claim.pid} not running",
                    "cyan",
                )

    return released_count


_HIJACK_LOOKUP_FAILED = object()


def _matching_hijack_record(
    project_file: str, claim: WorkspaceClaim
) -> dict[str, Any] | object | None:
    """Return the active hijack record, or a sentinel when lookup itself failed.

    Lookup failures fail closed: the claim stays until a later sweep can
    prove it is not hijacked.
    """
    try:
        from sase.agent.hijack.custody import matching_active_record

        return matching_active_record(project_file, claim)
    except Exception:
        return _HIJACK_LOOKUP_FAILED


def _apply_hijack_custody(
    project_file: str,
    claim: WorkspaceClaim,
    record: dict[str, Any],
    *,
    held_ttl_days: int | None,
    log_fn: Callable[[str, str | None], None] | None,
) -> tuple[bool, int | None]:
    """Retain or expire one hijack-owned claim. Never fall through to generic release."""
    from sase.agent.hijack.custody import expire_hijack_hold, hijacked_at_exceeds_ttl

    state = str(record.get("state") or "")
    if state in {"requested", "stopping"}:
        return False, held_ttl_days
    if state == "resolving":
        _reconcile_resolving_record(record)
        return False, held_ttl_days
    if state != "held":
        return False, held_ttl_days
    if is_process_running(claim.pid):
        return False, held_ttl_days
    if held_ttl_days is None:
        held_ttl_days = _held_claim_ttl_days()
    hijacked_at = record.get("hijacked_at")
    stamp = hijacked_at if isinstance(hijacked_at, str) else None
    if not hijacked_at_exceeds_ttl(stamp, held_ttl_days):
        return False, held_ttl_days
    try:
        expired = expire_hijack_hold(project_file, claim, record)
    except Exception:
        return False, held_ttl_days
    if not expired:
        return False, held_ttl_days
    _settle_stale_retention_record(project_file, claim)
    _clear_stale_occupant_record(project_file, claim)
    if log_fn:
        cl_info = f" for PR {claim.cl_name}" if claim.cl_name else ""
        log_fn(
            f"Released expired hijack workspace #{claim.workspace_num} "
            f"({claim.workflow}){cl_info} - held claim TTL elapsed",
            "cyan",
        )
    return True, held_ttl_days


def _reconcile_resolving_record(record: dict[str, Any]) -> None:
    """Best-effort reconcile of one resolving hijack record.

    Runs the idempotent recovery reconciliation (adopt the proven
    successor, repair settlement, or return to held when no successor
    exists). Never releases the claim: ``keep_resolving`` and
    ``retain_with_error`` retain custody, and even a successful return to
    held keeps the held claim until its TTL expires. All failures fail
    closed to retention so two cleanup processes cannot duplicate a launch
    or prematurely release a workspace. Also drains one bounded pending
    settled-projection repair by authoritative id lookup, never a
    ``settled/`` scan.
    """
    try:
        from sase.agent.hijack.recover_reconcile import (
            reconcile_recovery,
            repair_pending_settlements,
        )
    except Exception:
        return
    try:
        reconcile_recovery(record)
    except Exception:
        pass
    try:
        repair_pending_settlements(limit=1)
    except Exception:
        return


def _staged_origin_retains_claim(project_file: str, claim: WorkspaceClaim) -> bool:
    if not claim.artifacts_timestamp:
        return False
    try:
        from sase.core.agent_artifact_paths import resolve_agent_artifact_timestamp_path
        from sase.agent.staged_handoff import STAGED_HANDOFF_FILENAME

        artifacts = resolve_agent_artifact_timestamp_path(
            Path(project_file).parent.name, "ace-run", claim.artifacts_timestamp
        )
        # Presence, including malformed evidence, protects custody. Receipt
        # success alone cannot release a claim before successor delivery.
        (artifacts / STAGED_HANDOFF_FILENAME).lstat()
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return True


def _pending_retention_retains_claim(project_file: str, claim: WorkspaceClaim) -> bool:
    """Honor an exact-owner pending-retention fact until settlement decides.

    A pending fact protects the exact workspace/workflow/cl/timestamp/pid
    owner while a fresh-interpreter retry or guarded settlement is still
    outstanding. Once a terminal retention record settles, the pending fact
    is stale and no longer blocks TTL-driven cleanup.
    """
    if not claim.artifacts_timestamp:
        return False
    try:
        from sase.core.agent_artifact_paths import resolve_agent_artifact_timestamp_path
        from sase.turns.workspace_retention import (
            pending_retention_matches_owner,
            read_pending_retention,
        )
        from sase.workspace_provider.retention_record import (
            read_workspace_retention_record,
        )

        artifacts = resolve_agent_artifact_timestamp_path(
            Path(project_file).parent.name, "ace-run", claim.artifacts_timestamp
        )
        pending = read_pending_retention(artifacts)
        if pending is None:
            return False
        record = read_workspace_retention_record(artifacts)
        if record is not None and not record.unresolved:
            return False
        from sase.turns.workspace_retention import WorkspaceRetentionOwner

        owner = WorkspaceRetentionOwner(
            project_file=project_file,
            workspace_num=claim.workspace_num,
            workflow=claim.workflow,
            cl_name=claim.cl_name or "",
            artifacts_timestamp=claim.artifacts_timestamp or "",
            pid=claim.pid,
            artifacts_dir=str(artifacts),
        )
        return pending_retention_matches_owner(pending, owner)
    except Exception:
        return False


def _settle_stale_retention_record(project_file: str, claim: WorkspaceClaim) -> None:
    """Keep recovery surfaces in sync after releasing a terminal held claim."""
    if not claim.pinned or not claim.artifacts_timestamp:
        return
    try:
        from sase.core.agent_artifact_paths import resolve_agent_artifact_timestamp_path
        from sase.workspace_provider.retention_record import (
            mark_workspace_retention_settled,
        )

        artifacts = resolve_agent_artifact_timestamp_path(
            Path(project_file).parent.name, "ace-run", claim.artifacts_timestamp
        )
        mark_workspace_retention_settled(
            artifacts, reason="stale_cleanup", settled_at=_now().isoformat()
        )
    except Exception:
        return


def _clear_stale_occupant_record(project_file: str, claim: WorkspaceClaim) -> None:
    """Best-effort clear of a stale claim's checkout occupant marker."""
    if claim.workspace_num <= 1:
        return
    try:
        project_name = Path(project_file).parent.name
        workspace_dir, _ = get_workspace_directory_for_num(
            claim.workspace_num, project_name, clean=False
        )
    except Exception:
        return
    clear_owned_occupant_record(
        workspace_dir,
        claim.pid,
        artifacts_timestamp=claim.artifacts_timestamp,
        workflow=claim.workflow,
        cl_name=claim.cl_name,
        workspace_num=claim.workspace_num,
    )


def _get_all_project_files() -> list[str]:
    """Get all project file paths from ~/.sase/projects/.

    Returns:
        List of paths to project spec files for all projects. Prefers the
        canonical ``.sase`` extension and falls back to legacy ``.gp``.
    """
    from sase.ace.patch.project_spec_path import (
        active_project_spec_filename,
        legacy_active_project_spec_filename,
    )

    projects_dir = sase_projects_dir()
    if not projects_dir.exists():
        return []

    project_files: list[str] = []
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        canonical = project_dir / active_project_spec_filename(project_dir.name)
        if canonical.exists():
            project_files.append(str(canonical))
            continue
        legacy = project_dir / legacy_active_project_spec_filename(project_dir.name)
        if legacy.exists():
            project_files.append(str(legacy))

    return project_files

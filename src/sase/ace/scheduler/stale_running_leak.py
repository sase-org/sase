"""Leaked epic-launch monitor repair for stale-running cleanup."""

from collections.abc import Callable
from pathlib import Path

from sase.running_field import (
    WorkspaceClaim,
    get_claimed_workspaces,
    get_workspace_directory_for_num,
)

from ._stale_running_shared import (
    clear_stale_occupant_record,
    pending_retention_retains_claim,
    settle_stale_retention_record,
    staged_origin_retains_claim,
)


def repair_leaked_monitor_claim(
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
    if staged_origin_retains_claim(project_file, claim):
        return False
    if pending_retention_retains_claim(project_file, claim):
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
    settle_stale_retention_record(project_file, claim)
    clear_stale_occupant_record(project_file, claim)
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

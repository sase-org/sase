"""Read-only observation of onboarding facts for the Rust planner."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import subprocess
from typing import Any

from sase import workspace_provider
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import effective_project_name
from sase.noninteractive_subprocess import run_noninteractive
from sase.project_management import project_management_status
from sase.project_onboarding.discovery import (
    identity_for_origin,
    read_git_origin_url,
    record_identity_keys,
    resolve_git_dir,
)
from sase.workspace_provider.utils import non_interactive_git_env

_GIT_OBSERVE_TIMEOUT_SECONDS = 8.0
_SASE_MANAGED_RELATIVE = Path("sase") / "sase.yml"


def gather_facts(
    target: Mapping[str, Any],
    mode: str,
    *,
    actor: str,
) -> dict[str, Any]:
    """Gather planner facts without resolving refs, writing, or pruning.

    *actor* is accepted so callers share one detected identity; observation
    itself does not change with the actor. Unavailable probes keep their
    explanatory message instead of inventing found/not-found.
    """

    del actor
    workflow_type = str(target.get("workflow_type") or "")
    repo_ref = str(target.get("ref") or "")
    remote = _probe_remote(workflow_type, repo_ref)
    checkout_dir = _checkout_path(target)
    checkout = _observe_checkout(
        target,
        checkout_dir,
        default_branch=str(remote.get("default_branch") or ""),
    )
    records = _project_records()
    matching = _matching_record(target, checkout, records)
    facts: dict[str, Any] = {
        "remote": remote,
        "checkout": {
            "state": checkout["state"],
            "origin_url": checkout["origin_url"],
            "config_dirty": checkout["config_dirty"],
            "on_default_branch": checkout["on_default_branch"],
        },
        "projects": [
            {
                "key": row["key"],
                "name": row["name"],
                "aliases": list(row["aliases"]),
                "state": row["state"],
            }
            for row in records
        ],
        "creation_errors": [],
    }
    local_managed = checkout.get("local_managed")
    if local_managed is not None:
        facts["local_managed"] = local_managed
    if matching is not None:
        facts["record"] = {
            "key": matching["key"],
            "name": matching["name"],
            "aliases": list(matching["aliases"]),
            "state": matching["state"],
        }
    if mode == "create":
        facts["can_create"] = _can_create(workflow_type, target)
    return facts


def _probe_remote(workflow_type: str, repo_ref: str) -> dict[str, Any]:
    remote: dict[str, Any] = {
        "status": "unavailable",
        "visibility": "",
        "can_push": None,
        "sase_managed": None,
        "repo_id": "",
        "default_branch": "",
        "message": "",
        "web_url": "",
    }
    if not workflow_type or not repo_ref:
        remote["message"] = "missing provider target"
        return remote
    try:
        probe = workspace_provider.probe_repo(workflow_type, repo_ref)
    except Exception as exc:
        remote["message"] = str(exc)
        return remote
    if probe is None:
        remote["message"] = "provider probe returned no result"
        return remote
    status = str(probe.status or "unavailable")
    if status not in {"found", "not_found", "unavailable"}:
        status = "unavailable"
    remote["status"] = status
    remote["visibility"] = str(probe.visibility or "")
    remote["can_push"] = probe.can_push
    remote["sase_managed"] = probe.sase_managed
    remote["repo_id"] = str(probe.repo_id or "")
    remote["default_branch"] = str(probe.default_branch or "")
    remote["message"] = str(probe.message or "")
    remote["web_url"] = str(probe.web_url or "")
    if probe.is_empty is not None:
        remote["is_empty"] = probe.is_empty
    if probe.is_archived is not None:
        remote["is_archived"] = probe.is_archived
    return remote


def _checkout_path(target: Mapping[str, Any]) -> Path | None:
    raw_dir = str(target.get("checkout_dir") or "").strip()
    if not raw_dir:
        return None
    return Path(raw_dir).expanduser()


def _observe_checkout(
    target: Mapping[str, Any],
    checkout_dir: Path | None,
    default_branch: str,
) -> dict[str, Any]:
    checkout: dict[str, Any] = {
        "state": "absent",
        "origin_url": "",
        "config_dirty": False,
        "on_default_branch": None,
        "local_managed": None,
    }
    if checkout_dir is None:
        return checkout
    try:
        exists = checkout_dir.exists()
    except OSError:
        return checkout
    if not exists:
        return checkout
    if checkout_dir.is_file():
        checkout["state"] = "not_git"
        return checkout
    if checkout_dir.is_dir() and _is_empty_dir(checkout_dir):
        checkout["state"] = "empty_dir"
        return checkout
    git_dir = resolve_git_dir(checkout_dir)
    if git_dir is None:
        checkout["state"] = "not_git"
        return checkout
    origin = read_git_origin_url(str(checkout_dir))
    checkout["origin_url"] = origin
    target_identity = str(target.get("identity_key") or "").casefold()
    origin_identity = _origin_identity(origin, str(target.get("workflow_type") or ""))
    checkout["state"] = (
        "matching"
        if target_identity and origin_identity == target_identity
        else "mismatch"
    )
    checkout["config_dirty"] = _config_is_dirty(checkout_dir)
    checkout["on_default_branch"] = _on_default_branch(checkout_dir, default_branch)
    checkout["local_managed"] = _local_managed_at(checkout_dir)
    return checkout


def _origin_identity(origin: str, workflow_type: str) -> str:
    if not origin:
        return ""
    if workflow_type:
        try:
            parsed = workspace_provider.parse_repo_ref(workflow_type, origin)
        except Exception:
            parsed = None
        if parsed is not None and parsed.identity_key:
            return parsed.identity_key.casefold()
    return identity_for_origin(origin).casefold()


def _is_empty_dir(path: Path) -> bool:
    try:
        next(path.iterdir())
    except StopIteration:
        return True
    except OSError:
        return False
    return False


def _config_is_dirty(checkout: Path) -> bool:
    result = _run_git(
        checkout, "status", "--porcelain", "--", str(_SASE_MANAGED_RELATIVE)
    )
    if result is None or result.returncode != 0:
        return False
    return bool(result.stdout.strip())


def _on_default_branch(checkout: Path, default_branch: str) -> bool | None:
    if not default_branch:
        return None
    result = _run_git(checkout, "rev-parse", "--abbrev-ref", "HEAD")
    if result is None or result.returncode != 0:
        return None
    current = result.stdout.strip()
    if not current or current == "HEAD":
        return False
    wanted = default_branch
    if wanted.startswith("origin/"):
        wanted = wanted.split("/", 1)[1]
    if wanted.startswith("refs/heads/"):
        wanted = wanted.removeprefix("refs/heads/")
    return current == wanted


def _local_managed_at(checkout_dir: Path) -> bool | None:
    config_path = checkout_dir / _SASE_MANAGED_RELATIVE
    if not config_path.is_file():
        return None
    status = project_management_status(config_path)
    if not status.valid:
        return None
    return bool(status.is_sase_managed)


def _run_git(checkout: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    env = non_interactive_git_env()
    env["GH_PROMPT_DISABLED"] = "1"
    try:
        return run_noninteractive(
            ["git", *args],
            cwd=checkout,
            env=env,
            timeout=_GIT_OBSERVE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _project_records() -> list[dict[str, Any]]:
    try:
        records = list_project_records(sase_projects_dir(), "all")
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for record in records:
        if record.system_managed:
            continue
        rows.append(
            {
                "key": record.project_name,
                "name": effective_project_name(record),
                "aliases": list(record.aliases),
                "state": record.state,
                "workspace_dir": record.workspace_dir or "",
                "identity_keys": [
                    key.casefold() for key in record_identity_keys(record) if key
                ],
                "system_managed": record.system_managed,
                "is_project": record.is_project,
            }
        )
    return rows


def _matching_record(
    target: Mapping[str, Any],
    checkout: Mapping[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any] | None:
    identity = str(target.get("identity_key") or "").casefold()
    checkout_dir = str(Path(str(target.get("checkout_dir") or "")).expanduser())
    for row in records:
        identities = row.get("identity_keys") or []
        if identity and identity in identities:
            return row
        workspace = str(row.get("workspace_dir") or "")
        if (
            checkout_dir
            and workspace
            and Path(workspace).expanduser() == Path(checkout_dir)
            and checkout.get("state") == "matching"
        ):
            return row
    return None


def _can_create(workflow_type: str, target: Mapping[str, Any]) -> bool | None:
    namespace = str(target.get("owner") or "")
    if not workflow_type or not namespace:
        return None
    try:
        form = workspace_provider.describe_repo_creation(workflow_type, namespace)
    except Exception:
        return None
    if form is None:
        return None
    return form.can_create


__all__ = ["gather_facts"]

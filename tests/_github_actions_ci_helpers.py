"""Shared helpers for the GitHub Actions workflow/action contract tests.

Not itself a test module (leading underscore keeps pytest from collecting
it); the GitHub Actions contract modules import from here so they agree on how
workflow YAML and composite actions are parsed and inspected.
"""

from __future__ import annotations

import re
import stat
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent

# Jobs that run source lanes against the Rust artifacts `build-core` built from
# sase-core master rather than against published or stale local artifacts.
CORE_ARTIFACT_CONSUMER_JOBS = (
    "lint",
    "test",
    "visual-test",
    "ace-page-group-isolation",
    "perf-floors",
)

# Same idea as CORE_ARTIFACT_CONSUMER_JOBS, scoped to telemetry.yml's own jobs.
TELEMETRY_CORE_ARTIFACT_CONSUMER_JOBS = (
    "test-cost",
    "coverage-contexts",
    "contention-test",
)


def _load_ci_workflow() -> dict[str, Any]:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    return yaml.safe_load(workflow_path.read_text())


def _load_build_core_workflow() -> dict[str, Any]:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "build-core.yml"
    return yaml.safe_load(workflow_path.read_text())


def _load_telemetry_workflow() -> dict[str, Any]:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "telemetry.yml"
    return yaml.safe_load(workflow_path.read_text())


def _load_publish_workflow() -> dict[str, Any]:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "publish.yml"
    return yaml.safe_load(workflow_path.read_text())


def _load_release_workflow() -> dict[str, Any]:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "release.yml"
    return yaml.safe_load(workflow_path.read_text())


def _load_master_gate_workflow() -> dict[str, Any]:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "master-gate.yml"
    return yaml.safe_load(workflow_path.read_text())


def _load_full_workflow() -> dict[str, Any]:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "full.yml"
    return yaml.safe_load(workflow_path.read_text())


def _load_install_smoke_workflow() -> dict[str, Any]:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "install-smoke.yml"
    return yaml.safe_load(workflow_path.read_text())


def _load_release_steward_workflow() -> dict[str, Any]:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "release-steward.yml"
    return yaml.safe_load(workflow_path.read_text())


def _load_core_pin_ratchet_workflow() -> dict[str, Any]:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "core-pin-ratchet.yml"
    return yaml.safe_load(workflow_path.read_text())


def _load_shard_timings_ratchet_workflow() -> dict[str, Any]:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "shard-timings-ratchet.yml"
    return yaml.safe_load(workflow_path.read_text())


def _load_testpypi_drill_workflow() -> dict[str, Any]:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "testpypi-drill.yml"
    return yaml.safe_load(workflow_path.read_text())


def _load_setup_sase_action() -> dict[str, Any]:
    action_path = REPO_ROOT / ".github" / "actions" / "setup-sase" / "action.yml"
    return yaml.safe_load(action_path.read_text())


def _workflow_triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    return workflow["on" if "on" in workflow else True]


def _job_run_text(job: dict[str, Any]) -> str:
    return "\n".join(
        step.get("run", "") for step in job["steps"] if isinstance(step.get("run"), str)
    )


def _setup_sase_install_script() -> str:
    steps = _load_setup_sase_action()["runs"]["steps"]
    return next(
        step["run"] for step in steps if step.get("name") == "Install dependencies"
    )


def _write_executable(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


_LOCAL_REUSABLE_USES = re.compile(r"^\./\.github/workflows/([^/@]+\.yml)$")
_ACCESS_RANK = {"none": 0, "read": 1, "write": 2}


def _permission_dict(node: object) -> dict[str, str] | None:
    if not isinstance(node, dict) or "permissions" not in node:
        return None
    perms = node["permissions"]
    if not isinstance(perms, dict):
        return None
    return {str(scope): str(level) for scope, level in perms.items()}


def _access_rank(level: str) -> int:
    return _ACCESS_RANK.get(level, -1)


def _covers(have: str, needed: str) -> bool:
    have_rank = _access_rank(have)
    needed_rank = _access_rank(needed)
    return have_rank >= 0 and needed_rank >= 0 and have_rank >= needed_rank


def callee_declared_scopes(workflow: dict[str, Any]) -> dict[str, str]:
    """Union of a reusable callee's workflow-level and job-level scopes."""
    scopes: dict[str, str] = {}

    def _add(perms: dict[str, str] | None) -> None:
        if perms is None:
            return
        for scope, level in perms.items():
            current = scopes.get(scope)
            if current is None or _access_rank(level) > _access_rank(current):
                scopes[scope] = level

    _add(_permission_dict(workflow))
    jobs = workflow.get("jobs")
    if isinstance(jobs, dict):
        for job in jobs.values():
            _add(_permission_dict(job))
    return scopes


def caller_effective_permissions(
    workflow: dict[str, Any], job: dict[str, Any]
) -> dict[str, str] | None:
    """Job-level permissions if present, else workflow-level, else None."""
    if "permissions" in job:
        return _permission_dict(job)
    if "permissions" in workflow:
        return _permission_dict(workflow)
    return None


def permission_gaps(
    caller_perms: dict[str, str] | None,
    callee_scopes: dict[str, str],
) -> list[str]:
    """Scopes the caller does not explicitly grant at the callee's level.

    ``write`` covers ``read``. A caller with no explicit permissions map
    fails every callee-declared scope, because the repository default token
    is not visible in source.
    """
    if not callee_scopes:
        return []
    if caller_perms is None:
        return [
            f"{scope}:{needed} (caller has no explicit permissions)"
            for scope, needed in sorted(callee_scopes.items())
        ]
    gaps = []
    for scope, needed in sorted(callee_scopes.items()):
        have = caller_perms.get(scope, "none")
        if not _covers(have, needed):
            gaps.append(f"{scope}:{needed} (caller has {have})")
    return gaps


def reusable_caller_permission_gaps(workflows_dir: Path) -> list[str]:
    """Gaps for every local ``uses: ./.github/workflows/<callee>.yml`` job."""
    problems: list[str] = []
    for path in sorted(workflows_dir.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(workflow, dict):
            continue
        jobs = workflow.get("jobs")
        if not isinstance(jobs, dict):
            continue
        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                continue
            uses = job.get("uses")
            if not isinstance(uses, str):
                continue
            match = _LOCAL_REUSABLE_USES.fullmatch(uses.strip())
            if match is None:
                continue
            callee_name = match.group(1)
            callee_path = workflows_dir / callee_name
            if not callee_path.is_file():
                problems.append(
                    f"{path.name} job {job_name}: callee {callee_name} is missing"
                )
                continue
            callee = yaml.safe_load(callee_path.read_text(encoding="utf-8"))
            if not isinstance(callee, dict):
                problems.append(
                    f"{path.name} job {job_name}: callee {callee_name} is unreadable"
                )
                continue
            for gap in permission_gaps(
                caller_effective_permissions(workflow, job),
                callee_declared_scopes(callee),
            ):
                problems.append(f"{path.name} job {job_name} -> {callee_name}: {gap}")
    return problems


# Public aliases let split contract modules share these helpers without
# importing private names across module boundaries.
load_ci_workflow = _load_ci_workflow
load_build_core_workflow = _load_build_core_workflow
load_telemetry_workflow = _load_telemetry_workflow
load_master_gate_workflow = _load_master_gate_workflow
workflow_triggers = _workflow_triggers
job_run_text = _job_run_text

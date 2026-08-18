"""Current project derived from the VCS xprompt MRU store.

The current project is the first VCS xprompt MRU entry that resolves to an
enabled project. This module reads ``~/.sase/vcs_xprompt_mru.json`` and
exposes one write path, :func:`set_current_project`, which promotes a
project through :func:`sase.history.vcs_xprompt_mru.record_vcs_xprompt_usage`
— the same store a launch writes, not a second pin file.

Walk the MRU head-first, skip structural refs and disabled projects, and
map a project ref or Patch name onto one enabled project.

``peek_current_project_change_token`` is the cheap poller question — "might
the current project have changed?" — using only ``os.stat`` and the
time-gated :func:`sase.config.core.current_config_token`. The real resolve
belongs on a worker thread, never a render path, message handler, or timer
callback.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.ace.patch.cache import find_all_patches_cached
from sase.config.core import current_config_token
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import (
    ProjectRecordWire,
    effective_project_name,
)
from sase.history.vcs_xprompt_mru import vcs_xprompt_mru_path
from sase.project_alias_records import project_alias_map_from_records
from sase.xprompt import extract_project_from_vcs_tag
from sase.xprompt._parsing import resolve_known_project_ref

#: Minimum interval between filesystem metadata checks on display-only reads.
_PEEK_STAT_FLOOR_SECONDS = 0.5

#: Returned when a stat (other than a missing file) or the config token
#: lookup raises unexpectedly, so a broken read degrades to "no change
#: detected" rather than causing a refresh storm.
_TOKEN_ERROR_SENTINEL: tuple[object, ...] = ("current-project-peek-error",)

_token_cache_lock = threading.Lock()
_token_cache_deadline = 0.0
_token_cache_value: tuple[object, ...] = ()

_Origin = Literal["project", "patch"]


@dataclass(frozen=True, slots=True)
class CurrentProject:
    """One enabled project derived from a VCS xprompt MRU entry."""

    project_key: str
    display_name: str
    origin: _Origin
    origin_ref: str
    workflow_type: str


@dataclass(frozen=True, slots=True)
class SetCurrentProjectOutcome:
    """Result of attempting to promote a project to the MRU head."""

    status: Literal["set", "unchanged", "ineligible", "unverified"]
    project: CurrentProject | None
    message: str


def peek_current_project_change_token() -> tuple[object, ...]:
    """Return a cheap token that changes when the current project might have.

    Built from the MRU file's ``(mtime_ns, size)`` and the current config
    token. Filesystem metadata is checked at most once per short monotonic
    floor. Reads are ``os.stat`` only — no parsing, no project records.
    """
    global _token_cache_deadline, _token_cache_value  # noqa: PLW0603

    current_monotonic = time.monotonic()
    with _token_cache_lock:
        if current_monotonic < _token_cache_deadline:
            return _token_cache_value

        _token_cache_deadline = current_monotonic + _PEEK_STAT_FLOOR_SECONDS
        token: tuple[object, ...]
        try:
            token = (
                _stat_token(vcs_xprompt_mru_path()),
                current_config_token(),
            )
        except Exception:  # noqa: BLE001 - display reads always degrade.
            token = _TOKEN_ERROR_SENTINEL
        _token_cache_value = token
        return token


def resolve_current_project(
    *, projects_dir: Path | None = None
) -> CurrentProject | None:
    """Return the first MRU entry that maps to an enabled project.

    Builds the alias map, known-project map, Patch names, and project
    records once per call. Empty MRU, or an MRU where nothing resolves,
    yields ``None``.
    """
    prefixes = _mru_prefixes()
    if not prefixes:
        return None

    records, alias_map, known_projects = _project_snapshots(projects_dir)
    patches_by_name = _patch_names()
    for prefix in prefixes:
        resolved = _resolve_prefix(
            prefix,
            records=records,
            alias_map=alias_map,
            known_projects=known_projects,
            patches_by_name=patches_by_name,
        )
        if resolved is not None:
            return resolved
    return None


def set_current_project(
    project_key: str,
    *,
    projects_dir: Path | None = None,
) -> SetCurrentProjectOutcome:
    """Promote *project_key* to the head of the VCS xprompt MRU.

    Looks the key up through the same alias map the resolver uses, so a
    display name, alias, or directory key all work. Eligibility failures
    and an already-current project write nothing. A successful write is
    verified by re-resolving rather than assuming the MRU accepted it.
    """
    records, alias_map, _known_projects = _project_snapshots(projects_dir)
    requested = project_key.strip()
    canonical = alias_map.get(requested, requested) if requested else ""
    record = records.get(canonical)
    if record is None:
        label = requested or project_key
        return _ineligible(f"Project '{label}' was not found.")

    display = effective_project_name(record)
    if record.state != "enabled":
        return _ineligible(f"{display} is disabled; enable it first.")
    if not record.launchable or not record.project_file:
        return _ineligible(f"{display} has no launchable ProjectSpec.")

    from sase.workspace_provider import detect_workflow_type

    # Identical to the call ``_vcs_prefix_provider_mismatched`` makes, so a
    # prefix built here cannot be the silently-dropped provider-mismatch write.
    try:
        workflow_type = detect_workflow_type(record.project_file)
    except (OSError, ValueError):
        return _ineligible(f"{display} has no launchable ProjectSpec.")
    if not workflow_type:
        return _ineligible(f"{display} has no launchable ProjectSpec.")

    current = resolve_current_project(projects_dir=projects_dir)
    if current is not None and current.project_key == record.project_name:
        return SetCurrentProjectOutcome(
            status="unchanged",
            project=current,
            message=f"{display} is already the current project.",
        )

    from sase.history.vcs_xprompt_mru import record_vcs_xprompt_usage

    # ``record_vcs_xprompt_usage`` rewrites the file unconditionally; the
    # short-circuit above keeps every ACE instance from re-resolving.
    record_vcs_xprompt_usage(f"#{workflow_type}:{record.project_name}")

    verified = resolve_current_project(projects_dir=projects_dir)
    if verified is not None and verified.project_key == record.project_name:
        return SetCurrentProjectOutcome(
            status="set",
            project=verified,
            message=f"{display} is now the current project.",
        )
    if verified is None:
        return SetCurrentProjectOutcome(
            status="unverified",
            project=None,
            message=(
                f"Could not verify that {display} is current; no project resolved."
            ),
        )
    return SetCurrentProjectOutcome(
        status="unverified",
        project=verified,
        message=(
            f"Could not verify that {display} is current; "
            f"the resolver chose {verified.display_name}."
        ),
    )


def _ineligible(message: str) -> SetCurrentProjectOutcome:
    return SetCurrentProjectOutcome(
        status="ineligible",
        project=None,
        message=message,
    )


def _mru_prefixes() -> list[str]:
    """Load on-disk MRU prefixes without pruning or project-record reads."""
    path = vcs_xprompt_mru_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    entries = data.get("entries", [])
    return [entry for entry in entries if isinstance(entry, str)]


def _project_snapshots(
    projects_dir: Path | None,
) -> tuple[dict[str, ProjectRecordWire], dict[str, str], dict[str, Path]]:
    root = projects_dir if projects_dir is not None else sase_projects_dir()
    if not root.is_dir():
        return {}, {}, {}
    records = list_project_records(root, "all", include_home=False)
    records_by_key = {record.project_name: record for record in records}
    alias_map = project_alias_map_from_records(records, strict=False)
    known_projects: dict[str, Path] = {}
    for record in records:
        if record.state != "enabled" or not record.workspace_dir:
            continue
        workspace = Path(record.workspace_dir).expanduser()
        if workspace.is_dir():
            known_projects[record.project_name] = workspace
    return records_by_key, alias_map, known_projects


def _patch_names() -> dict[str, str]:
    """Return ``patch name -> owning project key`` from one cache read."""
    by_name: dict[str, str] = {}
    for patch in find_all_patches_cached():
        if patch.name not in by_name:
            by_name[patch.name] = patch.project_name
    return by_name


def _resolve_prefix(
    prefix: str,
    *,
    records: dict[str, ProjectRecordWire],
    alias_map: dict[str, str],
    known_projects: dict[str, Path],
    patches_by_name: dict[str, str],
) -> CurrentProject | None:
    ref = extract_project_from_vcs_tag(prefix)
    if ref is None or _is_structural_ref(ref):
        return None

    workflow_type = _workflow_type_from_prefix(prefix)
    canonical_ref = alias_map.get(ref, ref)
    project_key = resolve_known_project_ref(canonical_ref, known_projects)
    if project_key is not None:
        return _project_from_record(
            records.get(project_key),
            origin="project",
            origin_ref=ref,
            workflow_type=workflow_type,
        )

    patch_project = patches_by_name.get(ref)
    if patch_project is None:
        return None
    return _project_from_record(
        records.get(patch_project),
        origin="patch",
        origin_ref=ref,
        workflow_type=workflow_type,
    )


def _project_from_record(
    record: ProjectRecordWire | None,
    *,
    origin: _Origin,
    origin_ref: str,
    workflow_type: str,
) -> CurrentProject | None:
    if record is None or record.state != "enabled":
        return None
    return CurrentProject(
        project_key=record.project_name,
        display_name=effective_project_name(record),
        origin=origin,
        origin_ref=origin_ref,
        workflow_type=workflow_type,
    )


def _is_structural_ref(ref: str) -> bool:
    return "/" in ref or ref.startswith("~") or ref == "home"


def _workflow_type_from_prefix(prefix: str) -> str:
    tag = prefix.strip()
    if not tag.startswith("#"):
        return ""
    body = tag[1:]
    for suffix in ("!!", "??"):
        idx = body.find(suffix)
        if idx != -1:
            body = body[:idx] + body[idx + len(suffix) :]
            break
    separators = [
        idx for idx in (body.find(":"), body.find("_"), body.find("(")) if idx >= 0
    ]
    if separators:
        body = body[: min(separators)]
    if body.endswith("+"):
        body = body[:-1]
    return body


def _stat_token(path: Path) -> tuple[int, int] | None:
    """Return ``(mtime_ns, size)`` for *path*, or ``None`` when missing."""
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


__all__ = [
    "CurrentProject",
    "SetCurrentProjectOutcome",
    "peek_current_project_change_token",
    "resolve_current_project",
    "set_current_project",
]

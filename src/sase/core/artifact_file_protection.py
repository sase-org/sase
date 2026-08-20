"""Collect artifact ids protected by durable references or consumption."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re

from sase._repo_inventory_models import RepoRecord
from sase.core.artifact_consumption import default_artifact_consumption_log_path
from sase.core.artifact_consumption_query import summarize_artifact_consumption
from sase.core.paths import sase_projects_dir
from sase.repo_inventory import collect_repo_inventory


_ARTIFACT_ID_RE = re.compile(r"(?:file:)?(?P<id>(?:default|explicit):[0-9a-f]{24})")
_CONSUMED_FILE_REF_RE = re.compile(r"file:(?P<id>(?:default|explicit):[0-9a-f]{24})")
_TEXT_SUFFIXES = frozenset({".json", ".md", ".sase", ".txt", ".yml"})
_REQUIRED_SIDECAR_ROLES = ("beads", "plans")
_OPPORTUNISTIC_SIDECAR_ROLES = ("research",)
# Beads carry canonical artifact references in their `refs` list, and page
# publication can lag a `sase bead ref add`, so the store's current-state
# projection is scanned by name rather than by suffix. The append-only event
# streams under `events/` stay excluded: a `ReferenceRemoved` payload still
# names the id it detached, so replaying them would protect artifacts forever.
_ROLE_FILENAMES = {"beads": frozenset({"issues.jsonl"})}


@dataclass(frozen=True)
class ProtectedArtifactIds:
    """Protected ids by source plus collection coverage evidence."""

    referenced_ids: frozenset[str]
    consumed_ids: frozenset[str]
    sources_scanned: tuple[str, ...]
    sources_unavailable: tuple[str, ...]

    @property
    def ids(self) -> frozenset[str]:
        """Return the deduplicated union accepted by retention planners."""

        return self.referenced_ids | self.consumed_ids

    @property
    def overlap_ids(self) -> frozenset[str]:
        """Return ids protected by both durable references and consumption."""

        return self.referenced_ids & self.consumed_ids


def collect_protected_artifact_ids() -> ProtectedArtifactIds:
    """Collect durable-reference and recorded-consumption protections."""

    referenced_ids: set[str] = set()
    consumed_ids: set[str] = set()
    scanned: set[str] = set()
    unavailable: set[str] = set()

    projects_root = sase_projects_dir()
    _scan_root(
        projects_root,
        ids=referenced_ids,
        scanned=scanned,
        unavailable=unavailable,
        required=True,
        suffixes=frozenset({".sase"}),
    )

    try:
        inventory = collect_repo_inventory()
    except Exception as exc:
        unavailable.add(f"repository inventory: {exc}")
    else:
        project_names = sorted(
            {record.project for record in inventory.records if record.kind == "primary"}
        )
        for project in project_names:
            records = tuple(
                record
                for record in inventory.records
                if record.project == project and record.kind == "sidecar"
            )
            for role in _REQUIRED_SIDECAR_ROLES:
                root = _live_sidecar_root(records, role)
                if root is None:
                    unavailable.add(f"{project}:{role}")
                    continue
                _scan_root(
                    root,
                    ids=referenced_ids,
                    scanned=scanned,
                    unavailable=unavailable,
                    required=True,
                    suffixes=_TEXT_SUFFIXES,
                    extra_filenames=_ROLE_FILENAMES.get(role, frozenset()),
                )
            for role in _OPPORTUNISTIC_SIDECAR_ROLES:
                root = _live_sidecar_root(records, role)
                if root is None:
                    continue
                _scan_root(
                    root,
                    ids=referenced_ids,
                    scanned=scanned,
                    unavailable=unavailable,
                    required=False,
                    suffixes=_TEXT_SUFFIXES,
                )

    _collect_consumed_ids(
        ids=consumed_ids,
        scanned=scanned,
        unavailable=unavailable,
    )
    _collect_linked_ids(
        ids=referenced_ids,
        scanned=scanned,
        unavailable=unavailable,
    )

    return ProtectedArtifactIds(
        referenced_ids=frozenset(referenced_ids),
        consumed_ids=frozenset(consumed_ids),
        sources_scanned=tuple(sorted(scanned)),
        sources_unavailable=tuple(sorted(unavailable)),
    )


def _collect_consumed_ids(
    *,
    ids: set[str],
    scanned: set[str],
    unavailable: set[str],
) -> None:
    ledger = default_artifact_consumption_log_path().expanduser().resolve(strict=False)
    try:
        ledger_exists = ledger.exists()
    except OSError as exc:
        unavailable.add(f"{ledger}: {exc}")
        return
    if not ledger_exists:
        return

    try:
        summaries = summarize_artifact_consumption(log_path=ledger)
    except Exception as exc:
        unavailable.add(f"{ledger}: {exc}")
        return

    scanned.add(str(ledger))
    for reference in summaries:
        match = _CONSUMED_FILE_REF_RE.fullmatch(reference)
        if match is not None:
            ids.add(match.group("id"))


def _collect_linked_ids(
    *,
    ids: set[str],
    scanned: set[str],
    unavailable: set[str],
) -> None:
    """Protect ``file:`` ids named by the rebuildable artifact-link aggregate."""

    projects_root = sase_projects_dir()
    try:
        if not projects_root.is_dir():
            return
        project_dirs = sorted(projects_root.iterdir())
    except OSError as exc:
        unavailable.add(f"{projects_root}: {exc}")
        return

    for project_dir in project_dirs:
        path = project_dir / "artifact-links.json"
        try:
            exists = path.is_file()
        except OSError as exc:
            unavailable.add(f"{path}: {exc}")
            continue
        if not exists:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            unavailable.add(f"{path}: {exc}")
            continue
        scanned.add(str(path))
        ids.update(match.group("id") for match in _ARTIFACT_ID_RE.finditer(text))


def _live_sidecar_root(
    records: tuple[RepoRecord, ...],
    role: str,
) -> Path | None:
    candidates = tuple(record for record in records if _record_has_role(record, role))
    for record in candidates:
        paths = ((record.path, record.exists),) + tuple(
            (clone.path, clone.exists) for clone in record.clones
        )
        for raw_path, exists in paths:
            if exists and raw_path:
                path = Path(raw_path).expanduser()
                if path.is_dir():
                    return path
    return None


def _record_has_role(record: RepoRecord, role: str) -> bool:
    tokens = (record.name, record.slug or "")
    return any(token == role or token.endswith(f"--{role}") for token in tokens)


def _scan_root(
    root: Path,
    *,
    ids: set[str],
    scanned: set[str],
    unavailable: set[str],
    required: bool,
    suffixes: frozenset[str],
    extra_filenames: frozenset[str] = frozenset(),
) -> None:
    resolved = root.expanduser().resolve(strict=False)
    if not resolved.is_dir():
        if required:
            unavailable.add(str(resolved))
        return

    walk_errors: list[OSError] = []
    try:
        for directory, child_dirs, filenames in os.walk(
            resolved,
            followlinks=False,
            onerror=walk_errors.append,
        ):
            child_dirs[:] = [
                name
                for name in child_dirs
                if name != ".git" and not (Path(directory) / name).is_symlink()
            ]
            for filename in filenames:
                path = Path(directory) / filename
                if (
                    path.suffix.lower() not in suffixes
                    and filename not in extra_filenames
                ):
                    continue
                if path.is_symlink():
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    if required:
                        unavailable.add(str(path))
                    continue
                ids.update(
                    match.group("id") for match in _ARTIFACT_ID_RE.finditer(text)
                )
    except OSError:
        if required:
            unavailable.add(str(resolved))
        return

    scanned.add(str(resolved))
    if required:
        unavailable.update(f"{resolved}: {error}" for error in walk_errors)


__all__ = [
    "ProtectedArtifactIds",
    "collect_protected_artifact_ids",
]

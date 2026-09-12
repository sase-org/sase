"""Protection-source scanning for ACE-run artifact-directory retention."""

from __future__ import annotations

import os
import re
from pathlib import Path

from sase._repo_inventory_models import RepoInventory, RepoRecord
from sase.bead.model import Status
from sase.core import bead_read_facade as rust_beads
from sase.core.agent_artifact_paths import (
    ACE_RUN_WORKFLOW_DIR,
    parse_agent_artifact_path,
)
from sase.core.agent_artifact_run_retention_models import AceRunProtectionSnapshot
from sase.core.artifact_file_explicit import read_artifact_file_index
from sase.core.paths import sase_home, sase_projects_dir
from sase.repo_inventory import collect_repo_inventory


_TEXT_SUFFIXES = frozenset({".json", ".md", ".sase", ".txt", ".yml"})
_ROLE_FILENAMES: dict[str, frozenset[str]] = {}
_REQUIRED_SIDECAR_ROLES = ("beads", "plans")
# Prompt and chat archives can be much larger than the local run-dir corpus;
# they stay sidecar-backed readers, while durable run-dir refs enter through
# artifact indexes, links, bead state, plans, gates, and run metadata.
_OPPORTUNISTIC_SIDECAR_ROLES = ("research",)
_MAX_TEXT_SCAN_BYTES = 2 * 1024 * 1024
_AGENT_REF_RE = re.compile(r"(?<![\w.-])agent:(?P<name>[A-Za-z0-9_.~-]+)")
_ACE_RUN_REF_RE = re.compile(
    r"artifacts/ace-run/(?:\d{6}/\d{2}/)?(?P<timestamp>\d{14})"
)
_TRAILING_REF_PUNCTUATION = ".,;:)]}"


def collect_ace_run_retention_protections(
    *,
    projects_root: Path | str | None = None,
    artifact_index_path: Path | str | None = None,
    inventory: RepoInventory | None = None,
) -> AceRunProtectionSnapshot:
    """Collect references that make old ACE-run directories non-reclaimable."""

    root = Path(projects_root).expanduser() if projects_root else sase_projects_dir()
    dirs: set[str] = set()
    agent_names: set[str] = set()
    timestamps: set[str] = set()
    non_closed: dict[str, frozenset[str]] = {}
    scanned: set[str] = set()
    unavailable: set[str] = set()

    _collect_artifact_file_index_dirs(
        dirs=dirs,
        timestamps=timestamps,
        scanned=scanned,
        unavailable=unavailable,
        index_path=artifact_index_path,
        projects_root=root,
    )
    _scan_text_root(
        root,
        dirs=dirs,
        agent_names=agent_names,
        timestamps=timestamps,
        scanned=scanned,
        unavailable=unavailable,
        required=True,
        suffixes=frozenset({".sase"}),
        skip_dir_names=frozenset({".git", "artifacts", "repos"}),
    )

    try:
        repo_inventory = collect_repo_inventory() if inventory is None else inventory
    except Exception as exc:  # noqa: BLE001 - retention apply must know coverage gaps.
        unavailable.add(f"repository inventory: {exc}")
        repo_inventory = RepoInventory(())

    primary_projects = sorted(
        {
            record.project
            for record in repo_inventory.records
            if record.kind == "primary" and record.project
        }
    )
    for project in primary_projects:
        records = tuple(
            record
            for record in repo_inventory.records
            if record.project == project and record.kind == "sidecar"
        )
        _collect_project_sidecar_refs(
            project,
            records,
            dirs=dirs,
            agent_names=agent_names,
            timestamps=timestamps,
            non_closed=non_closed,
            scanned=scanned,
            unavailable=unavailable,
        )

    _scan_state_refs(
        dirs=dirs,
        agent_names=agent_names,
        timestamps=timestamps,
        scanned=scanned,
    )

    return AceRunProtectionSnapshot(
        protected_dirs=frozenset(dirs),
        protected_agent_names=frozenset(agent_names),
        protected_timestamps=frozenset(timestamps),
        non_closed_bead_ids_by_project=non_closed,
        sources_scanned=tuple(sorted(scanned)),
        sources_unavailable=tuple(sorted(unavailable)),
    )


def _collect_project_sidecar_refs(
    project: str,
    records: tuple[RepoRecord, ...],
    *,
    dirs: set[str],
    agent_names: set[str],
    timestamps: set[str],
    non_closed: dict[str, frozenset[str]],
    scanned: set[str],
    unavailable: set[str],
) -> None:
    for role in _REQUIRED_SIDECAR_ROLES:
        sidecar = _live_sidecar_root(records, role)
        if sidecar is None:
            unavailable.add(f"{project}:{role}")
            continue
        if role == "beads":
            non_closed[project] = _collect_bead_issue_refs(
                sidecar,
                dirs=dirs,
                agent_names=agent_names,
                timestamps=timestamps,
                scanned=scanned,
                unavailable=unavailable,
            )
            continue
        _scan_text_root(
            sidecar,
            dirs=dirs,
            agent_names=agent_names,
            timestamps=timestamps,
            scanned=scanned,
            unavailable=unavailable,
            required=True,
            suffixes=_TEXT_SUFFIXES,
            extra_filenames=_ROLE_FILENAMES.get(role, frozenset()),
            skip_dir_names=frozenset({".git", "artifacts"}),
        )
    for role in _OPPORTUNISTIC_SIDECAR_ROLES:
        sidecar = _live_sidecar_root(records, role)
        if sidecar is None:
            continue
        _scan_text_root(
            sidecar,
            dirs=dirs,
            agent_names=agent_names,
            timestamps=timestamps,
            scanned=scanned,
            unavailable=unavailable,
            required=False,
            suffixes=_TEXT_SUFFIXES,
            skip_dir_names=frozenset({".git", "artifacts"}),
        )


def _collect_artifact_file_index_dirs(
    *,
    dirs: set[str],
    timestamps: set[str],
    scanned: set[str],
    unavailable: set[str],
    index_path: Path | str | None,
    projects_root: Path,
) -> None:
    try:
        rows = read_artifact_file_index(index_path)
    except Exception as exc:  # noqa: BLE001 - apply blocks on this coverage gap.
        unavailable.add(f"artifact file index: {exc}")
        return
    if index_path is not None:
        scanned.add(str(Path(index_path).expanduser()))
    for row in rows:
        if not row.agent_artifacts_dir:
            continue
        path = Path(row.agent_artifacts_dir).expanduser()
        parsed = parse_agent_artifact_path(path, projects_root=projects_root)
        if parsed is None or parsed.workflow_dir_name != ACE_RUN_WORKFLOW_DIR:
            continue
        dirs.add(_normalized_path(path))
        timestamps.add(parsed.timestamp)


def _collect_bead_issue_refs(
    root: Path,
    *,
    dirs: set[str],
    agent_names: set[str],
    timestamps: set[str],
    scanned: set[str],
    unavailable: set[str],
) -> frozenset[str]:
    try:
        issues = rust_beads.list_issues(root)
    except Exception as exc:  # noqa: BLE001 - apply blocks on this coverage gap.
        unavailable.add(f"{root}: {exc}")
        return frozenset()
    scanned.add(f"{root}:issues")
    for issue in issues:
        _collect_text_refs(
            issue.description, dirs=dirs, agent_names=agent_names, timestamps=timestamps
        )
        _collect_text_refs(
            issue.design, dirs=dirs, agent_names=agent_names, timestamps=timestamps
        )
        for ref in issue.refs:
            _collect_text_refs(
                ref, dirs=dirs, agent_names=agent_names, timestamps=timestamps
            )
        for note in issue.notes:
            _collect_text_refs(
                note.text, dirs=dirs, agent_names=agent_names, timestamps=timestamps
            )
        for link in issue.links:
            _collect_text_refs(
                link.target_ref,
                dirs=dirs,
                agent_names=agent_names,
                timestamps=timestamps,
            )
            _collect_text_refs(
                link.description,
                dirs=dirs,
                agent_names=agent_names,
                timestamps=timestamps,
            )
    return frozenset(issue.id for issue in issues if issue.status is not Status.CLOSED)


def _scan_text_root(
    root: Path,
    *,
    dirs: set[str],
    agent_names: set[str],
    timestamps: set[str],
    scanned: set[str],
    unavailable: set[str],
    required: bool,
    suffixes: frozenset[str],
    extra_filenames: frozenset[str] = frozenset(),
    skip_dir_names: frozenset[str] = frozenset({".git"}),
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
                if name not in skip_dir_names
                and not (Path(directory) / name).is_symlink()
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
                    size_bytes = path.stat().st_size
                except OSError:
                    if required:
                        unavailable.add(str(path))
                    continue
                if size_bytes > _MAX_TEXT_SCAN_BYTES:
                    if required:
                        unavailable.add(
                            f"{path}: exceeds {_MAX_TEXT_SCAN_BYTES} byte scan limit"
                        )
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    if required:
                        unavailable.add(str(path))
                    continue
                _collect_text_refs(
                    text,
                    dirs=dirs,
                    agent_names=agent_names,
                    timestamps=timestamps,
                )
    except OSError:
        if required:
            unavailable.add(str(resolved))
        return
    scanned.add(str(resolved))
    if required:
        unavailable.update(f"{resolved}: {error}" for error in walk_errors)


def _scan_state_refs(
    *,
    dirs: set[str],
    agent_names: set[str],
    timestamps: set[str],
    scanned: set[str],
) -> None:
    for path in (
        sase_home() / "notifications" / "notifications.jsonl",
        sase_home() / "notifications" / "mentors_complete.json",
    ):
        _scan_text_file(
            path,
            dirs=dirs,
            agent_names=agent_names,
            timestamps=timestamps,
            scanned=scanned,
            required=False,
        )
    requests_root = sase_home() / "interaction_requests"
    try:
        children = tuple(requests_root.iterdir())
    except OSError:
        return
    for child in children:
        if child.is_file() and child.suffix.lower() == ".json":
            _scan_text_file(
                child,
                dirs=dirs,
                agent_names=agent_names,
                timestamps=timestamps,
                scanned=scanned,
                required=False,
            )


def _scan_text_file(
    path: Path,
    *,
    dirs: set[str],
    agent_names: set[str],
    timestamps: set[str],
    scanned: set[str],
    required: bool,
    unavailable: set[str] | None = None,
) -> None:
    try:
        if path.is_symlink() or not path.is_file():
            return
        size_bytes = path.stat().st_size
    except OSError:
        if required and unavailable is not None:
            unavailable.add(str(path))
        return
    if size_bytes > _MAX_TEXT_SCAN_BYTES:
        if required and unavailable is not None:
            unavailable.add(f"{path}: exceeds {_MAX_TEXT_SCAN_BYTES} byte scan limit")
        return
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        if required and unavailable is not None:
            unavailable.add(str(path))
        return
    _collect_text_refs(text, dirs=dirs, agent_names=agent_names, timestamps=timestamps)
    scanned.add(str(path))


def _collect_text_refs(
    text: str,
    *,
    dirs: set[str],
    agent_names: set[str],
    timestamps: set[str],
) -> None:
    for match in _AGENT_REF_RE.finditer(text):
        name = match.group("name").rstrip(_TRAILING_REF_PUNCTUATION)
        if name:
            agent_names.add(name)
    for match in _ACE_RUN_REF_RE.finditer(text):
        raw_path = _token_around_match(text, match.start(), match.end())
        timestamps.add(match.group("timestamp"))
        if raw_path.startswith(("~", "/")):
            dirs.add(_normalized_path(raw_path))


def _token_around_match(text: str, start: int, end: int) -> str:
    token_start = start
    while token_start > 0 and text[token_start - 1] not in " \t\r\n\"'<>`|":
        token_start -= 1
    token_end = end
    while token_end < len(text) and text[token_end] not in " \t\r\n\"'<>`|":
        token_end += 1
    return text[token_start:token_end].rstrip(_TRAILING_REF_PUNCTUATION)


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


def _normalized_path(path: Path | str) -> str:
    if not path:
        return ""
    return str(Path(path).expanduser().resolve(strict=False))


__all__ = ["collect_ace_run_retention_protections"]

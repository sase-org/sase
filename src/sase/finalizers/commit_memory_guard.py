"""Advisory finalizer memory guard (sase-1hi.8 guard phase).

A host-side, never-blocking commit-finalizer check: when an agent launched
from an approved plan commits a memory note no accepted memory decision (its
own or inherited from its epic) covers, the commit still lands and the
finalizer emits a ``warning`` diagnostic naming each uncovered path and the
plan. Agents not launched from a plan are never checked.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.finalizer_wire import FinalizerDiagnosticWire

GUARD_DIAGNOSTIC_CODE = "memory_change_uncovered"

_MEMORY_CANONICAL_PREFIX = "sase/memory/"
_MEMORY_LEGACY_PREFIX = "memory/"
_MEMORY_README_SUFFIX = "sase/memory/README.md"
_MEMORY_README_LEGACY = "memory/README.md"

_GENERATED_ROOT_BASENAMES = frozenset(
    {"AGENTS.md", "CLAUDE.md", "GEMINI.md", "QWEN.md", "OPENCODE.md"}
)

_PLAN_LAUNCH_META_KEYS = (
    "sdd_plan_path",
    "plan_archive_ref",
    "epic_plan_ref",
    "epic_plan_snapshot",
    "phase_bead_id",
    "epic_bead_id",
)


@dataclass(frozen=True)
class _MemoryCoverage:
    """Frozen memory authorization for one finalizer turn."""

    plan_label: str
    exact: frozenset[str]
    prefixes: tuple[str, ...]


def _canonical_memory_path(repo_relative: str) -> str | None:
    """Return the canonical ``sase/memory/...`` form of a repo-relative path."""
    text = repo_relative.replace("\\", "/").strip().lstrip("./")
    while text.startswith("/"):
        text = text[1:]
    lowered = text.lower()
    if lowered == _MEMORY_README_SUFFIX or lowered == _MEMORY_README_LEGACY:
        return _MEMORY_README_SUFFIX
    if lowered.startswith(_MEMORY_CANONICAL_PREFIX):
        rest = text[len(_MEMORY_CANONICAL_PREFIX) :]
        if not rest or rest.endswith("/"):
            return None
        return f"{_MEMORY_CANONICAL_PREFIX}{rest}"
    if lowered.startswith(_MEMORY_LEGACY_PREFIX):
        rest = text[len(_MEMORY_LEGACY_PREFIX) :]
        if not rest or rest.endswith("/"):
            return None
        return f"{_MEMORY_CANONICAL_PREFIX}{rest}"
    return None


def _is_generated_root_path(repo_relative: str) -> bool:
    """Return whether a repo-relative path is a generated root doc."""
    text = repo_relative.replace("\\", "/").strip()
    stripped = text.strip()
    while stripped.startswith("./"):
        stripped = stripped[2:]
    stripped = stripped.lstrip("/")
    if "/" in stripped:
        return False
    if stripped in _GENERATED_ROOT_BASENAMES:
        return True
    return stripped == "AGENTS.md.tmpl"


def _classify_changed_path(repo_relative: str) -> tuple[str, str | None]:
    """Classify one repo-relative changed path for the guard.

    Returns ``(kind, canonical)`` where kind is ``memory``, ``generated``,
    or ``other``. ``generated`` covers root ``AGENTS.md``, provider shims,
    and the memory README; ``memory`` covers every other
    ``sase/memory/**`` path.
    """
    canonical = _canonical_memory_path(repo_relative)
    if canonical is not None:
        if canonical == _MEMORY_README_SUFFIX:
            return ("generated", canonical)
        return ("memory", canonical)
    if _is_generated_root_path(repo_relative):
        return ("generated", repo_relative.replace("\\", "/").strip())
    return ("other", None)


def _slug_from_record_path(path: str) -> str:
    text = path.replace("\\", "/").strip().strip("/")
    if text.lower().startswith(_MEMORY_CANONICAL_PREFIX):
        text = text[len(_MEMORY_CANONICAL_PREFIX) :]
    elif text.lower().startswith(_MEMORY_LEGACY_PREFIX):
        text = text[len(_MEMORY_LEGACY_PREFIX) :]
    stem = text.rsplit("/", 1)[-1]
    if stem.lower().endswith(".md"):
        stem = stem[: -len(".md")]
    return stem


def _note_record_paths(record: dict[str, Any]) -> list[str]:
    raw = str(record.get("path") or "").strip()
    if not raw:
        return []
    canonical = _canonical_memory_path(raw)
    if canonical is not None:
        return [canonical]
    if raw.lower().endswith(".md") and "/" not in raw.replace("\\", "/"):
        return [f"{_MEMORY_CANONICAL_PREFIX}{raw}"]
    return []


def _coverage_from_sheet_rows(rows: list[dict[str, Any]]) -> _MemoryCoverage:
    """Build coverage from Decision Sheet rows (memory rows answered yes)."""
    exact: set[str] = set()
    prefixes: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("value") is not True:
            continue
        memory = row.get("memory")
        if not isinstance(memory, dict):
            continue
        resolved = memory.get("resolved")
        if not isinstance(resolved, list):
            continue
        selectors = memory.get("selectors")
        selector_texts = (
            [str(item) for item in selectors if str(item).strip()]
            if isinstance(selectors, list)
            else []
        )
        strand_specific = any(":" in item for item in selector_texts)
        for record in resolved:
            if not isinstance(record, dict):
                continue
            kind = str(record.get("kind") or "").strip().lower()
            if kind == "note":
                exact.update(_note_record_paths(record))
            elif kind == "strand":
                strand_path = _canonical_memory_path(str(record.get("path") or ""))
                if strand_path is not None:
                    exact.add(strand_path)
            elif kind == "web":
                slug = _slug_from_record_path(str(record.get("path") or ""))
                if not slug:
                    continue
                descriptor = f"{_MEMORY_CANONICAL_PREFIX}{slug}.md"
                strands = record.get("strands")
                strand_keys = (
                    [str(item) for item in strands if str(item).strip()]
                    if isinstance(strands, list)
                    else []
                )
                if strand_specific and strand_keys:
                    for keyword in strand_keys:
                        exact.add(f"{_MEMORY_CANONICAL_PREFIX}{slug}/{keyword}.md")
                    exact.add(descriptor)
                elif strand_keys:
                    prefixes.add(f"{_MEMORY_CANONICAL_PREFIX}{slug}/")
                    exact.add(descriptor)
                else:
                    prefixes.add(f"{_MEMORY_CANONICAL_PREFIX}{slug}/")
                    exact.add(descriptor)
    return _MemoryCoverage(
        plan_label="", exact=frozenset(exact), prefixes=tuple(sorted(prefixes))
    )


def _coverage_from_sheets(
    sheet: dict[str, Any] | None,
    inherited_sheet: dict[str, Any] | None,
    *,
    plan_label: str,
) -> _MemoryCoverage:
    """Union a plan sheet with its inherited epic grants into one coverage."""
    exact: set[str] = set()
    prefixes: set[str] = set()
    for candidate in (sheet, inherited_sheet):
        if not isinstance(candidate, dict):
            continue
        rows = candidate.get("rows")
        if not isinstance(rows, list):
            continue
        typed_rows = [row for row in rows if isinstance(row, dict)]
        part = _coverage_from_sheet_rows(typed_rows)
        exact.update(part.exact)
        prefixes.update(part.prefixes)
    return _MemoryCoverage(
        plan_label=plan_label, exact=frozenset(exact), prefixes=tuple(sorted(prefixes))
    )


def _is_covered(canonical: str, coverage: _MemoryCoverage) -> bool:
    if canonical in coverage.exact:
        return True
    return any(canonical.startswith(prefix) for prefix in coverage.prefixes)


def _find_uncovered_memory_changes(
    changed_repo_paths: list[str],
    coverage: _MemoryCoverage,
) -> list[str]:
    """Return the sorted uncovered canonical paths from repo-relative changes.

    Generated root docs (``AGENTS.md``, provider shims) and the memory
    README count as covered only when a covered non-generated memory note
    changed in the same declaration. Everything else under
    ``sase/memory/**`` needs its own accepted memory decision.
    """
    memory_hits: list[str] = []
    generated_hits: list[str] = []
    for raw in changed_repo_paths:
        kind, canonical = _classify_changed_path(raw)
        if kind == "memory" and canonical is not None:
            memory_hits.append(canonical)
        elif kind == "generated" and canonical is not None:
            generated_hits.append(canonical)
    covered_memory = [path for path in memory_hits if _is_covered(path, coverage)]
    uncovered: list[str] = [path for path in memory_hits if path not in covered_memory]
    if generated_hits and not covered_memory:
        uncovered.extend(generated_hits)
    return sorted(set(uncovered))


def _memory_guard_diagnostic(
    uncovered: list[str],
    plan_label: str,
    instance_id: str | None = None,
) -> FinalizerDiagnosticWire:
    """Build the never-blocking advisory warning for uncovered memory edits."""
    paths = ", ".join(sorted(set(uncovered)))
    label = plan_label.strip() or "the approved plan"
    return FinalizerDiagnosticWire(
        code=GUARD_DIAGNOSTIC_CODE,
        severity="warning",
        message=(
            f"memory_change_uncovered: {paths} changed without an accepted "
            f"memory decision covering them in {label}; "
            "add a memory decision or leave the note unchanged"
        ),
        instance_id=instance_id,
    )


def _agent_meta(artifacts_dir: str | None) -> dict[str, Any]:
    if not artifacts_dir:
        return {}
    try:
        payload = json.loads(
            (Path(artifacts_dir).expanduser() / "agent_meta.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, UnicodeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _plan_launch_signal(meta: dict[str, Any]) -> bool:
    for key in _PLAN_LAUNCH_META_KEYS:
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def _plan_candidates_from_env_and_meta(
    artifacts_dir: str | None, meta: dict[str, Any]
) -> list[str]:
    candidates: list[str] = []
    env_plan = (os.environ.get("SASE_PLAN") or "").strip()
    if env_plan:
        candidates.append(env_plan)
    for key in ("sdd_plan_path", "epic_plan_snapshot", "epic_plan_ref"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())
    archive_ref = meta.get("plan_archive_ref")
    if isinstance(archive_ref, str) and archive_ref.strip():
        resolved = _resolve_archive_ref(archive_ref.strip(), _guard_plan_roots(meta))
        if resolved is not None:
            candidates.append(resolved)
    seen: set[str] = set()
    ordered: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            ordered.append(candidate)
    return ordered


def _guard_plan_roots(meta: dict[str, Any]) -> tuple[Path, ...]:
    """Return plan roots for archive-ref resolution, best effort."""
    roots: list[Path] = []
    try:
        from sase.bead.cli_detail_context import plan_reference_roots
        from sase.sdd.plan_refs import (
            resolve_plan_roots,
            workspace_context_for_plan_resolution,
        )

        try:
            roots.extend(plan_reference_roots())
        except Exception:
            pass
        for key in (
            "agent_project_file",
            "project_file",
            "project_dir",
            "workspace_dir",
            "workspace",
        ):
            raw = meta.get(key)
            if not isinstance(raw, str) or not raw.strip():
                continue
            try:
                candidate = Path(raw.strip()).expanduser()
                base = candidate.parent if candidate.suffix else candidate
                workspace_dir, workspace_num = workspace_context_for_plan_resolution(
                    base
                )
                for root in resolve_plan_roots(workspace_dir, workspace_num):
                    if root not in roots:
                        roots.append(root)
            except Exception:
                continue
    except Exception:
        pass
    return tuple(roots)


def _resolve_archive_ref(ref: str, roots: tuple[Path, ...] | None = None) -> str | None:
    try:
        from sase.sdd.plan_refs import resolve_plan_reference_from_roots
    except Exception:
        return None
    candidate_roots: list[Path] = list(roots or ())
    if not candidate_roots:
        try:
            from sase.bead.cli_detail_context import plan_reference_roots

            candidate_roots.extend(plan_reference_roots())
        except Exception:
            pass
    for root_set in (tuple(candidate_roots), ()):
        try:
            if not root_set:
                continue
            resolution = resolve_plan_reference_from_roots(ref, roots=root_set)
        except Exception:
            continue
        resolved = getattr(resolution, "resolved_path", None)
        if resolved is not None and Path(str(resolved)).is_file():
            return str(resolved)
    direct = Path(ref.strip().lstrip("@")).expanduser()
    if direct.is_file():
        return str(direct)
    return None


def _load_sheet_for_plan(plan_path: str) -> tuple[dict[str, Any] | None, str] | None:
    """Return ``(sheet, title)`` for an existing plan file, else ``None``."""
    try:
        from sase.sdd.plan_decision_handoff import load_stamped_decisions
    except Exception:
        return None
    path = Path(plan_path.strip().lstrip("@")).expanduser()
    if not path.is_file():
        try:
            from sase.bead.cli_detail_context import plan_reference_roots
            from sase.sdd.plan_refs import resolve_plan_reference_from_roots

            roots = plan_reference_roots()
            if roots:
                resolution = resolve_plan_reference_from_roots(
                    plan_path.strip(), roots=roots
                )
                resolved = getattr(resolution, "resolved_path", None)
                if resolved is not None and Path(str(resolved)).is_file():
                    path = Path(str(resolved))
        except Exception:
            pass
        if not path.is_file():
            return None
    try:
        stamped = load_stamped_decisions(path)
    except Exception:
        return None
    if stamped is None:
        return None
    return (stamped.sheet, stamped.title)


def _resolve_memory_coverage(artifacts_dir: str | None) -> _MemoryCoverage | None:
    """Resolve the frozen memory grants for this finalizer turn.

    Returns ``None`` for agents not launched from a plan (the
    direct-prompt route stays valid and is never checked). A plan-launched
    agent with no accepted memory grants resolves to empty coverage, so any
    memory edit warns.
    """
    meta = _agent_meta(artifacts_dir)
    plan_candidates = _plan_candidates_from_env_and_meta(artifacts_dir, meta)
    try:
        from sase.sdd.plan_decision_handoff import epic_decision_context
    except Exception:
        epic_decision_context = None  # type: ignore[assignment]
    inherited_sheet: dict[str, Any] | None = None
    inherited_title = ""
    if epic_decision_context is not None and artifacts_dir:
        try:
            context = epic_decision_context(artifacts_dir)
        except Exception:
            context = None
        if context is not None:
            inherited_sheet = context.sheet
            inherited_title = context.epic_title
    sheet: dict[str, Any] | None = None
    plan_label = ""
    for candidate in plan_candidates:
        loaded = _load_sheet_for_plan(candidate)
        if loaded is None:
            continue
        sheet, title = loaded
        plan_label = f"plan {Path(candidate).stem}"
        if title.strip():
            plan_label = f"plan {title.strip()}"
        break
    if sheet is None and inherited_sheet is None:
        if plan_candidates or _plan_launch_signal(meta):
            label = plan_label or "the approved plan"
            if inherited_title.strip():
                label = f"epic {inherited_title.strip()}"
            return _MemoryCoverage(plan_label=label, exact=frozenset(), prefixes=())
        return None
    label = plan_label or (
        f"epic {inherited_title.strip()}"
        if inherited_title.strip()
        else "the approved plan"
    )
    return _coverage_from_sheets(sheet, inherited_sheet, plan_label=label)


def _git_diff_tree_files(repo_path: str, commit_sha: str) -> list[str]:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                repo_path,
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                commit_sha,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _collect_committed_paths_by_repo(
    markers: list[dict[str, Any]],
    *,
    list_files: Any | None = None,
) -> dict[str, list[str]]:
    """Group repo-relative committed paths by the marker's ``cwd``."""
    lister = list_files or _git_diff_tree_files
    grouped: dict[str, list[str]] = {}
    for marker in markers:
        if not isinstance(marker, dict):
            continue
        cwd = marker.get("cwd")
        sha = marker.get("commit_sha")
        if not isinstance(cwd, str) or not cwd.strip():
            continue
        if not isinstance(sha, str) or not sha.strip():
            continue
        try:
            files = lister(cwd.strip(), sha.strip())
        except Exception:
            continue
        if not files:
            continue
        key = cwd.strip()
        bucket = grouped.setdefault(key, [])
        bucket.extend(str(item) for item in files if str(item).strip())
    return grouped


def _build_memory_guard_diagnostics(
    changed_repo_paths: list[str],
    coverage: _MemoryCoverage | None,
    *,
    instance_id: str | None = None,
) -> list[FinalizerDiagnosticWire]:
    """Return the advisory warning, or ``[]`` when nothing is uncovered."""
    if coverage is None:
        return []
    uncovered = _find_uncovered_memory_changes(changed_repo_paths, coverage)
    if not uncovered:
        return []
    return [_memory_guard_diagnostic(uncovered, coverage.plan_label, instance_id)]


def _marker_key(marker: dict[str, Any]) -> tuple[Any, ...]:
    return (
        marker.get("cwd"),
        marker.get("result"),
        marker.get("commit_sha"),
        marker.get("commit_tree"),
        marker.get("entry_id"),
    )


def memory_guard_for_new_markers(
    artifacts_dir: str | None,
    before_markers: list[dict[str, Any]],
    after_markers: list[dict[str, Any]],
    *,
    instance_id: str | None = None,
) -> list[FinalizerDiagnosticWire]:
    """Return advisory warnings for memory files committed between markers.

    Never raises and never blocks: any resolution, git, or binding failure
    yields ``[]`` so the commit still lands without the warning.
    """
    try:
        before_keys = {_marker_key(item) for item in before_markers}
        new_markers = [
            dict(item) for item in after_markers if _marker_key(item) not in before_keys
        ]
        if not new_markers:
            return []
        coverage = _resolve_memory_coverage(artifacts_dir)
        if coverage is None:
            return []
        grouped = _collect_committed_paths_by_repo(new_markers)
        if not grouped:
            return []
        diagnostics: list[FinalizerDiagnosticWire] = []
        for paths in grouped.values():
            diagnostics.extend(
                _build_memory_guard_diagnostics(
                    paths, coverage, instance_id=instance_id
                )
            )
        return diagnostics
    except Exception:
        return []


__all__ = [
    "GUARD_DIAGNOSTIC_CODE",
    "memory_guard_for_new_markers",
]

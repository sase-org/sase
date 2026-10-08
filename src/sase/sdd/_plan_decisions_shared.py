"""Shared internals for the Plan Decisions feature.

Private module: the public names defined here (``PlanDecisionError``,
``require_binding``, and ``resolve_memory_records``) are the helpers needed
by more than one ``plan_decisions_*`` sibling, so they live here instead of
being imported ``_``-prefixed across modules. Everything else stays
``_``-private to this module. The public entry point remains
``sase.sdd.plan_decisions``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

OVERLAP_CODE = "decision-memory-overlap"
UNVERIFIED_CODE = "decision-requested-unverified"

DECISION_SCHEMA_PREFIX = "decision_"

SEVEN_BINDINGS = (
    "plan_decisions_payload",
    "plan_decisions_digest",
    "plan_decisions_resolve",
    "plan_decision_quote_match",
    "plan_decision_sheet",
    "plan_decision_summary",
    "plan_decisions_prompt_block",
)


class PlanDecisionError(ValueError):
    """Host-side decision failure with a stable diagnostic code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def in_agent_context() -> bool:
    """Return whether this process runs inside an agent."""
    return bool(os.environ.get("SASE_AGENT") or os.environ.get("SASE_ARTIFACTS_DIR"))


def artifacts_dir_from_env() -> str:
    """Return the planner artifacts dir for quote checks."""
    return str(os.environ.get("SASE_ARTIFACTS_DIR") or "")


def require_binding(name: str) -> Any:
    """Return the required Rust core binding for plan decisions."""
    from sase.core.rust import require_rust_binding

    return require_rust_binding(name)


def _grant_note_path(selector: str) -> str | None:
    """Return the future canonical project path for a grantable flat note."""
    import re

    raw = selector.strip()
    if not raw.endswith(".md"):
        return None
    if "/" in raw or "\\" in raw:
        return None
    if any(part in {"", ".", ".."} for part in raw.split("/")):
        return None
    stem = raw[:-3]
    if not stem or stem.lower() == "readme":
        return None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", stem):
        return None
    return f"sase/memory/{stem}.md"


def _grant_strand_record(
    selector: str,
) -> tuple[dict[str, Any], str] | None:
    """Return a future strand grant record and its identity key, if grantable."""
    import re

    from sase.memory.selector_models import classify_selector, StrandSelector
    from sase.memory.web.read_context import discover_scoped_memory_webs

    try:
        classified = classify_selector(selector)
    except Exception:
        return None
    if not isinstance(classified, StrandSelector):
        return None
    web_slug = classified.web_slug.strip()
    keyword = classified.keyword.strip()
    if not web_slug or not keyword:
        return None
    if "/" in keyword or "\\" in keyword or ":" in keyword:
        return None
    if any(part in {"", ".", ".."} for part in keyword.split("/")):
        return None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", keyword):
        return None
    if "/" in web_slug or "\\" in web_slug or ":" in web_slug:
        return None
    try:
        project_root = Path.cwd()
        home_root = Path.home()
        scoped = discover_scoped_memory_webs(project_root, home_root)
    except Exception:
        return None
    match = next((item for item in scoped if item.slug == web_slug), None)
    if match is None:
        return None
    scope = "project"
    try:
        origins = getattr(match, "origins", {})
        if origins:
            first = next(iter(origins.values()))
            candidate = str(getattr(first, "scope", "project"))
            if candidate in ("project", "home"):
                scope = candidate
        else:
            web_root = getattr(getattr(match, "web", None), "root", None)
            if web_root is not None:
                try:
                    if Path(str(web_root)).resolve(strict=False) == Path.home().resolve(
                        strict=False
                    ):
                        scope = "home"
                except Exception:
                    pass
    except Exception:
        scope = "project"
    future_path = f"sase/memory/{web_slug}/{keyword}.md"
    record = {
        "selector": selector,
        "kind": "strand",
        "scope": scope,
        "path": future_path,
        "type": "strand",
        "exists": False,
    }
    return record, f"strand:{scope}:{future_path}"


def resolve_memory_records(
    selectors: list[str],
) -> tuple[list[dict[str, Any]], set[str]]:
    """Resolve one decision's selectors to memory records and note keys.

    A valid missing flat note or a valid missing strand of an existing web
    resolves to a future grant record with ``exists: False``. Malformed
    selectors, unknown webs/scopes, ambiguous aliases, traversal, broken or
    escaping symlinks, layout collisions, and unreadable targets stay
    ``decision-memory-unresolvable``. Never creates files or invents webs.

    Raises :class:`PlanDecisionError` when a selector cannot be resolved.
    """
    from sase.memory.selector import resolve_memory_selector_batch
    from sase.memory.selector_models import MemorySelectorError

    records: list[dict[str, Any]] = []
    note_keys: set[str] = set()
    for selector in selectors:
        try:
            batch = resolve_memory_selector_batch([selector])
        except MemorySelectorError as exc:
            grant = _grant_record_for_missing_selector(selector, exc)
            if grant is None:
                raise PlanDecisionError(
                    "decision-memory-unresolvable", str(exc)
                ) from exc
            grant_records, grant_keys = grant
            records.extend(grant_records)
            note_keys.update(grant_keys)
            continue
        except Exception as exc:
            raise PlanDecisionError("decision-memory-unresolvable", str(exc)) from exc
        for note in batch.notes:
            try:
                canonical = note.content.path.canonical_path
                note_type = str(note.content.path.note.type or "reference")
                scope = str(note.origin)
            except Exception:
                continue
            kind = "note"
            path = str(canonical)
            note_keys.add(f"{kind}:{scope}:{path}")
            records.append(
                {
                    "selector": selector,
                    "kind": kind,
                    "scope": scope,
                    "path": path,
                    "type": note_type
                    if note_type in ("core", "reference", "web", "strand")
                    else "reference",
                    "exists": True,
                }
            )
        for section in batch.web_sections:
            try:
                web = section.web
                frozen = [node.strand.keyword for node in section.nodes]
                scope = str(section.nodes[0].scope) if section.nodes else "project"
            except Exception:
                continue
            path = str(getattr(web, "relative_path", web.slug))
            note_keys.add(f"web:{scope}:{path}")
            record: dict[str, Any] = {
                "selector": selector,
                "kind": "web",
                "scope": scope,
                "path": path,
                "type": "web",
                "exists": True,
                "strands": list(frozen),
            }
            records.append(record)
            for node in section.nodes:
                try:
                    strand_path = str(node.strand.relative_path)
                    strand_scope = str(node.scope)
                except Exception:
                    continue
                note_keys.add(f"strand:{strand_scope}:{strand_path}")
    if not records and not note_keys:
        raise PlanDecisionError(
            "decision-memory-unresolvable",
            f"memory selector did not resolve: {selectors!r}",
        )
    return records, note_keys


def _strand_selector_is_prefix_ambiguous(selector: str) -> bool:
    """Return whether a strand selector is a prefix of existing strands.

    Structural ambiguity check without reading diagnostic wording: a
    missing strand grants, but a prefix matching two or more existing
    strands stays unresolvable.
    """
    try:
        from sase.memory.selector_models import classify_selector, StrandSelector
        from sase.memory.web.read_context import discover_scoped_memory_webs
        from sase.memory.web.lookup import normalize_memory_web_reference
        from pathlib import Path as _AmbPath

        classified = classify_selector(selector)
        if not isinstance(classified, StrandSelector):
            return False
        scoped = discover_scoped_memory_webs(_AmbPath.cwd(), _AmbPath.home())
        match = next(
            (item for item in scoped if item.slug == classified.web_slug), None
        )
        if match is None:
            return False
        needle = normalize_memory_web_reference(classified.keyword)
        if not needle:
            return True
        hits = 0
        for strand in match.strands:
            for value in (strand.slug, strand.keyword, *strand.aliases):
                key = normalize_memory_web_reference(str(value))
                if key and key.startswith(needle):
                    hits += 1
                    break
            if hits > 1:
                return True
        return False
    except Exception:
        return False


def _selector_failure_reason(exc: object) -> str | None:
    """Return the structured host failure reason for a selector error.

    Reads only the explicit ``reason``/``code`` carried from the host
    selector/path failure at its origin, never diagnostic wording, so
    changing wording cannot change grantability.
    """
    seen: set[int] = set()
    current: object = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        reason = getattr(current, "reason", None)
        if isinstance(reason, str) and reason:
            return reason
        code = getattr(current, "code", None)
        if isinstance(code, str) and code:
            return code
        current = getattr(current, "__cause__", None)
    return None


def _grant_record_for_missing_selector(
    selector: str, error: object
) -> tuple[list[dict[str, Any]], set[str]] | None:
    """Return future grant records for a valid missing target, if grantable.

    The decision is structural, never based on diagnostic wording: only
    actual absence of a well-formed flat note or a strand in an existing
    resolved web grants. Invalid syntax, unknown web/scope, ambiguous
    lookup, traversal, symlink failure/escape, layout collision,
    unreadable/non-file targets, and existing non-readable note kinds
    stay ``decision-memory-unresolvable``. Never creates files or invents
    webs, scopes, aliases, or types.
    """
    reason = _selector_failure_reason(error)
    if reason is not None and reason != "missing":
        return None
    from sase.memory.selector_models import classify_selector, NoteSelector

    try:
        classified = classify_selector(selector)
    except Exception:
        return None
    if isinstance(classified, NoteSelector):
        future = _grant_note_path(selector)
        if future is None:
            return None
        # Only actual absence grants: any existing file, symlink, or
        # non-file at the future location keeps the original error.
        try:
            from pathlib import Path

            from sase.memory.paths import memory_write_root

            write_root = memory_write_root(Path.cwd())
            candidate = write_root / Path(future).name
            if candidate.is_symlink():
                return None
            if candidate.exists():
                return None
        except Exception:
            pass
        record = {
            "selector": selector,
            "kind": "note",
            "scope": "project",
            "path": future,
            "type": "reference",
            "exists": False,
        }
        return [record], {f"note:project:{future}"}
    grant = _grant_strand_record(selector)
    if grant is None:
        return None
    record, key = grant
    try:
        from pathlib import Path as _StrandPath

        from sase.memory.paths import memory_write_root as _strand_root

        _write_root = _strand_root(_StrandPath.cwd())
        _candidate = _write_root / _StrandPath(str(record.get("path") or "")).name
        # Strand grants are for missing strands only; an existing file or
        # symlink at the future strand path is not a clean missing target.
        # Prefix-ambiguous selectors name an existing strand prefix, so they
        # must not grant even when the exact keyword file is absent.
        if _candidate.is_symlink() or _candidate.exists():
            return None
        if reason is None and _strand_selector_is_prefix_ambiguous(selector):
            return None
    except Exception:
        pass
    return [record], {key}


__all__ = [
    "DECISION_SCHEMA_PREFIX",
    "OVERLAP_CODE",
    "SEVEN_BINDINGS",
    "UNVERIFIED_CODE",
    "PlanDecisionError",
    "artifacts_dir_from_env",
    "in_agent_context",
    "require_binding",
    "resolve_memory_records",
]

"""Python facade for kind-tagged artifact references.

Rust owns the reference grammar, canonicalization, scanning, and resolution.
This module owns the machine- and project-specific context supplied to those
operations and projects their wire records into typed Python values.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
import sys
from typing import Any, cast

from sase.artifact_ref_models import (
    ARTIFACT_REF_WIRE_SCHEMA_VERSION,
    BUILTIN_ARTIFACT_REF_KINDS,
    ArtifactRef,
    ArtifactRefContext,
    ArtifactRefDocumentRoot,
    ArtifactRefFragment,
    ArtifactRefPayload,
    ArtifactRefPromptCandidate,
    ArtifactRefProject,
    ArtifactRefRepository,
    ArtifactRefResolution,
    ArtifactRefResolutionStatus,
    ArtifactRefSpan,
    ParsedArtifactRef,
    check_record_schema as _check_record_schema,
    optional_str as _optional_str,
)
from sase.core.artifact_file_facade import default_artifact_files_index_path
from sase.core.paths import sase_projects_dir, sase_subdir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import effective_project_name
from sase.core.rust import require_rust_binding
from sase.repo_inventory import collect_repo_inventory
from sase.sdd.plan_refs import workspace_context_for_plan_resolution
from sase.sdd.store import (
    document_sidecar_roles,
    resolve_sdd_store,
)


ARTIFACT_REF_LSP_CATALOG_SCHEMA_VERSION = 1

_RESOLUTION_STATUSES = {
    "exact",
    "drifted",
    "ambiguous",
    "missing",
    "unknown_kind",
    "unknown_repo",
    "unknown_project",
}


def artifact_ref_context(
    workspace_dir: str | Path,
    workspace_num: int,
    project: str | None = None,
) -> ArtifactRefContext:
    """Build resolution context for one project's managed workspace."""

    workspace = Path(workspace_dir).expanduser().resolve(strict=False)
    store = resolve_sdd_store(workspace, workspace_num)
    roles = document_sidecar_roles(
        store.split_sidecar_roles(),
        include_plans=True,
    )
    document_roots: list[ArtifactRefDocumentRoot] = []
    seen_roots: set[tuple[str, Path]] = set()
    for role in roles:
        try:
            root = store.kind_root(role)
        except (KeyError, OSError, ValueError):
            continue
        _append_document_root(document_roots, seen_roots, role, root)
        if role == "plans":
            _append_document_root(
                document_roots,
                seen_roots,
                role,
                sase_subdir("plans"),
            )

    project_filter = project or _workspace_project_ref(workspace)
    try:
        inventory = collect_repo_inventory(project=project_filter)
    except Exception:
        inventory = None
    repository_records = () if inventory is None else inventory.records
    repositories = tuple(
        ArtifactRefRepository(
            name=record.name,
            aliases=tuple(
                dict.fromkeys(
                    value for value in (record.slug,) if value and value != record.name
                )
            ),
            checkout_path=_repository_checkout_path(record, workspace_num),
        )
        for record in repository_records
    )

    try:
        project_records = list_project_records(
            sase_projects_dir(),
            "all",
            include_home=False,
            projects_only=True,
        )
    except Exception:
        project_records = []
    projects = tuple(
        ArtifactRefProject(
            name=effective_project_name(record),
            key=record.project_name,
            aliases=tuple(dict.fromkeys(record.aliases)),
        )
        for record in project_records
    )
    return ArtifactRefContext(
        document_roots=tuple(document_roots),
        chats_root=sase_subdir("chats").expanduser().resolve(strict=False),
        artifact_index_path=default_artifact_files_index_path()
        .expanduser()
        .resolve(strict=False),
        repositories=repositories,
        projects=projects,
    )


def artifact_ref_lsp_catalog_payload(
    launch_workspace: str | Path | None = None,
) -> dict[str, object]:
    """Build the local artifact-reference catalog consumed by ``sase lsp``.

    Catalog construction is deliberately best-effort per project. A stale
    project record or unavailable workspace cannot prevent the other enabled
    projects from contributing editor context.
    """

    from sase.artifact_ref_lsp import build_artifact_ref_lsp_catalog_payload

    return build_artifact_ref_lsp_catalog_payload(
        launch_workspace,
        artifact_ref_context_fn=artifact_ref_context,
        effective_project_name_fn=effective_project_name,
        list_project_records_fn=list_project_records,
        projects_root=sase_projects_dir(),
        schema_version=ARTIFACT_REF_LSP_CATALOG_SCHEMA_VERSION,
        workspace_context_fn=workspace_context_for_plan_resolution,
        workspace_project_ref_fn=_workspace_project_ref,
    )


def parse_artifact_ref(value: str) -> ArtifactRef:
    _require_artifact_ref_schema()
    binding = require_rust_binding("artifact_ref_parse")
    raw = cast(Mapping[str, Any], binding(value))
    return ArtifactRef.from_wire(raw)


def _canonicalize_artifact_ref(
    path: str | Path,
    *,
    context: ArtifactRefContext,
) -> str | None:
    _require_artifact_ref_schema()
    normalized = Path(path).expanduser().resolve(strict=False)
    binding = require_rust_binding("artifact_ref_canonicalize")
    result = binding(str(normalized), context.to_wire())
    return None if result is None else str(result)


def resolve_artifact_ref(
    reference: str | ArtifactRef,
    *,
    context: ArtifactRefContext,
) -> ArtifactRefResolution:
    _require_artifact_ref_schema()
    parsed = parse_artifact_ref(reference) if isinstance(reference, str) else reference
    binding = require_rust_binding("artifact_ref_resolve")
    raw = cast(Mapping[str, Any], binding(parsed.to_wire(), context.to_wire()))
    _check_record_schema(raw, record="artifact-reference resolution")
    status = str(raw["status"])
    if status not in _RESOLUTION_STATUSES:
        raise RuntimeError(
            "sase_core_rs returned an unknown artifact-reference resolution "
            f"status: {status}"
        )
    resolved = raw.get("resolved_path")
    return ArtifactRefResolution(
        schema_version=int(raw["schema_version"]),
        status=cast(ArtifactRefResolutionStatus, status),
        rendered=str(raw["rendered"]),
        locator=_optional_str(raw.get("locator")),
        resolved_path=None if resolved is None else Path(str(resolved)),
        candidates=tuple(str(candidate) for candidate in raw["candidates"]),
    )


def scan_artifact_refs(text: str) -> tuple[ArtifactRefPromptCandidate, ...]:
    _require_artifact_ref_schema()
    binding = require_rust_binding("artifact_ref_scan_prompt")
    raw = cast(list[Mapping[str, Any]], binding(text))
    return tuple(ArtifactRefPromptCandidate.from_wire(item) for item in raw)


scan_artifact_ref_prompt = scan_artifact_refs


@dataclass(frozen=True, slots=True)
class _ArtifactRefFailure:
    reference: str
    status: str
    detail: str | None = None


def process_artifact_references(
    prompt: str,
    *,
    is_home_mode: bool = False,
    context: ArtifactRefContext | None = None,
) -> str:
    """Resolve and expand live artifact references in a launch prompt."""

    return _expand_artifact_references(
        prompt,
        is_home_mode=is_home_mode,
        context=context,
        rewrite=True,
    )


def validate_artifact_references(
    prompt: str,
    *,
    is_home_mode: bool = False,
    context: ArtifactRefContext | None = None,
) -> None:
    """Validate live artifact references without rewriting the prompt."""

    _expand_artifact_references(
        prompt,
        is_home_mode=is_home_mode,
        context=context,
        rewrite=False,
    )


def _expand_artifact_references(
    prompt: str,
    *,
    is_home_mode: bool,
    context: ArtifactRefContext | None,
    rewrite: bool,
) -> str:
    if "@" not in prompt:
        return prompt

    candidates = scan_artifact_refs(prompt)
    if not candidates:
        return prompt
    if context is None:
        context = launch_artifact_ref_context(is_home_mode=is_home_mode)

    from sase.xprompt._literal_zones import literal_zone_ranges

    literal_ranges = literal_zone_ranges(prompt)
    byte_to_char = _byte_to_character_offsets(prompt)
    replacements: list[tuple[int, int, str]] = []
    failures: list[_ArtifactRefFailure] = []
    known_kinds = set(context.known_kinds)
    for candidate in candidates:
        start, end = _character_span(
            candidate.candidate_span,
            byte_to_char=byte_to_char,
        )
        if _overlaps_any(start, end, literal_ranges):
            continue
        if candidate.kind not in known_kinds:
            continue
        if not candidate.well_formed:
            failures.append(_ArtifactRefFailure(candidate.text, "malformed"))
            continue
        try:
            parsed = parse_artifact_ref(candidate.reference)
            resolution = _resolve_for_launch(parsed, context=context)
        except (RuntimeError, ValueError) as exc:
            failures.append(_ArtifactRefFailure(candidate.text, "malformed", str(exc)))
            continue
        if resolution.status not in {"exact", "drifted"}:
            failures.append(_ArtifactRefFailure(candidate.text, resolution.status))
            continue
        try:
            replacement_text = _artifact_ref_replacement(
                parsed,
                resolution,
                context=context,
            )
        except (RuntimeError, ValueError) as exc:
            failures.append(_ArtifactRefFailure(candidate.text, "missing", str(exc)))
            continue
        replacements.append((start, end, replacement_text))

    if failures:
        _print_artifact_ref_failures(failures)
        sys.exit(1)
    if not rewrite or not replacements:
        return prompt

    expanded = prompt
    for start, end, replacement_text in reversed(replacements):
        expanded = f"{expanded[:start]}{replacement_text}{expanded[end:]}"
    return expanded


def _resolve_for_launch(
    reference: ArtifactRef,
    *,
    context: ArtifactRefContext,
) -> ArtifactRefResolution:
    resolution = resolve_artifact_ref(reference, context=context)
    if reference.kind_type != "commit" or resolution.status != "missing":
        return resolution

    repository = _repository_for_ref(reference.payload.repo or "", context)
    if repository is None or repository.checkout_path is None:
        return resolution
    full_sha = _resolve_checkout_commit(
        repository.checkout_path,
        reference.payload.sha or "",
    )
    if full_sha is None:
        return resolution
    repositories = tuple(
        replace(candidate, shas=(full_sha,)) if candidate is repository else candidate
        for candidate in context.repositories
    )
    return resolve_artifact_ref(
        reference,
        context=replace(context, repositories=repositories),
    )


def _artifact_ref_replacement(
    reference: ArtifactRef,
    resolution: ArtifactRefResolution,
    *,
    context: ArtifactRefContext,
) -> str:
    if reference.kind_type in {"document", "chat", "file"}:
        if resolution.resolved_path is None:
            raise RuntimeError("resolver returned no artifact path")
        return f"@{resolution.resolved_path}{_fragment_annotation(reference.fragment)}"
    if reference.kind_type == "commit":
        if resolution.locator is None:
            raise RuntimeError("resolver returned no commit locator")
        repository = _repository_for_ref(reference.payload.repo or "", context)
        if repository is None or repository.checkout_path is None:
            raise RuntimeError("repository checkout is unavailable")
        return f"{resolution.locator} (checkout: {repository.checkout_path})"
    if reference.kind_type == "bug":
        if resolution.locator is None or reference.payload.number is None:
            raise RuntimeError("resolver returned no bug locator")
        project = resolution.locator.rsplit("#", 1)[0]
        return (
            f"#{reference.payload.number} "
            f"{_resolved_bug_url(project, reference.payload.number)}"
        )
    raise RuntimeError(f"unsupported artifact reference kind: {reference.kind}")


def _fragment_annotation(fragment: ArtifactRefFragment | None) -> str:
    if fragment is None:
        return ""
    if fragment.type == "lines":
        assert fragment.start is not None
        assert fragment.end is not None
        if fragment.start == fragment.end:
            return f" (line {fragment.start})"
        return f" (lines {fragment.start}-{fragment.end})"
    if fragment.type == "page":
        assert fragment.page is not None
        return f" (page {fragment.page})"
    assert fragment.seconds is not None
    return f" (time {fragment.seconds}s)"


def _resolved_bug_url(project: str, number: int) -> str:
    from sase.ace.tui.artifacts_bugs import issue_url_for_number

    return issue_url_for_number(project, number)


def _resolve_checkout_commit(checkout_path: Path, sha: str) -> str | None:
    try:
        from sase.vcs_provider import get_vcs_provider

        resolved = get_vcs_provider(str(checkout_path)).revision_id(
            f"{sha}^{{commit}}",
            str(checkout_path),
        )
    except Exception:
        return None
    normalized = resolved.strip().lower()
    if len(normalized) != 40 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        return None
    return normalized


def _repository_for_ref(
    repo: str,
    context: ArtifactRefContext,
) -> ArtifactRefRepository | None:
    return next(
        (
            repository
            for repository in context.repositories
            if repository.name == repo or repo in repository.aliases
        ),
        None,
    )


def launch_artifact_ref_context(
    *,
    is_home_mode: bool,
) -> ArtifactRefContext:
    """Build the same local resolution context used for prompt launches."""

    from sase.artifact_ref_launch_context import build_launch_artifact_ref_context

    return build_launch_artifact_ref_context(
        artifact_ref_context_fn=artifact_ref_context,
        is_home_mode=is_home_mode,
        workspace_project_ref_fn=_workspace_project_ref,
    )


def _repository_checkout_path(record: object, workspace_num: int) -> Path | None:
    clone_for_workspace = getattr(record, "clone_for_workspace", None)
    clone = (
        clone_for_workspace(workspace_num) if callable(clone_for_workspace) else None
    )
    raw_path = getattr(clone, "path", None)
    exists = bool(getattr(clone, "exists", False))
    if raw_path is None and workspace_num in {0, 1}:
        raw_path = getattr(record, "path", None)
        exists = bool(getattr(record, "exists", False))
    if not raw_path or not exists:
        return None
    return Path(str(raw_path)).expanduser().resolve(strict=False)


def _byte_to_character_offsets(text: str) -> dict[int, int]:
    offsets = {0: 0}
    byte_offset = 0
    for character_offset, character in enumerate(text, start=1):
        byte_offset += len(character.encode("utf-8"))
        offsets[byte_offset] = character_offset
    return offsets


def _character_span(
    span: ArtifactRefSpan,
    *,
    byte_to_char: Mapping[int, int],
) -> tuple[int, int]:
    try:
        return byte_to_char[span.start], byte_to_char[span.end]
    except KeyError as exc:
        raise RuntimeError(
            "sase_core_rs returned an artifact-reference span outside UTF-8 "
            "character boundaries"
        ) from exc


def _overlaps_any(
    start: int,
    end: int,
    ranges: list[tuple[int, int]],
) -> bool:
    return any(
        start < range_end and end > range_start for range_start, range_end in ranges
    )


def _print_artifact_ref_failures(
    failures: list[_ArtifactRefFailure],
) -> None:
    print("\n❌ ERROR: The following artifact reference(s) could not be resolved:")
    for failure in failures:
        detail = f": {failure.detail}" if failure.detail else ""
        print(f"  - {failure.reference} ({failure.status}{detail})")
    print("\n⚠️ Artifact reference validation failed. Terminating workflow.\n")


def reference_for_entry_target(
    subtab: str,
    target: tuple[str, ...],
    *,
    context: ArtifactRefContext,
    row: object | None = None,
) -> str | None:
    """Render the canonical reference represented by one ACE artifact row."""

    expected = {
        "commits": "commit",
        "commit": "commit",
        "chats": "chat",
        "chat": "chat",
        "bugs": "bug",
        "bug": "bug",
        "plans": "plan",
        "plan": "plan",
    }.get(subtab)
    if expected is None or not target or target[0] != expected:
        return None
    try:
        if expected == "commit" and len(target) == 3:
            return parse_artifact_ref(f"commit:{target[1]}@{target[2]}").rendered
        if expected == "chat" and len(target) == 2:
            reference = _canonicalize_artifact_ref(
                target[1],
                context=context,
            )
            return (
                reference
                if reference is not None and reference.startswith("chat:")
                else None
            )
        if expected == "bug" and len(target) == 3:
            project = _project_display_name(target[1], context)
            return parse_artifact_ref(f"bug:{project}#{int(target[2])}").rendered
        if expected == "plan" and len(target) == 4:
            return _reference_for_plan_row(target[2], row, context)
    except (KeyError, TypeError, ValueError):
        return None
    return None


def _reference_for_plan_row(
    row_kind: str,
    row: object | None,
    context: ArtifactRefContext,
) -> str | None:
    if row is None:
        return None
    if row_kind in {"epic", "phase"}:
        issue = getattr(row, "issue", None)
        design = getattr(issue, "design", None)
        if not isinstance(design, str) or not design:
            return None
        try:
            parsed = parse_artifact_ref(design)
        except ValueError:
            return None
        return parsed.rendered if parsed.kind == "plans" else None
    if row_kind == "proposal":
        proposal = getattr(row, "proposal", None)
        plan_path = getattr(proposal, "plan_path", None)
        if not isinstance(plan_path, str) or not plan_path:
            return None
        reference = _canonicalize_artifact_ref(plan_path, context=context)
        return (
            reference
            if reference is not None and reference.startswith("plans:")
            else None
        )
    if row_kind == "archive":
        archive = getattr(row, "archive", None)
        match = getattr(row, "match", None)
        if match is not None:
            archive = match
        plan = getattr(archive, "plan", None)
        relpath = getattr(plan, "relpath", None)
        role = getattr(row, "archive_role", None) or getattr(row, "role", None)
        if not isinstance(role, str) or not role:
            plan_kind = getattr(plan, "kind", None)
            role = (
                plan_kind
                if isinstance(plan_kind, str)
                and plan_kind not in {"tale", "epic", "prompt", "local"}
                else "plans"
            )
        if not isinstance(relpath, str) or not relpath:
            return None
        return parse_artifact_ref(f"{role}:{relpath}").rendered
    return None


def _require_artifact_ref_schema() -> None:
    binding = require_rust_binding("artifact_ref_wire_schema_version")
    version = int(binding())
    if version != ARTIFACT_REF_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs artifact-reference wire is stale: "
            f"expected {ARTIFACT_REF_WIRE_SCHEMA_VERSION}, got {version}"
        )


def _append_document_root(
    roots: list[ArtifactRefDocumentRoot],
    seen: set[tuple[str, Path]],
    kind: str,
    root: str | Path,
) -> None:
    normalized = Path(root).expanduser().resolve(strict=False)
    key = (kind, normalized)
    if key in seen:
        return
    seen.add(key)
    roots.append(ArtifactRefDocumentRoot(kind, normalized))


def _workspace_project_ref(workspace: Path) -> str | None:
    try:
        from sase.workspace_provider import find_marker_from_cwd

        found = find_marker_from_cwd(str(workspace))
    except Exception:
        return None
    if found is None:
        return None
    marker = found[1]
    return marker.project_key or marker.project_name or None


def _project_display_name(
    project_ref: str,
    context: ArtifactRefContext,
) -> str:
    folded = project_ref.casefold()
    for project in context.projects:
        if (
            project.name.casefold() == folded
            or project.key.casefold() == folded
            or any(alias.casefold() == folded for alias in project.aliases)
        ):
            return project.name
    return project_ref


__all__ = [
    "ARTIFACT_REF_LSP_CATALOG_SCHEMA_VERSION",
    "ARTIFACT_REF_WIRE_SCHEMA_VERSION",
    "BUILTIN_ARTIFACT_REF_KINDS",
    "ArtifactRef",
    "ArtifactRefContext",
    "ArtifactRefDocumentRoot",
    "ArtifactRefFragment",
    "ArtifactRefPayload",
    "ArtifactRefPromptCandidate",
    "ArtifactRefProject",
    "ArtifactRefRepository",
    "ArtifactRefResolution",
    "ArtifactRefResolutionStatus",
    "ArtifactRefSpan",
    "ParsedArtifactRef",
    "artifact_ref_context",
    "artifact_ref_lsp_catalog_payload",
    "launch_artifact_ref_context",
    "parse_artifact_ref",
    "process_artifact_references",
    "reference_for_entry_target",
    "resolve_artifact_ref",
    "scan_artifact_ref_prompt",
    "scan_artifact_refs",
    "validate_artifact_references",
]

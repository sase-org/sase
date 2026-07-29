"""Python facade for kind-tagged artifact references.

Rust owns the reference grammar, canonicalization, scanning, and resolution.
This module owns the machine- and project-specific context supplied to those
operations and projects their wire records into typed Python values.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import os
from pathlib import Path
import sys
from typing import Any, Literal, cast

from sase.core.artifact_file_facade import default_artifact_files_index_path
from sase.core.paths import sase_projects_dir, sase_subdir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import effective_project_name
from sase.core.rust import require_rust_binding
from sase.repo_inventory import collect_repo_inventory
from sase.sdd.store import (
    document_sidecar_roles,
    resolve_sdd_store,
)


ARTIFACT_REF_WIRE_SCHEMA_VERSION = 1
BUILTIN_ARTIFACT_REF_KINDS = ("commit", "chat", "bug", "file")

ArtifactRefKindType = Literal["commit", "chat", "bug", "file", "document"]
ArtifactRefPayloadType = ArtifactRefKindType
ArtifactRefFragmentType = Literal["lines", "page", "time"]
ArtifactRefResolutionStatus = Literal[
    "exact",
    "drifted",
    "ambiguous",
    "missing",
    "unknown_kind",
    "unknown_repo",
    "unknown_project",
]

_RESOLUTION_STATUSES = {
    "exact",
    "drifted",
    "ambiguous",
    "missing",
    "unknown_kind",
    "unknown_repo",
    "unknown_project",
}


@dataclass(frozen=True, slots=True)
class ArtifactRefPayload:
    """One kind-specific artifact-reference payload."""

    type: ArtifactRefPayloadType
    path: str | None = None
    repo: str | None = None
    sha: str | None = None
    project: str | None = None
    number: int | None = None
    source: str | None = None
    digest: str | None = None

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> ArtifactRefPayload:
        payload_type = str(raw["type"])
        if payload_type not in {"commit", "chat", "bug", "file", "document"}:
            raise RuntimeError(
                "sase_core_rs returned an unknown artifact-reference payload "
                f"type: {payload_type}"
            )
        return cls(
            type=cast(ArtifactRefPayloadType, payload_type),
            path=_optional_str(raw.get("path")),
            repo=_optional_str(raw.get("repo")),
            sha=_optional_str(raw.get("sha")),
            project=_optional_str(raw.get("project")),
            number=_optional_int(raw.get("number")),
            source=_optional_str(raw.get("source")),
            digest=_optional_str(raw.get("digest")),
        )

    def to_wire(self) -> dict[str, object]:
        raw: dict[str, object] = {"type": self.type}
        for name in (
            "path",
            "repo",
            "sha",
            "project",
            "number",
            "source",
            "digest",
        ):
            value = getattr(self, name)
            if value is not None:
                raw[name] = value
        return raw


@dataclass(frozen=True, slots=True)
class ArtifactRefFragment:
    """One optional artifact-reference fragment anchor."""

    type: ArtifactRefFragmentType
    start: int | None = None
    end: int | None = None
    page: int | None = None
    seconds: int | None = None

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> ArtifactRefFragment:
        fragment_type = str(raw["type"])
        if fragment_type not in {"lines", "page", "time"}:
            raise RuntimeError(
                "sase_core_rs returned an unknown artifact-reference fragment "
                f"type: {fragment_type}"
            )
        return cls(
            type=cast(ArtifactRefFragmentType, fragment_type),
            start=_optional_int(raw.get("start")),
            end=_optional_int(raw.get("end")),
            page=_optional_int(raw.get("page")),
            seconds=_optional_int(raw.get("seconds")),
        )

    def to_wire(self) -> dict[str, object]:
        raw: dict[str, object] = {"type": self.type}
        for name in ("start", "end", "page", "seconds"):
            value = getattr(self, name)
            if value is not None:
                raw[name] = value
        return raw


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """A parsed canonical artifact reference."""

    schema_version: int
    kind: str
    kind_type: ArtifactRefKindType
    payload: ArtifactRefPayload
    fragment: ArtifactRefFragment | None
    rendered: str

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> ArtifactRef:
        _check_record_schema(raw, record="artifact-reference parse")
        raw_kind = cast(Mapping[str, Any], raw["kind"])
        kind_type = str(raw_kind["type"])
        if kind_type not in {"commit", "chat", "bug", "file", "document"}:
            raise RuntimeError(
                "sase_core_rs returned an unknown artifact-reference kind "
                f"type: {kind_type}"
            )
        kind = str(raw_kind["role"]) if kind_type == "document" else kind_type
        raw_fragment = raw.get("fragment")
        return cls(
            schema_version=int(raw["schema_version"]),
            kind=kind,
            kind_type=cast(ArtifactRefKindType, kind_type),
            payload=ArtifactRefPayload.from_wire(
                cast(Mapping[str, Any], raw["payload"])
            ),
            fragment=(
                None
                if raw_fragment is None
                else ArtifactRefFragment.from_wire(
                    cast(Mapping[str, Any], raw_fragment)
                )
            ),
            rendered=str(raw["rendered"]),
        )

    def to_wire(self) -> dict[str, object]:
        kind: dict[str, object] = {"type": self.kind_type}
        if self.kind_type == "document":
            kind["role"] = self.kind
        return {
            "schema_version": self.schema_version,
            "kind": kind,
            "payload": self.payload.to_wire(),
            "fragment": (None if self.fragment is None else self.fragment.to_wire()),
            "rendered": self.rendered,
        }


ParsedArtifactRef = ArtifactRef


@dataclass(frozen=True, slots=True)
class ArtifactRefDocumentRoot:
    kind: str
    root: Path

    def to_wire(self) -> dict[str, str]:
        return {"kind": self.kind, "root": str(self.root)}


@dataclass(frozen=True, slots=True)
class ArtifactRefRepository:
    name: str
    aliases: tuple[str, ...] = ()
    shas: tuple[str, ...] = ()
    checkout_path: Path | None = None

    def to_wire(self) -> dict[str, object]:
        return {
            "name": self.name,
            "aliases": list(self.aliases),
            "shas": list(self.shas),
        }


@dataclass(frozen=True, slots=True)
class ArtifactRefProject:
    name: str
    key: str
    aliases: tuple[str, ...] = ()

    def to_wire(self) -> dict[str, object]:
        return {
            "name": self.name,
            "key": self.key,
            "aliases": list(self.aliases),
        }


@dataclass(frozen=True, slots=True)
class ArtifactRefContext:
    """Caller-supplied local namespaces used by the Rust resolver."""

    document_roots: tuple[ArtifactRefDocumentRoot, ...]
    chats_root: Path
    artifact_index_path: Path
    repositories: tuple[ArtifactRefRepository, ...]
    projects: tuple[ArtifactRefProject, ...]

    @property
    def known_kinds(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    *BUILTIN_ARTIFACT_REF_KINDS,
                    *(entry.kind for entry in self.document_roots),
                )
            )
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "document_roots": [document.to_wire() for document in self.document_roots],
            "chats_root": str(self.chats_root),
            "artifact_index_path": str(self.artifact_index_path),
            "repositories": [repository.to_wire() for repository in self.repositories],
            "projects": [project.to_wire() for project in self.projects],
        }


@dataclass(frozen=True, slots=True)
class ArtifactRefResolution:
    schema_version: int
    status: ArtifactRefResolutionStatus
    rendered: str
    locator: str | None
    resolved_path: Path | None
    candidates: tuple[str, ...]

    @property
    def best_path(self) -> Path | None:
        if self.resolved_path is not None:
            return self.resolved_path
        if not self.candidates or self.status not in {"ambiguous", "missing"}:
            return None
        return Path(self.candidates[0])


@dataclass(frozen=True, slots=True)
class ArtifactRefSpan:
    start: int
    end: int

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> ArtifactRefSpan:
        return cls(start=int(raw["start"]), end=int(raw["end"]))


@dataclass(frozen=True, slots=True)
class ArtifactRefPromptCandidate:
    schema_version: int
    text: str
    reference: str
    kind: str
    well_formed: bool
    candidate_span: ArtifactRefSpan
    sigil_span: ArtifactRefSpan
    kind_span: ArtifactRefSpan
    separator_span: ArtifactRefSpan
    payload_span: ArtifactRefSpan
    fragment_span: ArtifactRefSpan | None

    @classmethod
    def from_wire(
        cls,
        raw: Mapping[str, Any],
    ) -> ArtifactRefPromptCandidate:
        _check_record_schema(raw, record="artifact-reference scan")
        raw_fragment = raw.get("fragment_span")
        return cls(
            schema_version=int(raw["schema_version"]),
            text=str(raw["text"]),
            reference=str(raw["reference"]),
            kind=str(raw["kind"]),
            well_formed=bool(raw["well_formed"]),
            candidate_span=ArtifactRefSpan.from_wire(
                cast(Mapping[str, Any], raw["candidate_span"])
            ),
            sigil_span=ArtifactRefSpan.from_wire(
                cast(Mapping[str, Any], raw["sigil_span"])
            ),
            kind_span=ArtifactRefSpan.from_wire(
                cast(Mapping[str, Any], raw["kind_span"])
            ),
            separator_span=ArtifactRefSpan.from_wire(
                cast(Mapping[str, Any], raw["separator_span"])
            ),
            payload_span=ArtifactRefSpan.from_wire(
                cast(Mapping[str, Any], raw["payload_span"])
            ),
            fragment_span=(
                None
                if raw_fragment is None
                else ArtifactRefSpan.from_wire(cast(Mapping[str, Any], raw_fragment))
            ),
        )


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


def parse_artifact_ref(value: str) -> ArtifactRef:
    _require_artifact_ref_schema()
    binding = require_rust_binding("artifact_ref_parse")
    raw = cast(Mapping[str, Any], binding(value))
    return ArtifactRef.from_wire(raw)


def render_artifact_ref(reference: ArtifactRef) -> str:
    _require_artifact_ref_schema()
    binding = require_rust_binding("artifact_ref_render")
    return str(binding(reference.to_wire()))


def canonicalize_artifact_ref(
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
        context = _launch_artifact_ref_context(is_home_mode=is_home_mode)

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


def _launch_artifact_ref_context(
    *,
    is_home_mode: bool,
) -> ArtifactRefContext:
    workspace = Path.cwd()
    workspace_num = _workspace_num_from_environment()
    project = _workspace_project_ref(workspace)
    if workspace_num is None:
        try:
            from sase.main.utils import ensure_project_file_and_get_workspace_num

            _project_file, detected_num, detected_project = (
                ensure_project_file_and_get_workspace_num(create_missing=False)
            )
            workspace_num = detected_num
            project = detected_project or project
        except Exception:
            pass
    if workspace_num is None:
        workspace_num = 0 if is_home_mode else 1
    return artifact_ref_context(workspace, workspace_num, project=project)


def _workspace_num_from_environment() -> int | None:
    for name in (
        "SASE_AGENT_WORKSPACE_NUM",
        "SASE_GIT_WORKSPACE_NUM",
        "SASE_GH_WORKSPACE_NUM",
    ):
        raw = os.environ.get(name)
        if raw is None:
            continue
        try:
            return int(raw)
        except ValueError:
            continue
    return None


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
            reference = canonicalize_artifact_ref(
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
        reference = canonicalize_artifact_ref(plan_path, context=context)
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


def _check_record_schema(
    raw: Mapping[str, Any],
    *,
    record: str,
) -> None:
    version = int(raw["schema_version"])
    if version != ARTIFACT_REF_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            f"sase_core_rs returned an unsupported {record} wire: {version}"
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


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _optional_int(value: object) -> int | None:
    return None if value is None else int(cast(Any, value))


__all__ = [
    "ARTIFACT_REF_WIRE_SCHEMA_VERSION",
    "BUILTIN_ARTIFACT_REF_KINDS",
    "ArtifactRef",
    "ArtifactRefContext",
    "ArtifactRefDocumentRoot",
    "ArtifactRefFragment",
    "ArtifactRefPayload",
    "ArtifactRefProject",
    "ArtifactRefPromptCandidate",
    "ArtifactRefRepository",
    "ArtifactRefResolution",
    "ArtifactRefResolutionStatus",
    "ArtifactRefSpan",
    "ParsedArtifactRef",
    "artifact_ref_context",
    "canonicalize_artifact_ref",
    "parse_artifact_ref",
    "process_artifact_references",
    "reference_for_entry_target",
    "render_artifact_ref",
    "resolve_artifact_ref",
    "scan_artifact_ref_prompt",
    "scan_artifact_refs",
    "validate_artifact_references",
]

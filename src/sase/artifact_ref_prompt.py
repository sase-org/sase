"""Launch-prompt expansion and validation for artifact references."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import logging
from pathlib import Path
import sys
from typing import cast

from sase.artifact_ref_context import launch_artifact_ref_context
from sase.artifact_ref_models import (
    ArtifactRef,
    ArtifactRefContext,
    ArtifactRefFragment,
    ArtifactRefRepository,
    ArtifactRefResolution,
    ArtifactRefSpan,
)
from sase.artifact_ref_operations import (
    parse_artifact_ref,
    render_artifact_ref,
    resolve_artifact_ref,
    scan_artifact_refs,
)
from sase.core.artifact_consumption import (
    ArtifactConsumptionEvent,
    ArtifactConsumptionResolutionStatus,
    append_artifact_consumption_events,
    artifact_consumption_role,
    build_artifact_consumption_event,
)
from sase.core.artifact_file_query_facade import query_artifact_files
from sase.core.artifact_file_vcs import materialize_artifact_file


log = logging.getLogger(__name__)


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
    staged_file_paths: set[str] | None = None,
) -> str:
    """Resolve and expand live artifact references in a launch prompt.

    Successfully staged file paths are added to ``staged_file_paths`` so the
    following plain-file pass does not record generated ``@/path`` tokens as
    separate authored references.
    """

    return _expand_artifact_references(
        prompt,
        is_home_mode=is_home_mode,
        context=context,
        rewrite=True,
        staged_file_paths=staged_file_paths,
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
        staged_file_paths=None,
    )


def _expand_artifact_references(
    prompt: str,
    *,
    is_home_mode: bool,
    context: ArtifactRefContext | None,
    rewrite: bool,
    staged_file_paths: set[str] | None,
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
    consumptions: list[tuple[ArtifactRef, ArtifactRefResolution, Path | None, str]] = []
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
        if resolution.status not in {"exact", "drifted", "vcs_backed"}:
            failures.append(
                _ArtifactRefFailure(
                    candidate.text,
                    resolution.status,
                    artifact_ref_resolution_hint(
                        parsed,
                        resolution,
                        context=context,
                    ),
                )
            )
            continue
        try:
            replacement_text, resolved_path = _artifact_ref_replacement(
                parsed,
                resolution,
                context=context,
            )
        except (RuntimeError, ValueError) as exc:
            failures.append(_ArtifactRefFailure(candidate.text, "missing", str(exc)))
            continue
        replacements.append((start, end, replacement_text))
        consumptions.append((parsed, resolution, resolved_path, replacement_text))

    if failures:
        _print_artifact_ref_failures(failures)
        sys.exit(1)
    if not rewrite or not replacements:
        return prompt

    expanded = prompt
    for start, end, replacement_text in reversed(replacements):
        expanded = f"{expanded[:start]}{replacement_text}{expanded[end:]}"
    if not is_home_mode:
        staged = _stage_artifact_references(consumptions)
        if staged_file_paths is not None:
            staged_file_paths.update(staged)
    _record_artifact_ref_consumption(consumptions)
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
) -> tuple[str, Path | None]:
    if reference.kind_type in {"document", "chat", "file", "bead", "agent"}:
        if reference.kind_type == "file" and resolution.status == "vcs_backed":
            path = _materialize_vcs_file_reference(reference, context=context)
            if path is None:
                raise RuntimeError(
                    "VCS-backed artifact content is unavailable"
                    + ("" if resolution.locator is None else f" ({resolution.locator})")
                )
            return f"@{path}{_fragment_annotation(reference.fragment)}", path
        if resolution.resolved_path is None:
            raise RuntimeError("resolver returned no artifact path")
        return (
            f"@{resolution.resolved_path}{_fragment_annotation(reference.fragment)}",
            resolution.resolved_path,
        )
    if reference.kind_type == "commit":
        if resolution.locator is None:
            raise RuntimeError("resolver returned no commit locator")
        repository = _repository_for_ref(reference.payload.repo or "", context)
        if repository is None or repository.checkout_path is None:
            raise RuntimeError("repository checkout is unavailable")
        return (
            f"{resolution.locator} (checkout: {repository.checkout_path})",
            repository.checkout_path,
        )
    if reference.kind_type == "bug":
        if resolution.locator is None or reference.payload.number is None:
            raise RuntimeError("resolver returned no bug locator")
        project = resolution.locator.rsplit("#", 1)[0]
        return (
            (
                f"#{reference.payload.number} "
                f"{_resolved_bug_url(project, reference.payload.number)}"
            ),
            None,
        )
    raise RuntimeError(f"unsupported artifact reference kind: {reference.kind}")


def _record_artifact_ref_consumption(
    consumptions: list[tuple[ArtifactRef, ArtifactRefResolution, Path | None, str]],
) -> None:
    try:
        events: list[ArtifactConsumptionEvent] = []
        seen_refs: set[str] = set()
        for parsed, resolution, resolved_path, _replacement_text in consumptions:
            fragment_free = replace(parsed, fragment=None)
            reference = render_artifact_ref(fragment_free)
            if reference in seen_refs:
                continue
            seen_refs.add(reference)
            fragment = (
                None
                if parsed.fragment is None
                else parsed.rendered[len(reference) + 1 :]
            )
            artifact_id = None
            if (
                parsed.kind_type == "file"
                and parsed.payload.source is not None
                and parsed.payload.digest is not None
            ):
                artifact_id = f"{parsed.payload.source}:{parsed.payload.digest}"
            events.append(
                build_artifact_consumption_event(
                    ref=reference,
                    ref_kind=parsed.kind,
                    fragment=fragment,
                    role=artifact_consumption_role(
                        parsed.kind_type,
                        parsed.kind,
                        resolved_path,
                    ),
                    artifact_id=artifact_id,
                    resolved_path=resolved_path,
                    resolution_status=cast(
                        ArtifactConsumptionResolutionStatus,
                        resolution.status,
                    ),
                )
            )
        append_artifact_consumption_events(events)
    except Exception as exc:
        log.debug("Could not record artifact-reference consumption: %s", exc)


def _stage_artifact_references(
    consumptions: list[tuple[ArtifactRef, ArtifactRefResolution, Path | None, str]],
) -> set[str]:
    """Stage the exact resolution list used by consumption telemetry."""

    from sase.core.prompt_artifact_staging import stage_prompt_artifact

    staged_file_paths: set[str] = set()
    for parsed, resolution, resolved_path, replacement_text in consumptions:
        raw_ref = f"@{render_artifact_ref(parsed)}"
        record = stage_prompt_artifact(
            raw_ref=raw_ref,
            expanded_ref=replacement_text,
            resolved_path=resolved_path,
            ref_kind=parsed.kind,
            label=_artifact_ref_label(parsed, resolved_path, raw_ref),
            locator=resolution.locator,
        )
        if record is not None and resolved_path is not None and resolved_path.is_file():
            staged_file_paths.add(str(resolved_path.resolve(strict=False)))
    return staged_file_paths


def _artifact_ref_label(
    reference: ArtifactRef,
    resolved_path: Path | None,
    raw_ref: str,
) -> str:
    if resolved_path is not None and resolved_path.is_file():
        return resolved_path.name
    payload = reference.payload
    for value in (payload.path, payload.name, payload.id):
        if value:
            return Path(value).name
    if payload.number is not None:
        return f"{payload.project or 'bug'}#{payload.number}"
    if payload.repo and payload.sha:
        return f"{payload.repo}@{payload.sha}"
    return raw_ref.removeprefix("@")


def _materialize_vcs_file_reference(
    reference: ArtifactRef,
    *,
    context: ArtifactRefContext,
) -> Path | None:
    source = reference.payload.source
    digest = reference.payload.digest
    if source is None or digest is None:
        return None
    artifact_id = f"{source}:{digest}"
    row = next(
        (
            candidate
            for candidate in query_artifact_files(
                context.artifact_index_path,
                limit=None,
            )
            if candidate.id == artifact_id
        ),
        None,
    )
    if row is None:
        return None
    return materialize_artifact_file(row, repositories=context.repositories)


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


def artifact_ref_resolution_hint(
    reference: ArtifactRef,
    resolution: ArtifactRefResolution,
    *,
    context: ArtifactRefContext | None = None,
) -> str | None:
    """Return an actionable publication hint for unresolved entity pages."""

    if resolution.status in {"exact", "drifted"}:
        return None
    if resolution.diagnostic is not None:
        return resolution.diagnostic
    if reference.kind_type == "bead":
        bead_id = reference.payload.id
        if not bead_id:
            return None
        if resolution.status == "unknown_project" and context is not None:
            project = _known_project_for_bead_id(bead_id, context)
            if project is not None:
                return (
                    f"hint: project {project} has no bead store in this "
                    "reference context"
                )
        return f"hint: no published page for {bead_id}; run `sase bead page refresh`"
    if reference.kind_type == "agent":
        name = reference.payload.name
        if not name:
            return None
        return f"hint: no published page for {name}; run `sase agent sync`"
    return None


def _known_project_for_bead_id(
    bead_id: str,
    context: ArtifactRefContext,
) -> str | None:
    matches: list[tuple[int, str]] = []
    for project in context.projects:
        refs = (project.name, project.key, *project.aliases)
        for ref in refs:
            if not ref:
                continue
            if bead_id == ref or bead_id.startswith(f"{ref}-"):
                matches.append((len(ref), project.name))
                break
    if not matches:
        return None
    longest = max(length for length, _project in matches)
    names = {project for length, project in matches if length == longest}
    return next(iter(names)) if len(names) == 1 else None


__all__ = [
    "artifact_ref_resolution_hint",
    "process_artifact_references",
    "validate_artifact_references",
]

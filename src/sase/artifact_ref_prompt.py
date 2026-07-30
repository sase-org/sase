"""Launch-prompt expansion and validation for artifact references."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
import sys

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
    resolve_artifact_ref,
    scan_artifact_refs,
)


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
    if reference.kind_type in {"document", "chat", "file", "bead", "agent"}:
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

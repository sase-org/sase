"""Launch-prompt expansion and validation for artifact references.

This module retains the stable prompt-processing surface. Focused parsing,
rendering, and resolution helpers live in the neighboring ``artifact_ref_prompt_*``
modules. Builtin kinds (``stitch``, ``patch``, short-id ``bead``, ``agent``)
resolve through ``sase.artifact_providers.builtin_entries`` against an
explicit :class:`~sase.artifact_ref_prompt_context.PromptRefContext` derived
from the prompt itself; every other kind keeps resolving through the Rust
resolver exactly as before.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
import logging
from pathlib import Path
import sys
from typing import cast

from sase.artifact_ref_kinds import parse_artifact_ref_canonical
from sase.artifact_ref_models import (
    ArtifactRef,
    ArtifactRefContext,
    ArtifactRefPromptCandidate,
    ArtifactRefResolution,
)
from sase.artifact_ref_operations import render_artifact_ref, scan_artifact_refs
from sase.artifact_ref_prompt_context import (
    PromptRefContext,
    explicit_prompt_ref_context,
    prompt_ref_contexts_for_prompt,
)
from sase.artifact_ref_prompt_materialize import (
    MaterializationFailure,
    materialize_missing_document_roots,
)
from sase.artifact_ref_prompt_parsing import (
    ArtifactRefFailure as _ArtifactRefFailure,
    byte_to_character_offsets as _byte_to_character_offsets,
    character_span as _character_span,
    overlaps_any as _overlaps_any,
    print_artifact_ref_failures as _print_artifact_ref_failures,
)
from sase.artifact_ref_prompt_rendering import (
    artifact_ref_replacement as _artifact_ref_replacement_impl,
    resolved_bug_url as _resolved_bug_url,
)
from sase.artifact_ref_prompt_resolution import (
    artifact_ref_resolution_hint,
    materialized_artifact_path as _materialized_artifact_path,
    repository_for_ref as _repository_for_ref,
    resolve_checkout_commit as _resolve_checkout_commit,
    resolve_for_launch as _resolve_for_launch_impl,
)
from sase.artifact_ref_renderers import ArtifactRendererJinjaProtection
from sase.artifact_providers.builtin_entries import (
    BuiltinEntryOutcome,
    resolve_builtin_entry,
)
from sase.core.artifact_consumption import (
    ArtifactConsumptionEvent,
    ArtifactConsumptionResolutionStatus,
    append_artifact_consumption_events,
    artifact_consumption_role,
    build_artifact_consumption_event,
)


log = logging.getLogger(__name__)

# Rust's kind registry carries no diagnostic text for these two historical
# readers (only the "plans" deprecation alias is baked into the catalog);
# the replacement pointer is Python-owned so it can name the current kind.
_HISTORICAL_KIND_DIAGNOSTICS = {
    "chat": "@chat: is a historical reader; cite the agent with @agent:<name>",
    "bug": "@bug: is a historical reader; cite the bead with @bead:<id>",
}


@dataclass(frozen=True, slots=True)
class _ExpandedArtifactRef:
    reference: ArtifactRef
    resolution: ArtifactRefResolution
    resolved_path: Path | None
    replacement_text: str
    raw_ref: str
    canonical_ref: str
    stable_id: str | None
    captured_record: object | None = None


def process_artifact_references(
    prompt: str,
    *,
    is_home_mode: bool = False,
    context: ArtifactRefContext | None = None,
    ref_contexts: Sequence[PromptRefContext] | None = None,
    staged_file_paths: set[str] | None = None,
    jinja_protection: ArtifactRendererJinjaProtection | None = None,
    materialize_missing_roots: bool = False,
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
        ref_contexts=ref_contexts,
        rewrite=True,
        staged_file_paths=staged_file_paths,
        jinja_protection=jinja_protection,
        materialize_missing_roots=materialize_missing_roots,
    )


def validate_artifact_references(
    prompt: str,
    *,
    is_home_mode: bool = False,
    context: ArtifactRefContext | None = None,
    ref_contexts: Sequence[PromptRefContext] | None = None,
) -> None:
    """Validate live artifact references without rewriting the prompt."""

    _expand_artifact_references(
        prompt,
        is_home_mode=is_home_mode,
        context=context,
        ref_contexts=ref_contexts,
        rewrite=False,
        staged_file_paths=None,
        jinja_protection=None,
    )


def _expand_artifact_references(
    prompt: str,
    *,
    is_home_mode: bool,
    context: ArtifactRefContext | None,
    ref_contexts: Sequence[PromptRefContext] | None,
    rewrite: bool,
    staged_file_paths: set[str] | None,
    jinja_protection: ArtifactRendererJinjaProtection | None,
    materialize_missing_roots: bool = False,
) -> str:
    if "@" not in prompt:
        return prompt

    candidates = scan_artifact_refs(prompt)
    if not candidates:
        return prompt

    segment_contexts = (
        (((0, len(prompt)), explicit_prompt_ref_context(context)),)
        if context is not None
        else prompt_ref_contexts_for_prompt(
            prompt, is_home_mode=is_home_mode, ref_contexts=ref_contexts
        )
    )

    from sase.xprompt._literal_zones import literal_zone_ranges

    literal_ranges = literal_zone_ranges(prompt)
    byte_to_char = _byte_to_character_offsets(prompt)
    materialization_failures: dict[tuple[int, str], MaterializationFailure] = {}
    if materialize_missing_roots:
        segment_contexts, materialization_failures = (
            _materialize_missing_roots_for_candidates(
                candidates,
                segment_contexts,
                literal_ranges=literal_ranges,
                byte_to_char=byte_to_char,
            )
        )

    replacements: list[tuple[int, int, str]] = []
    consumptions: list[_ExpandedArtifactRef] = []
    failures: list[_ArtifactRefFailure] = []
    seen_diagnostics: set[str] = set()
    for candidate in candidates:
        start, end = _character_span(
            candidate.candidate_span,
            byte_to_char=byte_to_char,
        )
        raw_candidate = candidate.text
        if _overlaps_any(start, end, literal_ranges):
            continue
        context_index = _context_index_for_offset(start, segment_contexts)
        ref_context = segment_contexts[context_index][1]
        known_kinds = set(ref_context.artifact_context.known_kinds)
        if candidate.kind not in known_kinds:
            continue
        if not candidate.well_formed:
            failures.append(_ArtifactRefFailure(raw_candidate, "malformed"))
            continue
        try:
            canonical = parse_artifact_ref_canonical(candidate.reference)
        except (RuntimeError, ValueError) as exc:
            failures.append(_ArtifactRefFailure(raw_candidate, "malformed", str(exc)))
            continue
        parsed = canonical.reference
        _warn_once(_kind_diagnostic(parsed, canonical.diagnostic), seen_diagnostics)

        outcome = resolve_builtin_entry(
            parsed,
            context=ref_context.artifact_context,
            ref_context=ref_context,
        )
        resolution = (
            _resolution_from_outcome(parsed, outcome)
            if outcome is not None
            else _resolve_for_launch(parsed, context=ref_context.artifact_context)
        )
        if resolution.status not in {"exact", "drifted", "vcs_backed"}:
            materialization_failure = materialization_failures.get(
                (context_index, parsed.kind)
            )
            failures.append(
                _ArtifactRefFailure(
                    raw_candidate,
                    resolution.status,
                    (
                        materialization_failure.detail
                        if materialization_failure is not None
                        else artifact_ref_resolution_hint(
                            parsed,
                            resolution,
                            context=ref_context.artifact_context,
                        )
                    ),
                )
            )
            continue
        try:
            replacement_text, resolved_path, captured_record = (
                _replacement_for_candidate(
                    parsed,
                    resolution,
                    outcome,
                    raw_candidate,
                    context=ref_context.artifact_context,
                    jinja_protection=jinja_protection,
                )
            )
        except (RuntimeError, ValueError) as exc:
            failures.append(_ArtifactRefFailure(raw_candidate, "missing", str(exc)))
            continue
        replacements.append((start, end, replacement_text))
        consumptions.append(
            _ExpandedArtifactRef(
                reference=parsed,
                resolution=resolution,
                resolved_path=resolved_path,
                replacement_text=replacement_text,
                raw_ref=raw_candidate,
                canonical_ref=_canonical_ref_text(parsed, outcome),
                stable_id=(
                    None
                    if outcome is None or outcome.entry is None
                    else outcome.entry.stable_id
                ),
                captured_record=captured_record,
            )
        )

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
    _print_captured_file_ref_notice(consumptions)
    _record_artifact_ref_consumption(consumptions)
    _record_artifact_ref_uses(consumptions)
    return expanded


def _context_index_for_offset(
    offset: int,
    segment_contexts: tuple[tuple[tuple[int, int], PromptRefContext], ...],
) -> int:
    last_index = len(segment_contexts) - 1
    for index, ((start, end), _ref_context) in enumerate(segment_contexts):
        if start <= offset < end:
            return index
    return last_index


def _materialize_missing_roots_for_candidates(
    candidates: Sequence[ArtifactRefPromptCandidate],
    segment_contexts: tuple[tuple[tuple[int, int], PromptRefContext], ...],
    *,
    literal_ranges: list[tuple[int, int]],
    byte_to_char: dict[int, int],
) -> tuple[
    tuple[tuple[tuple[int, int], PromptRefContext], ...],
    dict[tuple[int, str], MaterializationFailure],
]:
    kinds_by_context: dict[int, dict[str, None]] = {}
    for candidate in candidates:
        start, end = _character_span(
            candidate.candidate_span,
            byte_to_char=byte_to_char,
        )
        if _overlaps_any(start, end, literal_ranges):
            continue
        context_index = _context_index_for_offset(start, segment_contexts)
        ref_context = segment_contexts[context_index][1]
        known_kinds = set(ref_context.artifact_context.known_kinds)
        if candidate.kind not in known_kinds or not candidate.well_formed:
            continue
        try:
            canonical = parse_artifact_ref_canonical(candidate.reference)
        except (RuntimeError, ValueError):
            continue
        for kind in dict.fromkeys((canonical.reference.kind, candidate.kind)):
            if kind in known_kinds:
                kinds_by_context.setdefault(context_index, {})[kind] = None

    if not kinds_by_context:
        return segment_contexts, {}

    updated = list(segment_contexts)
    failures_by_context_kind: dict[tuple[int, str], MaterializationFailure] = {}
    for context_index, kinds in kinds_by_context.items():
        span, ref_context = updated[context_index]
        refreshed_context, failures = materialize_missing_document_roots(
            tuple(kinds),
            ref_context,
        )
        updated[context_index] = (span, refreshed_context)
        for failure in failures:
            failures_by_context_kind[(context_index, failure.kind)] = failure
    return tuple(updated), failures_by_context_kind


def _kind_diagnostic(
    reference: ArtifactRef, canonical_diagnostic: str | None
) -> str | None:
    if canonical_diagnostic is not None:
        return canonical_diagnostic
    return _HISTORICAL_KIND_DIAGNOSTICS.get(reference.kind)


def _warn_once(diagnostic: str | None, seen: set[str]) -> None:
    if diagnostic is None or diagnostic in seen:
        return
    seen.add(diagnostic)
    print(f"warning: {diagnostic}", file=sys.stderr)


def _resolution_from_outcome(
    reference: ArtifactRef,
    outcome: BuiltinEntryOutcome,
) -> ArtifactRefResolution:
    return ArtifactRefResolution(
        schema_version=reference.schema_version,
        status=outcome.status,
        rendered=outcome.canonical_reference or reference.rendered,
        locator=outcome.locator,
        resolved_path=outcome.resolved_path,
        candidates=outcome.candidates,
        diagnostic=outcome.diagnostic,
    )


def _replacement_for_candidate(
    reference: ArtifactRef,
    resolution: ArtifactRefResolution,
    outcome: BuiltinEntryOutcome | None,
    raw_ref: str,
    *,
    context: ArtifactRefContext,
    jinja_protection: ArtifactRendererJinjaProtection | None,
) -> tuple[str, Path | None, dict[str, object] | None]:
    if outcome is not None and outcome.prompt_text is not None:
        text = outcome.prompt_text
        if jinja_protection is not None:
            text = jinja_protection.protect(text)
        return text, outcome.resolved_path, None
    materialized_path = _materialized_artifact_path(
        reference, resolution, context=context
    )
    captured_record, captured_path = _capture_file_path_ref(
        reference,
        resolution,
        raw_ref,
    )
    if captured_record is not None and captured_record.get("skipped_reason"):
        raise RuntimeError(
            f"file capture skipped: {captured_record.get('skipped_reason')}"
        )
    if captured_path is not None:
        resolution = replace(resolution, resolved_path=captured_path)
    replacement_text, resolved_path = _artifact_ref_replacement(
        reference,
        resolution,
        context=context,
        materialized_path=materialized_path,
        jinja_protection=jinja_protection,
    )
    return replacement_text, resolved_path, captured_record


def _canonical_ref_text(
    reference: ArtifactRef, outcome: BuiltinEntryOutcome | None
) -> str:
    if outcome is not None and outcome.canonical_reference is not None:
        return outcome.canonical_reference
    return reference.rendered


def _resolve_for_launch(
    reference: ArtifactRef,
    *,
    context: ArtifactRefContext,
) -> ArtifactRefResolution:
    return _resolve_for_launch_impl(
        reference,
        context=context,
        resolve_checkout_commit=_resolve_checkout_commit,
    )


def _artifact_ref_replacement(
    reference: ArtifactRef,
    resolution: ArtifactRefResolution,
    *,
    context: ArtifactRefContext,
    materialized_path: Path | None,
    jinja_protection: ArtifactRendererJinjaProtection | None,
) -> tuple[str, Path | None]:
    return _artifact_ref_replacement_impl(
        reference,
        resolution,
        context=context,
        materialized_path=materialized_path,
        jinja_protection=jinja_protection,
        issue_url_resolver=_resolved_bug_url,
    )


def _record_artifact_ref_consumption(
    consumptions: list[_ExpandedArtifactRef],
) -> None:
    try:
        events: list[ArtifactConsumptionEvent] = []
        seen_refs: set[str] = set()
        for item in consumptions:
            parsed = item.reference
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
                        item.resolved_path,
                    ),
                    artifact_id=artifact_id,
                    resolved_path=item.resolved_path,
                    resolution_status=cast(
                        ArtifactConsumptionResolutionStatus,
                        item.resolution.status,
                    ),
                )
            )
        append_artifact_consumption_events(events)
    except Exception as exc:
        log.debug("Could not record artifact-reference consumption: %s", exc)


def _record_artifact_ref_uses(consumptions: list[_ExpandedArtifactRef]) -> None:
    """Write one immutable ref-uses row per occurrence, builtins included."""

    try:
        from sase.agent.identity import resolve_local_agent_name
        from sase.core.artifact_ref_uses import record_artifact_ref_use

        agent_name = resolve_local_agent_name()
        if agent_name is None:
            log.debug(
                "No local agent identity; skipping artifact-reference use records"
            )
            return
        for item in consumptions:
            record_artifact_ref_use(
                agent_name=agent_name,
                raw_ref=item.raw_ref,
                canonical_ref=item.canonical_ref,
                ref_kind=item.reference.kind,
                prompt_text=item.replacement_text,
                stable_id=item.stable_id,
            )
    except Exception as exc:
        log.debug("Could not record artifact-reference use: %s", exc)


def _stage_artifact_references(
    consumptions: list[_ExpandedArtifactRef],
) -> set[str]:
    """Stage the exact resolution list used by consumption telemetry."""

    from sase.core.prompt_artifact_staging import stage_prompt_artifact

    staged_file_paths: set[str] = set()
    for item in consumptions:
        if item.captured_record is not None:
            if item.resolved_path is not None and item.resolved_path.is_file():
                staged_file_paths.add(str(item.resolved_path.resolve(strict=False)))
            continue
        parsed = item.reference
        record = stage_prompt_artifact(
            raw_ref=item.raw_ref,
            expanded_ref=item.replacement_text,
            resolved_path=item.resolved_path,
            ref_kind=parsed.kind,
            label=_artifact_ref_label(parsed, item.resolved_path, item.raw_ref),
            locator=item.resolution.locator,
        )
        if (
            record is not None
            and item.resolved_path is not None
            and item.resolved_path.is_file()
        ):
            staged_file_paths.add(str(item.resolved_path.resolve(strict=False)))
    return staged_file_paths


def _capture_file_path_ref(
    reference: ArtifactRef,
    resolution: ArtifactRefResolution,
    raw_ref: str,
) -> tuple[dict[str, object] | None, Path | None]:
    if (
        reference.kind_type != "file"
        or reference.payload.type != "file_path"
        or resolution.status != "exact"
        or resolution.resolved_path is None
        or resolution.locator is None
    ):
        return None, None
    root_name, separator, _relative = resolution.locator.partition(":")
    if not separator:
        return None, None
    from sase.core.prompt_artifact_staging import capture_prompt_file_ref

    record = capture_prompt_file_ref(
        source=resolution.resolved_path,
        logical_path=resolution.locator,
        root_name=root_name,
        authored_path=reference.payload.path or "",
        raw_ref=raw_ref,
        expanded_ref=raw_ref,
    )
    if record is None:
        return None, None
    pool_relpath = record.get("pool_relpath")
    if not isinstance(pool_relpath, str) or not pool_relpath:
        return dict(record), None
    captured_path = Path.cwd().expanduser().resolve(strict=False)
    captured_path = captured_path / ".sase" / "artifacts" / pool_relpath
    return dict(record), captured_path


def _print_captured_file_ref_notice(
    consumptions: list[_ExpandedArtifactRef],
) -> None:
    rows: list[str] = []
    for item in consumptions:
        record = item.captured_record
        if not isinstance(record, dict):
            continue
        sha256 = str(record.get("sha256") or "")
        size = record.get("size_bytes")
        rows.append(
            "  "
            f"{item.raw_ref} -> {record.get('logical_path') or item.resolution.locator} "
            f"sha256={sha256[:12]} size={size} "
            f"sidecar=agents visibility={record.get('sidecar_visibility') or 'public'}"
        )
    if rows:
        print("Captured @file references:", file=sys.stderr)
        print("\n".join(rows), file=sys.stderr)


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


__all__ = [
    "artifact_ref_resolution_hint",
    "process_artifact_references",
    "validate_artifact_references",
]

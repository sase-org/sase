"""Launch-prompt expansion and validation for artifact references."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import logging
from pathlib import Path
import sys
from typing import cast

from jinja2 import TemplateError

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
from sase.artifact_ref_renderers import (
    ArtifactRendererJinjaProtection,
    generated_document_ref_xprompt,
    ref_renderer_registry,
)
from sase.sidecar_ref_config import canonical_ref_input
from sase.xprompt.input_binding import InputBindingError, bind_input_args
from sase.xprompt.models import XPrompt


log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _ArtifactRefFailure:
    reference: str
    status: str
    detail: str | None = None


class _ArtifactRefRendererError(RuntimeError):
    """Raised when the selected ref renderer cannot render."""


@dataclass(frozen=True, slots=True)
class _ExpandedArtifactRef:
    reference: ArtifactRef
    resolution: ArtifactRefResolution
    resolved_path: Path | None
    replacement_text: str
    raw_ref: str


@dataclass(frozen=True, slots=True)
class _RefRewrite:
    start: int
    replacement: str
    raw: str


def process_artifact_references(
    prompt: str,
    *,
    is_home_mode: bool = False,
    context: ArtifactRefContext | None = None,
    staged_file_paths: set[str] | None = None,
    jinja_protection: ArtifactRendererJinjaProtection | None = None,
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
        jinja_protection=jinja_protection,
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
        jinja_protection=None,
    )


def _expand_artifact_references(
    prompt: str,
    *,
    is_home_mode: bool,
    context: ArtifactRefContext | None,
    rewrite: bool,
    staged_file_paths: set[str] | None,
    jinja_protection: ArtifactRendererJinjaProtection | None,
) -> str:
    if "@" not in prompt and "#ref/" not in prompt:
        return prompt

    if context is None:
        context = launch_artifact_ref_context(is_home_mode=is_home_mode)
    ref_renderers: dict[str, XPrompt] | None = None
    rewrites: dict[int, _RefRewrite] = {}
    if "#ref/" in prompt:
        ref_renderers = ref_renderer_registry(context)
        prompt, rewrites = _rewrite_ref_xprompt_references(
            prompt,
            context=context,
            ref_renderers=ref_renderers,
        )

    if "@" not in prompt:
        return prompt

    candidates = scan_artifact_refs(prompt)
    if not candidates:
        return prompt
    if ref_renderers is None:
        ref_renderers = ref_renderer_registry(context)

    from sase.xprompt._literal_zones import literal_zone_ranges

    literal_ranges = literal_zone_ranges(prompt)
    byte_to_char = _byte_to_character_offsets(prompt)
    replacements: list[tuple[int, int, str]] = []
    consumptions: list[_ExpandedArtifactRef] = []
    failures: list[_ArtifactRefFailure] = []
    known_kinds = set(context.known_kinds)
    for occurrence_index, candidate in enumerate(candidates):
        start, end = _character_span(
            candidate.candidate_span,
            byte_to_char=byte_to_char,
        )
        raw_candidate = _raw_candidate_text(candidate.text, start, rewrites)
        if _overlaps_any(start, end, literal_ranges):
            continue
        if candidate.kind not in known_kinds:
            continue
        if not candidate.well_formed:
            failures.append(_ArtifactRefFailure(raw_candidate, "malformed"))
            continue
        try:
            parsed = parse_artifact_ref(candidate.reference)
            resolution = _resolve_for_launch(parsed, context=context)
        except (RuntimeError, ValueError) as exc:
            failures.append(_ArtifactRefFailure(raw_candidate, "malformed", str(exc)))
            continue
        if resolution.status not in {"exact", "drifted", "vcs_backed"}:
            failures.append(
                _ArtifactRefFailure(
                    raw_candidate,
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
            materialized_path = _materialized_artifact_path(
                parsed,
                resolution,
                context=context,
            )
            replacement_text, resolved_path = _artifact_ref_replacement(
                parsed,
                resolution,
                context=context,
                materialized_path=materialized_path,
                occurrence_index=occurrence_index,
                raw_ref=raw_candidate,
                ref_renderers=ref_renderers,
                jinja_protection=jinja_protection,
            )
        except _ArtifactRefRendererError as exc:
            failures.append(_ArtifactRefFailure(raw_candidate, "renderer", str(exc)))
            continue
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
    materialized_path: Path | None,
    occurrence_index: int,
    raw_ref: str,
    ref_renderers: Mapping[str, XPrompt],
    jinja_protection: ArtifactRendererJinjaProtection | None,
) -> tuple[str, Path | None]:
    resolved_path = _artifact_resolved_path(
        reference,
        resolution,
        context=context,
        materialized_path=materialized_path,
    )
    replacement_text = _render_ref_xprompt(
        reference,
        resolution,
        context=context,
        resolved_path=resolved_path,
        occurrence_index=occurrence_index,
        raw_ref=raw_ref,
        ref_renderers=ref_renderers,
    )
    if jinja_protection is not None:
        replacement_text = jinja_protection.protect(replacement_text)
    return replacement_text, resolved_path


def _artifact_resolved_path(
    reference: ArtifactRef,
    resolution: ArtifactRefResolution,
    *,
    context: ArtifactRefContext,
    materialized_path: Path | None,
) -> Path | None:
    if reference.kind_type in {"document", "chat", "file", "bead", "agent"}:
        if reference.kind_type == "file" and resolution.status == "vcs_backed":
            if materialized_path is None:
                raise RuntimeError(
                    "VCS-backed artifact content is unavailable"
                    + ("" if resolution.locator is None else f" ({resolution.locator})")
                )
            return materialized_path
        if resolution.resolved_path is None:
            raise RuntimeError("resolver returned no artifact path")
        return resolution.resolved_path
    if reference.kind_type == "commit":
        if resolution.locator is None:
            raise RuntimeError("resolver returned no commit locator")
        repository = _repository_for_ref(reference.payload.repo or "", context)
        if repository is None or repository.checkout_path is None:
            raise RuntimeError("repository checkout is unavailable")
        return repository.checkout_path
    if reference.kind_type == "bug":
        if resolution.locator is None or reference.payload.number is None:
            raise RuntimeError("resolver returned no bug locator")
        return None
    raise RuntimeError(f"unsupported artifact reference kind: {reference.kind}")


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


def _stage_artifact_references(
    consumptions: list[_ExpandedArtifactRef],
) -> set[str]:
    """Stage the exact resolution list used by consumption telemetry."""

    from sase.core.prompt_artifact_staging import stage_prompt_artifact

    staged_file_paths: set[str] = set()
    for item in consumptions:
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


def _materialized_artifact_path(
    reference: ArtifactRef,
    resolution: ArtifactRefResolution,
    *,
    context: ArtifactRefContext,
) -> Path | None:
    if reference.kind_type == "file" and resolution.status == "vcs_backed":
        return _materialize_vcs_file_reference(reference, context=context)
    return None


def _rewrite_ref_xprompt_references(
    prompt: str,
    *,
    context: ArtifactRefContext,
    ref_renderers: Mapping[str, XPrompt],
) -> tuple[str, dict[int, _RefRewrite]]:
    from sase.xprompt._literal_zones import literal_zone_ranges
    from sase.xprompt._parsing import iter_xprompt_references

    literal_ranges = literal_zone_ranges(prompt)
    replacements: list[tuple[int, int, str, str]] = []
    failures: list[_ArtifactRefFailure] = []
    known_kinds = set(context.known_kinds)
    for reference in iter_xprompt_references(prompt):
        if not reference.name.startswith("ref/"):
            continue
        if _overlaps_any(reference.start, reference.end, literal_ranges):
            continue

        kind = reference.name.removeprefix("ref/")
        renderer = ref_renderers.get(reference.name)
        if kind not in known_kinds or renderer is None:
            failures.append(
                _ArtifactRefFailure(
                    reference.raw,
                    "unknown_kind",
                    f"unknown artifact reference kind: {kind}",
                )
            )
            continue
        try:
            payload = _bind_ref_xprompt_argument(renderer, reference.raw)
        except InputBindingError as exc:
            failures.append(_ArtifactRefFailure(reference.raw, "invalid", str(exc)))
            continue
        replacements.append(
            (reference.start, reference.end, f"@{kind}:{payload}", reference.raw)
        )

    if failures:
        _print_artifact_ref_failures(failures)
        sys.exit(1)
    if not replacements:
        return prompt, {}

    chunks: list[str] = []
    rewrites: dict[int, _RefRewrite] = {}
    cursor = 0
    for start, end, replacement, raw in sorted(replacements):
        chunks.append(prompt[cursor:start])
        replacement_start = sum(len(chunk) for chunk in chunks)
        chunks.append(replacement)
        rewrites[replacement_start] = _RefRewrite(
            start=replacement_start,
            replacement=replacement,
            raw=raw,
        )
        cursor = end
    chunks.append(prompt[cursor:])
    return "".join(chunks), rewrites


def _bind_ref_xprompt_argument(renderer: XPrompt, raw: str) -> str:
    from sase.xprompt._parsing import parse_workflow_reference

    if len(renderer.inputs) != 1:
        raise InputBindingError(
            f"ref renderer {renderer.name!r} must declare exactly one input"
        )
    input_arg = renderer.inputs[0]
    _name, positional_args, named_args = parse_workflow_reference(raw.removeprefix("#"))
    bound = bind_input_args(renderer.inputs, positional_args, named_args)
    unknown = sorted(set(bound.explicit_values).difference({input_arg.name}))
    if unknown:
        raise InputBindingError("unknown ref argument(s): " + ", ".join(unknown))
    if input_arg.name not in bound.explicit_values:
        raise InputBindingError(f"missing required argument: {input_arg.name}")
    return str(bound.values[input_arg.name])


def _raw_candidate_text(
    candidate_text: str,
    start: int,
    rewrites: Mapping[int, _RefRewrite],
) -> str:
    rewrite = rewrites.get(start)
    if rewrite is None:
        return candidate_text
    if candidate_text.startswith(rewrite.replacement):
        return rewrite.raw + candidate_text[len(rewrite.replacement) :]
    return rewrite.raw


def _render_ref_xprompt(
    reference: ArtifactRef,
    resolution: ArtifactRefResolution,
    *,
    context: ArtifactRefContext,
    resolved_path: Path | None,
    occurrence_index: int,
    raw_ref: str,
    ref_renderers: Mapping[str, XPrompt],
) -> str:
    renderer = ref_renderers.get(f"ref/{reference.kind}")
    if renderer is None:
        if reference.kind_type == "document":
            renderer = generated_document_ref_xprompt(reference.kind)
        else:
            raise RuntimeError(f"no ref renderer is registered for {reference.kind}")

    render_context = _ref_render_context(
        reference,
        resolution,
        context=context,
        resolved_path=resolved_path,
        occurrence_index=occurrence_index,
        raw_ref=raw_ref,
    )
    try:
        from sase.xprompt._jinja import get_jinja_env

        rendered = (
            get_jinja_env().from_string(renderer.content).render(**render_context)
        )
    except TemplateError as exc:
        source = renderer.source_path or renderer.name
        raise _ArtifactRefRendererError(
            f"ref/{reference.kind} renderer error in {source}: {exc}"
        ) from exc
    return rendered.strip()


def _ref_render_context(
    reference: ArtifactRef,
    resolution: ArtifactRefResolution,
    *,
    context: ArtifactRefContext,
    resolved_path: Path | None,
    occurrence_index: int,
    raw_ref: str,
) -> dict[str, object]:
    canonical = _canonical_ref_text(resolution)
    fragment = _fragment_text(reference)
    legacy = _legacy_replacement_text(
        reference,
        resolution,
        context=context,
        resolved_path=resolved_path,
    )
    resolved_payload = _resolved_payload_reference(reference, resolution)
    sidecar = reference.kind if reference.kind_type == "document" else None
    url = _bug_url(reference, resolution)
    checkout = (
        str(resolved_path)
        if reference.kind_type == "commit" and resolved_path is not None
        else None
    )
    ref_map = {
        "raw": raw_ref,
        "canonical": canonical,
        "kind": reference.kind,
        "kind_type": reference.kind_type,
        "payload": _payload_text(reference),
        "fragment": fragment,
        "occurrence_index": occurrence_index,
        "resolved_path": _template_resolved_path(
            reference,
            resolved_payload,
            resolved_path,
        ),
        "checkout": checkout,
        "url": url,
        "project": _reference_project(reference, resolution, context),
        "sidecar": sidecar,
    }
    render_context: dict[str, object] = {
        "ref": ref_map,
        "sidecar": sidecar,
        "fragment": fragment,
        "fragment_annotation": _fragment_annotation(reference.fragment),
        "legacy": legacy,
        "file_path": _template_file_path(
            reference,
            resolved_payload,
            resolved_path,
        ),
        "resolved_file_path": None if resolved_path is None else str(resolved_path),
        "artifact_id": _artifact_id(reference),
        "commit": legacy
        if reference.kind_type == "commit"
        else _commit_payload(reference),
        "bug": legacy if reference.kind_type == "bug" else _bug_payload(reference),
        "bead_id": _bead_payload(resolved_payload),
        "agent_name": _agent_payload(resolved_payload),
    }
    canonical_input = canonical_ref_input(reference.kind)
    render_context[canonical_input] = _canonical_input_value(
        reference,
        resolved_payload,
        resolved_path,
    )
    return render_context


def _legacy_replacement_text(
    reference: ArtifactRef,
    resolution: ArtifactRefResolution,
    *,
    context: ArtifactRefContext,
    resolved_path: Path | None,
) -> str:
    if reference.kind_type in {"document", "chat", "file", "bead", "agent"}:
        if resolved_path is None:
            raise RuntimeError("resolver returned no artifact path")
        return f"@{resolved_path}{_fragment_annotation(reference.fragment)}"
    if reference.kind_type == "commit":
        if resolution.locator is None or resolved_path is None:
            raise RuntimeError("resolver returned no commit locator")
        return f"{resolution.locator} (checkout: {resolved_path})"
    if reference.kind_type == "bug":
        if reference.payload.number is None:
            raise RuntimeError("resolver returned no bug number")
        url = _bug_url(reference, resolution)
        if url is None:
            raise RuntimeError("resolver returned no bug locator")
        return f"#{reference.payload.number} {url}"
    raise RuntimeError(f"unsupported artifact reference kind: {reference.kind}")


def _canonical_ref_text(resolution: ArtifactRefResolution) -> str:
    return f"@{resolution.rendered}"


def _resolved_payload_reference(
    reference: ArtifactRef,
    resolution: ArtifactRefResolution,
) -> ArtifactRef:
    try:
        return parse_artifact_ref(resolution.rendered)
    except (RuntimeError, ValueError):
        return reference


def _canonical_input_value(
    reference: ArtifactRef,
    resolved_payload: ArtifactRef,
    resolved_path: Path | None,
) -> str:
    if reference.kind_type in {"document", "chat"}:
        return resolved_payload.payload.path or reference.payload.path or ""
    if reference.kind_type == "file":
        return _artifact_id(reference) or ""
    if reference.kind_type == "commit":
        return _commit_payload(resolved_payload)
    if reference.kind_type == "bug":
        return _bug_payload(resolved_payload)
    if reference.kind_type == "bead":
        return _bead_payload(resolved_payload)
    if reference.kind_type == "agent":
        return _agent_payload(resolved_payload)
    return "" if resolved_path is None else str(resolved_path)


def _template_file_path(
    reference: ArtifactRef,
    resolved_payload: ArtifactRef,
    resolved_path: Path | None,
) -> str | None:
    if reference.kind_type == "document":
        return resolved_payload.payload.path or reference.payload.path
    return None if resolved_path is None else str(resolved_path)


def _template_resolved_path(
    reference: ArtifactRef,
    resolved_payload: ArtifactRef,
    resolved_path: Path | None,
) -> str | None:
    if reference.kind_type == "document":
        return resolved_payload.payload.path or reference.payload.path
    return None if resolved_path is None else str(resolved_path)


def _payload_text(reference: ArtifactRef) -> str:
    payload = reference.payload
    if payload.path is not None:
        return payload.path
    if payload.repo is not None and payload.sha is not None:
        return f"{payload.repo}@{payload.sha}"
    if payload.project is not None and payload.number is not None:
        return f"{payload.project}#{payload.number}"
    if payload.source is not None and payload.digest is not None:
        return f"{payload.source}:{payload.digest}"
    if payload.id is not None:
        return payload.id
    if payload.name is not None:
        return payload.name
    if payload.number is not None:
        return str(payload.number)
    return reference.rendered


def _artifact_id(reference: ArtifactRef) -> str | None:
    if reference.payload.source is not None and reference.payload.digest is not None:
        return f"{reference.payload.source}:{reference.payload.digest}"
    return reference.payload.id


def _commit_payload(reference: ArtifactRef) -> str:
    if reference.payload.repo is not None and reference.payload.sha is not None:
        return f"{reference.payload.repo}@{reference.payload.sha}"
    return reference.rendered.removeprefix("commit:")


def _bug_payload(reference: ArtifactRef) -> str:
    if reference.payload.project is not None and reference.payload.number is not None:
        return f"{reference.payload.project}#{reference.payload.number}"
    return reference.rendered.removeprefix("bug:")


def _bead_payload(reference: ArtifactRef) -> str:
    return reference.payload.id or reference.rendered.removeprefix("bead:")


def _agent_payload(reference: ArtifactRef) -> str:
    return reference.payload.name or reference.rendered.removeprefix("agent:")


def _bug_url(reference: ArtifactRef, resolution: ArtifactRefResolution) -> str | None:
    if reference.kind_type != "bug":
        return None
    if resolution.locator is None or reference.payload.number is None:
        return None
    project = resolution.locator.rsplit("#", 1)[0]
    return _resolved_bug_url(project, reference.payload.number)


def _fragment_text(reference: ArtifactRef) -> str | None:
    if reference.fragment is None:
        return None
    fragment_free = replace(reference, fragment=None)
    base = render_artifact_ref(fragment_free)
    return reference.rendered[len(base) + 1 :]


def _reference_project(
    reference: ArtifactRef,
    resolution: ArtifactRefResolution,
    context: ArtifactRefContext,
) -> str | None:
    if reference.kind_type == "bug" and resolution.locator is not None:
        return resolution.locator.rsplit("#", 1)[0]
    if context.projects:
        return context.projects[0].name
    return None


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

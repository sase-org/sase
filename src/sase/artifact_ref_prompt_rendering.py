"""Renderer-template expansion for launch-prompt artifact references."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path

from jinja2 import TemplateError

from sase.artifact_ref_models import (
    ArtifactRef,
    ArtifactRefContext,
    ArtifactRefFragment,
    ArtifactRefResolution,
)
from sase.artifact_ref_operations import parse_artifact_ref, render_artifact_ref
from sase.artifact_ref_prompt_parsing import ArtifactRefRendererError
from sase.artifact_ref_prompt_resolution import artifact_resolved_path
from sase.artifact_ref_renderers import (
    ArtifactRendererJinjaProtection,
    generated_document_ref_xprompt,
)
from sase.sidecar_ref_config import canonical_ref_input
from sase.xprompt.models import XPrompt


_IssueUrlResolver = Callable[[str, int], str]


def artifact_ref_replacement(
    reference: ArtifactRef,
    resolution: ArtifactRefResolution,
    *,
    context: ArtifactRefContext,
    materialized_path: Path | None,
    occurrence_index: int,
    raw_ref: str,
    ref_renderers: Mapping[str, XPrompt],
    jinja_protection: ArtifactRendererJinjaProtection | None,
    issue_url_resolver: _IssueUrlResolver,
) -> tuple[str, Path | None]:
    """Render the replacement text and return it with its resolved path."""

    resolved_path = artifact_resolved_path(
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
        issue_url_resolver=issue_url_resolver,
    )
    if jinja_protection is not None:
        replacement_text = jinja_protection.protect(replacement_text)
    return replacement_text, resolved_path


def _render_ref_xprompt(
    reference: ArtifactRef,
    resolution: ArtifactRefResolution,
    *,
    context: ArtifactRefContext,
    resolved_path: Path | None,
    occurrence_index: int,
    raw_ref: str,
    ref_renderers: Mapping[str, XPrompt],
    issue_url_resolver: _IssueUrlResolver,
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
        issue_url_resolver=issue_url_resolver,
    )
    try:
        from sase.xprompt._jinja import get_jinja_env

        rendered = (
            get_jinja_env().from_string(renderer.content).render(**render_context)
        )
    except TemplateError as exc:
        source = renderer.source_path or renderer.name
        raise ArtifactRefRendererError(
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
    issue_url_resolver: _IssueUrlResolver,
) -> dict[str, object]:
    canonical = _canonical_ref_text(resolution)
    fragment = _fragment_text(reference)
    legacy = _legacy_replacement_text(
        reference,
        resolution,
        context=context,
        resolved_path=resolved_path,
        issue_url_resolver=issue_url_resolver,
    )
    resolved_payload = _resolved_payload_reference(reference, resolution)
    sidecar = reference.kind if reference.kind_type == "document" else None
    url = _bug_url(reference, resolution, issue_url_resolver)
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
    issue_url_resolver: _IssueUrlResolver,
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
        url = _bug_url(reference, resolution, issue_url_resolver)
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


def _bug_url(
    reference: ArtifactRef,
    resolution: ArtifactRefResolution,
    issue_url_resolver: _IssueUrlResolver,
) -> str | None:
    if reference.kind_type != "bug":
        return None
    if resolution.locator is None or reference.payload.number is None:
        return None
    project = resolution.locator.rsplit("#", 1)[0]
    return issue_url_resolver(project, reference.payload.number)


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
    if context.selected_project is not None:
        return context.selected_project
    if context.projects:
        return context.projects[0].name
    return None


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


def resolved_bug_url(project: str, number: int) -> str:
    """Return the provider URL for a resolved bug reference."""

    from sase.ace.tui.artifacts_bugs import issue_url_for_number

    return issue_url_for_number(project, number)

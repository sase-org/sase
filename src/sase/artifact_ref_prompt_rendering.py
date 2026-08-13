"""Hardcoded expansion for launch-prompt artifact references."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from sase.artifact_ref_models import (
    ArtifactRef,
    ArtifactRefContext,
    ArtifactRefDocumentExpansion,
    ArtifactRefFragment,
    ArtifactRefResolution,
)
from sase.artifact_ref_operations import (
    artifact_ref_expansion_render,
    artifact_ref_expansion_validate,
    render_artifact_ref,
)
from sase.artifact_ref_prompt_resolution import artifact_resolved_path
from sase.artifact_ref_renderers import ArtifactRendererJinjaProtection


_IssueUrlResolver = Callable[[str, int], str]

# Fail fast rather than deep inside a Rust-side render call if a future edit
# lets this set drift from sidecar_ref_config.DOCUMENT_REF_EXPANSION_PLACEHOLDERS.
_DOCUMENT_EXPANSION_SUPPORTED_PLACEHOLDERS = frozenset(
    {
        "kind",
        "argument",
        "canonical_argument",
        "display_label",
        "repo_relative_path",
        "sidecar_role",
        "checkout_path",
    }
)


def artifact_ref_replacement(
    reference: ArtifactRef,
    resolution: ArtifactRefResolution,
    *,
    context: ArtifactRefContext,
    materialized_path: Path | None,
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
    expansion = (
        context.document_expansion_for(reference.kind)
        if reference.kind_type == "document"
        else None
    )
    replacement_text = (
        _document_expansion_replacement_text(
            reference,
            expansion,
            resolved_path=resolved_path,
        )
        if expansion is not None
        else _legacy_replacement_text(
            reference,
            resolution,
            resolved_path=resolved_path,
            issue_url_resolver=issue_url_resolver,
        )
    )
    if jinja_protection is not None:
        replacement_text = jinja_protection.protect(replacement_text)
    return replacement_text, resolved_path


def _document_expansion_replacement_text(
    reference: ArtifactRef,
    expansion: ArtifactRefDocumentExpansion,
    *,
    resolved_path: Path | None,
) -> str:
    used_placeholders = set(artifact_ref_expansion_validate(expansion.expansion_format))
    assert used_placeholders <= _DOCUMENT_EXPANSION_SUPPORTED_PLACEHOLDERS
    argument = reference.payload.path or ""
    available = {
        "kind": reference.kind,
        "argument": argument,
        "canonical_argument": render_artifact_ref(replace(reference, fragment=None)),
        "repo_relative_path": argument,
        "display_label": Path(argument).name,
        "sidecar_role": expansion.role,
    }
    if "checkout_path" in used_placeholders:
        if resolved_path is None:
            raise RuntimeError("resolver returned no artifact path")
        available["checkout_path"] = str(resolved_path)
    values = {name: available[name] for name in used_placeholders}
    text = artifact_ref_expansion_render(expansion.expansion_format, values)
    return f"{text}{_fragment_annotation(reference.fragment)}"


def _legacy_replacement_text(
    reference: ArtifactRef,
    resolution: ArtifactRefResolution,
    *,
    resolved_path: Path | None,
    issue_url_resolver: _IssueUrlResolver,
) -> str:
    if reference.kind_type in {"document", "chat", "file", "bead", "agent"}:
        if resolved_path is None:
            raise RuntimeError("resolver returned no artifact path")
        text = f"@{resolved_path}{_fragment_annotation(reference.fragment)}"
        if reference.kind_type == "agent":
            text += _agent_transcript_pointer(reference, resolution, resolved_path)
        return text
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


def _agent_transcript_pointer(
    reference: ArtifactRef,
    resolution: ArtifactRefResolution,
    resolved_path: Path,
) -> str:
    """Point at chat.md/prompt.md beside an agent's page, when both exist.

    Only names the siblings when they actually exist next to the page,
    which is what makes dropping ``@chat`` from authoring lossless.
    """

    page_dir = resolved_path.parent
    if not (page_dir / "chat.md").exists() or not (page_dir / "prompt.md").exists():
        return ""
    name = reference.payload.name or ""
    project = (resolution.locator or "/").split("/", 1)[0]
    return (
        f" (agent {name} in project {project}; its prompt and chat "
        "transcript are prompt.md and chat.md beside that page)"
    )


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

    from sase.ace.tui.external_issues import issue_url_for_number

    return issue_url_for_number(project, number)


__all__ = [
    "artifact_ref_replacement",
    "resolved_bug_url",
]

"""Centralized expansion for launch-prompt artifact references."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from sase.artifact_ref_models import (
    ArtifactEntry,
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
from sase.sdd.artifact_link_neighborhood import (
    launch_one_hop_neighborhood,
    load_neighborhood_rows,
)
from sase.sdd.artifact_link_store import canonicalize_artifact_link_ref
from sase.sidecar_ref_config import (
    DEFAULT_DOCUMENT_REF_EXPANSION_FORMAT,
    sidecar_role_for_ref_kind,
)


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
_FILE_EXPANSION_FORMAT = "the {checkout_path} file"
_BEAD_EXPANSION_FORMAT = "the {canonical_argument} bead in the {project} project"
_AGENT_EXPANSION_FORMAT = "the {canonical_argument} agent in the {project} project"
_STITCH_EXPANSION_FORMAT = "the {captured_revision} stitch in the {repository} repo"
_PATCH_EXPANSION_FORMAT = "the {display_label} Patch in the {project} project"


def artifact_ref_replacement(
    reference: ArtifactRef,
    resolution: ArtifactRefResolution,
    *,
    context: ArtifactRefContext,
    materialized_path: Path | None,
    jinja_protection: ArtifactRendererJinjaProtection | None,
    issue_url_resolver: _IssueUrlResolver,
    entry: ArtifactEntry | None = None,
) -> tuple[str, Path | None]:
    """Render the replacement text and return it with its resolved path."""

    resolved_path = artifact_resolved_path(
        reference,
        resolution,
        context=context,
        materialized_path=materialized_path,
    )
    replacement_text = _replacement_text(
        reference,
        resolution,
        context=context,
        resolved_path=resolved_path,
        issue_url_resolver=issue_url_resolver,
        entry=entry,
    )
    replacement_text = f"{replacement_text}{_fragment_annotation(reference.fragment)}"
    if jinja_protection is not None:
        replacement_text = jinja_protection.protect(replacement_text)
    return replacement_text, resolved_path


def _replacement_text(
    reference: ArtifactRef,
    resolution: ArtifactRefResolution,
    *,
    context: ArtifactRefContext,
    resolved_path: Path | None,
    issue_url_resolver: _IssueUrlResolver,
    entry: ArtifactEntry | None,
) -> str:
    kind_type = reference.kind_type
    if kind_type == "document":
        return _document_expansion_text(
            reference,
            context.document_expansion_for(reference.kind),
            resolved_path=resolved_path,
        )
    if kind_type in {"file", "chat"}:
        return _path_file_text(resolved_path)
    if kind_type == "bead":
        return _bead_text(reference, resolution, entry)
    if kind_type == "agent":
        return _agent_text(reference, resolution, entry)
    if kind_type in {"stitch", "commit"}:
        return _stitch_text(resolution, entry)
    if kind_type == "patch":
        return _patch_text(reference, resolution, entry)
    if kind_type == "bug":
        return _bug_text(reference, resolution, issue_url_resolver)
    raise RuntimeError(f"unsupported artifact reference kind: {reference.kind}")


def _document_expansion_text(
    reference: ArtifactRef,
    expansion: ArtifactRefDocumentExpansion | None,
    *,
    resolved_path: Path | None,
) -> str:
    expansion_format = (
        DEFAULT_DOCUMENT_REF_EXPANSION_FORMAT
        if expansion is None
        else expansion.expansion_format
    )
    used_placeholders = set(artifact_ref_expansion_validate(expansion_format))
    assert used_placeholders <= _DOCUMENT_EXPANSION_SUPPORTED_PLACEHOLDERS
    argument = reference.payload.path or ""
    role = (
        sidecar_role_for_ref_kind(reference.kind)
        if expansion is None
        else expansion.role
    )
    available = {
        "kind": reference.kind,
        "argument": argument,
        "canonical_argument": render_artifact_ref(replace(reference, fragment=None)),
        "repo_relative_path": argument,
        "display_label": Path(argument).name,
        "sidecar_role": role,
    }
    if "checkout_path" in used_placeholders:
        if resolved_path is None:
            raise RuntimeError("resolver returned no artifact path")
        available["checkout_path"] = str(resolved_path)
    values = {name: available[name] for name in used_placeholders}
    text = artifact_ref_expansion_render(expansion_format, values)
    return _with_one_hop_neighborhood(reference, text)


def _with_one_hop_neighborhood(reference: ArtifactRef, text: str) -> str:
    """Append one typed hop of *reference*'s link neighborhood, if any.

    Never expands transitively: only rows touching *reference* itself, so a
    launch prompt stays predictable and small instead of pulling in a
    two-hop context explosion.
    """

    try:
        canonical = canonicalize_artifact_link_ref(
            render_artifact_ref(replace(reference, fragment=None))
        )
        items = launch_one_hop_neighborhood(
            canonical, load_neighborhood_rows(canonical)
        )
    except Exception:  # noqa: BLE001 - neighborhood expansion is best-effort
        return text
    if not items:
        return text
    return f"{text} (linked: {' · '.join(items)})"


def _path_file_text(resolved_path: Path | None) -> str:
    if resolved_path is None:
        raise RuntimeError("resolver returned no artifact path")
    return _render_expansion(
        _FILE_EXPANSION_FORMAT, {"checkout_path": str(resolved_path)}
    )


def _bead_text(
    reference: ArtifactRef,
    resolution: ArtifactRefResolution,
    entry: ArtifactEntry | None,
) -> str:
    project, bead_id = _project_and_object(
        kind="bead",
        locator=resolution.locator,
        rendered=resolution.rendered,
        entry=entry,
        payload_object=reference.payload.id,
    )
    return _render_expansion(
        _BEAD_EXPANSION_FORMAT,
        {"canonical_argument": bead_id, "project": project},
    )


def _agent_text(
    reference: ArtifactRef,
    resolution: ArtifactRefResolution,
    entry: ArtifactEntry | None,
) -> str:
    project, name = _project_and_object(
        kind="agent",
        locator=resolution.locator,
        rendered=resolution.rendered,
        entry=entry,
        payload_object=reference.payload.name,
        prefer_rendered_object=True,
    )
    return _render_expansion(
        _AGENT_EXPANSION_FORMAT,
        {"canonical_argument": name, "project": project},
    )


def _stitch_text(
    resolution: ArtifactRefResolution,
    entry: ArtifactEntry | None,
) -> str:
    repository = None if entry is None else entry.repository
    full_sha = None if entry is None else entry.captured_revision
    if not repository or not full_sha:
        if resolution.locator is None:
            raise RuntimeError("resolver returned no stitch locator")
        repository, full_sha = _split_locator(
            resolution.locator, separator="@", what="stitch", from_right=True
        )
    return _render_expansion(
        _STITCH_EXPANSION_FORMAT,
        {"captured_revision": full_sha, "repository": repository},
    )


def _patch_text(
    reference: ArtifactRef,
    resolution: ArtifactRefResolution,
    entry: ArtifactEntry | None,
) -> str:
    name = None if entry is None else entry.display_label
    project = None if entry is None else entry.project_display_name
    if not name or not project:
        if resolution.locator is None:
            raise RuntimeError("resolver returned no patch locator")
        project, name = _split_locator(resolution.locator, separator="/", what="patch")
    if not name:
        name = reference.payload.name
    if not name or not project:
        raise RuntimeError("resolver returned no patch locator")
    return _render_expansion(
        _PATCH_EXPANSION_FORMAT, {"display_label": name, "project": project}
    )


def _bug_text(
    reference: ArtifactRef,
    resolution: ArtifactRefResolution,
    issue_url_resolver: _IssueUrlResolver,
) -> str:
    if reference.payload.number is None:
        raise RuntimeError("resolver returned no bug number")
    url = _bug_url(reference, resolution, issue_url_resolver)
    if url is None or resolution.locator is None:
        raise RuntimeError("resolver returned no bug locator")
    project, _number = _split_locator(
        resolution.locator, separator="#", what="bug", from_right=True
    )
    return f"issue #{reference.payload.number} in the {project} project ({url})"


def _project_and_object(
    *,
    kind: str,
    locator: str | None,
    rendered: str,
    entry: ArtifactEntry | None,
    payload_object: str | None,
    prefer_rendered_object: bool = False,
) -> tuple[str, str]:
    project = None if entry is None else entry.project_display_name
    object_id = None if entry is None else entry.canonical_argument
    if prefer_rendered_object:
        object_id = _object_from_rendered(kind, rendered) or object_id
    elif not object_id:
        object_id = _object_from_rendered(kind, rendered)
    if (not project or not object_id) and locator is not None:
        loc_project, loc_object = _split_locator(locator, separator="/", what=kind)
        if not project:
            project = loc_project
        if not object_id:
            object_id = loc_object
    if not object_id:
        object_id = payload_object
    if not project or not object_id:
        raise RuntimeError(f"resolver returned no {kind} locator")
    return project, object_id


def _object_from_rendered(kind: str, rendered: str) -> str | None:
    prefix = f"{kind}:"
    if not rendered.startswith(prefix):
        return None
    object_id = rendered[len(prefix) :]
    return object_id or None


def _split_locator(
    locator: str,
    *,
    separator: str,
    what: str,
    from_right: bool = False,
) -> tuple[str, str]:
    if separator not in locator:
        raise RuntimeError(f"malformed {what} locator: {locator!r}")
    left, right = (
        locator.rsplit(separator, 1) if from_right else locator.split(separator, 1)
    )
    if not left or not right:
        raise RuntimeError(f"malformed {what} locator: {locator!r}")
    return left, right


def _render_expansion(expansion_format: str, values: dict[str, str]) -> str:
    placeholders = set(artifact_ref_expansion_validate(expansion_format))
    assert set(values) == placeholders
    return artifact_ref_expansion_render(expansion_format, values)


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

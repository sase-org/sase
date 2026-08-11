"""Golden Python reference for the external PR import classifier."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from sase.core.commit_footer_facade import parse_commit_footer
from sase.core.external_pr_wire import (
    ACTION_ADOPT,
    ACTION_REPAIR_ORIGIN,
    ACTION_SKIP,
    DESTINATION_ACTIVE,
    DESTINATION_ARCHIVE,
    EXTERNAL_PR_WIRE_SCHEMA_VERSION,
    PR_ORIGIN_EXTERNAL,
    PR_ORIGIN_SASE,
    PR_ORIGIN_UNKNOWN,
    REASON_ALREADY_OWNED,
    REASON_AMBIGUOUS_MARKER,
    REASON_MARKER_ORPHAN,
    REASON_MARKER_REPAIR,
    REASON_UNMARKED,
    CanonicalPullRequestUrl,
    ExternalPrImportPlanWire,
    ExternalPrImportRequestWire,
    LocalPatchWire,
)
from sase.status_state_machine.constants import ARCHIVE_STATUSES

_PATCH_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.~-]*$")


def _canonical_pull_request_url_python(
    raw: str,
) -> CanonicalPullRequestUrl | None:
    """Pure Python URL canonicalizer used by classifier parity tests."""
    value = raw.strip()
    if not value:
        return None
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlsplit(value)
    if not parsed.netloc or not parsed.path:
        return None
    host = (parsed.hostname or "").removeprefix("www.").lower()
    if not host:
        return None
    segments = [segment for segment in parsed.path.split("/") if segment]
    if (
        len(segments) == 4
        and segments[2] in {"pull", "pulls"}
        and segments[3].isdigit()
    ):
        owner, repo, number = segments[0], segments[1], int(segments[3])
    elif (
        len(segments) == 5
        and segments[2] == "-"
        and segments[3] == "merge_requests"
        and segments[4].isdigit()
    ):
        owner, repo, number = segments[0], segments[1], int(segments[4])
    else:
        return None
    owner_key = owner.lower()
    repo_key = repo.removesuffix(".git").lower()
    if not owner_key or not repo_key:
        return None
    key = f"{host}/{owner_key}/{repo_key}#{number}"
    return CanonicalPullRequestUrl(
        host=host,
        owner=owner_key,
        repo=repo_key,
        number=number,
        key=key,
    )


def _plan_external_pr_import_python(
    request: ExternalPrImportRequestWire,
) -> ExternalPrImportPlanWire:
    """Pure decision engine mirrored by the Rust classifier."""
    if request.schema_version != EXTERNAL_PR_WIRE_SCHEMA_VERSION:
        raise ValueError(
            "external PR wire schema mismatch: "
            f"got {request.schema_version}, expected {EXTERNAL_PR_WIRE_SCHEMA_VERSION}"
        )

    canonical = _canonical_pull_request_url_python(request.remote.url)
    canonical_key = canonical.key if canonical is not None else None
    canonical_pr_url = request.remote.url.strip() if canonical is not None else None
    footer = parse_commit_footer(request.remote.body)
    marker = next(
        (tag.label.strip() for tag in reversed(footer.tags) if tag.key == "PATCH"),
        None,
    )
    status, destination = _mapped_status_and_destination(
        request.remote.state,
        request.remote.is_draft,
        request.remote.merged_at,
    )
    description = _description_without_footer(request.remote.title, footer.body)

    if canonical_key is not None:
        owned = next(
            (
                patch
                for patch in request.local_patches
                if _patch_pr_key(patch) == canonical_key
            ),
            None,
        )
        if owned is not None:
            marker_names_owned = marker == owned.name
            if not (
                marker_names_owned and (owned.reserved or not owned.pr_url.strip())
            ):
                return ExternalPrImportPlanWire(
                    action=ACTION_SKIP,
                    reason=REASON_ALREADY_OWNED,
                    patch_name=owned.name,
                    name_base=None,
                    pr_origin=owned.pr_origin,
                    status=status,
                    destination=destination,
                    description=description,
                    canonical_pr_url=canonical_pr_url,
                )

    if marker is not None:
        if _is_valid_patch_name(marker):
            if any(patch.name == marker for patch in request.local_patches):
                return ExternalPrImportPlanWire(
                    action=ACTION_REPAIR_ORIGIN,
                    reason=REASON_MARKER_REPAIR,
                    patch_name=marker,
                    name_base=None,
                    pr_origin=PR_ORIGIN_SASE,
                    status=status,
                    destination=destination,
                    description=description,
                    canonical_pr_url=canonical_pr_url,
                )
            return ExternalPrImportPlanWire(
                action=ACTION_ADOPT,
                reason=REASON_MARKER_ORPHAN,
                patch_name=marker,
                name_base=None,
                pr_origin=PR_ORIGIN_SASE,
                status=status,
                destination=destination,
                description=description,
                canonical_pr_url=canonical_pr_url,
            )
        return ExternalPrImportPlanWire(
            action=ACTION_ADOPT,
            reason=REASON_AMBIGUOUS_MARKER,
            patch_name=None,
            name_base=_name_base(request),
            pr_origin=PR_ORIGIN_UNKNOWN,
            status=status,
            destination=destination,
            description=description,
            canonical_pr_url=canonical_pr_url,
        )

    return ExternalPrImportPlanWire(
        action=ACTION_ADOPT,
        reason=REASON_UNMARKED,
        patch_name=None,
        name_base=_name_base(request),
        pr_origin=PR_ORIGIN_EXTERNAL,
        status=status,
        destination=destination,
        description=description,
        canonical_pr_url=canonical_pr_url,
    )


def _patch_pr_key(patch: LocalPatchWire) -> str | None:
    canonical = _canonical_pull_request_url_python(patch.pr_url)
    return canonical.key if canonical is not None else None


def _mapped_status_and_destination(
    state: str,
    is_draft: bool,
    merged_at: str,
) -> tuple[str, str]:
    if merged_at.strip():
        status = "Submitted"
    elif state == "open" and is_draft:
        status = "Draft"
    elif state == "open":
        status = "Mailed"
    else:
        status = "Archived"
    destination = (
        DESTINATION_ARCHIVE if status in ARCHIVE_STATUSES else DESTINATION_ACTIVE
    )
    return status, destination


def _description_without_footer(title: str, body_without_footer: str) -> str:
    title = title.strip()
    body = body_without_footer.strip()
    if title and body:
        return f"{title}\n\n{body}"
    return title or body


def _is_valid_patch_name(value: str) -> bool:
    return bool(value.strip() and _PATCH_NAME_RE.match(value.strip()))


def _name_base(request: ExternalPrImportRequestWire) -> str:
    for value in (request.remote.title, request.remote.head_ref):
        slug = _slug_name_base(value)
        if slug:
            return slug
    return f"pr-{request.remote.number}"


def _slug_name_base(value: str) -> str:
    result = re.sub(r"[^0-9A-Za-z]+", "_", value.lower())
    result = re.sub(r"_+", "_", result).strip("_")
    return result[:48].strip("_")


__all__ = [
    "_canonical_pull_request_url_python",
    "_plan_external_pr_import_python",
]

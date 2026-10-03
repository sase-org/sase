"""History document builder for the memory history pager.

Split from :mod:`sase.memory.history.pager_provider`; the facade
re-exports these public names so the original import path keeps working.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from sase.artifact_ref_target_models import ArtifactRefDocumentOwner
from sase.memory.history._pager_provider_common import (
    wire_history_path,
    wire_subject_id,
)
from sase.memory.history.scopes import HistoryScopeError
from sase.memory.history.service import HistoryService
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.history.models import VersionPin, committed_pin_for_ordinal
from sase.pager.syntax_policy import classify_source


def build_history_document(
    *,
    scope: Any,
    subject: str,
    initial_revision: str | None = None,
    view: str = "read",
    compare_base: str | None = None,
    explicit_base: bool = False,
    service: HistoryService | None = None,
    title: str | None = None,
) -> PagerDocument:
    """Build a selector-based pager document for later panel/feed phases.

    *explicit_base* marks a base the Timeline lens set: only then may
    a ``now`` target compare against a committed base instead of the
    default endpoints (mirrors ``VersionPin.explicit_base``).
    """
    active = service or HistoryService()
    selector = subject
    revision = initial_revision or "now"
    try:
        response = active.version(scope, selector, revision, include_body=True)
    except Exception as exc:
        raise HistoryScopeError(f"cannot build history document: {exc}") from exc
    if not response.get("existed", True):
        raise HistoryScopeError(f"history subject {selector!r} does not exist")
    body = str(response.get("body", "") or "")
    if response.get("body_missing"):
        body = f"(unavailable: historical body for {selector} is not stored)"
    version = response.get("version", {})
    ordinal = int(version.get("ordinal", 0) or 0) if isinstance(version, dict) else 0
    # Stamp the resolved repo-relative path so the memory provider owns
    # the section whatever the selector's spelling (bare ``decisions`` or
    # ``glossary:stitch`` never name the memory root themselves).
    resolved_path = wire_history_path(response, selector)
    subject_id = wire_subject_id(response, selector)
    owner: ArtifactRefDocumentOwner | None = None
    try:
        repo_root = Path(str(getattr(scope, "repo_root", ".")))
        owner = ArtifactRefDocumentOwner(
            source_reference=resolved_path,
            source_directory=str(repo_root),
            checkout_candidates=(repo_root,),
            revision=version.get("commit")
            if isinstance(version, dict) and isinstance(version.get("commit"), str)
            else None,
        )
    except Exception:
        owner = None
    from sase.pager.history.models import live_pin_for_subject

    requested_view = view if view in ("read", "diff") else "read"
    base_ordinal: int | None = None
    if isinstance(compare_base, str) and compare_base.strip():
        cleaned = compare_base.strip().removeprefix("v")
        if cleaned.isdigit():
            base_ordinal = int(cleaned)
    if ordinal == 0:
        pin: VersionPin = live_pin_for_subject(subject_id)
        if requested_view == "diff":
            pin = replace(pin, view="diff")
        if explicit_base and base_ordinal is not None and base_ordinal > 0:
            pin = replace(pin, compare_base=base_ordinal, explicit_base=True)
    else:
        pin = committed_pin_for_ordinal(
            subject_id,
            ordinal,
            commit=version.get("commit") if isinstance(version, dict) else None,
            blob_oid=version.get("blob_oid") if isinstance(version, dict) else None,
            view=requested_view,  # type: ignore[arg-type]
            compare_base=base_ordinal,
        )
    section = PagerSection(
        identity=f"history:{subject}:{revision}",
        title=title or subject.rsplit("/", 1)[-1],
        kind="file",
        body=body,
        subject_ref=resolved_path,
        raw_source=classify_source(
            category="raw_file", logical_filename="note.md", source=body
        ),
        origin=PagerOrigin.FILE,
        owner=owner,
        version_pin=pin,  # type: ignore[call-arg]
    )
    return PagerDocument(
        sections=(section,),
        title=title or subject,
        origin=PagerOrigin.FILE,
    )


def selector_to_core_selector(raw: str, repo_root: Path) -> str:
    """Share selector conversion with the CLI instead of duplicating parsing."""
    from sase.memory.history.cli_history import translate_history_selector

    return translate_history_selector(raw, repo_root)


__all__ = ["build_history_document", "selector_to_core_selector"]

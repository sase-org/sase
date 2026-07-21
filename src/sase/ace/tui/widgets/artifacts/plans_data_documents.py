"""Resolution and loading of plan documents linked from beads."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sase.plan_documents import PlanWorkspace, resolve_plan_path

from .plans_data_models import LinkedPlanDocument, PlansSnapshot
from .plans_data_sources import yaml_value_to_string


@dataclass(frozen=True)
class LinkedPlanPayload:
    """Path-keyed payload reused when multiple beads link one document."""

    content: str
    frontmatter: dict[str, str]
    body: str
    error: str | None
    signature: tuple[int, int, int, int] | None


def load_linked_plan_document(
    reference: str,
    *,
    workspace_dir: str | None,
    plans_root: Path,
    read_cache: dict[Path, LinkedPlanPayload],
    read_text: Callable[[Path], str],
) -> LinkedPlanDocument:
    """Resolve, read, and prepare one linked plan without raising."""
    path = _resolve_linked_plan_path(
        reference,
        workspace_dir=workspace_dir,
        plans_root=plans_root,
    )
    if path is None:
        return LinkedPlanDocument(
            reference=reference,
            path="",
            content="",
            frontmatter={},
            body="",
            error="Linked plan unavailable: invalid reference.",
            signature=None,
        )

    payload = read_cache.get(path)
    if payload is None:
        payload = _read_linked_plan_payload(path, read_text=read_text)
        read_cache[path] = payload
    return LinkedPlanDocument(
        reference=reference,
        path=str(path),
        content=payload.content,
        frontmatter=payload.frontmatter,
        body=payload.body,
        error=payload.error,
        signature=payload.signature,
    )


def _resolve_linked_plan_path(
    reference: str,
    *,
    workspace_dir: str | None,
    plans_root: Path,
) -> Path | None:
    """Resolve every stable reference form emitted by plan approval."""
    resolved = resolve_plan_path(
        reference,
        workspaces=(
            PlanWorkspace(
                workspace_dir=workspace_dir or "",
                plans_root=str(plans_root),
            ),
        ),
    )
    if resolved.status == "invalid_reference" or resolved.path is None:
        return None
    return Path(resolved.path)


def _read_linked_plan_payload(
    path: Path,
    *,
    read_text: Callable[[Path], str],
) -> LinkedPlanPayload:
    """Read and parse a linked plan into display-ready worker data."""
    signature = _linked_plan_signature(path)
    if signature is None:
        return _unavailable_linked_plan_payload(
            "Linked plan unavailable: file not found."
        )
    try:
        content = read_text(path)
    except (OSError, UnicodeError, ValueError):
        return _unavailable_linked_plan_payload(
            "Linked plan unavailable: file could not be read.",
            signature=signature,
        )

    from sase.sdd.frontmatter import parse_frontmatter

    try:
        frontmatter, body, had_frontmatter = parse_frontmatter(content)
        display_frontmatter = {
            key: yaml_value_to_string(value)
            for key, value in frontmatter.items()
            if isinstance(key, str)
        }
    except Exception:
        return _unavailable_linked_plan_payload(
            "Linked plan unavailable: malformed document.",
            signature=signature,
        )
    if content.startswith("---\n") and not had_frontmatter:
        return _unavailable_linked_plan_payload(
            "Linked plan unavailable: malformed document.",
            signature=signature,
        )
    return LinkedPlanPayload(
        content=content,
        frontmatter=display_frontmatter,
        body=body,
        error=None,
        signature=signature,
    )


def read_linked_plan_text(path: Path) -> str:
    """Read a linked plan; kept separate so deduplication is testable."""
    return path.read_text(encoding="utf-8")


def _unavailable_linked_plan_payload(
    message: str,
    *,
    signature: tuple[int, int, int, int] | None = None,
) -> LinkedPlanPayload:
    return LinkedPlanPayload("", {}, "", message, signature)


def _linked_plan_signature(path: Path) -> tuple[int, int, int, int] | None:
    try:
        stat = path.stat()
    except (OSError, ValueError):
        return None
    return (stat.st_mtime_ns, stat.st_size, stat.st_mode, stat.st_ctime_ns)


def current_linked_plan_key(
    previous: PlansSnapshot | None,
) -> tuple[tuple[object, ...], ...]:
    if previous is None:
        return ()
    return tuple(
        (
            project,
            issue_id,
            document.reference,
            document.path,
            (
                None
                if not document.path
                else _linked_plan_signature(Path(document.path))
            ),
        )
        for (project, issue_id), document in sorted(
            previous.linked_plan_documents.items()
        )
    )


def loaded_linked_plan_key(
    documents: dict[tuple[str, str], LinkedPlanDocument],
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            project,
            issue_id,
            document.reference,
            document.path,
            document.signature,
        )
        for (project, issue_id), document in sorted(documents.items())
    )

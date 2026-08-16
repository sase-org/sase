"""Best-effort bead-lineage publication after a primary commit."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _BeadPagePublicationOutcome:
    """Result of projecting one committed bead's lineage into its sidecar."""

    changed: bool = False
    committed: bool = False
    queued: bool = False
    skip_reason: str | None = None
    error: str | None = None


def publish_committed_bead_pages(
    commit_message: str,
    *,
    primary_root: Path | str,
    project: str | None = None,
    mutation_origin: str = "user",
    operation_context: Any | None = None,
) -> _BeadPagePublicationOutcome:
    """Publish the lineage named by ``SASE_BEAD`` without ever raising."""

    try:
        from sase.sdd.checkout_anchor import resolve_checkout_anchor

        anchor = resolve_checkout_anchor(primary_root)
        bead_id = _committed_bead_id(commit_message)
        if not bead_id:
            return _BeadPagePublicationOutcome(
                skip_reason="commit has no SASE_BEAD tag"
            )
        return _publish_bead_lineage(
            bead_id,
            primary_root=anchor.primary_root,
            project=project or anchor.project_name,
            mutation_origin=mutation_origin,
            operation_context=operation_context,
        )
    except Exception as exc:  # noqa: BLE001 - auxiliary post-commit boundary.
        return _error_outcome(exc)


def _publish_bead_lineage(
    bead_id: str,
    *,
    primary_root: Path,
    project: str | None,
    mutation_origin: str = "user",
    operation_context: Any | None = None,
) -> _BeadPagePublicationOutcome:

    from sase.sdd.plan_refs import workspace_context_for_plan_resolution
    from sase.sdd.store import resolve_sdd_store

    workspace_dir, workspace_num = workspace_context_for_plan_resolution(primary_root)
    store = resolve_sdd_store(workspace_dir, workspace_num)
    if not store.is_sidecar_storage or store.beads_dir is None:
        return _BeadPagePublicationOutcome(
            skip_reason="project has no recorded beads sidecar"
        )

    from sase.sdd._git_contention import store_git_write_lock

    beads_repo = store.repo_root_for_kind("beads")
    with store_git_write_lock(
        beads_repo,
        op="sdd.bead_pages.post_commit",
        mutates_worktree=True,
    ) as acquired:
        if not acquired:
            return _error_outcome("beads store write lock is busy")

        from sase.bead.store_locator import open_bead_project_for_beads_dir
        from sase.bead_pages.associations import build_bead_association_index
        from sase.bead_pages.paths import bead_lineage_root, bead_page_path
        from sase.bead_pages.rendering import render_bead_page_bytes
        from sase.sdd.hosted_links import hosted_link_resolver

        root_id = bead_lineage_root(bead_id)
        changed_paths: list[Path] = []
        page_error: str | None = None
        try:
            with open_bead_project_for_beads_dir(store.kind_root("beads")) as view:
                issues = tuple(view.list_issues())
                known_ids = frozenset(issue.id for issue in issues)
                if bead_id not in known_ids:
                    return _BeadPagePublicationOutcome(
                        skip_reason=f"bead does not exist in store: {bead_id}"
                    )
                lineage = tuple(
                    sorted(
                        (
                            issue
                            for issue in issues
                            if bead_lineage_root(issue.id) == root_id
                        ),
                        key=lambda issue: issue.id,
                    )
                )
                resolver = hosted_link_resolver(
                    store,
                    project=project,
                    primary_root=primary_root,
                )
                association_index = build_bead_association_index(
                    store,
                    primary_root=primary_root,
                    project=project,
                    link_resolver=resolver,
                    bead_issues=issues,
                )
                payloads = tuple(
                    (
                        beads_repo / bead_page_path(issue.id),
                        render_bead_page_bytes(
                            view,
                            issue,
                            association_index,
                            link_resolver=resolver,
                        ),
                    )
                    for issue in lineage
                )
            changed_paths = _write_changed_pages(payloads)
        except Exception as exc:  # noqa: BLE001 - pages remain best-effort.
            page_error = str(exc) or type(exc).__name__
            _logger.warning("Could not publish committed bead pages: %s", page_error)

        # The store may already contain a bead mutation from this agent turn.
        # Commit the whole beads root after rendering so state and pages land in
        # one atomic sidecar commit under the lock held above.
        from sase.sdd.files import commit_sdd_store_files

        try:
            commit_kwargs: dict[str, Any] = {}
            if mutation_origin != "user":
                commit_kwargs["mutation_origin"] = mutation_origin
            if operation_context is not None:
                commit_kwargs["operation_context"] = operation_context
            committed = commit_sdd_store_files(
                store,
                f"chore(beads): sync bead state and pages for {root_id}",
                paths=[store.kind_root("beads")],
                auto_commit_type="beads",
                push_after_commit="async",
                already_locked=True,
                **commit_kwargs,
            )
        except Exception as exc:  # noqa: BLE001 - preserve changed projection.
            return _error_outcome(exc, changed=bool(changed_paths))
        return _BeadPagePublicationOutcome(
            changed=bool(changed_paths),
            committed=committed,
            error=page_error,
        )


def _committed_bead_id(commit_message: str) -> str | None:
    from sase.core.commit_footer_facade import parse_commit_footer

    footer = parse_commit_footer(commit_message)
    return next(
        (tag.label.strip() for tag in footer.tags if tag.key == "BEAD"),
        None,
    )


def _write_changed_pages(
    payloads: tuple[tuple[Path, bytes], ...],
) -> list[Path]:
    changed: list[Path] = []
    for path, payload in payloads:
        if path.is_file() and path.read_bytes() == payload:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        changed.append(path)
    return changed


def _error_outcome(
    error: BaseException | str,
    *,
    changed: bool = False,
) -> _BeadPagePublicationOutcome:
    message = str(error) or type(error).__name__
    _logger.warning("Could not publish committed bead pages: %s", message)
    return _BeadPagePublicationOutcome(changed=changed, error=message)


__all__ = [
    "publish_committed_bead_pages",
]

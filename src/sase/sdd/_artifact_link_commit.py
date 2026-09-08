"""Path-scoped commits for durable artifact-link sidecar indexes."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING, Literal

from sase.sdd._artifact_link_files import (
    is_canonical_artifact_link_index,
    is_canonical_artifact_link_index_location,
)
from sase.sdd._artifact_link_ignore import ensure_artifact_link_lock_gitignore
from sase.sdd._store_types import document_sidecar_roles

if TYPE_CHECKING:
    from sase.sdd._artifact_link_store_impl import ArtifactLinkStore
    from sase.sdd.store import SddStore


ARTIFACT_LINK_COMMIT_MESSAGE = "chore(artifact-links): persist link indexes"
ARTIFACT_LINK_COMMIT_TYPE = "sdd"
ARTIFACT_LINK_FILE_HOOK_CAUSE = "artifact_links"
BEAD_LINK_COMMIT_MESSAGE = "chore(beads): update artifact links"


class ArtifactLinkPersistError(RuntimeError):
    """Raised when a scoped artifact-link commit or publication fails.

    The JSON/event mutation is left on disk so a finalizer or operator can
    retry. ``diagnostic`` is the operator-facing report.
    """

    def __init__(self, message: str, *, diagnostic: str | None = None) -> None:
        super().__init__(message)
        self.diagnostic = diagnostic or message


@dataclass(frozen=True)
class _ArtifactLinkCommitResult:
    """Outcome of :func:`commit_artifact_link_indexes`."""

    committed: bool
    repo_roots: tuple[Path, ...] = ()
    publication_error: str | None = None

    def __bool__(self) -> bool:
        return self.committed


@dataclass(frozen=True)
class _ArtifactLinkPublicationContext:
    """Identity for recording retry state for one document sidecar root."""

    project_key: str
    role: str
    remote_url: str


def commit_artifact_link_indexes(
    index_paths: Iterable[Path],
    *,
    store: SddStore | None = None,
    project_key: str | None = None,
    repo_roots: Sequence[Path] = (),
    artifacts_dir: str | Path | None = None,
    already_locked: bool = False,
    mutation_origin: str = "user",
    push_after_commit: bool | Literal["async"] | None = None,
    verify_publication: bool = False,
    extra_paths_by_root: dict[Path, list[Path]] | None = None,
    message: str = ARTIFACT_LINK_COMMIT_MESSAGE,
) -> _ArtifactLinkCommitResult:
    """Commit eligible link indexes, at most once per owning sidecar.

    Invalid indexes are skipped. Lock sentinels are never staged. A missing
    lock-ignore rule is installed and included in the same commit.
    """

    grouped = _group_valid_indexes(index_paths, store=store, repo_roots=repo_roots)
    if extra_paths_by_root:
        for root, extra in extra_paths_by_root.items():
            resolved = root.expanduser().resolve(strict=False)
            grouped[resolved].extend(extra)
    if not grouped:
        return _ArtifactLinkCommitResult(committed=False)

    commit_paths: list[Path] = []
    committed_roots: list[Path] = []
    for root, indexes in grouped.items():
        gitignore = ensure_artifact_link_lock_gitignore(root)
        unique_indexes = list(dict.fromkeys(indexes))
        if gitignore is not None:
            unique_indexes.append(gitignore)
        if not unique_indexes:
            continue
        commit_paths.extend(unique_indexes)
        committed_roots.append(root)

    if not commit_paths:
        return _ArtifactLinkCommitResult(committed=False)

    committed = _commit_paths(
        commit_paths,
        store=store,
        repo_roots=tuple(grouped),
        artifacts_dir=artifacts_dir,
        already_locked=already_locked,
        mutation_origin=mutation_origin,
        push_after_commit=push_after_commit,
        message=message,
    )
    publication_error = None
    if committed and verify_publication:
        contexts = _publication_contexts_for_roots(store, project_key=project_key)
        publication_error = _publication_error_for_roots(
            committed_roots,
            contexts=contexts,
            register_retry=mutation_origin == "machine",
        )
    return _ArtifactLinkCommitResult(
        committed=committed,
        repo_roots=tuple(committed_roots),
        publication_error=publication_error,
    )


def persist_artifact_link_graph_mutation(
    link_store: ArtifactLinkStore,
    *,
    changed_indexes: Sequence[Path],
    beads_changed: bool,
    artifacts_dir: str | Path | None = None,
    mutation_origin: str = "user",
) -> None:
    """Commit and publish one explicit link add/rm, or raise on failure.

    Interactive CLI callers leave ``mutation_origin`` at ``"user"``. Background
    jobs pass ``"machine"`` so the ownership contract cannot be bypassed.
    """

    if changed_indexes:
        result = commit_artifact_link_indexes(
            changed_indexes,
            store=link_store.sdd_store,
            project_key=link_store.project_key,
            repo_roots=tuple(link_store.sidecar_roots.values()),
            artifacts_dir=artifacts_dir,
            verify_publication=True,
            mutation_origin=mutation_origin,
        )
        if result.publication_error:
            raise ArtifactLinkPersistError(
                result.publication_error,
                diagnostic=result.publication_error,
            )
    if beads_changed:
        _commit_bead_link_events(
            link_store,
            artifacts_dir=artifacts_dir,
            mutation_origin=mutation_origin,
        )


def _ensure_artifact_link_commit_published(
    repo_root: Path,
    *,
    description: str | None = None,
    publication_context: _ArtifactLinkPublicationContext | None = None,
    register_retry: bool = False,
) -> str | None:
    """Publish a finalizer-created sidecar commit or return a diagnostic."""

    return _unpublished_sidecar_error(
        repo_root,
        description=description,
        publication_context=publication_context,
        register_retry=register_retry,
    )


def _group_valid_indexes(
    index_paths: Iterable[Path],
    *,
    store: SddStore | None,
    repo_roots: Sequence[Path],
) -> dict[Path, list[Path]]:
    roots = _candidate_repo_roots(store=store, repo_roots=repo_roots)
    grouped: dict[Path, list[Path]] = defaultdict(list)
    for raw in index_paths:
        path = Path(raw)
        owner = _owning_root(path, roots)
        if owner is None:
            continue
        if path.exists():
            valid = is_canonical_artifact_link_index(path, owner)
        else:
            valid = is_canonical_artifact_link_index_location(path, owner)
        if not valid:
            continue
        grouped[owner].append(path.expanduser().resolve(strict=False))
    return grouped


def _candidate_repo_roots(
    *, store: SddStore | None, repo_roots: Sequence[Path]
) -> tuple[Path, ...]:
    roots: list[Path] = []
    if store is not None:
        if store.is_sidecar_storage:
            roles = document_sidecar_roles(
                store.split_sidecar_roles(), include_plans=True
            )
            for role in roles:
                try:
                    root = store.repo_root_for_kind(role)
                    roots.append(root.expanduser().resolve(strict=False))
                except (OSError, ValueError, RuntimeError):
                    continue
        else:
            roots.append(store.repo_root.expanduser().resolve(strict=False))
    for raw in repo_roots:
        resolved = Path(raw).expanduser().resolve(strict=False)
        if resolved not in roots:
            roots.append(resolved)
    return tuple(roots)


def _owning_root(path: Path, roots: Sequence[Path]) -> Path | None:
    try:
        resolved = path.expanduser().resolve(strict=False)
    except OSError:
        return None
    for root in roots:
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        return root
    return None


def _commit_paths(
    paths: Sequence[Path],
    *,
    store: SddStore | None,
    repo_roots: Sequence[Path],
    artifacts_dir: str | Path | None,
    already_locked: bool,
    mutation_origin: str,
    push_after_commit: bool | Literal["async"] | None,
    message: str,
) -> bool:
    from sase.sdd.files import commit_sdd_files, commit_sdd_store_files

    if store is not None:
        result = commit_sdd_store_files(
            store,
            message,
            auto_commit_type=ARTIFACT_LINK_COMMIT_TYPE,
            paths=paths,
            artifacts_dir=artifacts_dir,
            already_locked=already_locked,
            cause=ARTIFACT_LINK_FILE_HOOK_CAUSE,
            mutation_origin=mutation_origin,
            push_after_commit=push_after_commit,
        )
        return bool(result)

    committed_any = False
    for root in repo_roots:
        owned = [path for path in paths if _owning_root(path, (root,)) is root]
        if not owned:
            continue
        committed_any = (
            commit_sdd_files(
                root,
                message,
                auto_commit_type=ARTIFACT_LINK_COMMIT_TYPE,
                paths=owned,
                artifacts_dir=artifacts_dir,
                already_locked=already_locked,
                cause=ARTIFACT_LINK_FILE_HOOK_CAUSE,
                mutation_origin=mutation_origin,
            )
            or committed_any
        )
    return committed_any


def _commit_bead_link_events(
    link_store: ArtifactLinkStore,
    *,
    artifacts_dir: str | Path | None,
    mutation_origin: str = "user",
) -> None:
    beads_dir = link_store.beads_dir
    if beads_dir is None:
        return
    from sase.bead.cli_common import (
        BeadPublicationError,
        ensure_bead_mutation_published,
    )
    from sase.sdd.files import commit_sdd_files, commit_sdd_store_files

    committed = False
    if link_store.sdd_store is not None:
        committed = bool(
            commit_sdd_store_files(
                link_store.sdd_store,
                BEAD_LINK_COMMIT_MESSAGE,
                auto_commit_type="beads",
                paths=[beads_dir],
                artifacts_dir=artifacts_dir,
                mutation_origin=mutation_origin,
            )
        )
    else:
        repo = beads_dir if (beads_dir / ".git").is_dir() else beads_dir.parent
        committed = commit_sdd_files(
            repo,
            BEAD_LINK_COMMIT_MESSAGE,
            auto_commit_type="beads",
            paths=[beads_dir],
            artifacts_dir=artifacts_dir,
            mutation_origin=mutation_origin,
        )
    if not committed:
        return
    try:
        ensure_bead_mutation_published(beads_dir, description=BEAD_LINK_COMMIT_MESSAGE)
    except BeadPublicationError as exc:
        raise ArtifactLinkPersistError(str(exc), diagnostic=exc.diagnostic) from exc


def _publication_error_for_roots(
    repo_roots: Sequence[Path],
    *,
    contexts: Mapping[Path, _ArtifactLinkPublicationContext] | None = None,
    register_retry: bool = False,
) -> str | None:
    errors: list[str] = []
    for root in repo_roots:
        error = _ensure_artifact_link_commit_published(
            root,
            description=ARTIFACT_LINK_COMMIT_MESSAGE,
            publication_context=(contexts or {}).get(
                root.expanduser().resolve(strict=False)
            ),
            register_retry=register_retry,
        )
        if error:
            errors.append(error)
    if not errors:
        return None
    return "\n".join(errors)


def _unpublished_sidecar_error(
    repo_root: Path,
    *,
    description: str | None,
    publication_context: _ArtifactLinkPublicationContext | None = None,
    register_retry: bool = False,
) -> str | None:
    from sase.bead._sync_publication import head_is_published
    from sase.bead.sync import (
        MUTATION_PUBLICATION_WORKER_LOCK_WAIT_SECONDS,
        push_bead_work_launch,
    )

    if not _has_tracking_upstream(repo_root):
        return None
    if head_is_published(repo_root):
        return None
    outcome = None
    try:
        outcome = push_bead_work_launch(
            repo_root,
            worker_lock_wait=MUTATION_PUBLICATION_WORKER_LOCK_WAIT_SECONDS,
        )
    except Exception:
        pass
    if head_is_published(repo_root):
        return None
    subject = description or "artifact-link mutation"
    unpushed = _unpushed_commit_count(repo_root)
    retry_note = _record_publication_retry_note(
        repo_root,
        publication_context=publication_context,
        outcome=outcome,
        enabled=register_retry,
    )
    return (
        f"ERROR: {subject} was committed locally but NOT published.\n"
        f"  unpublished artifact-link commit(s): {unpushed}\n"
        f"  sidecar repository: {repo_root}\n"
        "  This mutation is durable on this machine but invisible to other "
        "machines until published.\n"
        f"  Remediation: git -C {repo_root} push"
        f"{retry_note}"
    )


def _publication_contexts_for_roots(
    store: SddStore | None, *, project_key: str | None
) -> dict[Path, _ArtifactLinkPublicationContext]:
    if store is None or project_key is None or not store.is_sidecar_storage:
        return {}
    contexts: dict[Path, _ArtifactLinkPublicationContext] = {}
    roles = document_sidecar_roles(store.split_sidecar_roles(), include_plans=True)
    for role in roles:
        remote_url = store.remote_url_for_kind(role)
        if remote_url is None:
            continue
        try:
            root = store.repo_root_for_kind(role).expanduser().resolve(strict=False)
        except (OSError, ValueError, RuntimeError):
            continue
        contexts[root] = _ArtifactLinkPublicationContext(
            project_key=project_key,
            role=role,
            remote_url=remote_url,
        )
    return contexts


def _record_publication_retry_note(
    repo_root: Path,
    *,
    publication_context: _ArtifactLinkPublicationContext | None,
    outcome: object,
    enabled: bool,
) -> str:
    if not enabled or publication_context is None:
        return ""
    from sase.sdd._artifact_link_publication_retry import (
        register_artifact_link_publication_failure,
    )

    log_path = getattr(outcome, "log_path", None)
    skipped_locked = bool(getattr(outcome, "skipped_locked", False))
    error = getattr(outcome, "error", None)
    if skipped_locked:
        attempt_status = "deferred"
        message = "managed sync worker already holds the publication lock"
    else:
        attempt_status = "failed"
        message = str(error or "publication worker did not publish HEAD")
    registration = register_artifact_link_publication_failure(
        project_key=publication_context.project_key,
        role=publication_context.role,
        repo_root=repo_root,
        remote_url=publication_context.remote_url,
        error=message,
        log_path=log_path,
        attempt_status=attempt_status,
    )
    if registration.recorded:
        return (
            "\n  Scheduled artifact_link_backfill will retry publication from "
            "durable host state."
        )
    if registration.diagnostic:
        return f"\n  Retry state: {registration.diagnostic}"
    return ""


def _has_tracking_upstream(repo_root: Path) -> bool:
    result = subprocess.run(
        [
            "git",
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{upstream}",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def _unpushed_commit_count(repo_root: Path) -> int:
    result = subprocess.run(
        ["git", "rev-list", "--count", "@{upstream}..HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return 0
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


__all__ = [
    "ARTIFACT_LINK_COMMIT_MESSAGE",
    "ARTIFACT_LINK_COMMIT_TYPE",
    "ARTIFACT_LINK_FILE_HOOK_CAUSE",
    "BEAD_LINK_COMMIT_MESSAGE",
    "ArtifactLinkPersistError",
    "commit_artifact_link_indexes",
    "persist_artifact_link_graph_mutation",
]

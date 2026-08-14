"""Publish canonical prompt documents and their captured bytes."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path

from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.prompt_archive.git_ops import (
    clean_prompt_archive_worktree as _clean_prompt_archive_worktree,
    commit_prompt_archive_if_dirty as _commit_prompt_archive_if_dirty,
)
from sase.agents_sync.prompt_archive.preparation import (
    PreparedPromptArchive,
    hosted_resolver as _hosted_resolver,
    prepare_prompt_archive as _prepare_prompt_archive,
    repository_roots as _repository_roots,
)
from sase.agents_sync.publication_outbox import (
    AgentPublicationOutboxItem,
    enqueue_agent_publication,
)
from sase.agents_sync.referenced_by_outbox import enqueue_referenced_by_request
from sase.agents_sync.targets import resolve_sync_targets
from sase.config import require_agent_owner_identity
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    agent_local_hood,
    globalize_owned_agent_name,
    normalize_agent_archive_name,
    normalize_owned_agent_name,
)
from sase.sase_agent import sase_agent_ref_for_shell


log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PromptArchivePublicationOutcome:
    """Best-effort result for one archive publication attempt."""

    published: bool = False
    queued: bool = False
    prompt_path: Path | None = None
    skip_reason: str | None = None
    error: str | None = None


def publish_prompt_archive(
    agent_name: str,
    primary_revision: str,
    *,
    project: str | None = None,
    commit_cwd: Path | str,
    agent_artifacts_dir: Path | str | None = None,
    prompt_content: str | None = None,
    plan_ref: str | None = None,
    prompt_name: str | None = None,
    yyyymm: str | None = None,
    git_runner: GitRunner = run_git,
    lock_timeout_seconds: float | None = None,
) -> PromptArchivePublicationOutcome:
    """Publish one run's prompt without crossing the primary commit boundary."""

    try:
        return _publish_prompt_archive(
            agent_name,
            primary_revision,
            project=project,
            commit_cwd=Path(commit_cwd).resolve(strict=False),
            agent_artifacts_dir=agent_artifacts_dir,
            prompt_content=prompt_content,
            plan_ref=plan_ref,
            prompt_name=prompt_name,
            yyyymm=yyyymm,
            git_runner=git_runner,
            lock_timeout_seconds=lock_timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - auxiliary publication boundary.
        return PromptArchivePublicationOutcome(error=str(exc) or type(exc).__name__)


def _publish_prompt_archive(
    agent_name: str,
    primary_revision: str,
    *,
    project: str | None,
    commit_cwd: Path,
    agent_artifacts_dir: Path | str | None,
    prompt_content: str | None,
    plan_ref: str | None,
    prompt_name: str | None,
    yyyymm: str | None,
    git_runner: GitRunner,
    lock_timeout_seconds: float | None,
) -> PromptArchivePublicationOutcome:
    from sase.agents_sync.commit_publication import resolve_publication_project_key

    selector = project or resolve_publication_project_key(
        commit_cwd,
        git_runner=git_runner,
    )
    if not selector:
        return PromptArchivePublicationOutcome(
            skip_reason="repository does not map to a SASE project"
        )
    selection = resolve_sync_targets((selector,))
    if len(selection.targets) != 1:
        outcome = selection.outcomes[0] if selection.outcomes else None
        detail = (
            (outcome.skip_reason or outcome.error) if outcome is not None else None
        ) or "agents target is unavailable"
        return PromptArchivePublicationOutcome(skip_reason=detail)
    target = selection.targets[0]

    artifacts_dir = _agent_artifacts_dir(agent_artifacts_dir)
    if artifacts_dir is None or not (artifacts_dir / "raw_xprompt.md").is_file():
        return PromptArchivePublicationOutcome(
            skip_reason="agent raw_xprompt.md is unavailable"
        )

    owner = require_agent_owner_identity()
    identity = AgentIdentitySnapshot(owner)
    local_agent = normalize_agent_archive_name(
        normalize_owned_agent_name(agent_name, identity)
    )
    global_agent = globalize_owned_agent_name(local_agent, identity)
    agent_ref = sase_agent_ref_for_shell(local_agent, identity)
    enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key=target.project_key,
            project=target.project,
            local_agent=agent_ref.local_name,
            global_agent=agent_ref.global_name,
            primary_revision=primary_revision,
            local_hood=agent_local_hood(agent_ref.local_name),
        )
    )

    from sase.agents_sync import git_sync

    timeout = (
        git_sync.configured_agents_lock_timeout()
        if lock_timeout_seconds is None
        else max(lock_timeout_seconds, 0.0)
    )
    clone_error = git_sync.ensure_agents_clone(
        target,
        git_runner=git_runner,
        lock_timeout_seconds=timeout,
    )
    if clone_error is not None:
        return PromptArchivePublicationOutcome(queued=True, error=clone_error)
    lock_path = (
        git_sync.agents_git_dir(target.sidecar_path, git_runner)
        / "sase-agents-sync.lock"
    )
    prompt_outcome: PromptArchivePublicationOutcome | None = None
    with git_sync.bounded_agents_lock(lock_path, timeout) as acquired:
        if not acquired:
            return PromptArchivePublicationOutcome(
                queued=True,
                error="agents sync lock is busy",
            )
        cleanup_error = _clean_prompt_archive_worktree(target.sidecar_path, git_runner)
        if cleanup_error is not None:
            return PromptArchivePublicationOutcome(queued=True, error=cleanup_error)
        pulled = git_sync.pull_agents_rebase(
            target.sidecar_path,
            git_runner,
            "agents_sync.prompt_archive_pull",
        )
        if pulled.returncode != 0:
            cleanup = git_sync.abort_agents_rebase(target.sidecar_path, git_runner)
            return PromptArchivePublicationOutcome(
                queued=True,
                error=git_sync.agents_git_error(
                    "prompt archive git pull --rebase failed", pulled, cleanup
                ),
            )
        try:
            prepared = prepare_prompt_archive(
                target=target,
                repo=target.sidecar_path,
                agent_name=local_agent,
                global_agent=global_agent,
                primary_revision=primary_revision,
                commit_cwd=commit_cwd,
                agent_artifacts_dir=artifacts_dir,
                prompt_content=prompt_content,
                plan_ref=plan_ref,
                prompt_name=prompt_name,
                yyyymm=yyyymm,
                git_runner=git_runner,
            )
            commit_result = _commit_prompt_archive_if_dirty(
                target.sidecar_path,
                global_agent,
                git_runner,
            )
            if isinstance(commit_result, str):
                return PromptArchivePublicationOutcome(
                    queued=True,
                    prompt_path=prepared.prompt_path,
                    error=commit_result,
                )
            should_push = (
                commit_result
                or git_sync.agents_ahead_count(target.sidecar_path, git_runner) > 0
            )
            if should_push:
                pushed = git_runner(
                    target.sidecar_path,
                    ["push"],
                    network=True,
                    op="agents_sync.prompt_archive_push",
                )
                if pushed.returncode != 0:
                    return PromptArchivePublicationOutcome(
                        queued=True,
                        prompt_path=prepared.prompt_path,
                        error=git_sync.agents_git_error(
                            "prompt archive git push failed", pushed
                        ),
                    )
            try:
                from sase.core.artifact_ref_files_index import upsert_ref_file_versions

                upsert_ref_file_versions(
                    prepared.rendered.linked_records,
                    agent_name=global_agent,
                    project=target.project,
                    sidecar_repo=target.sidecar_path.name,
                )
            except Exception:
                log.debug("Could not update artifact ref-files index", exc_info=True)
            for request in prepared.referenced_by_requests:
                enqueue_referenced_by_request(request)
            prompt_outcome = PromptArchivePublicationOutcome(
                published=bool(commit_result),
                queued=True,
                prompt_path=prepared.prompt_path,
            )
        finally:
            # A failed attempt is regenerated from the immutable local pool.
            _clean_prompt_archive_worktree(target.sidecar_path, git_runner)
    if prompt_outcome is None:
        return PromptArchivePublicationOutcome(
            queued=True,
            error="prompt archive publication did not produce an outcome",
        )
    referenced_by_error = _drain_referenced_by_after_prompt_publish(
        target,
        git_runner=git_runner,
    )
    if referenced_by_error is None:
        return prompt_outcome
    return PromptArchivePublicationOutcome(
        published=prompt_outcome.published,
        queued=prompt_outcome.queued,
        prompt_path=prompt_outcome.prompt_path,
        skip_reason=prompt_outcome.skip_reason,
        error=referenced_by_error,
    )


def prepare_prompt_archive(
    *,
    target: ProjectTarget,
    repo: Path,
    agent_name: str,
    global_agent: str,
    primary_revision: str,
    commit_cwd: Path,
    agent_artifacts_dir: Path,
    prompt_content: str | None = None,
    plan_ref: str | None = None,
    prompt_name: str | None = None,
    yyyymm: str | None = None,
    git_runner: GitRunner = run_git,
) -> PreparedPromptArchive:
    """Prepare one archive inside a checkout whose write lock is already held."""

    return _prepare_prompt_archive(
        target=target,
        repo=repo,
        agent_name=agent_name,
        global_agent=global_agent,
        primary_revision=primary_revision,
        commit_cwd=commit_cwd,
        agent_artifacts_dir=agent_artifacts_dir,
        prompt_content=prompt_content,
        plan_ref=plan_ref,
        prompt_name=prompt_name,
        yyyymm=yyyymm,
        git_runner=git_runner,
        hosted_resolver_factory=_hosted_resolver,
        repository_roots_factory=_repository_roots,
    )


def _drain_referenced_by_after_prompt_publish(
    target: ProjectTarget,
    *,
    git_runner: GitRunner,
) -> str | None:
    try:
        from sase.agents_sync.referenced_by_publication import (
            drain_referenced_by_requests,
        )

        diagnostics = drain_referenced_by_requests(target, git_runner=git_runner)
    except Exception as exc:  # noqa: BLE001 - prompt publication already succeeded.
        return f"referenced-by write-back failed: {exc}"
    if not diagnostics:
        return None
    return "\n".join(diagnostics)


def _agent_artifacts_dir(value: Path | str | None) -> Path | None:
    raw = value if value is not None else os.environ.get("SASE_ARTIFACTS_DIR")
    if raw is None or not str(raw).strip():
        return None
    return Path(raw).expanduser().resolve(strict=False)


__all__ = [
    "PromptArchivePublicationOutcome",
    "prepare_prompt_archive",
    "publish_prompt_archive",
]

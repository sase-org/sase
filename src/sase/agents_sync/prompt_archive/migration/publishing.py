"""Publish migration commits and explain push recovery."""

from __future__ import annotations

from pathlib import Path
import shlex

from sase.agents_sync.git import GitRunner
from sase.agents_sync.models import ProjectTarget


def publish_migration_sidecars(
    target: ProjectTarget,
    plans_repo: Path,
    *,
    month: str | None,
    active_repos: set[Path],
    git_runner: GitRunner,
) -> None:
    """Synchronously publish new or restart-pending migration commits."""

    repositories = (
        ("agents", target.sidecar_path),
        ("plans", plans_repo),
    )
    pending: list[tuple[str, Path]] = []
    for label, repo in repositories:
        subjects = _ahead_subjects(repo, git_runner)
        is_restart = subjects is not None and _contains_migration_commit(
            label,
            subjects,
            month=month,
        )
        if (subjects and (repo in active_repos or is_restart)) or (
            subjects is None and repo in active_repos
        ):
            pending.append((label, repo))
    for index, (label, repo) in enumerate(pending):
        pushed = git_runner(
            repo,
            ["push", "origin", "HEAD"],
            network=True,
            op=f"prompt_migrate.push_{label}",
        )
        if pushed.returncode == 0:
            continue
        recovered = (
            _recover_failed_agents_migration_push(target, repo, git_runner, pushed)
            if label == "agents"
            else None
        )
        if recovered is not None:
            remaining = tuple(path for _name, path in pending[index + 1 :])
            raise RuntimeError(
                _publication_recovery_message(
                    target,
                    month=month,
                    failed_label=label,
                    detail=recovered,
                    repositories=remaining,
                    replay_push=False,
                )
            )
        detail = _sanitized_migration_push_detail(pushed)
        remaining = tuple(path for _name, path in pending[index:])
        raise RuntimeError(
            _publication_recovery_message(
                target,
                month=month,
                failed_label=label,
                detail=detail,
                repositories=remaining,
            )
        )


def _recover_failed_agents_migration_push(
    target: ProjectTarget,
    repo: Path,
    git_runner: GitRunner,
    pushed: object,
) -> str | None:
    """Recover a content-security agents push rejection without replaying it.

    Secret-scanning and repository-rule rejections go through the shared
    recovery path (ledger block, private preserve, managed-clone reset).
    Transport and divergence failures return ``None`` so the caller keeps
    the legacy operator recovery that names an explicit re-push.
    """

    from sase.agents_sync.publication_recovery import (
        REJECTED_REPOSITORY_RULE,
        REJECTED_SECRET_SCAN,
        recover_publication_push,
        sanitized_push_error,
    )

    recovery = recover_publication_push(
        repo,
        git_runner,
        project_key=target.project_key,
        repository_identity=target.remote_url,
        returncode=int(getattr(pushed, "returncode", 1)),
        stdout=str(getattr(pushed, "stdout", None) or ""),
        stderr=str(getattr(pushed, "stderr", None) or ""),
    )
    if recovery.rejection.classification not in (
        REJECTED_SECRET_SCAN,
        REJECTED_REPOSITORY_RULE,
    ):
        return None
    if recovery.error:
        return recovery.error
    return sanitized_push_error(
        "migration push",
        recovery.rejection,
        blocked_paths=recovery.blocked_paths,
    )


def _sanitized_migration_push_detail(pushed: object) -> str:
    """Describe a migration push failure without echoing remote secrets.

    Secret-scanning and repository-rule rejections surface sanitized,
    value-free text; transport and divergence failures keep their legacy
    detail because migration retries are operator-driven, not a drain loop.
    """

    from sase.agents_sync.publication_recovery import (
        REJECTED_REPOSITORY_RULE,
        REJECTED_SECRET_SCAN,
        PublicationPushRejection,
        classify_publication_push,
        sanitized_push_error,
    )

    stdout = str(getattr(pushed, "stdout", None) or "")
    stderr = str(getattr(pushed, "stderr", None) or "")
    rejection: PublicationPushRejection = classify_publication_push(
        returncode=int(getattr(pushed, "returncode", 1)),
        stdout=stdout,
        stderr=stderr,
    )
    if rejection.classification in (
        REJECTED_SECRET_SCAN,
        REJECTED_REPOSITORY_RULE,
    ):
        return sanitized_push_error("migration push", rejection)
    return (stderr or stdout or "git push failed").strip()


def _ahead_subjects(repo: Path, git_runner: GitRunner) -> tuple[str, ...] | None:
    result = git_runner(
        repo,
        ["log", "--format=%s", "@{upstream}..HEAD"],
        op="prompt_migrate.ahead",
    )
    if result.returncode != 0:
        return None
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def _contains_migration_commit(
    label: str,
    subjects: tuple[str, ...],
    *,
    month: str | None,
) -> bool:
    if label == "agents":
        prefix = "chore(prompts): migrate "
        suffix = " prompt archive"
    else:
        prefix = "Migrate "
        suffix = " prompts to agents sidecar"
    return any(
        subject == f"{prefix}{month}{suffix}"
        if month is not None
        else subject.startswith(prefix) and subject.endswith(suffix)
        for subject in subjects
    )


def _publication_recovery_message(
    target: ProjectTarget,
    *,
    month: str | None,
    failed_label: str,
    detail: str,
    repositories: tuple[Path, ...],
    replay_push: bool = True,
) -> str:
    commands: list[str] = []
    if replay_push:
        commands.extend(
            f"git -C {shlex.quote(str(repo))} push origin HEAD" for repo in repositories
        )
    rerun = (
        f"sase agent prompts migrate --write --project {shlex.quote(target.project)}"
    )
    if month is not None:
        rerun += f" --month {month}"
    commands.append(rerun)
    rendered = "\n  ".join(commands)
    if replay_push:
        return (
            f"{failed_label} sidecar migration push failed: {detail}\n"
            "Migration commits remain durable locally. Recover with exactly:\n"
            f"  {rendered}"
        )
    return (
        f"{failed_label} sidecar migration push failed: {detail}\n"
        "The rejected commit was not replayed. Continue with:\n"
        f"  {rendered}"
    )


__all__ = [
    "publish_migration_sidecars",
]

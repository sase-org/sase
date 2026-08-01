"""Publish canonical prompt documents and their captured bytes."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

from sase.agent_lanes import lane_name, lane_ref_for_agent
from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.prompt_archive.index import render_prompt_month_index
from sase.agents_sync.prompt_archive.naming import resolve_prompt_name
from sase.agents_sync.prompt_archive.paths import (
    artifacts_month_dir,
    prompt_document_path,
    prompts_month_dir,
    relative_artifact_link,
)
from sase.agents_sync.prompt_archive.render import (
    RenderedPromptArchive,
    load_manifest_records,
    render_prompt_document,
)
from sase.agents_sync.publication_outbox import (
    AgentPublicationOutboxItem,
    enqueue_agent_publication,
)
from sase.agents_sync.targets import resolve_sync_targets
from sase.config import require_agent_owner_identity
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    agent_local_hood,
    globalize_owned_agent_name,
    normalize_agent_archive_name,
    normalize_owned_agent_name,
)
from sase.core.artifact_file_helpers import hash_file
from sase.core.prompt_artifact_staging import (
    PROMPT_ARTIFACT_MANIFEST_NAME,
    PromptArtifactRecord,
)
from sase.repo_inventory import collect_repo_inventory
from sase.sdd.hosted_links import HostedLinkResolver
from sase.sdd.plan_header_block import (
    PlanHeaderSectionKind,
    parse_plan_header_block,
)

_ARCHIVE_PATHS = ("prompts", "artifacts")


@dataclass(frozen=True, slots=True)
class PromptArchivePublicationOutcome:
    """Best-effort result for one archive publication attempt."""

    published: bool = False
    queued: bool = False
    prompt_path: Path | None = None
    skip_reason: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class _PreparedPromptArchive:
    """Files prepared inside an already locked agents checkout."""

    prompt_path: Path
    rendered: RenderedPromptArchive
    copied_artifacts: tuple[Path, ...]


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
    lane = lane_ref_for_agent(local_agent, identity)
    enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key=target.project_key,
            project=target.project,
            local_agent=lane.local_name,
            global_agent=lane.global_name,
            primary_revision=primary_revision,
            local_hood=agent_local_hood(lane.local_name),
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
            return PromptArchivePublicationOutcome(
                published=bool(commit_result),
                queued=True,
                prompt_path=prepared.prompt_path,
            )
        finally:
            # A failed attempt is regenerated from the immutable local pool.
            _clean_prompt_archive_worktree(target.sidecar_path, git_runner)


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
) -> _PreparedPromptArchive:
    """Prepare one archive inside a checkout whose write lock is already held."""

    meta = _read_json(agent_artifacts_dir / "agent_meta.json")
    workspace_root = _workspace_root(meta, commit_cwd)
    archive_month = yyyymm or _archive_month(agent_artifacts_dir)
    resolved_plan_ref = _canonical_plan_ref(
        plan_ref or _plan_ref(meta),
        workspace_root,
    )
    plan_label = _plan_label(resolved_plan_ref)
    plan_slug = Path(plan_label).stem if plan_label else None
    month_dir = prompts_month_dir(repo, archive_month)
    month_dir.mkdir(parents=True, exist_ok=True)

    reusable = _prompt_names_for_agent(month_dir, global_agent)
    resolved_prompt_name = resolve_prompt_name(
        prompt_name or plan_slug,
        lane_name(global_agent),
        month_dir.glob("*.md"),
        reusable_names=reusable,
    )
    prompt_path = prompt_document_path(repo, archive_month, resolved_prompt_name)
    manifest_path = (
        workspace_root / ".sase" / "artifacts" / PROMPT_ARTIFACT_MANIFEST_NAME
    )
    records = load_manifest_records(manifest_path, agent_artifacts_dir)
    hosted = _hosted_resolver(workspace_root, target, git_runner)
    target_resolver = _ArtifactTargetResolver(
        yyyymm=archive_month,
        repo=repo,
        workspace_root=workspace_root,
        primary_root=commit_cwd,
        primary_revision=primary_revision,
        hosted=hosted,
        git_runner=git_runner,
    )
    prompt = (
        prompt_content
        if prompt_content is not None
        else (agent_artifacts_dir / "raw_xprompt.md").read_text(encoding="utf-8")
    )
    rendered = render_prompt_document(
        prompt,
        records,
        artifact_target=target_resolver,
        agent_label=global_agent,
        agent_target=hosted.agent_url(global_agent) if hosted is not None else None,
        plan_label=plan_label,
        plan_target=(
            hosted.plan_url(resolved_plan_ref)
            if hosted is not None and resolved_plan_ref is not None
            else None
        ),
    )
    copied = _publish_linked_artifacts(
        rendered.linked_records,
        target_resolver,
    )
    _atomic_write_text(prompt_path, rendered.document)
    index_path = month_dir / "README.md"
    _atomic_write_text(index_path, render_prompt_month_index(month_dir))
    return _PreparedPromptArchive(prompt_path, rendered, copied)


class _ArtifactTargetResolver:
    def __init__(
        self,
        *,
        yyyymm: str,
        repo: Path,
        workspace_root: Path,
        primary_root: Path,
        primary_revision: str,
        hosted: HostedLinkResolver | None,
        git_runner: GitRunner,
    ) -> None:
        self.yyyymm = yyyymm
        self.repo = repo
        self.workspace_root = workspace_root
        self.primary_root = primary_root.resolve(strict=False)
        self.primary_revision = primary_revision
        self.hosted = hosted
        self.git_runner = git_runner
        self.staging_root = workspace_root / ".sase" / "artifacts"
        self._repo_roots = _repository_roots()

    def __call__(self, record: PromptArtifactRecord) -> str | None:
        pool_relpath = record.get("pool_relpath")
        digest = record.get("sha256")
        if pool_relpath and digest:
            source = self.staging_root / pool_relpath
            if not source.is_file():
                return None
            return relative_artifact_link(self.yyyymm, source.name)
        vcs_repo = record.get("vcs_repo")
        vcs_relpath = record.get("vcs_relpath")
        if vcs_repo and vcs_relpath and self.hosted is not None:
            root = self._record_vcs_root(record) or self._repo_roots.get(vcs_repo)
            if root is None:
                return None
            revision = (
                self.primary_revision
                if root == self.primary_root
                else _git_revision(root, self.git_runner)
            )
            if not revision:
                return None
            return self.hosted.blob_url_for_repository(root, revision, vcs_relpath)
        locator = record.get("locator")
        if isinstance(locator, str) and locator.startswith(("https://", "http://")):
            return locator
        kind = record.get("ref_kind")
        if kind == "commit" and locator and self.hosted is not None:
            repo_name, separator, sha = locator.rpartition("@")
            root = self._repo_roots.get(repo_name) if separator else None
            return (
                self.hosted.commit_url_for_repository(root, sha)
                if root is not None
                else None
            )
        if kind == "bug" and locator:
            project, separator, raw_number = locator.rpartition("#")
            if separator and raw_number.isdigit():
                try:
                    from sase.ace.tui.artifacts_bugs import issue_url_for_number

                    return issue_url_for_number(project, int(raw_number))
                except Exception:
                    return None
        if kind == "agent" and self.hosted is not None:
            agent_name = locator.rsplit("/", 1)[-1] if locator else None
            return self.hosted.agent_url(agent_name or record.get("label") or "")
        return None

    def _record_vcs_root(self, record: PromptArtifactRecord) -> Path | None:
        raw_source = record.get("source_path")
        if not raw_source:
            return None
        source = Path(raw_source).expanduser()
        result = self.git_runner(
            source.parent,
            ["rev-parse", "--show-toplevel"],
            op="prompt_archive.source_repository",
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        return Path(result.stdout.strip()).expanduser().resolve(strict=False)

    def source_for(self, record: PromptArtifactRecord) -> Path | None:
        pool_relpath = record.get("pool_relpath")
        if not pool_relpath:
            return None
        source = (self.staging_root / pool_relpath).resolve(strict=False)
        pool = (self.staging_root / "pool").resolve(strict=False)
        return source if source.is_relative_to(pool) and source.is_file() else None


def _publish_linked_artifacts(
    records: tuple[PromptArtifactRecord, ...],
    resolver: _ArtifactTargetResolver,
) -> tuple[Path, ...]:
    copied: list[Path] = []
    destination_dir = artifacts_month_dir(resolver.repo, resolver.yyyymm)
    for record in records:
        source = resolver.source_for(record)
        if source is None:
            continue
        expected = record.get("sha256")
        if not expected or hash_file(source) != expected:
            raise RuntimeError(f"prompt artifact digest mismatch: {source}")
        destination = destination_dir / source.name
        _copy_content_addressed(source, destination, expected)
        copied.append(destination)
    return tuple(copied)


def _commit_prompt_archive_if_dirty(
    repo: Path,
    global_agent: str,
    git_runner: GitRunner,
) -> bool | str:
    """Commit only the incremental prompt/archive path set."""

    archive_paths = tuple(
        path
        for path in _ARCHIVE_PATHS
        if (repo / path).exists() or _tracked_archive_path(repo, path, git_runner)
    )
    if not archive_paths:
        return False
    staged = git_runner(
        repo,
        ["add", "--", *archive_paths],
        op="agents_sync.prompt_archive_stage",
    )
    if staged.returncode != 0:
        return _git_error("could not stage prompt archive", staged)
    dirty = git_runner(
        repo,
        ["diff", "--cached", "--quiet", "--", *archive_paths],
        op="agents_sync.prompt_archive_diff",
    )
    if dirty.returncode == 0:
        return False
    if dirty.returncode != 1:
        return _git_error("could not inspect staged prompt archive", dirty)
    committed = git_runner(
        repo,
        [
            "-c",
            "user.name=SASE",
            "-c",
            "user.email=sase@localhost",
            "commit",
            "-m",
            f"chore(agents): archive prompt for {global_agent}",
        ],
        op="agents_sync.prompt_archive_commit",
    )
    return (
        True
        if committed.returncode == 0
        else _git_error("could not commit prompt archive", committed)
    )


def _tracked_archive_path(repo: Path, path: str, git_runner: GitRunner) -> bool:
    result = git_runner(
        repo,
        ["ls-files", "--", path],
        op="agents_sync.prompt_archive_path_tracked",
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def _clean_prompt_archive_worktree(repo: Path, git_runner: GitRunner) -> str | None:
    """Restore the regenerable prompt archive paths to ``HEAD``."""

    reset = git_runner(
        repo,
        ["reset", "--quiet", "HEAD", "--", *_ARCHIVE_PATHS],
        op="agents_sync.prompt_archive_reset",
    )
    if reset.returncode != 0:
        return _git_error("could not reset prompt archive index", reset)
    tracked = git_runner(
        repo,
        ["ls-files", "--", *_ARCHIVE_PATHS],
        op="agents_sync.prompt_archive_tracked",
    )
    if tracked.returncode != 0:
        return _git_error("could not inspect tracked prompt archive", tracked)
    restore_roots = tuple(
        root
        for root in _ARCHIVE_PATHS
        if any(
            path == root or path.startswith(f"{root}/")
            for path in tracked.stdout.splitlines()
        )
    )
    if restore_roots:
        restored = git_runner(
            repo,
            ["checkout", "--", *restore_roots],
            op="agents_sync.prompt_archive_restore",
        )
        if restored.returncode != 0:
            return _git_error("could not restore prompt archive", restored)
    cleaned = git_runner(
        repo,
        ["clean", "-fd", "--", *_ARCHIVE_PATHS],
        op="agents_sync.prompt_archive_clean",
    )
    return (
        None
        if cleaned.returncode == 0
        else _git_error("could not clean prompt archive", cleaned)
    )


def _hosted_resolver(
    workspace_root: Path,
    target: ProjectTarget,
    git_runner: GitRunner,
) -> HostedLinkResolver | None:
    try:
        from sase.sdd.plan_refs import workspace_context_for_plan_resolution
        from sase.sdd.store import resolve_sdd_store

        workspace, number = workspace_context_for_plan_resolution(workspace_root)
        store = resolve_sdd_store(workspace, number)
        return HostedLinkResolver(
            store,
            project=target.project,
            primary_root=workspace_root,
            git_runner=git_runner,
        )
    except Exception:
        return None


def _prompt_names_for_agent(month_dir: Path, global_agent: str) -> tuple[str, ...]:
    reusable: list[str] = []
    for path in month_dir.glob("*.md"):
        if path.name == "README.md":
            continue
        try:
            parsed = parse_plan_header_block(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if any(
            entry.label == global_agent
            for section in parsed.sections
            if section.kind is PlanHeaderSectionKind.AGENTS
            for entry in section.entries
        ):
            reusable.append(path.stem)
    return tuple(reusable)


def _agent_artifacts_dir(value: Path | str | None) -> Path | None:
    raw = value if value is not None else os.environ.get("SASE_ARTIFACTS_DIR")
    if raw is None or not str(raw).strip():
        return None
    return Path(raw).expanduser().resolve(strict=False)


def _archive_month(artifacts_dir: Path) -> str:
    for part in reversed(artifacts_dir.parts):
        if len(part) >= 6 and part[:6].isdigit():
            return part[:6]
    from sase.sdd._paths import get_yyyymm

    return get_yyyymm()


def _plan_ref(meta: dict[str, Any]) -> str | None:
    for key in ("sdd_plan_path", "epic_plan_ref", "plan_path"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            raw = value.strip()
            return raw if raw.startswith("plans:") else f"plans:{raw}"
    return None


def _plan_label(plan_ref: str | None) -> str | None:
    if plan_ref is None:
        return None
    return plan_ref.removeprefix("plans:").removeprefix("./")


def _canonical_plan_ref(plan_ref: str | None, workspace_root: Path) -> str | None:
    if plan_ref is None:
        return None
    try:
        from sase.sdd.plan_refs import (
            canonicalize_plan_reference_from_roots,
            resolve_plan_reference_from_roots,
            workspace_context_for_plan_resolution,
        )
        from sase.sdd.store import resolve_sdd_store

        workspace, number = workspace_context_for_plan_resolution(workspace_root)
        store = resolve_sdd_store(workspace, number)
        root = store.kind_root("plans")
        resolution = resolve_plan_reference_from_roots(plan_ref, roots=(root,))
        if resolution.resolved_path is not None:
            canonical = canonicalize_plan_reference_from_roots(
                resolution.resolved_path,
                roots=(root,),
            )
            if canonical is not None:
                return canonical
    except Exception:
        pass
    return plan_ref


def _workspace_root(meta: dict[str, Any], fallback: Path) -> Path:
    value = meta.get("workspace_dir")
    if isinstance(value, str) and value.strip():
        return Path(value).expanduser().resolve(strict=False)
    return fallback.resolve(strict=False)


def _repository_roots() -> dict[str, Path]:
    try:
        inventory = collect_repo_inventory()
    except Exception:
        return {}
    roots: dict[str, Path] = {}
    for record in inventory.records:
        candidates = (record.path, *(clone.path for clone in record.clones))
        for raw in candidates:
            if raw:
                roots.setdefault(
                    record.name, Path(raw).expanduser().resolve(strict=False)
                )
    return roots


def _git_revision(root: Path, git_runner: GitRunner) -> str | None:
    result = git_runner(root, ["rev-parse", "HEAD"], op="prompt_archive.revision")
    return result.stdout.strip() if result.returncode == 0 else None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_tmp = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    os.close(descriptor)
    tmp = Path(raw_tmp)
    try:
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _copy_content_addressed(source: Path, target: Path, digest: str) -> None:
    if target.exists():
        if hash_file(target) != digest:
            raise RuntimeError(f"prompt artifact digest collision at {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_tmp = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    os.close(descriptor)
    tmp = Path(raw_tmp)
    try:
        shutil.copy2(source, tmp)
        if hash_file(tmp) != digest:
            raise RuntimeError(f"prompt artifact changed while publishing: {source}")
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def _git_error(
    prefix: str,
    result: subprocess.CompletedProcess[str],
) -> str:
    detail = (result.stderr or result.stdout or "unknown git error").strip()
    return f"{prefix}: {detail}"


__all__ = [
    "PromptArchivePublicationOutcome",
    "prepare_prompt_archive",
    "publish_prompt_archive",
]

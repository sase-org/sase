"""Prepare prompt documents and their linked artifacts for publication."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from sase.agents_sync.git import GitRunner
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.prompt_archive.index import render_prompt_month_index
from sase.agents_sync.prompt_archive.naming import resolve_prompt_name
from sase.agents_sync.prompt_archive.paths import (
    prompt_document_path,
    prompts_month_dir,
)
from sase.agents_sync.prompt_archive.render import (
    RenderedPromptArchive,
    load_manifest_records,
    render_prompt_document,
)
from sase.agents_sync.referenced_by_outbox import ReferencedByOutboxItem
from sase.core.artifact_file_helpers import hash_file
from sase.core.rust import require_rust_binding
from sase.core.prompt_artifact_staging import (
    PROMPT_ARTIFACT_MANIFEST_NAME,
    PromptArtifactRecord,
)
from sase.repo_inventory import collect_repo_inventory
from sase.sase_agent import sase_agent_name
from sase.sdd.hosted_links import HostedLinkResolver
from sase.sdd.plan_header_block import (
    PlanHeaderSectionKind,
    parse_plan_header_block,
)
from sase.sdd.plan_refs import PLAN_REFERENCE_PREFIX

type _HostedResolverFactory = Callable[
    [Path, ProjectTarget, GitRunner], HostedLinkResolver | None
]
type _RepositoryRootsFactory = Callable[[], dict[str, Path]]


@dataclass(frozen=True, slots=True)
class PreparedPromptArchive:
    """Files prepared inside an already locked agents checkout."""

    prompt_path: Path
    rendered: RenderedPromptArchive
    copied_artifacts: tuple[Path, ...]
    referenced_by_requests: tuple[ReferencedByOutboxItem, ...] = ()


def prepare_prompt_archive(
    *,
    target: ProjectTarget,
    repo: Path,
    agent_name: str,
    global_agent: str,
    primary_revision: str,
    commit_cwd: Path,
    agent_artifacts_dir: Path,
    prompt_content: str | None,
    plan_ref: str | None,
    prompt_name: str | None,
    yyyymm: str | None,
    git_runner: GitRunner,
    hosted_resolver_factory: _HostedResolverFactory,
    repository_roots_factory: _RepositoryRootsFactory,
) -> PreparedPromptArchive:
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
        sase_agent_name(global_agent),
        month_dir.glob("*.md"),
        reusable_names=reusable,
    )
    prompt_path = prompt_document_path(repo, archive_month, resolved_prompt_name)
    manifest_path = (
        workspace_root / ".sase" / "artifacts" / PROMPT_ARTIFACT_MANIFEST_NAME
    )
    records = load_manifest_records(manifest_path, agent_artifacts_dir)
    hosted = hosted_resolver_factory(workspace_root, target, git_runner)
    repository_roots = repository_roots_factory()
    target_resolver = _ArtifactTargetResolver(
        yyyymm=archive_month,
        repo=repo,
        project=target.project,
        workspace_root=workspace_root,
        primary_root=commit_cwd,
        primary_revision=primary_revision,
        hosted=hosted,
        git_runner=git_runner,
        repository_roots=repository_roots,
    )
    prompt = (
        prompt_content
        if prompt_content is not None
        else (agent_artifacts_dir / "raw_xprompt.md").read_text(encoding="utf-8")
    )
    agent_target = hosted.agent_url(global_agent) if hosted is not None else None
    rendered = render_prompt_document(
        prompt,
        records,
        artifact_target=target_resolver,
        agent_label=global_agent,
        agent_target=agent_target,
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
    referenced_by_requests = _plan_referenced_by_requests(
        target=target,
        rendered=rendered,
        agent_artifacts_dir=agent_artifacts_dir,
        global_agent=global_agent,
        primary_revision=primary_revision,
        workspace_root=workspace_root,
        repository_roots=repository_roots,
        agent_url=agent_target,
    )
    _atomic_write_text(prompt_path, rendered.document)
    index_path = month_dir / "README.md"
    _atomic_write_text(index_path, render_prompt_month_index(month_dir))
    return PreparedPromptArchive(prompt_path, rendered, copied, referenced_by_requests)


class _ArtifactTargetResolver:
    def __init__(
        self,
        *,
        yyyymm: str,
        repo: Path,
        project: str,
        workspace_root: Path,
        primary_root: Path,
        primary_revision: str,
        hosted: HostedLinkResolver | None,
        git_runner: GitRunner,
        repository_roots: dict[str, Path],
    ) -> None:
        self.yyyymm = yyyymm
        self.repo = repo
        self.project = project
        self.workspace_root = workspace_root
        self.primary_root = primary_root.resolve(strict=False)
        self.primary_revision = primary_revision
        self.hosted = hosted
        self.git_runner = git_runner
        self.staging_root = workspace_root / ".sase" / "artifacts"
        self._repo_roots = repository_roots

    def __call__(self, record: PromptArtifactRecord) -> str | None:
        pool_relpath = record.get("pool_relpath")
        digest = record.get("sha256")
        if pool_relpath and digest:
            source = self.staging_root / pool_relpath
            if not source.is_file():
                return None
            return str(
                require_rust_binding("artifact_object_prompt_link")(
                    require_rust_binding("artifact_object_relpath")(digest)
                )
            )
        locator = record.get("locator")
        kind = record.get("ref_kind")
        if kind in {"commit", "stitch"} and locator and self.hosted is not None:
            repo_name, separator, sha = locator.rpartition("@")
            root = self._repo_roots.get(repo_name) if separator else None
            return (
                self.hosted.commit_url_for_repository(root, sha)
                if root is not None
                else None
            )
        if kind == "bead" and locator and self.hosted is not None:
            _project, separator, bead_id = locator.rpartition("/")
            return self.hosted.bead_url(bead_id) if separator else None
        if kind == "patch" and locator:
            return _patch_pr_url(locator, self.project)
        vcs_repo = record.get("vcs_repo")
        vcs_relpath = record.get("vcs_relpath")
        if vcs_repo and vcs_relpath and self.hosted is not None:
            root = self._record_vcs_root(record) or self._repo_roots.get(vcs_repo)
            if root is None:
                return None
            revision = record.get("vcs_revision")
            if not revision:
                revision = (
                    self.primary_revision
                    if root == self.primary_root
                    else _git_revision(root, self.git_runner)
                )
            if not revision:
                return None
            return self.hosted.blob_url_for_repository(root, revision, vcs_relpath)
        if isinstance(locator, str) and locator.startswith(("https://", "http://")):
            return locator
        if kind == "bug" and locator:
            project, separator, raw_number = locator.rpartition("#")
            if separator and raw_number.isdigit():
                return _issue_url_for_number(project, int(raw_number))
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
    for record in records:
        source = resolver.source_for(record)
        if source is None:
            continue
        expected = record.get("sha256")
        if not expected or hash_file(source) != expected:
            raise RuntimeError(f"prompt artifact digest mismatch: {source}")
        destination = resolver.repo / str(
            require_rust_binding("artifact_object_relpath")(expected)
        )
        _copy_content_addressed(source, destination, expected)
        copied.append(destination)
    return tuple(copied)


def _plan_referenced_by_requests(
    *,
    target: ProjectTarget,
    rendered: RenderedPromptArchive,
    agent_artifacts_dir: Path,
    global_agent: str,
    primary_revision: str,
    workspace_root: Path,
    repository_roots: dict[str, Path],
    agent_url: str | None,
) -> tuple[ReferencedByOutboxItem, ...]:
    try:
        from sase.agents_sync.referenced_by_planning import (
            plan_referenced_by_requests,
        )
        from sase.sdd.plan_refs import workspace_context_for_plan_resolution
        from sase.sdd.store import resolve_sdd_store

        workspace, number = workspace_context_for_plan_resolution(workspace_root)
        store = resolve_sdd_store(workspace, number)
        return plan_referenced_by_requests(
            target=target,
            rendered=rendered,
            agent_artifacts_dir=agent_artifacts_dir,
            global_agent=global_agent,
            primary_revision=primary_revision,
            store=store,
            workspace_root=workspace_root,
            repository_roots=repository_roots,
            agent_url=agent_url,
        )
    except Exception:
        return ()


def _patch_pr_url(locator: str, current_project: str) -> str | None:
    locator_project, separator, patch_name = locator.partition("/")
    if not separator or not locator_project or not patch_name:
        return None
    try:
        from sase.core.paths import sase_projects_dir
        from sase.core.parser_facade import parse_patch_project_file
        from sase.core.project_lifecycle_facade import list_project_records
        from sase.core.project_lifecycle_wire import (
            ProjectRecordWire,
            effective_project_name,
        )

        records = list_project_records(
            sase_projects_dir(),
            "all",
            include_home=False,
            projects_only=True,
        )

        def matches(record: ProjectRecordWire, value: str) -> bool:
            folded = value.casefold()
            return folded in {
                record.project_name.casefold(),
                effective_project_name(record).casefold(),
                *(alias.casefold() for alias in record.aliases),
            }

        record = next(
            (
                candidate
                for candidate in records
                if matches(candidate, current_project)
                and matches(candidate, locator_project)
            ),
            None,
        )
        if record is None:
            return None
        for raw_path in (record.project_file, record.archive_file):
            if not raw_path:
                continue
            for patch in parse_patch_project_file(raw_path):
                if patch.name == patch_name:
                    return patch.pr_url
    except Exception:
        return None
    return None


def _issue_url_for_number(project: str, number: int) -> str | None:
    """Resolve a tracker URL without importing the ACE UI layer."""
    try:
        from sase.core.paths import sase_projects_dir
        from sase.core.project_lifecycle_facade import list_project_records
        from sase.core.project_lifecycle_wire import effective_project_name
        from sase.vcs_provider import get_vcs_provider, supports_issues

        records = list_project_records(
            sase_projects_dir(),
            "all",
            include_home=False,
            projects_only=True,
        )
        project_folded = project.casefold()
        record = next(
            (
                candidate
                for candidate in records
                if candidate.is_project
                and not candidate.system_managed
                and project_folded
                in {
                    candidate.project_name.casefold(),
                    effective_project_name(candidate).casefold(),
                    *(alias.casefold() for alias in candidate.aliases),
                }
            ),
            None,
        )
        if record is None:
            return None
        cwd = (record.workspace_dir or "").strip()
        if not cwd:
            return None
        if not supports_issues(cwd):
            return None
        provider = get_vcs_provider(cwd)
        return provider.get_issue_url(number, cwd)
    except Exception:
        return None


def hosted_resolver(
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


def repository_roots() -> dict[str, Path]:
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
            if raw.startswith(PLAN_REFERENCE_PREFIX):
                return raw
            # "plans:" is immutable-history: an agent's own recorded metadata
            # may still carry the legacy spelling. Normalize it here too,
            # rather than double-prefixing it below.
            raw = raw.removeprefix("plans:")
            return f"{PLAN_REFERENCE_PREFIX}{raw}"
    return None


def _plan_label(plan_ref: str | None) -> str | None:
    if plan_ref is None:
        return None
    # "plans:" is immutable-history: an archived prompt's plan metadata may
    # still carry the legacy spelling. Accept it here too.
    label = plan_ref.removeprefix(PLAN_REFERENCE_PREFIX).removeprefix("plans:")
    return label.removeprefix("./")


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


__all__ = [
    "PreparedPromptArchive",
    "hosted_resolver",
    "prepare_prompt_archive",
    "repository_roots",
]

"""Plan the historical prompt migration without mutating either sidecar."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import re

from sase._git_remote import github_blob_url
from sase.agents_sync.links import hosted_provider
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.prompt_archive.migration._common import (
    MigrationItem,
    PromptMigrationSkip,
    relpath,
)
from sase.sdd._legacy_prompt_files import list_plans_store_prompt_files
from sase.sdd.artifact_links import (
    SddArtifactLinkType,
    update_source_aware_artifact_link,
)
from sase.sdd.hosted_links import resolve_hosted_branch, resolve_origin_remote_url


def plan_items(
    plans_repo: Path,
    agents_repo: Path,
    *,
    month: str | None,
) -> tuple[MigrationItem, ...]:
    plan_url = _hosted_blob_builder(plans_repo)
    prompt_url = _hosted_blob_builder(agents_repo)
    items: list[MigrationItem] = []
    for source, prompt_month in list_plans_store_prompt_files(plans_repo, month=month):
        destination = agents_repo / "prompts" / prompt_month / source.name
        skips: list[PromptMigrationSkip] = []
        plan_path = _resolve_plan_path(plans_repo, prompt_month, source.name)
        original_prompt = source.read_text(encoding="utf-8")
        prompt_content = original_prompt
        plan_content: str | None = None
        plan_changed = False
        displaced_destination: Path | None = None
        displaced_content: str | None = None
        if plan_path is None:
            skips.append(
                PromptMigrationSkip(
                    relpath(plans_repo, source),
                    "paired plan is missing; moved prompt without adding PLAN",
                )
            )
        else:
            prompt_content, prompt_skip = _rewrite_prompt_link(
                prompt_content,
                plans_repo=plans_repo,
                source=source,
                label=f"{prompt_month}/{source.name}",
                href=plan_url(f"{prompt_month}/{source.name}"),
            )
            if prompt_skip is not None:
                skips.append(prompt_skip)
            original_plan = plan_path.read_text(encoding="utf-8")
            plan_content, plan_skip = _rewrite_plan_link(
                original_plan,
                plans_repo=plans_repo,
                plan_path=plan_path,
                label=f"prompts/{prompt_month}/{source.name}",
                href=prompt_url(f"prompts/{prompt_month}/{source.name}"),
            )
            if plan_skip is not None:
                skips.append(plan_skip)
            plan_changed = plan_content != original_plan
        if (
            destination.is_file()
            and destination.read_text(encoding="utf-8") != prompt_content
        ):
            displaced_content = destination.read_text(encoding="utf-8")
            displaced_destination = _displaced_destination(
                destination,
                displaced_content,
            )
        items.append(
            MigrationItem(
                prompt_month,
                source,
                destination,
                prompt_content,
                plan_path,
                plan_content,
                plan_changed,
                displaced_destination,
                displaced_content,
                tuple(skips),
            )
        )
    return tuple(items)


def filter_publishable_migration_items(
    target: ProjectTarget,
    plans_repo: Path,
    items: tuple[MigrationItem, ...],
) -> tuple[tuple[MigrationItem, ...], tuple[PromptMigrationSkip, ...]]:
    """Withhold secret-bearing prompt text before any agents-sidecar write."""

    from sase.agents_sync.prompt_archive.protection import (
        protection_scope_for_target,
        protection_skip_reason,
        scan_archive_text_bytes,
    )

    if not items:
        return items, ()
    scope = protection_scope_for_target(target)
    publishable: list[MigrationItem] = []
    skips: list[PromptMigrationSkip] = []
    for item in items:
        relative = relpath(target.sidecar_path, item.destination)
        verdict = scan_archive_text_bytes(
            item.prompt_content.encode("utf-8"),
            scope=scope,
            relative_destination=relative,
            affected_requests=(f"migrate:{relative}",),
        )
        if verdict.publishable:
            publishable.append(item)
            continue
        skips.append(
            PromptMigrationSkip(
                relpath(plans_repo, item.source),
                protection_skip_reason(verdict.status),
            )
        )
    return tuple(publishable), tuple(skips)


def _rewrite_prompt_link(
    content: str,
    *,
    plans_repo: Path,
    source: Path,
    label: str,
    href: str | None,
) -> tuple[str, PromptMigrationSkip | None]:
    if href is None:
        return content, PromptMigrationSkip(
            relpath(plans_repo, source), "plans-sidecar hosted URL is unavailable"
        )
    try:
        return (
            update_source_aware_artifact_link(
                content,
                plans_repo,
                source,
                None,
                SddArtifactLinkType.PLAN,
                target_label=label,
                target_href=href,
                remove_legacy=True,
            ),
            None,
        )
    except ValueError as exc:
        return content, PromptMigrationSkip(
            relpath(plans_repo, source), f"PLAN rewrite skipped: {exc}"
        )


def _rewrite_plan_link(
    content: str,
    *,
    plans_repo: Path,
    plan_path: Path,
    label: str,
    href: str | None,
) -> tuple[str, PromptMigrationSkip | None]:
    if href is None:
        return content, PromptMigrationSkip(
            relpath(plans_repo, plan_path),
            "agents-sidecar hosted URL is unavailable",
        )
    try:
        return (
            update_source_aware_artifact_link(
                content,
                plans_repo,
                plan_path,
                None,
                SddArtifactLinkType.PROMPT,
                target_label=label,
                target_href=href,
                remove_legacy=True,
            ),
            None,
        )
    except ValueError as exc:
        fallback = _replace_canonical_link_line(
            content,
            link_type="PROMPT",
            label=label,
            href=href,
        )
        if fallback is not None:
            return fallback, None
        return content, PromptMigrationSkip(
            relpath(plans_repo, plan_path), f"PROMPT rewrite skipped: {exc}"
        )


def _resolve_plan_path(plans_repo: Path, month: str, name: str) -> Path | None:
    candidates = (
        plans_repo / month / name,
        plans_repo / "plans" / month / name,
    )
    matches = tuple(path for path in candidates if path.is_file())
    return matches[0] if len(matches) == 1 else None


def _displaced_destination(destination: Path, content: str) -> Path:
    counter = 1
    while True:
        candidate = destination.with_name(
            f"{destination.stem}_{counter}{destination.suffix}"
        )
        if not candidate.exists() or candidate.read_text(encoding="utf-8") == content:
            return candidate
        counter += 1


def _replace_canonical_link_line(
    content: str,
    *,
    link_type: str,
    label: str,
    href: str,
) -> str | None:
    """Repair one known header line when unrelated body prose confuses parsing."""

    pattern = re.compile(rf"(?m)^- \*\*{link_type}:\*\*[^\n]*$")
    updated, count = pattern.subn(
        f"- **{link_type}:** [{label}]({href})",
        content,
        count=1,
    )
    return updated if count == 1 else None


def _hosted_blob_builder(repo: Path) -> Callable[[str], str | None]:
    remote = resolve_origin_remote_url(repo)
    branch = resolve_hosted_branch(repo)

    def build(path: str) -> str | None:
        if remote is None or branch is None:
            return None
        return github_blob_url(
            remote,
            provider=hosted_provider(remote),
            branch=branch,
            path=path,
        )

    return build


__all__ = [
    "filter_publishable_migration_items",
    "plan_items",
]

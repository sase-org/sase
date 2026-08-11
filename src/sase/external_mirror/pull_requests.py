"""Pull-request mirror pass shared by the chop and CLI."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from sase.ace.patch.importer import (
    ImportedPatch,
    import_patch,
    repair_patch_pr_association,
)
from sase.ace.patch.models import Patch
from sase.ace.patch.parser import parse_patch_project_file
from sase.core.commit_footer_facade import parse_commit_footer
from sase.core.patch import ensure_project_prefix
from sase.core.pr_mirror_facade import (
    PullRequestImportDecision,
    PullRequestPatchOwner,
    classify_pull_request,
    normalize_pull_request_url,
)
from sase.external_mirror.config import (
    ExternalMirrorConfig,
    get_external_mirror_config,
)
from sase.external_mirror.state import (
    MirrorCursor,
    clear_backoff,
    isoformat_utc,
    next_backoff,
    overlap_window,
    parse_datetime,
    read_cursor,
    utc_now,
    write_cursor,
)
from sase.project_display_names import project_display_name_for
from sase.vcs_provider import PullRequestListState, PullRequestWire

_KIND = "pull_requests"
_FULL_SCAN_INTERVAL = timedelta(hours=24)
_INCREMENTAL_LIMIT = 100
_FULL_SCAN_LIMIT = 0
_MAX_IMPORTS_PER_PASS = 25
_WORK_BUDGET_SECONDS = 90.0


@dataclass(frozen=True)
class _PlannedPullRequestMutation:
    action: str
    patch_name: str | None
    pr_url: str
    pr_origin: str
    status: str
    destination: str
    reason: str


@dataclass(frozen=True)
class MirrorPassResult:
    project: str
    pull_requests: int = 0
    imported: int = 0
    repaired: int = 0
    skipped: int = 0
    conflicts: int = 0
    deferred: int = 0
    failed: int = 0
    full_scan: bool = False
    dry_run: bool = False
    reason: str | None = None
    planned: tuple[_PlannedPullRequestMutation, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.failed == 0


@dataclass
class _MutableResult:
    project: str
    pull_requests: int = 0
    imported: int = 0
    repaired: int = 0
    skipped: int = 0
    conflicts: int = 0
    deferred: int = 0
    failed: int = 0
    full_scan: bool = False
    dry_run: bool = False
    reason: str | None = None
    planned: list[_PlannedPullRequestMutation] = field(default_factory=list)

    def freeze(self) -> MirrorPassResult:
        return MirrorPassResult(
            project=self.project,
            pull_requests=self.pull_requests,
            imported=self.imported,
            repaired=self.repaired,
            skipped=self.skipped,
            conflicts=self.conflicts,
            deferred=self.deferred,
            failed=self.failed,
            full_scan=self.full_scan,
            dry_run=self.dry_run,
            reason=self.reason,
            planned=tuple(self.planned),
        )


@dataclass
class _PatchIndexes:
    by_name: dict[str, PullRequestPatchOwner]
    by_url: dict[str, PullRequestPatchOwner]
    names: set[str]


class _PullRequestProvider(Protocol):
    def list_pull_requests(
        self,
        cwd: str,
        state: PullRequestListState = "open",
        limit: int = 100,
    ) -> list[PullRequestWire]: ...


def run_pull_request_mirror_pass(
    *,
    project: str,
    project_file: str,
    workspace_dir: str,
    state_dir: str | Path,
    full: bool = False,
    dry_run: bool = False,
    config: ExternalMirrorConfig | None = None,
    now: datetime | None = None,
    work_deadline: float | None = None,
    supports_pull_requests_fn: Callable[[str], bool] | None = None,
    provider_factory: Callable[[str], _PullRequestProvider] | None = None,
) -> MirrorPassResult:
    """Mirror remote pull requests for one project into local Patch records."""

    from sase.vcs_provider import get_vcs_provider, supports_pull_requests

    config = config or get_external_mirror_config()
    now = now or utc_now()
    result = _MutableResult(project=project, dry_run=dry_run)
    supports_fn = supports_pull_requests_fn or supports_pull_requests
    provider_fn: Callable[[str], _PullRequestProvider] = (
        provider_factory or get_vcs_provider
    )

    try:
        supported = supports_fn(workspace_dir)
    except Exception as exc:  # noqa: BLE001 - provider discovery is reported.
        result.failed = 1
        result.reason = f"capability_probe_failed:{type(exc).__name__}"
        return result.freeze()
    if not supported:
        result.reason = "pull_requests_not_supported"
        return result.freeze()

    cursor = read_cursor(state_dir, _KIND, project)
    next_attempt = parse_datetime(cursor.next_attempt_at)
    if next_attempt is not None and now < next_attempt:
        result.reason = "backoff"
        return result.freeze()

    full_scan = _should_full_scan(cursor, full=full, now=now)
    result.full_scan = full_scan
    cursor_after_provider_failure = next_backoff(cursor, now=now)
    if not dry_run:
        write_cursor(state_dir, _KIND, project, cursor_after_provider_failure)

    try:
        provider = provider_fn(workspace_dir)
        pull_requests = provider.list_pull_requests(
            workspace_dir,
            state="all",
            limit=_FULL_SCAN_LIMIT if full_scan else _INCREMENTAL_LIMIT,
        )
    except Exception as exc:  # noqa: BLE001 - remote/auth failures become backoff.
        result.failed = 1
        result.reason = f"provider_error:{type(exc).__name__}"
        return result.freeze()

    cursor = clear_backoff(cursor)
    indexes = _load_indexes(project_file)
    candidates = _candidate_records(
        pull_requests,
        cursor=cursor,
        full_scan=full_scan,
        authors=config.pr_authors,
        result=result,
    )
    result.pull_requests = len(candidates)
    deadline = work_deadline or (time.monotonic() + _WORK_BUDGET_SECONDS)
    success_all = result.failed == 0
    mutations = 0
    latest: tuple[datetime, str] | None = None

    for index, (updated_at, provider_id, pull_request) in enumerate(candidates):
        if latest is None or (updated_at, provider_id) > latest:
            latest = (updated_at, provider_id)
        decision = _classify_pull_request(pull_request, indexes)
        if decision.reason == "marker_conflict":
            result.conflicts += 1

        if decision.action == "skip":
            result.skipped += 1
            continue

        if dry_run:
            planned_name = _planned_patch_name(project, pull_request, indexes, decision)
            _record_planned(result, decision, pull_request, planned_name)
            if planned_name is not None:
                indexes.names.add(planned_name)
            if decision.action == "repair":
                result.repaired += 1
            else:
                result.imported += 1
            continue

        if mutations >= _MAX_IMPORTS_PER_PASS or time.monotonic() >= deadline:
            result.deferred += len(candidates) - index
            break

        try:
            imported = _apply_decision(
                project=project,
                project_file=project_file,
                pull_request=pull_request,
                decision=decision,
            )
        except Exception:  # noqa: BLE001 - keep scanning state conservative.
            result.failed += 1
            success_all = False
            continue
        mutations += 1
        if imported is None:
            result.skipped += 1
            continue
        _add_imported_to_indexes(indexes, imported)
        if decision.action == "repair":
            result.repaired += 1
        else:
            result.imported += 1

    if not dry_run:
        clean = success_all and result.failed == 0 and result.deferred == 0
        next_cursor = cursor
        if clean and latest is not None:
            next_cursor = MirrorCursor(
                updated_at=isoformat_utc(latest[0]),
                provider_id=latest[1],
                last_full_scan_at=cursor.last_full_scan_at,
                failures=0,
                next_attempt_at="",
            )
        if clean and full_scan:
            next_cursor = MirrorCursor(
                updated_at=next_cursor.updated_at,
                provider_id=next_cursor.provider_id,
                last_full_scan_at=isoformat_utc(now),
                failures=0,
                next_attempt_at="",
            )
        write_cursor(state_dir, _KIND, project, next_cursor)

    if result.reason is None:
        if result.deferred:
            result.reason = "deferred"
        elif result.failed:
            result.reason = "failed"
        elif not candidates:
            result.reason = "no_pull_requests"
    return result.freeze()


def _should_full_scan(cursor: MirrorCursor, *, full: bool, now: datetime) -> bool:
    if full:
        return True
    last_full_scan_at = parse_datetime(cursor.last_full_scan_at)
    return last_full_scan_at is None or now - last_full_scan_at >= _FULL_SCAN_INTERVAL


def _candidate_records(
    pull_requests: list[PullRequestWire],
    *,
    cursor: MirrorCursor,
    full_scan: bool,
    authors: tuple[str, ...],
    result: _MutableResult,
) -> list[tuple[datetime, str, PullRequestWire]]:
    author_filter = {author.casefold() for author in authors}
    lower_bound = None if full_scan else overlap_window(cursor)
    deduped: dict[str, tuple[datetime, str, PullRequestWire]] = {}
    for pull_request in pull_requests:
        if author_filter and pull_request.author.casefold() not in author_filter:
            continue
        provider_id = pull_request.provider_id or str(pull_request.number)
        updated_at = parse_datetime(pull_request.updated_at)
        if updated_at is None:
            result.failed += 1
            continue
        if lower_bound is not None and updated_at < lower_bound:
            continue
        existing = deduped.get(provider_id)
        row = (updated_at, provider_id, pull_request)
        if existing is None or row[:2] > existing[:2]:
            deduped[provider_id] = row
    return sorted(deduped.values(), key=lambda row: (row[0], row[1]))


def _load_indexes(project_file: str) -> _PatchIndexes:
    active = Path(project_file)
    from sase.ace.patch.archive import get_archive_file_path

    archive = Path(get_archive_file_path(project_file))
    patches: list[Patch] = []
    for path in (active, archive):
        if path.is_file():
            patches.extend(parse_patch_project_file(str(path)))
    by_name: dict[str, PullRequestPatchOwner] = {}
    by_url: dict[str, PullRequestPatchOwner] = {}
    names: set[str] = set()
    for patch in patches:
        owner = _owner_from_patch(patch)
        by_name[patch.name] = owner
        names.add(patch.name)
        if patch.pr_url:
            canonical = normalize_pull_request_url(patch.pr_url).canonical
            by_url.setdefault(canonical, owner)
    return _PatchIndexes(by_name=by_name, by_url=by_url, names=names)


def _owner_from_patch(patch: Patch) -> PullRequestPatchOwner:
    return PullRequestPatchOwner(
        name=patch.name,
        pr_origin=patch.pr_origin,
        status=patch.status,
        pr_url=patch.pr_url or "",
        is_reservation=patch.status == "Reserved",
    )


def _classify_pull_request(
    pull_request: PullRequestWire,
    indexes: _PatchIndexes,
) -> PullRequestImportDecision:
    canonical_url = normalize_pull_request_url(pull_request.url).canonical
    marker_name = _marker_name(pull_request.body)
    marker_owner = indexes.by_name.get(marker_name) if marker_name else None
    request: dict[str, object] = {
        "number": pull_request.number,
        "url": pull_request.url,
        "state": pull_request.state,
        "is_draft": pull_request.is_draft,
        "merged_at": pull_request.merged_at,
        "body": pull_request.body,
        "url_owner": _owner_wire(indexes.by_url.get(canonical_url)),
        "marker_owner": _owner_wire(marker_owner),
    }
    return classify_pull_request(request)


def _owner_wire(owner: PullRequestPatchOwner | None) -> dict[str, object] | None:
    return owner.to_wire() if owner is not None else None


def _marker_name(body: str) -> str | None:
    parsed = parse_commit_footer(body)
    for tag in parsed.tags:
        if tag.key == "PATCH":
            return tag.label.strip() or None
    return None


def _apply_decision(
    *,
    project: str,
    project_file: str,
    pull_request: PullRequestWire,
    decision: PullRequestImportDecision,
) -> ImportedPatch | None:
    description = _description_for_pr(pull_request)
    if decision.action == "repair" and decision.patch_name:
        return repair_patch_pr_association(
            project_file=project_file,
            patch_name=decision.patch_name,
            pr_url=pull_request.url,
            pr_origin=decision.pr_origin,
            status=decision.status,
            description=description,
        )
    return import_patch(
        project_file=project_file,
        name=_base_name_for_pr(project, pull_request),
        description=description,
        pr_url=pull_request.url,
        pr_origin=decision.pr_origin,
        status=decision.status,
    )


def _description_for_pr(pull_request: PullRequestWire) -> str:
    title = pull_request.title.strip()
    body = parse_commit_footer(pull_request.body).body.strip()
    if title and body:
        return f"{title}\n\n{body}"
    return title or body or pull_request.url


def _base_name_for_pr(project: str, pull_request: PullRequestWire) -> str:
    source = pull_request.title or pull_request.head_ref or f"pr_{pull_request.number}"
    sanitized = _sanitize_patch_stem(source) or f"pr_{pull_request.number}"
    return ensure_project_prefix(project_display_name_for(project), sanitized)


def _sanitize_patch_stem(value: str) -> str:
    lowered = value.strip().lower()
    replaced = re.sub(r"[^a-z0-9]+", "_", lowered)
    collapsed = re.sub(r"_+", "_", replaced).strip("_")
    return collapsed[:80].strip("_")


def _record_planned(
    result: _MutableResult,
    decision: PullRequestImportDecision,
    pull_request: PullRequestWire,
    planned_name: str | None,
) -> None:
    result.planned.append(
        _PlannedPullRequestMutation(
            action=decision.action,
            patch_name=planned_name,
            pr_url=pull_request.url,
            pr_origin=decision.pr_origin,
            status=decision.status,
            destination=decision.destination,
            reason=decision.reason,
        )
    )


def _planned_patch_name(
    project: str,
    pull_request: PullRequestWire,
    indexes: _PatchIndexes,
    decision: PullRequestImportDecision,
) -> str | None:
    if decision.action == "repair":
        return decision.patch_name
    base_name = _base_name_for_pr(project, pull_request)
    suffix = _next_planned_suffix(base_name, indexes.names)
    return f"{base_name}_{suffix}"


def _next_planned_suffix(base_name: str, names: set[str]) -> int:
    from sase.core.patch import get_next_suffix_number

    return get_next_suffix_number(base_name, names)


def _add_imported_to_indexes(indexes: _PatchIndexes, imported: ImportedPatch) -> None:
    owner = PullRequestPatchOwner(
        name=imported.name,
        pr_origin=imported.pr_origin,
        status=imported.status,
        pr_url=imported.pr_url,
        is_reservation=False,
    )
    indexes.names.add(imported.name)
    indexes.by_name[imported.name] = owner
    indexes.by_url[normalize_pull_request_url(imported.pr_url).canonical] = owner


__all__ = [
    "MirrorPassResult",
    "run_pull_request_mirror_pass",
]

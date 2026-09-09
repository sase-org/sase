"""Doctor checks and repair planning for missing plan sidecar archives."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from sase.bead.model import BeadTier, Issue, IssueType
from sase.sdd._paths import is_month_dir_name
from sase.sdd.frontmatter import parse_frontmatter, set_frontmatter_fields
from sase.sdd.plan_refs import (
    PLAN_REFERENCE_KIND,
    PLAN_REFERENCE_PREFIX,
    canonicalize_plan_reference_from_roots,
    parse_plan_reference,
)
from sase.sdd.plan_tiers import normalize_plan_tier, read_plan_tier_from_content
from sase.sdd.referenced_by_index import REFERENCED_BY_LINKS_DIR

if TYPE_CHECKING:
    from sase.sdd.store import SddStore


PlanArchiveCategory = Literal[
    "bead-linked",
    "orphaned-link-index",
    "local-only-canonical",
]

_DISPLAY_LIMIT = 20
_PLAN_ARCHIVE_REPAIR_WORKER_LOCK_WAIT_SECONDS = 2.0


@dataclass(frozen=True)
class _PlanArchiveFinding:
    """One missing archived plan detected by ``sase bead doctor``."""

    category: PlanArchiveCategory
    plan_ref: str
    relpath: str
    sidecar_path: Path
    source_path: Path | None = None
    bead_id: str | None = None
    plan_tier: Literal["tale", "epic"] | None = None
    source_machine: str | None = None
    detail: str = ""

    @property
    def recoverable(self) -> bool:
        return self.source_path is not None and not self.detail


@dataclass(frozen=True)
class PlanArchiveDoctorReport:
    """Complete plan-archive health snapshot for the active project."""

    sidecar_root: Path
    plan_roots: tuple[Path, ...]
    bead_linked_missing: tuple[_PlanArchiveFinding, ...] = ()
    orphaned_link_indexes: tuple[_PlanArchiveFinding, ...] = ()
    local_only_canonical: tuple[_PlanArchiveFinding, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def findings(self) -> tuple[_PlanArchiveFinding, ...]:
        return (
            *self.bead_linked_missing,
            *self.orphaned_link_indexes,
            *self.local_only_canonical,
        )

    @property
    def recoverable_findings(self) -> tuple[_PlanArchiveFinding, ...]:
        return tuple(finding for finding in self.findings if finding.recoverable)

    @property
    def unrecoverable_findings(self) -> tuple[_PlanArchiveFinding, ...]:
        return tuple(
            finding
            for finding in self.findings
            if finding.source_path is None or finding.detail
        )

    @property
    def healthy(self) -> bool:
        return not self.errors and not self.findings


@dataclass(frozen=True)
class _PlanArchiveRepairResult:
    """Result of applying a plan archive repair preview."""

    repaired: tuple[str, ...]
    committed: bool


def inspect_plan_archive_health(
    issues: list[Issue] | tuple[Issue, ...],
    store: SddStore,
    *,
    plan_roots: tuple[Path, ...],
) -> PlanArchiveDoctorReport:
    """Return missing-plan sidecar findings for the current project."""

    sidecar_root = store.kind_root("plans").expanduser().resolve(strict=False)
    normalized_roots = _normalized_roots((sidecar_root, *plan_roots))
    source_roots = tuple(root for root in normalized_roots if root != sidecar_root)

    bead_linked_by_ref: dict[str, _PlanArchiveFinding] = {}
    owner_by_ref: dict[str, str] = {}
    issues_by_id = {issue.id: issue for issue in issues}
    for issue in issues:
        if issue.issue_type is not IssueType.PLAN:
            continue
        plan_ref, relpath = _reference_and_relpath(issue.design, normalized_roots)
        if plan_ref is None or relpath is None:
            continue
        owner_by_ref.setdefault(plan_ref, issue.id)
        sidecar_path = sidecar_root / relpath
        if sidecar_path.is_file():
            continue
        finding = _finding(
            "bead-linked",
            plan_ref,
            relpath,
            sidecar_path,
            source_roots,
            issue=issue,
        )
        bead_linked_by_ref[plan_ref] = finding

    orphaned_by_ref: dict[str, _PlanArchiveFinding] = {}
    for relpath, plan_ref in _iter_orphaned_link_indexes(sidecar_root):
        if (sidecar_root / relpath).is_file():
            continue
        if plan_ref in bead_linked_by_ref:
            continue
        bead_id = owner_by_ref.get(plan_ref) or _bead_id_from_link_index(
            sidecar_root / _link_index_relpath(relpath),
            plan_ref=plan_ref,
            known_beads=issues_by_id,
        )
        orphan_issue = issues_by_id.get(bead_id or "")
        orphaned_by_ref[plan_ref] = _finding(
            "orphaned-link-index",
            plan_ref,
            relpath,
            sidecar_root / relpath,
            source_roots,
            issue=orphan_issue,
            bead_id=bead_id,
        )

    local_only: dict[str, _PlanArchiveFinding] = {}
    authoritative_refs = {*bead_linked_by_ref, *orphaned_by_ref}
    for source_root in source_roots:
        for source_path, relpath, plan_ref in _iter_local_plan_sources(source_root):
            if plan_ref in authoritative_refs:
                continue
            sidecar_path = sidecar_root / relpath
            if sidecar_path.is_file():
                continue
            local_only.setdefault(
                plan_ref,
                _PlanArchiveFinding(
                    category="local-only-canonical",
                    plan_ref=plan_ref,
                    relpath=relpath,
                    sidecar_path=sidecar_path,
                    source_path=source_path,
                ),
            )

    return PlanArchiveDoctorReport(
        sidecar_root=sidecar_root,
        plan_roots=normalized_roots,
        bead_linked_missing=tuple(
            bead_linked_by_ref[ref] for ref in sorted(bead_linked_by_ref)
        ),
        orphaned_link_indexes=tuple(
            orphaned_by_ref[ref] for ref in sorted(orphaned_by_ref)
        ),
        local_only_canonical=tuple(local_only[ref] for ref in sorted(local_only)),
    )


def render_plan_archive_health_messages(
    report: PlanArchiveDoctorReport,
) -> list[str]:
    """Render concise doctor messages for a plan archive health report."""

    if report.healthy:
        return []

    messages: list[str] = []
    if report.errors:
        messages.extend(
            f"WARNING: plan archive doctor unavailable: {error}"
            for error in report.errors
        )
        return messages

    counts = (
        f"{len(report.bead_linked_missing)} bead-linked missing",
        f"{len(report.orphaned_link_indexes)} orphaned link index",
        f"{len(report.local_only_canonical)} local-only canonical",
    )
    messages.append(
        "WARNING: plan archive sidecar drift: "
        + ", ".join(counts)
        + " (repair with: sase bead doctor --fix-plan-archive)"
    )
    messages.extend(
        _render_finding_lines("missing bead-linked plan", report.bead_linked_missing)
    )
    messages.extend(
        _render_finding_lines("orphaned plan link index", report.orphaned_link_indexes)
    )
    messages.extend(
        _render_finding_lines(
            "local-only canonical plan",
            report.local_only_canonical,
            suffix="not necessarily approved",
        )
    )
    return messages


def repair_plan_archive(
    report: PlanArchiveDoctorReport,
    store: SddStore,
    *,
    primary_root: Path,
) -> _PlanArchiveRepairResult:
    """Apply a previously confirmed missing-plan archive repair preview."""

    findings = report.recoverable_findings
    if not findings:
        return _PlanArchiveRepairResult(repaired=(), committed=False)

    changed_paths: list[Path] = []
    for finding in findings:
        if finding.source_path is None:
            continue
        changed_path = _archive_finding(finding, store, primary_root=primary_root)
        if changed_path is not None:
            changed_paths.append(changed_path)

    if not changed_paths:
        return _PlanArchiveRepairResult(repaired=(), committed=False)

    from sase.bead._sync_publication import has_push_remote, head_is_published
    from sase.sdd._commit_store import push_sdd_store_after_commit
    from sase.sdd.files import commit_sdd_store_files

    commit_result = commit_sdd_store_files(
        store,
        "Backfill missing plan archives",
        paths=changed_paths,
        push_after_commit=True,
        worker_lock_wait=_PLAN_ARCHIVE_REPAIR_WORKER_LOCK_WAIT_SECONDS,
    )
    plans_repo = store.repo_root_for_kind("plans")
    if commit_result.committed and has_push_remote(plans_repo):
        outcome = commit_result.push
        if outcome is None and not head_is_published(plans_repo):
            outcome = push_sdd_store_after_commit(
                store,
                push_after_commit=True,
                worker_lock_wait=_PLAN_ARCHIVE_REPAIR_WORKER_LOCK_WAIT_SECONDS,
            )
        _raise_for_plan_archive_repair_push(outcome, plans_repo)
        if not head_is_published(plans_repo):
            raise RuntimeError(
                f"{plans_repo} HEAD was not published after plan archive repair"
            )

    repaired_refs = tuple(
        finding.plan_ref for finding in findings if finding.sidecar_path.is_file()
    )
    return _PlanArchiveRepairResult(
        repaired=repaired_refs,
        committed=bool(commit_result),
    )


def preview_plan_archive_repairs(
    report: PlanArchiveDoctorReport,
) -> list[str]:
    """Render repair-preview lines for a plan archive report."""

    lines = ["Plan archive repair preview:"]
    repairs = report.recoverable_findings
    if repairs:
        for finding in repairs[:_DISPLAY_LIMIT]:
            owner = f" (bead_id: {finding.bead_id})" if finding.bead_id else ""
            lines.append(
                f"  archive {finding.plan_ref} from {finding.source_path}{owner}"
            )
        lines.extend(_omitted_line(len(repairs), _DISPLAY_LIMIT))
    else:
        lines.append("  (no recoverable archives)")

    unrecoverable = report.unrecoverable_findings
    lines.append("Unrecoverable plan archives:")
    if unrecoverable:
        for finding in unrecoverable[:_DISPLAY_LIMIT]:
            detail = finding.detail or "source content not found on this machine"
            if finding.source_machine:
                detail = f"{detail}; likely source machine: {finding.source_machine}"
            lines.append(f"  {finding.plan_ref}: {detail}")
        lines.extend(_omitted_line(len(unrecoverable), _DISPLAY_LIMIT))
    else:
        lines.append("  (none)")
    return lines


def unavailable_plan_archive_report(
    error: BaseException,
    *,
    sidecar_root: Path | None = None,
    plan_roots: tuple[Path, ...] = (),
) -> PlanArchiveDoctorReport:
    """Return a report carrying an availability error."""

    return PlanArchiveDoctorReport(
        sidecar_root=sidecar_root or Path(),
        plan_roots=plan_roots,
        errors=(str(error) or type(error).__name__,),
    )


def _finding(
    category: PlanArchiveCategory,
    plan_ref: str,
    relpath: str,
    sidecar_path: Path,
    source_roots: tuple[Path, ...],
    *,
    issue: Issue | None = None,
    bead_id: str | None = None,
) -> _PlanArchiveFinding:
    source_path = _source_path_for_relpath(relpath, source_roots)
    owner = bead_id or (issue.id if issue is not None else None)
    detail = ""
    if source_path is not None and owner is not None:
        source_owner = _read_plan_bead_id(source_path)
        if source_owner not in (None, owner):
            detail = f"source frontmatter names another bead: {source_owner}"
    return _PlanArchiveFinding(
        category=category,
        plan_ref=plan_ref,
        relpath=relpath,
        sidecar_path=sidecar_path,
        source_path=source_path,
        bead_id=owner,
        plan_tier=_issue_plan_tier(issue),
        source_machine=(
            _source_machine_from_creator(issue.created_by)
            if issue is not None
            else None
        ),
        detail=detail,
    )


def _archive_finding(
    finding: _PlanArchiveFinding,
    store: SddStore,
    *,
    primary_root: Path,
) -> Path | None:
    source_path = finding.source_path
    if source_path is None:
        return None
    source_for_archive = _ensure_source_bead_id(source_path, finding.bead_id)
    tier = _tier_for_archive(source_for_archive, finding)
    month, filename = finding.relpath.split("/", 1)
    from sase.sdd.plan_archive import archive_plan_file

    archived = archive_plan_file(
        source_for_archive,
        store,
        tier=tier,
        yyyymm=month,
        destination_name=filename,
        preserve_existing=True,
        primary_root=primary_root,
        expect_prompt_snapshot=(tier == "epic"),
    )
    return archived.path if archived.written else None


def _raise_for_plan_archive_repair_push(outcome: object, repo_root: Path) -> None:
    pushed = bool(getattr(outcome, "pushed", False))
    skipped_no_remote = bool(getattr(outcome, "skipped_no_remote", False))
    if outcome is None or pushed or skipped_no_remote:
        return
    if bool(getattr(outcome, "skipped_locked", False)):
        raise RuntimeError(
            f"{repo_root} publication deferred: sync worker lock is held"
        )
    detail = str(getattr(outcome, "error", "") or "push was rejected")
    raise RuntimeError(f"{repo_root} publication failed: {detail}")


def _ensure_source_bead_id(source_path: Path, bead_id: str | None) -> Path:
    if bead_id is None:
        return source_path
    content = source_path.read_text(encoding="utf-8")
    current = _frontmatter_bead_id(content)
    if current == bead_id:
        return source_path
    if current not in (None, ""):
        raise RuntimeError(
            f"{source_path} already names bead_id {current!r}, not {bead_id!r}"
        )
    source_path.write_text(
        set_frontmatter_fields(content, {"bead_id": bead_id}),
        encoding="utf-8",
    )
    return source_path


def _tier_for_archive(
    source_path: Path,
    finding: _PlanArchiveFinding,
) -> Literal["tale", "epic"]:
    try:
        content = source_path.read_text(encoding="utf-8")
    except OSError:
        content = ""
    tier = read_plan_tier_from_content(content)
    if tier == "tale":
        return "tale"
    if tier == "epic":
        return "epic"
    return finding.plan_tier or "tale"


def _issue_plan_tier(issue: Issue | None) -> Literal["tale", "epic"] | None:
    if issue is None:
        return None
    return "epic" if issue.tier is BeadTier.EPIC else "tale"


def _reference_and_relpath(
    value: str,
    roots: tuple[Path, ...],
) -> tuple[str | None, str | None]:
    text = value.strip()
    if not text:
        return None, None
    try:
        parsed = parse_plan_reference(text)
    except (RuntimeError, ValueError):
        return None, None
    if parsed.kind != PLAN_REFERENCE_KIND:
        return None, None
    if not parsed.legacy:
        return parsed.rendered, parsed.path
    canonical = canonicalize_plan_reference_from_roots(text, roots=roots)
    if canonical is None:
        return None, None
    parsed = parse_plan_reference(canonical)
    return parsed.rendered, parsed.path


def _iter_orphaned_link_indexes(sidecar_root: Path) -> tuple[tuple[str, str], ...]:
    links_root = sidecar_root / REFERENCED_BY_LINKS_DIR
    if not links_root.is_dir():
        return ()
    result: list[tuple[str, str]] = []
    for path in sorted(links_root.glob("*/*.md.json")):
        if not path.is_file():
            continue
        relpath = path.relative_to(links_root).with_suffix("").as_posix()
        if not _is_plan_relpath(relpath):
            continue
        result.append((relpath, f"{PLAN_REFERENCE_PREFIX}{relpath}"))
    return tuple(result)


def _iter_local_plan_sources(root: Path) -> tuple[tuple[Path, str, str], ...]:
    if not root.is_dir():
        return ()
    result: list[tuple[Path, str, str]] = []
    for month in sorted(path for path in root.iterdir() if path.is_dir()):
        if not is_month_dir_name(month.name):
            continue
        for path in sorted(month.glob("*.md")):
            if not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            frontmatter, error = _plan_frontmatter(content)
            if (
                error is not None
                or normalize_plan_tier(frontmatter.get("tier")) is None
            ):
                continue
            relpath = path.relative_to(root).as_posix()
            result.append((path, relpath, f"{PLAN_REFERENCE_PREFIX}{relpath}"))
    return tuple(result)


def _source_path_for_relpath(relpath: str, roots: tuple[Path, ...]) -> Path | None:
    for root in roots:
        path = root / relpath
        if path.is_file():
            return path.expanduser().resolve(strict=False)
    return None


def _bead_id_from_link_index(
    path: Path,
    *,
    plan_ref: str,
    known_beads: dict[str, Issue],
) -> str | None:
    try:
        from sase.sdd._artifact_link_store_support import read_artifact_link_index

        rows = read_artifact_link_index(path, artifact_ref=plan_ref).get("rows", [])
    except Exception:
        return None
    bead_ids: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        for key in ("source_ref", "target_ref"):
            ref = str(row.get(key) or "")
            if not ref.startswith("bead:"):
                continue
            bead_id = ref.removeprefix("bead:").strip()
            if bead_id in known_beads:
                bead_ids.add(bead_id)
    if len(bead_ids) == 1:
        return next(iter(bead_ids))
    return None


def _link_index_relpath(plan_relpath: str) -> Path:
    return Path(REFERENCED_BY_LINKS_DIR) / f"{plan_relpath}.json"


def _read_plan_bead_id(path: Path) -> str | None:
    try:
        return _frontmatter_bead_id(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return None


def _frontmatter_bead_id(content: str) -> str | None:
    frontmatter, _body, _had_frontmatter = parse_frontmatter(content)
    for field in ("bead_id", "bead"):
        raw = frontmatter.get(field)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def _plan_frontmatter(content: str) -> tuple[dict[str, object], str | None]:
    from sase.sdd.plan_tiers import parse_plan_frontmatter

    return parse_plan_frontmatter(content)


def _is_plan_relpath(value: str) -> bool:
    path = Path(value)
    return (
        len(path.parts) == 2
        and is_month_dir_name(path.parts[0])
        and path.suffix == ".md"
        and bool(path.name)
    )


def _normalized_roots(roots: tuple[Path, ...]) -> tuple[Path, ...]:
    return tuple(
        dict.fromkeys(root.expanduser().resolve(strict=False) for root in roots)
    )


def _render_finding_lines(
    label: str,
    findings: tuple[_PlanArchiveFinding, ...],
    *,
    suffix: str | None = None,
) -> list[str]:
    lines: list[str] = []
    for finding in findings[:_DISPLAY_LIMIT]:
        owner = f" for {finding.bead_id}" if finding.bead_id else ""
        source = (
            f"; recover from {finding.source_path}"
            if finding.source_path is not None and not finding.detail
            else "; unrecoverable here"
        )
        detail = f"; {finding.detail}" if finding.detail else ""
        tail = f"; {suffix}" if suffix else ""
        lines.append(f"  {label}: {finding.plan_ref}{owner}{source}{detail}{tail}")
    lines.extend(_omitted_line(len(findings), _DISPLAY_LIMIT))
    return lines


def _omitted_line(total: int, limit: int) -> list[str]:
    omitted = total - limit
    return [f"  ... {omitted} more"] if omitted > 0 else []


def _source_machine_from_creator(created_by: str) -> str | None:
    parts = [part for part in created_by.split(".") if part]
    if len(parts) < 3:
        return None
    machine = parts[-2].strip()
    return machine or None


__all__ = [
    "PlanArchiveDoctorReport",
    "inspect_plan_archive_health",
    "preview_plan_archive_repairs",
    "render_plan_archive_health_messages",
    "repair_plan_archive",
    "unavailable_plan_archive_report",
]

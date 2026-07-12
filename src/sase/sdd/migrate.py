"""Migration from the legacy ``--sdd`` clone to split companion repositories."""

from __future__ import annotations

from dataclasses import dataclass
import difflib
from pathlib import Path
import re
import shutil
import subprocess

from sase.sdd._bead_ignore import ensure_bead_store_gitignore
from sase.sdd._commit import commit_sdd_files, network_git_timeout, run_sdd_git
from sase.sdd._paths import get_primary_workspace_dir
from sase.sdd._store_adoption import materialization_lock
from sase.sdd._store_records import read_sdd_store_record, write_sdd_store_record
from sase.sdd._store_types import SddMaterializationError, SddStoreRecord

_MONTH_RE = re.compile(r"^[0-9]{6}$")
_FRONTMATTER_LINK_RE = re.compile(
    r"^(?P<prefix>\s*(?:prompt|plan):\s*)(?P<quote>['\"]?)(?P<value>[^'\"\r\n]+)(?P=quote)(?P<suffix>\s*)$"
)
_LEGACY_PLAN_PREFIXES = (".sase/sdd/plans/", "sdd/plans/", "plans/")
_BEAD_DB_NAMES = {"beads.db", "beads.db-shm", "beads.db-wal"}


@dataclass(frozen=True)
class _SddMigrationAction:
    source: Path
    destination: Path
    content: bytes


@dataclass(frozen=True)
class _SddMigrationPlan:
    primary: Path
    legacy_root: Path | None
    plans_root: Path
    research_root: Path
    record: SddStoreRecord
    actions: tuple[_SddMigrationAction, ...]

    @property
    def has_changes(self) -> bool:
        return self.legacy_root is not None


def plan_split_sdd_migration(
    workspace_dir: str | Path, workspace_num: int = 1
) -> _SddMigrationPlan:
    """Return a read-only, conflict-checking split migration plan."""

    workspace = Path(workspace_dir).expanduser()
    primary = Path(
        get_primary_workspace_dir(str(workspace), workspace_num)
    ).expanduser()
    record = read_sdd_store_record(primary)
    if record is None or not record.is_companion_storage:
        raise SddMaterializationError(
            "split SDD companions are not initialized; run `sase sdd init` first"
        )
    if record.plans is None or record.research is None:
        raise SddMaterializationError("split SDD companion record is incomplete")

    plans_root = _companion_clone_dir(workspace, record.plans.repo)
    research_root = _companion_clone_dir(workspace, record.research.repo)
    legacy_root = _find_legacy_root(primary, workspace)
    if legacy_root is None:
        return _SddMigrationPlan(primary, None, plans_root, research_root, record, ())

    actions: list[_SddMigrationAction] = []
    for kind, destination_root in (
        ("plans", plans_root),
        ("research", research_root),
    ):
        source_root = legacy_root / kind
        if not source_root.is_dir():
            continue
        for month in sorted(source_root.iterdir()):
            if not month.is_dir() or _MONTH_RE.fullmatch(month.name) is None:
                continue
            for source in sorted(path for path in month.rglob("*") if path.is_file()):
                relative = source.relative_to(source_root)
                destination = destination_root / relative
                content = source.read_bytes()
                if source.suffix.casefold() == ".md":
                    content = _rewrite_frontmatter_links(content)
                _append_action(actions, source, destination, content)

    beads_root = legacy_root / "beads"
    if beads_root.is_dir():
        for source in sorted(path for path in beads_root.rglob("*") if path.is_file()):
            if source.name in _BEAD_DB_NAMES:
                continue
            destination = plans_root / "beads" / source.relative_to(beads_root)
            _append_action(actions, source, destination, source.read_bytes())

    return _SddMigrationPlan(
        primary,
        legacy_root,
        plans_root,
        research_root,
        record,
        tuple(actions),
    )


def apply_split_sdd_migration(
    workspace_dir: str | Path, workspace_num: int = 1
) -> _SddMigrationPlan:
    """Apply and push a split migration while holding the materialization lock."""

    workspace = Path(workspace_dir).expanduser()
    primary = Path(
        get_primary_workspace_dir(str(workspace), workspace_num)
    ).expanduser()
    with materialization_lock(primary):
        from sase.sdd.store import ensure_sdd_kind_clone

        ensure_sdd_kind_clone(workspace, workspace_num, "plans", strict=True)
        ensure_sdd_kind_clone(workspace, workspace_num, "research", strict=True)
        plan = plan_split_sdd_migration(workspace, workspace_num)
        if plan.legacy_root is None:
            return plan

        changed_by_root: dict[Path, list[Path]] = {
            plan.plans_root: [],
            plan.research_root: [],
        }
        for action in plan.actions:
            action.destination.parent.mkdir(parents=True, exist_ok=True)
            action.destination.write_bytes(action.content)
            root = (
                plan.plans_root
                if action.destination.is_relative_to(plan.plans_root)
                else plan.research_root
            )
            changed_by_root[root].append(action.destination)

        gitignore = ensure_bead_store_gitignore(plan.plans_root)
        if gitignore is not None:
            changed_by_root[plan.plans_root].append(gitignore)

        for kind, root in (
            ("plans", plan.plans_root),
            ("research", plan.research_root),
        ):
            companion = plan.record.companion_for_kind(kind)
            assert companion is not None
            if changed_by_root[root]:
                commit_sdd_files(
                    root,
                    f"Migrate legacy SDD {kind}",
                    auto_commit_type="sdd",
                    paths=changed_by_root[root],
                    repo_name=companion.repo,
                    record_commit_marker=False,
                )
            _push_companion(root)

        write_sdd_store_record(plan.primary, plan.record)
        shutil.rmtree(plan.legacy_root)
        return plan


def render_split_sdd_migration_diff(plan: _SddMigrationPlan) -> str:
    """Render deterministic text diffs and binary copy summaries."""

    lines: list[str] = []
    for action in plan.actions:
        try:
            before = action.source.read_text(encoding="utf-8")
            after = action.content.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            lines.append(f"copy binary {action.source} -> {action.destination}")
            continue
        diff = "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=str(action.source),
                tofile=str(action.destination),
            )
        )
        lines.append(diff or f"copy {action.source} -> {action.destination}")
    if plan.legacy_root is not None:
        lines.append(f"retire legacy clone {plan.legacy_root}")
    return "\n".join(line.rstrip("\n") for line in lines if line)


def _append_action(
    actions: list[_SddMigrationAction],
    source: Path,
    destination: Path,
    content: bytes,
) -> None:
    if destination.exists():
        if destination.is_file() and destination.read_bytes() == content:
            return
        raise SddMaterializationError(
            f"migration destination conflicts with legacy content: {destination}"
        )
    actions.append(_SddMigrationAction(source, destination, content))


def _rewrite_frontmatter_links(content: bytes) -> bytes:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return content
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return content
    in_frontmatter = True
    for index in range(1, len(lines)):
        raw = lines[index]
        ending = "\n" if raw.endswith("\n") else ""
        line = raw.rstrip("\r\n")
        if line.strip() == "---":
            in_frontmatter = False
            break
        if not in_frontmatter:
            break
        match = _FRONTMATTER_LINK_RE.match(line)
        if match is None:
            continue
        value = match.group("value").strip()
        rewritten = value
        for prefix in _LEGACY_PLAN_PREFIXES:
            if rewritten.startswith(prefix):
                rewritten = rewritten.removeprefix(prefix)
                break
        if rewritten != value:
            lines[index] = (
                f"{match.group('prefix')}{match.group('quote')}{rewritten}"
                f"{match.group('quote')}{match.group('suffix')}{ending}"
            )
    return "".join(lines).encode("utf-8")


def _find_legacy_root(primary: Path, workspace: Path) -> Path | None:
    candidates = (
        primary / ".sase" / "sdd",
        primary / "sdd",
        workspace / ".sase" / "sdd",
        workspace / "sdd",
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def _companion_clone_dir(workspace: Path, repo: str) -> Path:
    from sase.linked_repos import resolve_linked_repo_clone_dir

    return Path(
        resolve_linked_repo_clone_dir(workspace, repo.rstrip("/").rsplit("/", 1)[-1])
    )


def _push_companion(root: Path) -> None:
    try:
        run_sdd_git(
            ["push", "origin", "HEAD"],
            cwd=root,
            op="sdd.migrate.push",
            timeout=network_git_timeout(),
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, OSError) as exc:
        raise SddMaterializationError(
            f"failed to push migrated SDD companion {root}: {exc}"
        ) from exc

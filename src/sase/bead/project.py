"""BeadProject: public API for beads issue tracking."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from sase.bead import db as db_mod
from sase.bead.config import get_default_config, load_config, save_config
from sase.bead.ids import IdGenerator, max_child_counter, max_top_level_counter
from sase.bead.jsonl import export_to_jsonl
from sase.bead.model import Dependency, Issue, IssueType, Status
from sase.bead.sync import git_sync, rebuild_from_jsonl, sync_status
from sase.telemetry.metrics import (
    BEAD_ACTIVE,
    BEAD_OPERATIONS,
    BEAD_STATUS_TRANSITIONS,
)


class AlreadyReadyError(Exception):
    """Raised when an epic plan is already marked is_ready_to_work."""


class NotAPlanError(Exception):
    """Raised when mark_ready_to_work is called on a non-plan issue."""


BEADS_DIRNAME = ".sase_beads"
"""Default beads subdirectory name (used in version-controlled mode)."""

BEADS_DIRNAME_NON_VC = "beads"
"""Beads subdirectory name inside .sase/sdd/ (non-version-controlled mode)."""


class BeadProject:
    """Main API for beads issue tracking.

    Wraps the database, config, and sync layers into a single interface.
    """

    def __init__(
        self, root_dir: str | Path, beads_dirname: str = BEADS_DIRNAME
    ) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.beads_dir = self.root_dir / beads_dirname
        if not self.beads_dir.exists():
            raise FileNotFoundError(
                f"No {beads_dirname}/ directory found at {self.root_dir}. "
                "Run 'sase bead init' first."
            )
        # Rebuild from JSONL if needed (e.g., fresh clone)
        rebuild_from_jsonl(self.beads_dir)
        self._config: dict[str, object] = load_config(self.beads_dir)
        self._conn = db_mod.init_db(self.beads_dir / "beads.db")
        prefix = str(self._config.get("issue_prefix", "beads"))
        raw_counter = self._config.get("next_counter", 1)
        counter = raw_counter if isinstance(raw_counter, int) else int(str(raw_counter))
        self._id_gen = IdGenerator(prefix, counter)

    def __enter__(self) -> BeadProject:
        return self

    def __exit__(self, *_: object) -> None:
        self._conn.close()

    @staticmethod
    def init(root_dir: str | Path, beads_dirname: str = BEADS_DIRNAME) -> BeadProject:
        """Create a new beads directory and return a BeadProject."""
        root = Path(root_dir).resolve()
        beads_dir = root / beads_dirname
        beads_dir.mkdir(parents=True, exist_ok=True)
        # Write default config
        config = get_default_config(root)
        save_config(beads_dir, config)
        # Create empty database
        conn = db_mod.init_db(beads_dir / "beads.db")
        conn.close()
        # Create empty JSONL
        (beads_dir / "issues.jsonl").touch()
        return BeadProject(root, beads_dirname=beads_dirname)

    def create(
        self,
        title: str,
        issue_type: IssueType,
        parent_id: str | None = None,
        *,
        description: str = "",
        notes: str = "",
        design: str = "",
        assignee: str = "",
        changespec_name: str | int | None = "",
        changespec_bug_id: str | int | None = "",
    ) -> Issue:
        """Create a new issue.

        If *parent_id* is provided the new issue ID is hierarchical:
        ``<parent_id>.<N>`` where *N* is the next available integer.
        Otherwise the global counter-based ID generator is used.
        """
        now = _now()
        owner = str(self._config.get("owner", ""))
        if parent_id is not None:
            issue_id = self._next_child_id(parent_id)
        else:
            minimum_counter = self._next_top_level_counter()
            issue_id = self._id_gen.next_id(minimum_counter=minimum_counter)
        issue = Issue(
            id=issue_id,
            title=title,
            status=Status.OPEN,
            issue_type=issue_type,
            parent_id=parent_id,
            owner=owner,
            assignee=assignee,
            created_at=now,
            created_by=owner,
            updated_at=now,
            description=description,
            notes=notes,
            design=design,
            changespec_name=_optional_text(changespec_name),
            changespec_bug_id=_optional_text(changespec_bug_id),
        )
        db_mod.create_issue(self._conn, issue)
        BEAD_OPERATIONS.labels(operation="create").inc()
        if parent_id is None:
            self._save_counter()
        self._export()
        return issue

    def show(self, issue_id: str) -> Issue:
        """Get a single issue by ID. Raises KeyError if not found."""
        issue = db_mod.get_issue(self._conn, issue_id)
        if issue is None:
            raise KeyError(f"Issue not found: {issue_id}")
        return issue

    def list_issues(
        self,
        statuses: list[Status] | None = None,
        issue_types: list[IssueType] | None = None,
    ) -> list[Issue]:
        """List issues with optional filters."""
        issues = db_mod.list_issues(
            self._conn, statuses=statuses, issue_types=issue_types
        )
        if statuses is None:
            self._update_active_gauge(issues)
        return issues

    def ready(self) -> list[Issue]:
        """Return open issues with no active blockers."""
        return db_mod.ready_issues(self._conn)

    def update(self, issue_id: str, **fields: str | int | None) -> Issue:
        """Update fields on an issue."""
        if "is_ready_to_work" in fields:
            raise ValueError(
                "is_ready_to_work cannot be set via update(); "
                "use mark_ready_to_work() instead."
            )
        old_issue = db_mod.get_issue(self._conn, issue_id)
        if old_issue is not None:
            fields = _normalize_changespec_fields(fields)
            _validate_issue_update(old_issue, fields)
        fields["updated_at"] = _now()
        issue = db_mod.update_issue(self._conn, issue_id, **fields)
        if issue is None:
            raise KeyError(f"Issue not found: {issue_id}")
        BEAD_OPERATIONS.labels(operation="update").inc()
        if (
            old_issue is not None
            and "status" in fields
            and fields["status"] is not None
            and old_issue.status.value != fields["status"]
        ):
            BEAD_STATUS_TRANSITIONS.labels(
                from_status=old_issue.status.value,
                to_status=fields["status"],
            ).inc()
        self._export()
        return issue

    def close(self, issue_ids: list[str], reason: str | None = None) -> list[Issue]:
        """Close one or more issues.

        If a plan bead is closed, all its phase children are also closed.
        """
        now = _now()
        closed: list[Issue] = []
        for issue_id in issue_ids:
            issue = db_mod.get_issue(self._conn, issue_id)
            if issue is None:
                raise KeyError(f"Issue not found: {issue_id}")
            # Close children first if this is a plan bead
            if issue.issue_type == IssueType.PLAN:
                for child in db_mod.get_epic_children(self._conn, issue_id):
                    if child.status != Status.CLOSED:
                        old_child_status = child.status.value
                        closed_child = db_mod.close_issue(
                            self._conn, child.id, now, reason
                        )
                        if closed_child is not None:
                            BEAD_STATUS_TRANSITIONS.labels(
                                from_status=old_child_status,
                                to_status="closed",
                            ).inc()
                            closed.append(closed_child)
            old_status = issue.status.value
            issue = db_mod.close_issue(self._conn, issue_id, now, reason)
            if issue is None:
                raise KeyError(f"Issue not found: {issue_id}")
            BEAD_OPERATIONS.labels(operation="close").inc()
            BEAD_STATUS_TRANSITIONS.labels(
                from_status=old_status, to_status="closed"
            ).inc()
            closed.append(issue)
        self._export()
        return closed

    def remove(self, issue_id: str) -> list[Issue]:
        """Delete an issue and all its children.

        Returns the list of issues that were removed (the target plus any
        cascade-deleted children), ordered children-first.
        Raises KeyError if the issue does not exist.
        """
        issue = db_mod.get_issue(self._conn, issue_id)
        if issue is None:
            raise KeyError(f"Issue not found: {issue_id}")
        # Collect children before deletion (CASCADE will remove them)
        removed: list[Issue] = []
        if issue.issue_type == IssueType.PLAN:
            removed.extend(db_mod.get_epic_children(self._conn, issue_id))
        removed.append(issue)
        db_mod.delete_issue(self._conn, issue_id)
        self._export()
        return removed

    def mark_ready_to_work(self, epic_id: str) -> Issue:
        """Flip the epic plan's is_ready_to_work flag to True.

        Raises KeyError if the issue does not exist, NotAPlanError if it
        is not a plan, and AlreadyReadyError if the flag is already set.
        """
        issue = db_mod.get_issue(self._conn, epic_id)
        if issue is None:
            raise KeyError(f"Issue not found: {epic_id}")
        if issue.issue_type != IssueType.PLAN:
            raise NotAPlanError(
                f"is_ready_to_work only applies to plan beads (got "
                f"{issue.issue_type.value} for {epic_id})"
            )
        if issue.is_ready_to_work:
            raise AlreadyReadyError(
                f"{epic_id} is already marked is_ready_to_work=True"
            )
        updated = db_mod.mark_issue_ready_to_work(self._conn, epic_id, _now())
        if updated is None:
            raise KeyError(f"Issue not found: {epic_id}")
        BEAD_OPERATIONS.labels(operation="mark_ready_to_work").inc()
        self._export()
        return updated

    def unmark_ready_to_work(self, epic_id: str) -> Issue:
        """Reset is_ready_to_work=False on an epic plan bead.

        Used by ``sase bead work`` to roll the flag back when the downstream
        agent launch fails after the flag has already been flipped. The flip
        itself stays a one-way mutator via :meth:`mark_ready_to_work` — this
        is the explicit recovery hatch.

        Raises KeyError if the issue does not exist.
        """
        updated = db_mod.update_issue(
            self._conn, epic_id, is_ready_to_work=0, updated_at=_now()
        )
        if updated is None:
            raise KeyError(f"Issue not found: {epic_id}")
        self._export()
        return updated

    def add_dependency(self, issue_id: str, depends_on_id: str) -> Dependency:
        """Add a dependency: issue_id depends on depends_on_id."""
        owner = str(self._config.get("owner", ""))
        dep = db_mod.add_dependency(self._conn, issue_id, depends_on_id, _now(), owner)
        self._export()
        return dep

    def blocked(self) -> list[Issue]:
        """Return issues with at least one active blocker."""
        return db_mod.blocked_issues(self._conn)

    def sync(self) -> None:
        """Export to JSONL and stage in git."""
        self._export()
        git_sync(self.beads_dir)

    def sync_is_clean(self) -> bool:
        """Check if JSONL has uncommitted changes."""
        return sync_status(self.beads_dir)

    def stats(self) -> dict[str, int]:
        """Return counts by status and type."""
        return db_mod.stats(self._conn)

    def doctor(self) -> list[str]:
        """Run diagnostics and return messages."""
        messages: list[str] = []
        # Check config
        config_path = self.beads_dir / "config.json"
        if not config_path.exists():
            messages.append("WARNING: config.json missing")
        # Check JSONL
        jsonl_path = self.beads_dir / "issues.jsonl"
        if not jsonl_path.exists():
            messages.append("WARNING: issues.jsonl missing")
        # Check database
        db_path = self.beads_dir / "beads.db"
        if not db_path.exists():
            messages.append("WARNING: beads.db missing")
        # Check sync status
        if not sync_status(self.beads_dir):
            messages.append("WARNING: issues.jsonl has uncommitted changes")
        # Count orphan children (parent doesn't exist)
        orphans = self._conn.execute(
            "SELECT id FROM issues WHERE issue_type = 'phase' "
            "AND parent_id NOT IN (SELECT id FROM issues)"
        ).fetchall()
        if orphans:
            ids = [r["id"] for r in orphans]
            messages.append(
                f"WARNING: orphan children (missing parent): {', '.join(ids)}"
            )
        if not messages:
            messages.append("OK: no issues found")
        return messages

    def get_epic_children(self, epic_id: str) -> list[Issue]:
        """Get all child issues of an epic."""
        return db_mod.get_epic_children(self._conn, epic_id)

    def _next_child_id(self, parent_id: str) -> str:
        """Generate the next hierarchical child ID ``<parent_id>.<N>``."""
        max_n = max(
            self._max_local_child_counter(parent_id),
            max_child_counter(parent_id, self._workspace_beads_dirs()),
        )
        return f"{parent_id}.{max_n + 1}"

    def _max_local_child_counter(self, parent_id: str) -> int:
        """Return the highest direct child counter currently in the local DB."""
        prefix = f"{parent_id}."
        rows = self._conn.execute(
            "SELECT id FROM issues WHERE id LIKE ?", (f"{prefix}%",)
        ).fetchall()
        max_n = 0
        for row in rows:
            suffix = row["id"][len(prefix) :]
            # Only consider direct children (no dots in suffix)
            if "." not in suffix:
                try:
                    n = int(suffix)
                    max_n = max(max_n, n)
                except ValueError:
                    pass
        return max_n

    def _next_top_level_counter(self) -> int:
        """Return the next safe top-level counter for this workspace set."""
        prefix = str(self._config.get("issue_prefix", "beads"))
        return max(
            self._id_gen.counter,
            max_top_level_counter(prefix, self._workspace_beads_dirs()) + 1,
        )

    def _workspace_beads_dirs(self) -> list[Path]:
        """Return discovered workspace bead stores, always including this one."""
        if Path.cwd().resolve().is_relative_to(self.root_dir):
            try:
                from sase.bead.workspace import get_project_beads_dirs

                discovered = get_project_beads_dirs()
            except Exception:
                discovered = None
        else:
            discovered = None

        beads_dirs: list[Path] = []
        seen: set[Path] = set()
        for beads_dir in [*(discovered or []), self.beads_dir]:
            resolved = Path(beads_dir).resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            beads_dirs.append(resolved)
        return beads_dirs

    def _update_active_gauge(self, issues: list[Issue]) -> None:
        """Update BEAD_ACTIVE gauge from a full (unfiltered) issue list."""
        project = str(self._config.get("issue_prefix", "beads"))
        counts: dict[str, int] = {}
        for issue in issues:
            counts[issue.status.value] = counts.get(issue.status.value, 0) + 1
        for status in Status:
            BEAD_ACTIVE.labels(project=project, status=status.value).set(
                counts.get(status.value, 0)
            )

    def _export(self) -> None:
        """Export current state to JSONL."""
        export_to_jsonl(self._conn, self.beads_dir / "issues.jsonl")

    def _save_counter(self) -> None:
        """Persist the ID counter to config."""
        self._config["next_counter"] = self._id_gen.counter
        save_config(self.beads_dir, self._config)


def _now() -> str:
    """Current UTC timestamp as ISO 8601 string."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _optional_text(value: str | int | None) -> str:
    return "" if value is None else str(value)


def _normalize_changespec_fields(
    fields: dict[str, str | int | None],
) -> dict[str, str | int | None]:
    normalized = dict(fields)
    for name in ("changespec_name", "changespec_bug_id"):
        if name in normalized:
            normalized[name] = _optional_text(normalized[name])
    return normalized


def _validate_issue_update(issue: Issue, fields: dict[str, str | int | None]) -> None:
    if "changespec_name" not in fields and "changespec_bug_id" not in fields:
        return
    candidate = replace(
        issue,
        changespec_name=(
            _optional_text(fields["changespec_name"])
            if "changespec_name" in fields
            else issue.changespec_name
        ),
        changespec_bug_id=(
            _optional_text(fields["changespec_bug_id"])
            if "changespec_bug_id" in fields
            else issue.changespec_bug_id
        ),
    )
    candidate.validate()

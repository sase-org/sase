"""BeadProject: public API for beads issue tracking."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sase.bead import db as db_mod
from sase.bead.config import get_default_config, load_config, save_config
from sase.bead.ids import IdGenerator
from sase.bead.jsonl import export_to_jsonl
from sase.bead.model import Dependency, Issue, IssueType, Status
from sase.bead.sync import git_sync, rebuild_from_jsonl, sync_status


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
            issue_id = self._id_gen.next_id()
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
        )
        db_mod.create_issue(self._conn, issue)
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
        status: Status | None = None,
        issue_type: IssueType | None = None,
    ) -> list[Issue]:
        """List issues with optional filters."""
        return db_mod.list_issues(self._conn, status=status, issue_type=issue_type)

    def ready(self) -> list[Issue]:
        """Return open issues with no active blockers."""
        return db_mod.ready_issues(self._conn)

    def update(self, issue_id: str, **fields: str | None) -> Issue:
        """Update fields on an issue."""
        fields["updated_at"] = _now()
        issue = db_mod.update_issue(self._conn, issue_id, **fields)
        if issue is None:
            raise KeyError(f"Issue not found: {issue_id}")
        self._export()
        return issue

    def close(self, issue_ids: list[str], reason: str | None = None) -> list[Issue]:
        """Close one or more issues."""
        now = _now()
        closed: list[Issue] = []
        for issue_id in issue_ids:
            issue = db_mod.close_issue(self._conn, issue_id, now, reason)
            if issue is None:
                raise KeyError(f"Issue not found: {issue_id}")
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
        """Export to JSONL and commit to git."""
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
        return f"{prefix}{max_n + 1}"

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

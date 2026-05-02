"""BeadProject: public API for beads issue tracking."""

from __future__ import annotations

import contextlib
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from sase.bead import db as db_mod
from sase.bead.config import get_default_config, load_config, save_config
from sase.bead.ids import IdGenerator, max_child_counter, max_top_level_counter
from sase.bead.jsonl import export_to_jsonl
from sase.bead.model import BeadTier, Dependency, Issue, IssueType, Status
from sase.bead.sync import git_sync, rebuild_from_jsonl
from sase.telemetry.metrics import (
    BEAD_ACTIVE,
    BEAD_OPERATIONS,
    BEAD_STATUS_TRANSITIONS,
)


class AlreadyReadyError(Exception):
    """Raised when an epic plan is already marked is_ready_to_work."""


class NotAPlanError(Exception):
    """Raised when mark_ready_to_work is called on a non-plan issue."""


BEADS_DIRNAME = "sdd/beads"
"""Default beads subdirectory name (used in version-controlled mode)."""

BEADS_DIRNAME_NON_VC = "beads"
"""Beads subdirectory name inside .sase/sdd/ (non-version-controlled mode)."""


class BeadProject:
    """Main API for beads issue tracking.

    Preserves the historical Python API while delegating storage, reads, and
    mutations to Rust-backed facades. The local SQLite connection is kept as a
    compatibility mirror for legacy helpers/tests that still need one.
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
        # Keep the legacy SQLite file available for compatibility callers,
        # while the primary public API reads from Rust's JSONL-backed engine.
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
        config = get_default_config(root)
        from sase.core import bead_mutation_facade as rust_beads

        rust_beads.init_store(
            root,
            beads_dirname,
            issue_prefix=str(config.get("issue_prefix", "beads")),
            owner=str(config.get("owner", "")),
        )
        conn = db_mod.init_db(root / beads_dirname / "beads.db")
        conn.close()
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
        tier: BeadTier | str | None = None,
        changespec_name: str | int | None = "",
        changespec_bug_id: str | int | None = "",
    ) -> Issue:
        """Create a new issue.

        If *parent_id* is provided the new issue ID is hierarchical:
        ``<parent_id>.<N>`` where *N* is the next available integer.
        Otherwise the global counter-based ID generator is used.
        """
        from sase.core import bead_mutation_facade as rust_beads

        issue, _outcome = rust_beads.create(
            self.beads_dir,
            title=title,
            issue_type=issue_type,
            tier=tier,
            parent_id=parent_id,
            description=description,
            notes=notes,
            design=design,
            assignee=assignee,
            changespec_name=changespec_name,
            changespec_bug_id=changespec_bug_id,
            now=_now(),
            workspace_beads_dirs=self._workspace_beads_dirs(),
        )
        BEAD_OPERATIONS.labels(operation="create").inc()
        self._refresh_db_from_jsonl()
        return issue

    def show(self, issue_id: str) -> Issue:
        """Get a single issue by ID. Raises KeyError if not found."""
        from sase.core import bead_read_facade as rust_beads

        return rust_beads.show(self.beads_dir, issue_id)

    def list_issues(
        self,
        statuses: list[Status] | None = None,
        issue_types: list[IssueType] | None = None,
        tiers: list[BeadTier] | None = None,
    ) -> list[Issue]:
        """List issues with optional filters."""
        from sase.core import bead_read_facade as rust_beads

        issues = rust_beads.list_issues(
            self.beads_dir,
            statuses=statuses,
            issue_types=issue_types,
            tiers=tiers,
        )
        if statuses is None:
            self._update_active_gauge(issues)
        return issues

    def ready(self) -> list[Issue]:
        """Return open issues with no active blockers."""
        from sase.core import bead_read_facade as rust_beads

        return rust_beads.ready(self.beads_dir)

    def update(self, issue_id: str, **fields: str | int | None) -> Issue:
        """Update fields on an issue."""
        if "is_ready_to_work" in fields:
            raise ValueError(
                "is_ready_to_work cannot be set via update(); "
                "use mark_ready_to_work() instead."
            )
        from sase.core import bead_mutation_facade as rust_beads

        try:
            old_issue: Issue | None = self.show(issue_id)
        except KeyError:
            old_issue = None
        if old_issue is not None:
            fields = _normalize_changespec_fields(fields)
            _validate_issue_update(old_issue, fields)
        issue, _outcome = rust_beads.update(
            self.beads_dir, issue_id, **fields, now=_now()
        )
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
        self._refresh_db_from_jsonl()
        return issue

    def close(self, issue_ids: list[str], reason: str | None = None) -> list[Issue]:
        """Close one or more issues.

        If a plan bead is closed, all its phase children are also closed.
        """
        from sase.core import bead_mutation_facade as rust_beads

        old_issues: dict[str, Issue] = {}
        for issue_id in issue_ids:
            old_issue = self.show(issue_id)
            old_issues[issue_id] = old_issue
            if old_issue.issue_type == IssueType.PLAN:
                for child in self.get_epic_children(issue_id):
                    old_issues.setdefault(child.id, child)
        closed, _outcome = rust_beads.close(
            self.beads_dir, issue_ids, reason=reason, now=_now()
        )
        for issue in closed:
            BEAD_OPERATIONS.labels(operation="close").inc()
            old_status = old_issues.get(issue.id, issue).status.value
            BEAD_STATUS_TRANSITIONS.labels(
                from_status=old_status, to_status="closed"
            ).inc()
        self._refresh_db_from_jsonl()
        return closed

    def remove(self, issue_id: str) -> list[Issue]:
        """Delete an issue and all its children.

        Returns the list of issues that were removed (the target plus any
        cascade-deleted children), ordered children-first.
        Raises KeyError if the issue does not exist.
        """
        from sase.core import bead_mutation_facade as rust_beads

        removed, _outcome = rust_beads.remove(self.beads_dir, issue_id)
        self._refresh_db_from_jsonl()
        return removed

    def mark_ready_to_work(self, epic_id: str) -> Issue:
        """Flip the epic plan's is_ready_to_work flag to True.

        Raises KeyError if the issue does not exist, NotAPlanError if it
        is not a plan, and AlreadyReadyError if the flag is already set.
        """
        from sase.core import bead_mutation_facade as rust_beads

        updated, _outcome = rust_beads.mark_ready_to_work(
            self.beads_dir, epic_id, now=_now()
        )
        BEAD_OPERATIONS.labels(operation="mark_ready_to_work").inc()
        self._refresh_db_from_jsonl()
        return updated

    def unmark_ready_to_work(self, epic_id: str) -> Issue:
        """Reset is_ready_to_work=False on an epic plan bead.

        Used by ``sase bead work`` to roll the flag back when the downstream
        agent launch fails after the flag has already been flipped. The flip
        itself stays a one-way mutator via :meth:`mark_ready_to_work` — this
        is the explicit recovery hatch.

        Raises KeyError if the issue does not exist.
        """
        from sase.core import bead_mutation_facade as rust_beads

        updated, _outcome = rust_beads.unmark_ready_to_work(
            self.beads_dir, epic_id, now=_now()
        )
        self._refresh_db_from_jsonl()
        return updated

    def add_dependency(self, issue_id: str, depends_on_id: str) -> Dependency:
        """Add a dependency: issue_id depends on depends_on_id."""
        from sase.core import bead_mutation_facade as rust_beads

        dep, _outcome = rust_beads.add_dependency(
            self.beads_dir, issue_id, depends_on_id, now=_now()
        )
        self._refresh_db_from_jsonl()
        return dep

    def blocked(self) -> list[Issue]:
        """Return issues with at least one active blocker."""
        from sase.core import bead_read_facade as rust_beads

        return rust_beads.blocked(self.beads_dir)

    def sync(self) -> None:
        """Export to JSONL and stage in git."""
        self._export()
        git_sync(self.beads_dir)

    def sync_is_clean(self) -> bool:
        """Check if JSONL has uncommitted changes."""
        from sase.core import bead_mutation_facade as rust_beads

        return rust_beads.sync_is_clean(self.beads_dir)

    def stats(self) -> dict[str, int]:
        """Return counts by status and type."""
        from sase.core import bead_read_facade as rust_beads

        return rust_beads.stats(self.beads_dir)

    def doctor(self) -> list[str]:
        """Run diagnostics and return messages."""
        from sase.core import bead_read_facade as rust_beads

        messages = rust_beads.doctor(self.beads_dir)
        if not self.sync_is_clean():
            ok_message = "OK: no issues found"
            if messages == [ok_message]:
                messages = []
            messages.append("WARNING: issues.jsonl has uncommitted changes")
        return messages

    def get_epic_children(self, epic_id: str) -> list[Issue]:
        """Get all child issues of an epic."""
        from sase.core import bead_read_facade as rust_beads

        return rust_beads.get_epic_children(self.beads_dir, epic_id)

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
        from sase.core import bead_mutation_facade as rust_beads

        try:
            rust_beads.export_jsonl(self.beads_dir)
        except (AttributeError, ImportError, ValueError):
            export_to_jsonl(self._conn, self.beads_dir / "issues.jsonl")
        self._refresh_db_from_jsonl()

    def _save_counter(self) -> None:
        """Persist the ID counter to config."""
        self._config["next_counter"] = self._id_gen.counter
        save_config(self.beads_dir, self._config)

    def _refresh_db_from_jsonl(self) -> None:
        """Refresh the compatibility SQLite mirror from Rust-owned JSONL."""
        with contextlib.suppress(sqlite3.Error):
            self._conn.close()
        db_path = self.beads_dir / "beads.db"
        for suffix in ("", "-shm", "-wal"):
            path = db_path.parent / (db_path.name + suffix)
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
        rebuild_from_jsonl(self.beads_dir)
        self._conn = db_mod.init_db(db_path)
        self._config = load_config(self.beads_dir)
        raw_counter = self._config.get("next_counter", 1)
        counter = raw_counter if isinstance(raw_counter, int) else int(str(raw_counter))
        self._id_gen = IdGenerator(
            str(self._config.get("issue_prefix", "beads")), counter
        )


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

"""BeadProject: public API for beads issue tracking."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from sase.artifact_ref_models import ArtifactRefContext
from sase.bead import db as db_mod
from sase.bead.config import get_default_config, load_config, save_config
from sase.bead.ids import IdGenerator, max_top_level_counter
from sase.bead.jsonl import export_to_jsonl
from sase.bead.model import (
    BeadSearchMatch,
    BeadTier,
    Dependency,
    Issue,
    IssueType,
    PhaseSize,
    Resolution,
    Status,
)
from sase.bead.sync import (
    bead_state_is_clean,
    bead_store_write_lock,
    git_sync,
    rebuild_from_jsonl,
)


class AlreadyReadyError(Exception):
    """Raised when an epic plan is already marked is_ready_to_work."""


class NotAPlanError(Exception):
    """Raised when mark_ready_to_work is called on a non-plan issue."""


@dataclass(frozen=True)
class EpicPreclaimRollback:
    """Prior bead state returned by one atomic epic-work preclaim."""

    bead_id: str
    status: Status
    assignee: str


BEADS_DIRNAME = "sdd/beads"
"""Default beads subdirectory name (used in in-tree mode)."""

BEADS_DIRNAME_NON_VC = "beads"
"""Beads subdirectory name inside .sase/sdd/ (local/separate-repo modes)."""

BEADS_DIRNAME_ROOT = "."
"""Beads dirname that makes the dedicated sidecar root the bead directory."""


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
        self._config: dict[str, object] = load_config(self.beads_dir)
        self._conn_cache: sqlite3.Connection | None = None
        self._mutation_changed = False
        prefix = str(self._config.get("issue_prefix", "beads"))
        raw_counter = self._config.get("next_counter", 1)
        counter = raw_counter if isinstance(raw_counter, int) else int(str(raw_counter))
        self._id_gen = IdGenerator(prefix, counter)

    def __enter__(self) -> BeadProject:
        return self

    def __exit__(self, *_: object) -> None:
        self._close_connection()

    @property
    def _conn(self) -> sqlite3.Connection:
        """Open the compatibility mirror on first legacy use."""
        if self._conn_cache is None:
            rebuild_from_jsonl(self.beads_dir)
            self._conn_cache = db_mod.init_db(self.beads_dir / "beads.db")
        return self._conn_cache

    @property
    def owner(self) -> str:
        """Return the configured bead-store owner."""
        owner = self._config.get("owner", "")
        return owner if isinstance(owner, str) else str(owner)

    @property
    def mutation_changed(self) -> bool:
        """Whether any Rust-backed mutation changed this project instance."""
        return self._mutation_changed

    def _close_connection(self) -> None:
        if self._conn_cache is not None:
            self._conn_cache.close()
            self._conn_cache = None

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
        refs: list[str] | tuple[str, ...] = (),
        assignee: str = "",
        tier: BeadTier | str | None = None,
        changespec_name: str | int | None = "",
        changespec_bug_id: str | int | None = "",
        model: str = "",
        size: PhaseSize | str | None = None,
    ) -> Issue:
        """Create a new issue.

        If *parent_id* is provided the new issue ID is hierarchical:
        ``<parent_id>.<N>`` where *N* is the next available integer.
        Otherwise the global counter-based ID generator is used.
        """
        from sase.core import bead_mutation_facade as rust_beads

        issue, outcome = rust_beads.create(
            self.beads_dir,
            title=title,
            issue_type=issue_type,
            tier=tier,
            parent_id=parent_id,
            description=description,
            notes=notes,
            design=design,
            refs=refs,
            assignee=assignee,
            changespec_name=changespec_name,
            changespec_bug_id=changespec_bug_id,
            model=model,
            size=size,
            now=_now(),
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return issue

    def show(self, issue_id: str) -> Issue:
        """Get a single issue by ID. Raises KeyError if not found."""
        from sase.core import bead_read_facade as rust_beads

        return rust_beads.show(self.beads_dir, issue_id)

    def history(self, issue_id: str) -> dict[str, object]:
        """Return the ordered field-level event history for one issue."""
        from sase.core import bead_read_facade as rust_beads

        return rust_beads.history(self.beads_dir, issue_id)

    def lost_notes(
        self,
        issue_id: str | None = None,
    ) -> list[dict[str, object]]:
        """Return historical note revisions absent from current notes."""
        from sase.core import bead_read_facade as rust_beads

        return rust_beads.lost_notes(self.beads_dir, issue_id)

    def list_issues(
        self,
        statuses: list[Status] | None = None,
        issue_types: list[IssueType] | None = None,
        tiers: list[BeadTier] | None = None,
    ) -> list[Issue]:
        """List issues with optional filters."""
        from sase.core import bead_read_facade as rust_beads

        return rust_beads.list_issues(
            self.beads_dir,
            statuses=statuses,
            issue_types=issue_types,
            tiers=tiers,
        )

    def search(
        self,
        query: str,
        statuses: list[Status] | None = None,
        issue_types: list[IssueType] | None = None,
        tiers: list[BeadTier] | None = None,
        limit: int | None = None,
    ) -> list[BeadSearchMatch]:
        """Search issues with optional filters."""
        from sase.core import bead_read_facade as rust_beads

        return rust_beads.search(
            self.beads_dir,
            query,
            statuses=statuses,
            issue_types=issue_types,
            tiers=tiers,
            limit=limit,
        )

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
        issue, outcome = rust_beads.update(
            self.beads_dir, issue_id, **fields, now=_now()
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return issue

    def append_note(
        self,
        issue_id: str,
        entry: str,
        *,
        author: str | None = None,
    ) -> Issue:
        """Append one attributed entry to an issue's notes."""
        from sase.core import bead_mutation_facade as rust_beads

        issue, outcome = rust_beads.append_note(
            self.beads_dir,
            issue_id,
            entry,
            author=author,
            now=_now(),
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return issue

    def claim_for_agent_launch(self, bead_id: str, agent_name: str) -> Issue:
        """Atomically claim one non-closed bead for an agent launch."""
        issue, _changed = self.claim_for_agent_launch_outcome(bead_id, agent_name)
        return issue

    def claim_for_agent_launch_outcome(
        self, bead_id: str, agent_name: str
    ) -> tuple[Issue, bool]:
        """Claim for launch and return whether core persisted a transition."""
        from sase.core import bead_mutation_facade as rust_beads

        issue, outcome = rust_beads.claim_for_agent_launch(
            self.beads_dir,
            bead_id,
            agent_name,
            now=_now(),
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return issue, bool(outcome.get("changed", True))

    def claim_for_agent_wait(self, bead_id: str, agent_name: str) -> tuple[Issue, bool]:
        """Reserve an open bead while its owning agent waits to launch."""
        from sase.core import bead_mutation_facade as rust_beads

        issue, outcome = rust_beads.claim_for_agent_wait(
            self.beads_dir,
            bead_id,
            agent_name,
            now=_now(),
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return issue, bool(outcome["changed"])

    def release_agent_claim(self, bead_id: str, agent_name: str) -> tuple[Issue, bool]:
        """Release a waiting claim when it is still held by *agent_name*."""
        from sase.core import bead_mutation_facade as rust_beads

        issue, outcome = rust_beads.release_agent_claim(
            self.beads_dir,
            bead_id,
            agent_name,
            now=_now(),
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return issue, bool(outcome["changed"])

    def preclaim_epic_work(
        self,
        epic_id: str,
        assignments: list[tuple[str, str]],
        land_agent_name: str,
    ) -> tuple[EpicPreclaimRollback, ...]:
        """Preassign one rendered epic work plan and return rollback state."""
        from sase.core import bead_mutation_facade as rust_beads

        _issues, outcome = rust_beads.preclaim_epic_work(
            self.beads_dir,
            epic_id,
            assignments=assignments,
            land_agent_name=land_agent_name,
            now=_now(),
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return tuple(
            EpicPreclaimRollback(
                bead_id=str(record["bead_id"]),
                status=Status(str(record["status"])),
                assignee=str(record.get("assignee", "")),
            )
            for record in outcome.get("rollback_preclaims", [])
        )

    def close(
        self,
        issue_ids: list[str],
        reason: str | None = None,
        resolution: Resolution | str | None = None,
        force: bool = False,
        note: str | None = None,
        author: str | None = None,
    ) -> list[Issue]:
        """Close one or more issues.

        Descendants must already be closed unless ``force`` explicitly sweeps
        them with a non-done resolution and reason. When ``note`` is provided,
        append it to every explicitly listed issue in the same mutation.
        """
        from sase.core import bead_mutation_facade as rust_beads

        closed, outcome = rust_beads.close(
            self.beads_dir,
            issue_ids,
            reason=reason,
            resolution=resolution,
            force=force,
            note=note,
            author=author,
            now=_now(),
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return closed

    def open(self, issue_id: str) -> tuple[Issue, list[Issue]]:
        """Reopen an issue and every closed ancestor above it."""
        from sase.core import bead_mutation_facade as rust_beads
        from sase.core.bead_wire import issues_from_list

        issue, outcome = rust_beads.open_issue(
            self.beads_dir,
            issue_id,
            now=_now(),
        )
        self._record_mutation_outcome(outcome)
        reopened_ancestors = issues_from_list(outcome.get("issues", []))
        self._refresh_db_from_jsonl()
        return issue, reopened_ancestors

    def remove(self, issue_id: str) -> list[Issue]:
        """Delete an issue and all its children.

        Returns the list of issues that were removed (the target plus any
        cascade-deleted children), ordered children-first.
        Raises KeyError if the issue does not exist.
        """
        from sase.core import bead_mutation_facade as rust_beads

        removed, outcome = rust_beads.remove(self.beads_dir, issue_id)
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return removed

    def remove_many(self, issue_ids: list[str]) -> list[Issue]:
        """Atomically delete one or more issues and their descendants.

        Every requested ID is validated before mutation. The returned issues
        are unique even when requests overlap or repeat.
        """
        from sase.core import bead_mutation_facade as rust_beads

        removed, outcome = rust_beads.remove_many(self.beads_dir, issue_ids)
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return removed

    def mark_ready_to_work(self, epic_id: str) -> Issue:
        """Flip the epic plan's is_ready_to_work flag to True.

        Raises KeyError if the issue does not exist, NotAPlanError if it
        is not a plan, and AlreadyReadyError if the flag is already set.
        """
        from sase.core import bead_mutation_facade as rust_beads

        updated, outcome = rust_beads.mark_ready_to_work(
            self.beads_dir, epic_id, now=_now()
        )
        self._record_mutation_outcome(outcome)
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

        updated, outcome = rust_beads.unmark_ready_to_work(
            self.beads_dir, epic_id, now=_now()
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return updated

    def add_dependency(self, issue_id: str, depends_on_id: str) -> Dependency:
        """Add a dependency: issue_id depends on depends_on_id."""
        from sase.core import bead_mutation_facade as rust_beads

        dep, outcome = rust_beads.add_dependency(
            self.beads_dir, issue_id, depends_on_id, now=_now()
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return dep

    def remove_dependencies(
        self, issue_id: str, depends_on_ids: list[str]
    ) -> list[Dependency]:
        """Remove dependency edges from issue_id to depends_on_ids."""
        from sase.core import bead_mutation_facade as rust_beads

        dependencies, outcome = rust_beads.remove_dependencies(
            self.beads_dir, issue_id, depends_on_ids, now=_now()
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return dependencies

    def blocked(self) -> list[Issue]:
        """Return issues with at least one active blocker."""
        from sase.core import bead_read_facade as rust_beads

        return rust_beads.blocked(self.beads_dir)

    def sync(self) -> None:
        """Export compatibility projection and stage bead state in git."""
        with bead_store_write_lock(self.beads_dir) as already_locked:
            self._export()
            git_sync(self.beads_dir, already_locked=already_locked)

    def sync_is_clean(self) -> bool:
        """Check if canonical bead state has uncommitted changes."""
        return bead_state_is_clean(self.beads_dir)

    def stats(self) -> dict[str, int]:
        """Return counts by status and type."""
        from sase.core import bead_read_facade as rust_beads

        return rust_beads.stats(self.beads_dir)

    def doctor(
        self,
        plan_roots: tuple[Path, ...] | None = None,
        reference_context: ArtifactRefContext | None = None,
    ) -> list[str]:
        """Run diagnostics and return messages."""
        from sase.core import bead_read_facade as rust_beads
        from sase.bead.sync import bead_sync_diagnostics

        if plan_roots is None and reference_context is None:
            messages = rust_beads.doctor(self.beads_dir)
        else:
            messages = rust_beads.doctor(
                self.beads_dir,
                plan_roots,
                reference_context,
            )
        if not self.sync_is_clean():
            ok_message = "OK: no issues found"
            if messages == [ok_message]:
                messages = []
            messages.append("WARNING: bead state has uncommitted changes")
        sync_messages = bead_sync_diagnostics(self.beads_dir)
        if sync_messages and messages == ["OK: no issues found"]:
            messages = []
        messages.extend(sync_messages)
        return messages

    def get_epic_children(self, epic_id: str) -> list[Issue]:
        """Get all child issues of an epic."""
        from sase.core import bead_read_facade as rust_beads

        return rust_beads.get_epic_children(self.beads_dir, epic_id)

    def _next_child_id(self, parent_id: str) -> str:
        """Generate the next hierarchical child ID ``<parent_id>.<N>``."""
        max_n = self._max_local_child_counter(parent_id)
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
        """Return the next safe top-level counter for this bead store."""
        prefix = str(self._config.get("issue_prefix", "beads"))
        return max(
            self._id_gen.counter,
            max_top_level_counter(prefix, self.beads_dir) + 1,
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

    def _record_mutation_outcome(self, outcome: dict[str, object]) -> None:
        """Accumulate honest core mutation results for commit gating."""
        self._mutation_changed |= bool(outcome.get("changed", True))

    def _refresh_db_from_jsonl(self) -> None:
        """Refresh lightweight config state after a Rust-owned mutation.

        The SQLite compatibility mirror is rebuilt lazily on its next use,
        using ``issues.jsonl`` mtimes.
        """
        self._close_connection()
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

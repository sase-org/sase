"""Read and diagnostic operations for :class:`sase.bead.project.BeadProject`."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.artifact_ref_models import ArtifactRefContext
from sase.bead.model import BeadSearchMatch, BeadTier, Issue, IssueType, Status

if TYPE_CHECKING:
    from collections.abc import Callable


class BeadProjectQueryMixin:
    """Rust-backed query methods for ``BeadProject``."""

    beads_dir: Path
    sync_is_clean: Callable[[], bool]

    def show(self, issue_id: str) -> Issue:
        """Get a single issue by ID. Raises KeyError if not found."""
        from sase.core import bead_read_facade as rust_beads

        return rust_beads.show(self.beads_dir, issue_id)

    def resolve_id(self, issue_id: str) -> str:
        """Return the canonical full ID for a full or shorthand bead ID."""
        from sase.core import bead_read_facade as rust_beads

        return rust_beads.resolve_id(self.beads_dir, issue_id)

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

    def blocked(self) -> list[Issue]:
        """Return issues with at least one active blocker."""
        from sase.core import bead_read_facade as rust_beads

        return rust_beads.blocked(self.beads_dir)

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
        from sase.bead.sync import bead_sync_diagnostics
        from sase.core import bead_read_facade as rust_beads

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
        return _append_stale_prefix_diagnostic(messages, self.beads_dir)

    def doctor_report(
        self,
        plan_roots: tuple[Path, ...] | None = None,
        reference_context: ArtifactRefContext | None = None,
    ) -> dict[str, Any]:
        """Run diagnostics and return structured projection details."""
        from sase.bead.sync import bead_sync_diagnostics
        from sase.core import bead_read_facade as rust_beads

        report = rust_beads.doctor_report(
            self.beads_dir,
            plan_roots,
            reference_context,
        )
        messages = [str(message) for message in report["messages"]]
        if not self.sync_is_clean():
            ok_message = "OK: no issues found"
            if messages == [ok_message]:
                messages = []
            messages.append("WARNING: bead state has uncommitted changes")
        sync_messages = bead_sync_diagnostics(self.beads_dir)
        if sync_messages and messages == ["OK: no issues found"]:
            messages = []
        messages.extend(sync_messages)
        report["messages"] = _append_stale_prefix_diagnostic(messages, self.beads_dir)
        return report

    def get_epic_children(self, epic_id: str) -> list[Issue]:
        """Get all child issues of an epic."""
        from sase.core import bead_read_facade as rust_beads

        return rust_beads.get_epic_children(self.beads_dir, epic_id)


def _append_stale_prefix_diagnostic(messages: list[str], beads_dir: Path) -> list[str]:
    """Warn when a store's issue prefix leaked a ProjectSpec key."""
    from sase.bead.prefix_policy import stale_key_prefix_report

    report = stale_key_prefix_report(beads_dir)
    if report is None:
        return messages
    stored, corrected = report
    if messages == ["OK: no issues found"]:
        messages = []
    messages.append(
        f"WARNING: bead issue prefix '{stored}' is a ProjectSpec key; "
        f"project name is '{corrected}' "
        "(repair with: sase bead doctor --fix-issue-prefix)"
    )
    return messages

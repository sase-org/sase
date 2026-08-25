"""Agent-claim mutation operations for :class:`sase.bead.project.BeadProject`."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sase.bead._project_types import EpicPreclaimRollback
from sase.bead.model import Issue, Status

if TYPE_CHECKING:
    from collections.abc import Callable


class BeadProjectMutationClaimsMixin:
    """Rust-backed agent-claim methods for ``BeadProject``."""

    beads_dir: Path
    _current_time: Callable[[], str]
    _record_mutation_outcome: Callable[[dict[str, object]], None]
    _refresh_db_from_jsonl: Callable[[], None]

    if TYPE_CHECKING:

        def resolve_id(self, issue_id: str) -> str: ...

    def claim_for_agent_launch(self, bead_id: str, agent_name: str) -> Issue:
        """Atomically claim one non-closed bead for an agent launch."""
        issue, _changed = self.claim_for_agent_launch_outcome(bead_id, agent_name)
        return issue

    def claim_for_agent_launch_outcome(
        self, bead_id: str, agent_name: str
    ) -> tuple[Issue, bool]:
        """Claim for launch and return whether core persisted a transition."""
        from sase.core import bead_mutation_facade as rust_beads

        bead_id = self.resolve_id(bead_id)
        issue, outcome = rust_beads.claim_for_agent_launch(
            self.beads_dir,
            bead_id,
            agent_name,
            now=self._current_time(),
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return issue, bool(outcome.get("changed", True))

    def claim_for_agent_wait(self, bead_id: str, agent_name: str) -> tuple[Issue, bool]:
        """Reserve an open bead while its owning agent waits to launch."""
        from sase.core import bead_mutation_facade as rust_beads

        bead_id = self.resolve_id(bead_id)
        issue, outcome = rust_beads.claim_for_agent_wait(
            self.beads_dir,
            bead_id,
            agent_name,
            now=self._current_time(),
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return issue, bool(outcome["changed"])

    def release_agent_claim(self, bead_id: str, agent_name: str) -> tuple[Issue, bool]:
        """Release a waiting claim when it is still held by *agent_name*."""
        from sase.core import bead_mutation_facade as rust_beads

        bead_id = self.resolve_id(bead_id)
        issue, outcome = rust_beads.release_agent_claim(
            self.beads_dir,
            bead_id,
            agent_name,
            now=self._current_time(),
        )
        self._record_mutation_outcome(outcome)
        self._refresh_db_from_jsonl()
        return issue, bool(outcome["changed"])

    def preclaim_epic_work(
        self,
        epic_id: str,
        assignments: list[tuple[str, str]],
        land_agent_name: str | None,
    ) -> tuple[EpicPreclaimRollback, ...]:
        """Preassign selected epic work agents and return rollback state."""
        from sase.core import bead_mutation_facade as rust_beads

        epic_id = self.resolve_id(epic_id)
        assignments = [
            (self.resolve_id(bead_id), agent_name)
            for bead_id, agent_name in assignments
        ]
        _issues, outcome = rust_beads.preclaim_epic_work(
            self.beads_dir,
            epic_id,
            assignments=assignments,
            land_agent_name=land_agent_name,
            now=self._current_time(),
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

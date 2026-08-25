"""Name and aggregate queries for the wait-dependency artifact index."""

from __future__ import annotations

from pathlib import Path

from sase.core.agent_tribe import InvalidTribeError, parse_tribe_reference
from sase.plan_chain import planner_row_name

from ._artifact_state import same_artifact_dir
from ._index_entities import WaitDependencyEntityQueries
from ._index_fork_queries import WaitDependencyForkQueries
from ._index_identity_queries import WaitDependencyIdentityQueries
from ._tribe_binding import TribeMemberRow, resolve_tribe_wait_binding
from ._types import (
    ArtifactCandidate,
    FamilyCandidate,
    TribeCandidate,
    WAIT_SUCCESS_OUTCOMES,
    WaitCandidate,
)


class WaitDependencyIndexQueries(
    WaitDependencyForkQueries,
    WaitDependencyIdentityQueries,
    WaitDependencyEntityQueries,
):
    """Read-side operations shared by :class:`WaitDependencyIndex`."""

    clans: dict[str, dict[str, list[ArtifactCandidate]]]
    tribes: dict[str, list[ArtifactCandidate]]
    effective_clan_tribes: dict[tuple[str, str], str]
    named: dict[str, WaitCandidate]
    artifacts_by_dir: dict[str, ArtifactCandidate]

    def tribe_candidate(
        self,
        tribe: str,
        *,
        newer_than: str | None,
        exclude_artifact_dir: str | Path | None = None,
    ) -> TribeCandidate | None:
        """Return the earliest complete entity launched after *newer_than*.

        A tribe-assigned clan member enrolls its whole generation. Clan entities use
        the generation's earliest member launch as their timestamp and resolve
        only once the same member aggregate used by clan waits is successful.
        """
        if newer_than is None:
            return None

        direct_tribes_by_artifact: dict[str, set[str]] = {}
        for direct_tribe, artifacts in self.tribes.items():
            for artifact in artifacts:
                direct_tribes_by_artifact.setdefault(artifact.artifact_dir, set()).add(
                    direct_tribe
                )

        rows: list[TribeMemberRow] = []
        for artifact in self.artifacts_by_dir.values():
            direct_tribes = direct_tribes_by_artifact.get(artifact.artifact_dir)
            for member_tribe in direct_tribes or (None,):
                rows.append(
                    TribeMemberRow(
                        tribe=member_tribe,
                        launch_timestamp=artifact.timestamp,
                        identity=artifact.artifact_dir,
                        name=artifact.name,
                        clan_name=artifact.clan_name,
                        clan_generation=artifact.clan_generation,
                        effective_clan_tribe=self.effective_clan_tribes.get(
                            (artifact.clan_name, artifact.clan_generation)
                        )
                        if artifact.clan_name is not None
                        and artifact.clan_generation is not None
                        else None,
                        is_complete=artifact.is_resolved and artifact.is_done,
                        is_terminal=(
                            artifact.is_done
                            or artifact.is_failed
                            or artifact.is_identity_success
                        ),
                    )
                )

        exclude_identity = next(
            (
                artifact.artifact_dir
                for artifact in self.artifacts_by_dir.values()
                if same_artifact_dir(artifact.artifact_dir, exclude_artifact_dir)
            ),
            None,
        )
        binding = resolve_tribe_wait_binding(
            tribe,
            rows,
            newer_than=newer_than,
            exclude_identity=exclude_identity,
        )
        if (
            binding.state != "bound"
            or binding.kind is None
            or binding.name is None
            or binding.timestamp is None
        ):
            return None

        if binding.kind == "agent":
            members: tuple[ArtifactCandidate, ...]
            standalone = (
                self.artifacts_by_dir.get(binding.identity)
                if binding.identity is not None
                else None
            )
            members = (standalone,) if standalone is not None else ()
        else:
            assert binding.generation is not None
            members = tuple(
                sorted(
                    self.clans.get(binding.name, {}).get(binding.generation, []),
                    key=lambda member: member.timestamp,
                )
            )
        if not members:
            return None
        return TribeCandidate(
            tribe=tribe,
            kind=binding.kind,
            name=binding.name,
            generation=binding.generation,
            timestamp=binding.timestamp,
            members=members,
        )

    def clan_candidate(
        self,
        name: str,
        *,
        exclude_artifact_dir: str | Path | None = None,
    ) -> FamilyCandidate | None:
        """Return aggregate completion for the newest rootless clan generation."""
        entity = self._clan_entity(name, exclude_artifact_dir=exclude_artifact_dir)
        if entity is None:
            return None
        return FamilyCandidate(
            timestamp=entity.timestamp,
            is_resolved=entity.is_resolved,
            is_done=entity.is_done,
            is_identity_success=all(
                member.is_identity_success for member in entity.members
            ),
            is_failed=any(member.is_failed for member in entity.members),
        )

    def family_candidate(
        self,
        name: str,
        *,
        exclude_artifact_dir: str | Path | None = None,
    ) -> FamilyCandidate | None:
        entity = self._family_entity(name, exclude_artifact_dir=exclude_artifact_dir)
        if entity is None:
            return None
        return FamilyCandidate(
            timestamp=entity.timestamp,
            is_resolved=entity.is_resolved,
            is_done=entity.is_done,
            is_identity_success=any(
                candidate.is_identity_success for candidate in entity.members
            ),
            is_failed=any(candidate.is_failed for candidate in entity.members),
        )

    def family_candidate_for_root(
        self,
        root: ArtifactCandidate,
        *,
        exclude_artifact_dir: str | Path | None = None,
    ) -> FamilyCandidate | None:
        if root.parent_timestamp:
            return None
        family_name = root.family_name or root.name
        if not family_name:
            return None
        family_agents = self._aggregate_candidates(
            self.families.get(family_name),
            exclude_artifact_dir=exclude_artifact_dir,
        )
        if not family_agents:
            return None
        generation = self._family_generation(family_agents, root)
        if not generation:
            return None
        effective_generation = self._family_members_after_monitor_handoffs(
            tuple(generation)
        )
        handoffs_present = self._family_monitor_handoffs_have_successors(
            tuple(generation)
        )
        newest_timestamp = max(candidate.timestamp for candidate in generation)
        return FamilyCandidate(
            timestamp=newest_timestamp,
            is_resolved=(
                handoffs_present
                and all(candidate.is_resolved for candidate in effective_generation)
            ),
            is_done=any(candidate.is_done for candidate in effective_generation),
            is_identity_success=any(
                candidate.is_identity_success for candidate in effective_generation
            ),
            is_failed=any(candidate.is_failed for candidate in effective_generation),
        )

    def workflow_candidate(
        self,
        name: str,
        *,
        exclude_artifact_dir: str | Path | None = None,
    ) -> WaitCandidate | None:
        # Workflow-name aggregates intentionally retain the queued exclusion:
        # including sequential workflow steps here can deadlock their promotion.
        entity = self._workflow_entity(name, exclude_artifact_dir=exclude_artifact_dir)
        if entity is None:
            return None

        return WaitCandidate(
            timestamp=entity.timestamp,
            is_resolved=entity.is_resolved,
            is_done=entity.is_done,
        )

    def _planner_row_candidate(self, name: str) -> WaitCandidate | None:
        """Return a submitted-planner-row candidate for a legacy-spelled wait.

        A ``%wait`` on a legacy planner-row spelling (``base.plan``) resolves to
        the canonical ``base--plan`` named candidate. Canonical names already
        hit ``self.named`` directly, so they are skipped here.
        """
        alias = planner_row_name(name, include_legacy_dash=True)
        if alias is None or alias == name:
            return None
        return self.named.get(alias)

    def is_resolved(
        self,
        name: str,
        *,
        exclude_artifact_dir: str | Path | None = None,
        newer_than: str | None = None,
    ) -> bool:
        if name.startswith("@"):
            try:
                tribe = parse_tribe_reference(name)
            except InvalidTribeError:
                return False
            assert tribe is not None
            return (
                self.tribe_candidate(
                    tribe,
                    newer_than=newer_than,
                    exclude_artifact_dir=exclude_artifact_dir,
                )
                is not None
            )

        candidates = [
            candidate
            for candidate in (
                self.clan_candidate(name, exclude_artifact_dir=exclude_artifact_dir),
                self.family_candidate(name, exclude_artifact_dir=exclude_artifact_dir),
                self.workflow_candidate(
                    name,
                    exclude_artifact_dir=exclude_artifact_dir,
                ),
                self.named.get(name),
                self._planner_row_candidate(name),
            )
            if candidate is not None
        ]
        if not candidates:
            return False

        latest = max(candidates, key=lambda candidate: candidate.timestamp)
        return (
            (newer_than is None or latest.timestamp > newer_than)
            and latest.is_resolved
            and latest.is_done
        )

    def terminal_blocking_artifacts_for_name(
        self,
        name: str,
        *,
        exclude_artifact_dir: str | Path | None = None,
        newer_than: str | None = None,
    ) -> tuple[ArtifactCandidate, ...]:
        if name.startswith("@"):
            return ()

        entities = [
            entity
            for entity in (
                self._clan_entity(name, exclude_artifact_dir=exclude_artifact_dir),
                self._family_entity(name, exclude_artifact_dir=exclude_artifact_dir),
                self._workflow_entity(name, exclude_artifact_dir=exclude_artifact_dir),
                self._named_entity(name),
            )
            if entity is not None
        ]
        if not entities:
            return ()
        latest = max(entities, key=lambda entity: entity.timestamp)
        if newer_than is not None and latest.timestamp <= newer_than:
            return ()
        if latest.is_resolved and latest.is_done:
            return ()
        return tuple(
            member
            for member in latest.members
            if member.has_done_marker
            and member.outcome is not None
            and member.outcome not in WAIT_SUCCESS_OUTCOMES
        )

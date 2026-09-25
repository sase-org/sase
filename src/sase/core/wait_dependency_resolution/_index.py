"""Wait-dependency artifact index."""

from __future__ import annotations

from sase.plan_chain import (
    agent_session_parallel_value,
    agent_session_value,
)

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.core.agent_clan_tribe import ClanTribeMemberWire, resolve_clan_tribe
from sase.core.dismissed_agent_completion import (
    ArchivedAgentCompletion,
    load_archived_agent_completions,
)
from sase.core.agent_tribe import (
    InvalidTribeError,
    RawAgentTribeIdentity,
    canonicalize_agent_tribe_metadata,
    load_raw_agent_tribes,
    validate_tribe_name,
)

from ._artifact_state import (
    agent_session_base_from_meta,
    artifact_failed_for_identity,
    artifact_is_resolved,
    artifact_succeeded_for_identity,
    done_outcome_from_data,
    shell_followup_handoff_agent,
    shell_member_kind_for_meta,
    waiting_marker_crossed_dependency_barrier,
)
from ._index_queries import WaitDependencyIndexQueries
from ._json_io import read_json_dict
from ._submitted_plans import plan_path_marker, submitted_plan_artifact
from ._tribe_binding import TribeMemberRow
from ._types import (
    WAIT_SUCCESS_OUTCOMES,
    ArtifactCandidate,
    WaitCandidate,
)

_NO_RECORDED_TRIBE: object = object()
"""Sentinel for "the clan record carries no tribe for this generation"."""


@dataclass
class WaitDependencyIndex(WaitDependencyIndexQueries):
    named: dict[str, WaitCandidate]
    workflows: dict[str, list[ArtifactCandidate]]
    agent_sessions: dict[str, list[ArtifactCandidate]]
    clans: dict[str, dict[str, list[ArtifactCandidate]]]
    tribes: dict[str, list[ArtifactCandidate]]
    effective_clan_tribes: dict[tuple[str, str], str]
    agent_tribes: dict[RawAgentTribeIdentity, str]
    global_stored_tribes: tuple[str, ...]
    artifacts: dict[tuple[str, str], ArtifactCandidate]
    artifacts_by_dir: dict[str, ArtifactCandidate]
    _artifacts_by_dir_key_cache: dict[str, ArtifactCandidate] | None = field(
        init=False,
        repr=False,
        compare=False,
        default=None,
    )
    _tribe_member_rows_cache: list[TribeMemberRow] | None = field(
        init=False,
        repr=False,
        compare=False,
        default=None,
    )
    _clan_record_cache: dict[str, dict[str, Any] | None] = field(
        init=False,
        repr=False,
        compare=False,
        default_factory=dict,
    )

    @classmethod
    def empty(
        cls,
        *,
        agent_tribes_path: Path | str | None = None,
        legacy_agent_tags_path: Path | str | None = None,
        global_stored_tribes: tuple[str, ...] = (),
    ) -> WaitDependencyIndex:
        return cls(
            named={},
            workflows={},
            agent_sessions={},
            clans={},
            tribes={},
            effective_clan_tribes={},
            agent_tribes=load_raw_agent_tribes(
                agent_tribes_path,
                legacy_path=legacy_agent_tags_path,
            ),
            global_stored_tribes=global_stored_tribes,
            artifacts={},
            artifacts_by_dir={},
        )

    @classmethod
    def build(
        cls,
        project_name: str,
        *,
        projects_root: Path | str | None = None,
        agent_tribes_path: Path | str | None = None,
        legacy_agent_tags_path: Path | str | None = None,
        global_stored_tribes: tuple[str, ...] = (),
    ) -> WaitDependencyIndex:
        index = cls.empty(
            agent_tribes_path=agent_tribes_path,
            legacy_agent_tags_path=legacy_agent_tags_path,
            global_stored_tribes=global_stored_tribes,
        )
        artifacts = []
        for artifact_dir in iter_agent_artifact_dirs(
            project_name,
            "ace-run",
            projects_root=projects_root,
        ):
            meta = read_json_dict(artifact_dir / "agent_meta.json")
            if meta is not None:
                artifacts.append((artifact_dir, meta, project_name))
        index.add_many(artifacts)
        return index

    def add_many(
        self,
        artifacts: Iterable[tuple[Path, dict[str, Any], str]],
    ) -> None:
        """Add artifact rows using one dismissed-archive fallback query."""

        prepared = [
            (
                artifact_dir,
                meta,
                project_name,
                read_json_dict(artifact_dir / "done.json"),
            )
            for artifact_dir, meta, project_name in artifacts
        ]
        archived = load_archived_agent_completions(
            (artifact_dir, meta, project_name)
            for artifact_dir, meta, project_name, done_data in prepared
            if done_data is None and not (artifact_dir / "done.json").exists()
        )
        for artifact_dir, meta, project_name, done_data in prepared:
            self._add_prepared(
                artifact_dir,
                meta,
                project_name=project_name,
                done_data=done_data,
                archived_completion=archived.get(str(artifact_dir)),
            )

    def add(
        self,
        artifact_dir: Path,
        meta: dict[str, Any],
        *,
        project_name: str = "",
    ) -> None:
        """Add one artifact, using a one-row archive fallback batch."""

        done_path = artifact_dir / "done.json"
        done_data = read_json_dict(done_path)
        archived = (
            load_archived_agent_completions(((artifact_dir, meta, project_name),))
            if done_data is None and not done_path.exists()
            else {}
        )
        self._add_prepared(
            artifact_dir,
            meta,
            project_name=project_name,
            done_data=done_data,
            archived_completion=archived.get(str(artifact_dir)),
        )

    def add_scan_record(
        self,
        artifact_dir: Path,
        meta: dict[str, Any],
        *,
        project_name: str = "",
        done_data: dict[str, Any] | None = None,
    ) -> None:
        """Index one snapshot record without reading marker files from disk."""

        self._add_prepared(
            artifact_dir,
            meta,
            project_name=project_name,
            done_data=done_data,
            archived_completion=None,
        )

    def _add_prepared(
        self,
        artifact_dir: Path,
        meta: dict[str, Any],
        *,
        project_name: str,
        done_data: dict[str, Any] | None,
        archived_completion: ArchivedAgentCompletion | None,
    ) -> None:
        self._invalidate_query_caches()
        done_path = artifact_dir / "done.json"
        if done_data is not None:
            outcome = done_outcome_from_data(done_data)
            is_resolved = artifact_is_resolved(artifact_dir, meta, outcome)
            is_done = outcome in WAIT_SUCCESS_OUTCOMES
            is_identity_success = artifact_succeeded_for_identity(done_data)
            is_failed = artifact_failed_for_identity(done_data)
            archived_completion = None
            has_done_marker = True
        elif archived_completion is not None:
            outcome = archived_completion.outcome
            is_resolved = archived_completion.is_resolved
            is_done = archived_completion.is_done
            is_identity_success = archived_completion.is_identity_success
            is_failed = archived_completion.is_failed
            has_done_marker = False
        else:
            outcome = None
            is_resolved = artifact_is_resolved(artifact_dir, meta, outcome)
            is_done = False
            is_identity_success = False
            is_failed = False
            has_done_marker = False
        is_queued = (
            (artifact_dir / "waiting.json").exists()
            and not done_path.exists()
            and archived_completion is None
        )
        is_dependency_parked = (
            is_queued
            and not waiting_marker_crossed_dependency_barrier(artifact_dir, meta)
        )
        timestamp = artifact_dir.name

        name = meta.get("name")
        if isinstance(name, str):
            self._record_named_candidate(
                name,
                WaitCandidate(
                    timestamp=timestamp,
                    is_resolved=is_resolved,
                    is_done=is_done,
                    is_failed=is_failed,
                    name=name,
                    project_name=project_name,
                    artifact_dir=str(artifact_dir),
                    outcome=outcome,
                    has_done_marker=has_done_marker,
                ),
            )

        # A submitted-and-waiting planner row has no successful done.json, so it
        # never feeds the workflow/agent-session aggregate below. Index it as a
        # resolved named candidate under its canonical ``<base>--plan`` row name
        # so a ``%wait`` on that planner row unblocks while the plan is in
        # review, without making the whole plan chain look complete.
        plan_artifact = submitted_plan_artifact(
            meta=meta,
            plan_path_marker=plan_path_marker(artifact_dir),
            outcome=outcome,
        )
        if plan_artifact is not None:
            self._record_named_candidate(
                plan_artifact.planner_row_name,
                WaitCandidate(timestamp=timestamp, is_resolved=True, is_done=True),
                prefer_on_tie=True,
            )

        workflow_name = meta.get("workflow_name")
        agent_session_name = agent_session_base_from_meta(meta)
        parent_timestamp = (
            meta.get("parent_timestamp")
            if isinstance(meta.get("parent_timestamp"), str)
            else None
        )
        clan_name = meta.get("agent_clan")
        if not isinstance(clan_name, str) or not clan_name:
            # legacy agent-family spelling: pre-rename metas carry
            # ``agent_family``; ``agent_session_value`` reads the new key first.
            session_name = agent_session_value(meta)
            if (
                agent_session_parallel_value(meta) is True
                and isinstance(session_name, str)
                and session_name
            ):
                clan_name = session_name
        if not isinstance(clan_name, str) or not clan_name:
            clan_name = None
        generation: str | None = None
        if clan_name is not None:
            generation_value = meta.get("agent_clan_generation")
            generation = (
                generation_value
                if isinstance(generation_value, str) and generation_value
                else parent_timestamp or timestamp
            )
        clan_tribe = self._valid_tribe(meta.get("clan_tribe"))
        artifact = ArtifactCandidate(
            name=name if isinstance(name, str) else str(workflow_name or ""),
            timestamp=timestamp,
            project_name=project_name,
            artifact_dir=str(artifact_dir),
            parent_timestamp=parent_timestamp,
            agent_session_name=agent_session_name,
            is_resolved=is_resolved,
            is_done=is_done,
            is_identity_success=is_identity_success,
            is_failed=is_failed,
            is_queued=is_queued,
            is_dependency_parked=is_dependency_parked,
            clan_name=clan_name,
            clan_generation=generation,
            clan_tribe=clan_tribe,
            archived_completion=archived_completion,
            outcome=outcome,
            has_done_marker=has_done_marker,
            shell_followup_agent=shell_followup_handoff_agent(meta, done_data),
            shell_member_kind=shell_member_kind_for_meta(meta),
        )
        if project_name:
            self.artifacts[(project_name, timestamp)] = artifact
        self.artifacts_by_dir[str(artifact_dir)] = artifact

        if isinstance(workflow_name, str):
            self.workflows.setdefault(workflow_name, []).append(artifact)
            if agent_session_name is not None:
                self.agent_sessions.setdefault(agent_session_name, []).append(artifact)

        if clan_name is not None and generation is not None:
            self.clans.setdefault(clan_name, {}).setdefault(generation, []).append(
                artifact
            )
            self._refresh_effective_clan_tribe(clan_name, generation)

        canonical_meta = canonicalize_agent_tribe_metadata(dict(meta))
        direct_tribes = {
            tribe
            for tribe in (
                self._valid_tribe(canonical_meta.get("tribe")),
                self._posthoc_tribe(meta, timestamp),
            )
            if tribe is not None
        }
        for tribe in direct_tribes:
            self.tribes.setdefault(tribe, []).append(artifact)

    def _invalidate_query_caches(self) -> None:
        self._artifacts_by_dir_key_cache = None
        self._tribe_member_rows_cache = None

    @staticmethod
    def _valid_tribe(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        try:
            return validate_tribe_name(value)
        except InvalidTribeError:
            return None

    def _posthoc_tribe(self, meta: Mapping[str, Any], timestamp: str) -> str | None:
        cl_name = meta.get("cl_name")
        if not isinstance(cl_name, str) or not cl_name:
            return None
        for agent_type in ("workflow", "run"):
            tribe = self.agent_tribes.get((agent_type, cl_name, timestamp))
            if tribe is not None:
                return tribe
        return None

    def _clan_record(self, clan_name: str) -> dict[str, Any] | None:
        """Return one clan's durable record, loading it at most once."""
        if clan_name in self._clan_record_cache:
            return self._clan_record_cache[clan_name]
        record: dict[str, Any] | None = None
        try:
            from sase.core.agent_clan_record import load_clan_record

            loaded = load_clan_record(clan_name)
            record = loaded if isinstance(loaded, dict) else None
        except Exception:  # noqa: BLE001 - record overlay is best-effort.
            record = None
        self._clan_record_cache[clan_name] = record
        return record

    def _recorded_clan_tribe(
        self,
        clan_name: str,
        generation: str,
    ) -> str | None | object:
        """Return the record's tribe for *(clan, generation)*.

        Returns the ``_NO_RECORDED_TRIBE`` sentinel when the record has no
        tribe for this generation, the tribe string when recorded, and
        ``None`` for an explicit edited-unset tombstone.
        """
        record = self._clan_record(clan_name)
        if record is None:
            return _NO_RECORDED_TRIBE
        generations = record.get("generations")
        if not isinstance(generations, dict):
            return _NO_RECORDED_TRIBE
        generation_record = generations.get(generation)
        if not isinstance(generation_record, dict):
            return _NO_RECORDED_TRIBE
        tribe_record = generation_record.get("tribe")
        if not isinstance(tribe_record, dict):
            return _NO_RECORDED_TRIBE
        if "value" not in tribe_record:
            return _NO_RECORDED_TRIBE
        value = tribe_record.get("value")
        if value is None:
            if tribe_record.get("source") == "edited":
                return None
            return _NO_RECORDED_TRIBE
        if not isinstance(value, str) or not value:
            return _NO_RECORDED_TRIBE
        valid = self._valid_tribe(value)
        return valid if valid is not None else _NO_RECORDED_TRIBE

    def _refresh_effective_clan_tribe(
        self,
        clan_name: str,
        generation: str,
    ) -> None:
        members = self.clans[clan_name][generation]
        key = (clan_name, generation)
        recorded = self._recorded_clan_tribe(clan_name, generation)
        if recorded is not _NO_RECORDED_TRIBE:
            if recorded is None:
                self.effective_clan_tribes.pop(key, None)
            else:
                self.effective_clan_tribes[key] = recorded  # type: ignore[assignment]
            return
        resolution = resolve_clan_tribe(
            clan_name,
            generation,
            [
                ClanTribeMemberWire(
                    agent_clan=clan_name,
                    agent_clan_generation=generation,
                    launch_timestamp=member.timestamp,
                    identity=member.artifact_dir,
                    clan_tribe=member.clan_tribe,
                )
                for member in members
            ],
        )
        if resolution.tribe is None:
            self.effective_clan_tribes.pop(key, None)
        else:
            self.effective_clan_tribes[key] = resolution.tribe

    def _record_named_candidate(
        self,
        name: str,
        candidate: WaitCandidate,
        *,
        prefer_on_tie: bool = False,
    ) -> None:
        """Keep the newest named candidate, preferring *candidate* on ties.

        ``prefer_on_tie`` lets a submitted-planner row override the ordinary
        same-artifact candidate it shares a timestamp with.
        """
        latest = self.named.get(name)
        if (
            latest is None
            or candidate.timestamp > latest.timestamp
            or (prefer_on_tie and candidate.timestamp == latest.timestamp)
        ):
            self.named[name] = candidate


def build_wait_dependency_index(
    project_name: str,
    *,
    projects_root: Path | str | None = None,
    agent_tribes_path: Path | str | None = None,
    legacy_agent_tags_path: Path | str | None = None,
    global_stored_tribes: tuple[str, ...] = (),
) -> WaitDependencyIndex:
    return WaitDependencyIndex.build(
        project_name,
        projects_root=projects_root,
        agent_tribes_path=agent_tribes_path,
        legacy_agent_tags_path=legacy_agent_tags_path,
        global_stored_tribes=global_stored_tribes,
    )

"""Collect and enrich per-session observations."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from sase.instructions import fingerprints as fp
from sase.instructions import run_index as runs
from sase.instructions._verify_observers import (
    observe_claude,
    observe_codex,
    observe_grok,
    observe_muse,
)
from sase.instructions.models import SessionObservation


def _tri_or(left: bool | None, right: bool | None) -> bool | None:
    if left is True or right is True:
        return True
    if left is None or right is None:
        return None
    return False


def _as_tri(value: object) -> bool | None:
    return value if isinstance(value, bool) or value is None else None


def collect_observations(
    scored_runs: list[runs.ScoredRun],
) -> list[SessionObservation]:
    """Collect one observation per provider session."""
    observations: list[SessionObservation] = []
    home = runs.home_h1()
    for run in scored_runs:
        project = runs.project_h1(run.workspace_dir)
        if run.provider == "claude":
            observations.extend(observe_claude(run, home, project))
        elif run.provider == "codex":
            observations.extend(observe_codex(run, home, project))
        elif run.provider == "grok":
            observations.extend(observe_grok(run, project))
        elif run.provider == "muse":
            observations.extend(observe_muse(run, home, project))
        elif run.provider == "agy":
            observations.append(
                SessionObservation(
                    provider="agy",
                    run_name=run.name,
                    session_id=run.artifact_dir,
                    contract_count=0,
                    home=False,
                    project=None,
                    directive=None,
                    native_full_count=0,
                    foreign=None,
                )
            )
    observations = _drop_foreign_observations(observations, scored_runs)
    return _enrich_delivery_columns(observations, scored_runs)


def _drop_foreign_observations(
    observations: list[SessionObservation], scored_runs: list[runs.ScoredRun]
) -> list[SessionObservation]:
    """Drop root sessions (and their Claude helpers) from other invocations."""
    from sase.instructions.coverage_records import (
        run_manifest_records,
        session_is_foreign,
    )
    from sase.instructions.coverage_sessions import root_sessions

    if not observations:
        return observations
    sessions = root_sessions(scored_runs)
    by_run_records = {
        run.artifact_dir: run_manifest_records(run.artifact_dir) for run in scored_runs
    }
    foreign = {
        (session.run_name, session.session_id)
        for session in sessions
        if session_is_foreign(session, by_run_records.get(session.artifact_dir, []))
    }
    if not foreign:
        return observations
    kept: list[SessionObservation] = []
    for item in observations:
        if item.helper_type is None:
            if (item.run_name, item.session_id) in foreign:
                continue
        elif any(
            item.run_name == run_name and item.session_id.startswith(f"{session_id}/")
            for run_name, session_id in foreign
        ):
            continue
        kept.append(item)
    return kept


def _enrich_delivery_columns(
    observations: list[SessionObservation], scored_runs: list[runs.ScoredRun]
) -> list[SessionObservation]:
    """Associate transcripts with manifests and score exact bundle markers."""
    from sase.instructions.coverage_records import (
        delivery_label,
        matching_manifests,
        manifest_layer_included,
        run_manifest_records,
    )
    from sase.instructions.coverage_sessions import root_sessions

    sessions = root_sessions(scored_runs)
    by_run_records = {
        run.artifact_dir: run_manifest_records(run.artifact_dir) for run in scored_runs
    }
    observation_index = {
        (item.run_name, item.provider, item.session_id): index
        for index, item in enumerate(observations)
        if item.helper_type is None
    }
    enriched = list(observations)
    matched_roots: list[tuple[Any, Any, int]] = []
    for session in sessions:
        index = observation_index.get(
            (session.run_name, session.provider, session.session_id)
        )
        if index is None:
            continue
        records = by_run_records.get(session.artifact_dir, [])
        matches = matching_manifests(session, records)
        if not matches:
            continue
        record = matches[0]
        item = enriched[index]
        bundle_count: int | None = None
        if record.delivery_status == "explicit" and record.invocation_id:
            found = fp.count_bundle_markers(
                session.bundle_markers, record.invocation_id
            )
            bundle_count = None if session.partial and found == 0 else found
        channels = {name: dict(values) for name, values in item.channels.items()}
        home_native = _as_tri(channels.get("home", {}).get("native"))
        project_native = _as_tri(channels.get("project", {}).get("native"))
        home_explicit = _as_tri(channels.get("home", {}).get("explicit"))
        project_explicit = _as_tri(channels.get("project", {}).get("explicit"))
        if record.delivery_status == "explicit":
            visible = bundle_count is not None and bundle_count > 0
            home_explicit = (
                manifest_layer_included(record, "home")
                if visible
                else (None if session.partial else False)
            )
            project_explicit = (
                manifest_layer_included(record, "project")
                if visible
                else (None if session.partial else False)
            )
            channels.setdefault("home", {})["explicit"] = home_explicit
            channels.setdefault("project", {})["explicit"] = project_explicit
        enriched[index] = replace(
            item,
            home=(
                _tri_or(home_native, home_explicit)
                if home_native is not None or home_explicit is not None
                else item.home
            ),
            project=(
                _tri_or(project_native, project_explicit)
                if project_native is not None or project_explicit is not None
                else item.project
            ),
            channels=channels,
            bundle_count=bundle_count,
            delivery=delivery_label(record),
            home_expected=(
                manifest_layer_included(record, "home")
                if record.delivery_status == "explicit"
                else None
            ),
            bundle_markers=session.bundle_markers,
        )
        matched_roots.append((session, record, index))

    # Claude helper prompts use the helper sha and the root invocation id.
    for session, record, _root_index in matched_roots:
        if session.provider != "claude" or not record.invocation_id:
            continue
        delivery = record.manifest.get("delivery")
        subagent = delivery.get("subagent") if isinstance(delivery, dict) else None
        if not isinstance(subagent, dict) or subagent.get("status") != "explicit":
            continue
        helper_sha = subagent.get("bundle_sha256")
        if not isinstance(helper_sha, str):
            helper_sha = None
        for index, helper in enumerate(enriched):
            if (
                helper.provider != "claude"
                or helper.run_name != session.run_name
                or helper.helper_type is None
                or not helper.session_id.startswith(f"{session.session_id}/")
            ):
                continue
            helper_bundle_count = (
                fp.count_bundle_markers(
                    helper.bundle_markers,
                    record.invocation_id,
                    bundle_sha256=helper_sha,
                )
                if helper_sha
                else 0
            )
            root_bundle_count = fp.count_bundle_markers(
                helper.bundle_markers,
                record.invocation_id,
                bundle_sha256=record.bundle_sha256,
            )
            enriched[index] = replace(
                helper,
                helper_bundle=helper_bundle_count > 0,
                root_bundle_in_helper=root_bundle_count,
            )
    return enriched

"""Invocation-exact delivery matching and the deep conformance doctor check."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import hashlib
from pathlib import Path

from sase.instructions import coverage_records
from sase.instructions.coverage_records import ManifestRecord, matching_manifests
from sase.instructions.coverage_sessions import RootSession
from sase.instructions import claude, codex, fingerprints, grok, muse
from sase.instructions.models import SessionObservation
from sase.instructions.run_index import ScoredRun


def _record(
    artifacts: Path,
    *,
    seq: int,
    invocation: str,
    rendered_at: datetime,
    status: str = "explicit",
    subagent: dict[str, object] | None = None,
    fallback: dict[str, str] | None = None,
) -> ManifestRecord:
    delivery: dict[str, object] = {
        "status": status,
        "invocation_id": invocation,
        "session_ids": [],
        "rendered_at": rendered_at.isoformat(),
        "subagent": subagent,
    }
    if fallback is not None:
        delivery["fallback"] = fallback
    manifest = {
        "facts": {"provider": "claude", "purpose": "ordinary"},
        "bundle": {"sha256": "0123456789ab" + "0" * 52},
        "delivery": delivery,
        "sections": [
            {"id": "home.core.note", "layer": "home", "status": "included"},
            {"id": "proj.core.note", "layer": "project", "status": "included"},
        ],
    }
    return ManifestRecord(
        artifact_dir=str(artifacts),
        seq=seq,
        provider="claude",
        purpose="ordinary",
        rendered_at=rendered_at,
        render_ms=None,
        cache=None,
        manifest_path=f"instructions/{seq:02d}-claude.json",
        manifest=manifest,
        invocation_id=invocation,
        delivery_status=status,
        fallback_reason=fallback.get("reason") if fallback else None,
        bundle_sha256=str(manifest["bundle"]["sha256"]),
    )


def test_marker_invocation_precedes_provider_time_match(tmp_path: Path) -> None:
    """A marker ties a session to its exact manifest, even if it is older."""
    older = _record(
        tmp_path,
        seq=0,
        invocation="invocation-exact",
        rendered_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    newer = _record(
        tmp_path,
        seq=1,
        invocation="invocation-later",
        rendered_at=datetime(2026, 10, 2, tzinfo=UTC),
    )
    session = RootSession(
        provider="claude",
        run_name="agent-a",
        artifact_dir=str(tmp_path),
        workspace_dir="/work/synthetic",
        session_id="session-a",
        session_start=datetime(2026, 10, 3, tzinfo=UTC),
        bundle_markers=(("0123456789ab", "invocation-exact"),),
    )
    assert matching_manifests(session, [newer, older]) == [older]


def test_real_bundle_marker_round_trips_every_explicit_channel(
    tmp_path: Path, monkeypatch
) -> None:
    """The actual delivered-text marker is visible in each provider channel."""
    from sase.llm_provider.instruction_delivery import delivered_text
    from sase.instructions.manifests import read_run_manifests
    from tests.instructions.fixture_shadow import write_real_shadow_run

    monkeypatch.setenv("SASE_INSTRUCTIONS_HOME", str(tmp_path / "instructions-home"))
    artifacts, manifest, bundle = write_real_shadow_run(tmp_path, provider="codex")
    invocation = manifest["delivery"]["invocation_id"]
    manifest["delivery"].update(
        status="explicit",
        channel="codex.developer_instructions",
        session_ids=["session-by-id"],
    )
    (artifacts / "instructions" / "00-codex.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    delivered = delivered_text(bundle, manifest["bundle"]["sha256"], invocation)
    provider_sources = {
        "claude": claude.instruction_sources(
            [
                {
                    "type": "attachment",
                    "attachment": {
                        "type": "prompt_snapshot",
                        "systemPrompt": [delivered],
                    },
                }
            ]
        ),
        "codex": codex.instruction_sources(
            [
                {
                    "payload": {
                        "type": "message",
                        "role": "developer",
                        "content": [{"text": delivered}],
                    }
                }
            ]
        ),
        "grok": grok.instruction_sources({}, f"<human_rules>{delivered}</human_rules>"),
        "muse": muse.instruction_sources(
            [{"prompt": f"{delivered}\n\n--- User Prompt ---\nTask."}]
        ),
    }
    for native, explicit in provider_sources.values():
        assert native == []
        assert (
            fingerprints.count_bundle_markers(
                fingerprints.bundle_markers(explicit), invocation
            )
            == 1
        )
        assert fingerprints.count_contract_occurrences(explicit) == 1

    helper_bundle = "# SASE Helper Instructions\n\nReturn findings to the root.\n"
    helper_sha = hashlib.sha256(helper_bundle.encode()).hexdigest()
    helper_text = delivered_text(helper_bundle, helper_sha, invocation)
    helper_records = [
        {
            "type": "attachment",
            "attachment": {
                "type": "prompt_snapshot",
                "systemPrompt": [helper_text],
            },
        }
    ]
    _helper_native, helper_explicit = claude.instruction_sources(helper_records)
    helper_markers = fingerprints.bundle_markers(helper_explicit)
    assert (
        fingerprints.count_bundle_markers(
            helper_markers, invocation, bundle_sha256=helper_sha
        )
        == 1
    )
    assert (
        fingerprints.count_bundle_markers(
            helper_markers,
            invocation,
            bundle_sha256=manifest["bundle"]["sha256"],
        )
        == 0
    )

    entry = read_run_manifests(artifacts)[0]
    record = coverage_records.record_from_entry(entry, artifacts)
    assert record is not None
    session = RootSession(
        provider="codex",
        run_name="agent-real",
        artifact_dir=str(artifacts),
        workspace_dir="/work/synthetic",
        session_id="session-by-id",
        session_start=datetime(2026, 10, 1, tzinfo=UTC),
    )
    assert matching_manifests(session, [record]) == [record]


def test_session_id_precedes_provider_time_match(tmp_path: Path) -> None:
    """Recorded adapter session ids match even when rendered_at is late."""
    record = _record(
        tmp_path,
        seq=0,
        invocation="invocation-session",
        rendered_at=datetime(2026, 10, 5, tzinfo=UTC),
    )
    record = ManifestRecord(
        **{
            **record.__dict__,
            "session_ids": ("session-by-id",),
        }
    )
    session = RootSession(
        provider="claude",
        run_name="agent-b",
        artifact_dir=str(tmp_path),
        workspace_dir="/work/synthetic",
        session_id="session-by-id",
        session_start=datetime(2026, 10, 1, tzinfo=UTC),
    )
    assert matching_manifests(session, [record]) == [record]


def _doctor_context(tmp_path: Path):
    from sase.doctor.runner import DoctorContext

    return DoctorContext(cwd=tmp_path, project=None, sase_home=tmp_path / ".sase")


def test_conformance_warns_for_duplicate_root_and_leaked_helper_markers(
    tmp_path: Path, monkeypatch
) -> None:
    """The deep check names root duplicates, helper gaps, and root leaks."""
    from sase.doctor import checks_instructions
    from sase.instructions import coverage_records, coverage_sessions, run_index

    now = datetime.now(tz=UTC)
    run = ScoredRun(
        provider="claude",
        name="agent-c",
        workspace_dir="/work/synthetic",
        artifact_dir=str(tmp_path),
        started_at=now,
        ended_at=None,
        project=None,
    )
    root_record = _record(
        tmp_path,
        seq=0,
        invocation="root-invocation",
        rendered_at=now,
        subagent={"status": "explicit", "bundle_sha256": "abcdef123456"},
    )
    session = RootSession(
        provider="claude",
        run_name=run.name,
        artifact_dir=str(tmp_path),
        workspace_dir=run.workspace_dir,
        session_id="root-session",
        session_start=now,
        bundle_markers=(("0123456789ab", "root-invocation"),) * 2,
    )
    observations = [
        SessionObservation(
            provider="claude",
            run_name=run.name,
            session_id="root-session",
            contract_count=1,
            native_full_count=0,
            bundle_count=2,
            delivery="explicit",
        ),
        SessionObservation(
            provider="claude",
            run_name=run.name,
            session_id="root-session/agent-1",
            contract_count=0,
            helper_type="general-purpose",
            helper_bundle=False,
            root_bundle_in_helper=1,
        ),
    ]
    monkeypatch.setattr(run_index, "enumerate_runs", lambda **_kwargs: [run])
    monkeypatch.setattr(
        coverage_records, "run_manifest_records", lambda _adir: [root_record]
    )
    monkeypatch.setattr(coverage_sessions, "root_sessions", lambda _runs: [session])
    monkeypatch.setattr(
        "sase.instructions.verify.collect_observations", lambda _runs: observations
    )
    monkeypatch.setattr(
        "sase.instructions.manifests.read_run_manifests", lambda _adir: []
    )
    check = checks_instructions._check_instructions_conformance(
        _doctor_context(tmp_path)
    )
    assert check.status == "WARN"
    assert "root marker 2×" in check.summary
    assert "helper marker missing" in check.summary
    assert "root marker leaked" in check.summary


def test_conformance_skips_without_explicit_manifests(
    tmp_path: Path, monkeypatch
) -> None:
    from sase.doctor import checks_instructions
    from sase.instructions import run_index

    monkeypatch.setattr(run_index, "enumerate_runs", lambda **_kwargs: [])
    check = checks_instructions._check_instructions_conformance(
        _doctor_context(tmp_path)
    )
    assert check.status == "SKIP"

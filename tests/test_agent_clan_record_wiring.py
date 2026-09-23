"""Regression tests for clan-record wiring (bead sase-170.3).

A clan's summary and tribe are recorded durably per clan generation, so they
survive member kills, dismissals, relaunches, and full reloads. These tests
exercise the sase-side wiring against the real ``sase_core_rs`` bindings:
launch recording, capture before deletion, the scan overlay on full/bounded/
delta loads, and the wait-index tribe overlay.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.core.agent_clan_record import (
    capture_clan_record_from_artifacts,
    clan_attribute_update,
    clan_records_dir,
    load_clan_record,
    record_clan_attributes,
)
from sase.core.agent_scan_facade import (
    _options_to_dict,
    scan_agent_artifact_dirs,
    scan_agent_artifacts,
)
from sase.core.agent_scan_wire_records import AgentArtifactScanOptionsWire

CLAN = "wiring-clan"
GENERATION = "20260504120000"
DECLARER_TS = "20260504120000"
MEMBER_TS = "20260504120100"
JOINER_TS = "20260504120200"
SUMMARY = "Audit authentication and authorization"
TRIBE = "study"


def _write_meta(artifact_dir: Path, meta: dict[str, Any]) -> Path:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return artifact_dir


def _declarer_meta() -> dict[str, Any]:
    return {
        "name": f"{CLAN}.lead",
        "agent_clan": CLAN,
        "agent_clan_generation": GENERATION,
        "clan_tribe": TRIBE,
        "clan_summary": SUMMARY,
    }


def _member_meta(name: str = f"{CLAN}.worker") -> dict[str, Any]:
    return {
        "name": name,
        "agent_clan": CLAN,
        "agent_clan_generation": GENERATION,
    }


def _make_projects_root(tmp_path: Path) -> Path:
    return tmp_path / "projects"


def _ace_dir(projects_root: Path, timestamp: str) -> Path:
    return projects_root / "myproj" / "artifacts" / "ace-run" / timestamp


def _record_declared(
    artifacts_dir: str,
    *,
    summary: str | None = SUMMARY,
    tribe: str | None = TRIBE,
) -> None:
    update: dict[str, Any] = {"clan": CLAN, "generation": GENERATION}
    if tribe is not None:
        update["tribe"] = clan_attribute_update(
            tribe, "declared", source_identity=artifacts_dir
        )
    if summary is not None:
        update["summary"] = clan_attribute_update(
            summary, "declared", source_identity=artifacts_dir
        )
    outcome = record_clan_attributes(update, strict=True)
    assert outcome is not None and outcome["changed"] is True


def _clan_context_for(
    snapshot: Any, clan: str = CLAN, generation: str = GENERATION
) -> Any:
    matches = [
        context
        for context in snapshot.clan_context
        if context.agent_clan == clan and context.agent_clan_generation == generation
    ]
    assert len(matches) == 1
    return matches[0]


def test_facade_strict_surfaces_errors_and_soft_mode_swallows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    assert clan_records_dir().name == "agent_clans"

    with pytest.raises(ValueError):
        record_clan_attributes(
            {"clan": "", "generation": GENERATION},
            strict=True,
        )
    assert (
        record_clan_attributes(
            {"clan": "", "generation": GENERATION},
        )
        is None
    )


def test_capture_is_noop_for_non_clan_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    plain = tmp_path / "artifacts" / DECLARER_TS
    _write_meta(plain, {"name": "lonely"})
    assert capture_clan_record_from_artifacts(plain) is None
    assert load_clan_record(CLAN) is None
    assert not (tmp_path / ".sase" / "agent_clans").exists()


def test_capture_preserves_declarer_on_dismiss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dismissing the declarer captures its attributes before removal."""
    import shutil

    from sase.core.agent_cleanup_execution import try_delete_agent_artifacts

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    projects_root = _make_projects_root(tmp_path)
    declarer = _write_meta(_ace_dir(projects_root, DECLARER_TS), _declarer_meta())
    _write_meta(_ace_dir(projects_root, MEMBER_TS), _member_meta())

    # The real deletion path: capture runs inside try_delete, then the
    # dismiss/kill flow removes the directory.
    assert try_delete_agent_artifacts(str(declarer)) is True
    shutil.rmtree(declarer)

    after = scan_agent_artifacts(projects_root)
    context = _clan_context_for(after)
    assert context.clan_summary == SUMMARY
    assert context.clan_tribe == TRIBE


def test_recorded_summary_survives_declarer_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Launch-recorded values survive once the declarer directory is gone."""
    import shutil

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    projects_root = _make_projects_root(tmp_path)
    declarer = _write_meta(_ace_dir(projects_root, DECLARER_TS), _declarer_meta())
    _write_meta(_ace_dir(projects_root, MEMBER_TS), _member_meta())
    _record_declared(str(declarer))

    before = scan_agent_artifacts(projects_root)
    context = _clan_context_for(before)
    assert context.clan_summary == SUMMARY
    assert context.clan_tribe == TRIBE

    shutil.rmtree(declarer)

    after = scan_agent_artifacts(projects_root)
    context = _clan_context_for(after)
    assert context.clan_summary == SUMMARY
    assert context.clan_tribe == TRIBE


def test_recorded_summary_survives_wipe_remove(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.names._wipe_execute import _remove_artifact_dirs

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    projects_root = _make_projects_root(tmp_path)
    declarer = _write_meta(_ace_dir(projects_root, DECLARER_TS), _declarer_meta())
    _write_meta(_ace_dir(projects_root, MEMBER_TS), _member_meta())
    _record_declared(str(declarer))

    errors: list[str] = []
    removed = _remove_artifact_dirs({declarer}, errors)
    assert errors == []
    assert removed == {declarer}

    after = scan_agent_artifacts(projects_root)
    context = _clan_context_for(after)
    assert context.clan_summary == SUMMARY
    assert context.clan_tribe == TRIBE


def test_relaunched_join_member_sees_recorded_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    from sase.core.agent_cleanup_execution import try_delete_agent_artifacts

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    projects_root = _make_projects_root(tmp_path)
    declarer = _write_meta(_ace_dir(projects_root, DECLARER_TS), _declarer_meta())
    _record_declared(str(declarer))
    assert try_delete_agent_artifacts(str(declarer)) is True
    shutil.rmtree(declarer)

    # A relaunched join-form member carries no summary of its own.
    _write_meta(
        _ace_dir(projects_root, JOINER_TS),
        _member_meta(f"{CLAN}.retry1"),
    )
    snapshot = scan_agent_artifacts(projects_root)
    context = _clan_context_for(snapshot)
    assert context.clan_summary == SUMMARY
    assert context.clan_tribe == TRIBE


def test_bounded_and_delta_scans_keep_recorded_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    projects_root = _make_projects_root(tmp_path)
    declarer = _write_meta(_ace_dir(projects_root, DECLARER_TS), _declarer_meta())
    member = _write_meta(_ace_dir(projects_root, MEMBER_TS), _member_meta())
    _record_declared(str(declarer))

    bounded = scan_agent_artifacts(
        projects_root,
        AgentArtifactScanOptionsWire(not_before_timestamp=MEMBER_TS),
    )
    assert _clan_context_for(bounded).clan_summary == SUMMARY

    delta = scan_agent_artifact_dirs(projects_root, [member])
    assert _clan_context_for(delta).clan_summary == SUMMARY
    assert _clan_context_for(delta).clan_tribe == TRIBE


def test_scan_options_default_records_dir_and_explicit_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    defaulted = _options_to_dict(AgentArtifactScanOptionsWire())
    assert defaulted["clan_records_dir"] == str(clan_records_dir())

    explicit = _options_to_dict(
        AgentArtifactScanOptionsWire(clan_records_dir="/tmp/custom-clans")
    )
    assert explicit["clan_records_dir"] == "/tmp/custom-clans"


def test_capture_binding_error_does_not_break_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.core import agent_clan_record
    from sase.core.agent_cleanup_execution import try_delete_agent_artifacts

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    def _boom(artifacts_dir: Any, **kwargs: Any) -> Any:
        raise RuntimeError("record store down")

    monkeypatch.setattr(agent_clan_record, "capture_clan_record_from_artifacts", _boom)
    victim = tmp_path / "artifacts" / DECLARER_TS
    _write_meta(victim, _declarer_meta())
    (victim / "workflow_state.json").write_text("{}", encoding="utf-8")
    (victim / "done.json").write_text("{}", encoding="utf-8")
    assert try_delete_agent_artifacts(str(victim)) is True
    assert not (victim / "workflow_state.json").exists()
    assert not (victim / "done.json").exists()


def _launch_plan() -> SimpleNamespace:
    return SimpleNamespace(clan_name=CLAN, generation=GENERATION)


def test_launch_records_declared_literal_summary_and_tribe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.axe.run_agent_directive_clans import record_clan_attributes_at_launch

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    artifacts_dir = str(tmp_path / "artifacts" / DECLARER_TS)
    directives = SimpleNamespace(
        clan_declared=True,
        clan_tribe=TRIBE,
        clan_summary=SUMMARY,
        clan_summary_script=None,
    )
    record_clan_attributes_at_launch(
        artifacts_dir=artifacts_dir,
        clan_membership_plan=_launch_plan(),
        directives=directives,
        epic_clan_summary_script=None,
        epic_work_metadata={},
        resolved_summary=SUMMARY,
        used_summary_script=None,
    )
    record = load_clan_record(CLAN, strict=True)
    assert record is not None
    generation = record["generations"][GENERATION]
    assert generation["tribe"]["value"] == TRIBE
    assert generation["tribe"]["source"] == "declared"
    assert generation["summary"]["value"] == SUMMARY
    assert generation["summary"]["source"] == "declared"


def test_launch_records_declared_script_and_propagated_tribe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.axe.run_agent_directive_clans import record_clan_attributes_at_launch

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    artifacts_dir = str(tmp_path / "artifacts" / DECLARER_TS)
    directives = SimpleNamespace(
        clan_declared=True,
        clan_tribe=None,
        clan_summary=None,
        clan_summary_script="./describe",
    )
    record_clan_attributes_at_launch(
        artifacts_dir=artifacts_dir,
        clan_membership_plan=_launch_plan(),
        directives=directives,
        epic_clan_summary_script=None,
        epic_work_metadata={"clan_tribe": "epic"},
        resolved_summary=SUMMARY,
        used_summary_script="./describe",
    )
    record = load_clan_record(CLAN, strict=True)
    assert record is not None
    generation = record["generations"][GENERATION]
    assert generation["summary_script"]["value"] == "./describe"
    assert generation["summary_script"]["source"] == "declared"
    assert generation["summary"]["source"] == "script"
    assert generation["tribe"]["value"] == "epic"
    assert generation["tribe"]["source"] == "propagated"


def test_launch_records_epic_nominee_and_fill_only_tribe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.axe.run_agent_directive_clans import record_clan_attributes_at_launch

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    artifacts_dir = str(tmp_path / "artifacts" / MEMBER_TS)
    directives = SimpleNamespace(
        clan_declared=False,
        clan_tribe=None,
        clan_summary=None,
        clan_summary_script=None,
    )
    record_clan_attributes_at_launch(
        artifacts_dir=artifacts_dir,
        clan_membership_plan=_launch_plan(),
        directives=directives,
        epic_clan_summary_script="epic-script",
        epic_work_metadata={"clan_tribe": "epic"},
        resolved_summary=SUMMARY,
        used_summary_script="epic-script",
    )
    record = load_clan_record(CLAN, strict=True)
    assert record is not None
    generation = record["generations"][GENERATION]
    assert generation["summary"]["source"] == "script"
    assert generation["summary_script"]["source"] == "propagated"

    # A fill-only propagated tribe must not overwrite an edited tribe.
    edited = record_clan_attributes(
        {
            "clan": CLAN,
            "generation": GENERATION,
            "tribe": clan_attribute_update(
                "edited-tribe", "edited", source_identity="tui"
            ),
        },
        strict=True,
    )
    assert edited is not None and edited["changed"] is True
    record_clan_attributes_at_launch(
        artifacts_dir=artifacts_dir,
        clan_membership_plan=_launch_plan(),
        directives=directives,
        epic_clan_summary_script=None,
        epic_work_metadata={"clan_tribe": "epic"},
        resolved_summary=None,
        used_summary_script=None,
    )
    reread = load_clan_record(CLAN, strict=True)
    assert reread is not None
    assert reread["generations"][GENERATION]["tribe"]["value"] == "edited-tribe"


def _wait_meta(
    name: str,
    *,
    clan_tribe: str | None = "epic",
    generation: str = GENERATION,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "name": name,
        "agent_clan": CLAN,
        "agent_clan_generation": generation,
    }
    if clan_tribe is not None:
        meta["clan_tribe"] = clan_tribe
    return meta


def test_wait_index_honors_recorded_tribe_over_member_epic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.core.wait_dependency_resolution import WaitDependencyIndex

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    outcome = record_clan_attributes(
        {
            "clan": CLAN,
            "generation": GENERATION,
            "tribe": clan_attribute_update(TRIBE, "edited", source_identity="tui"),
        },
        strict=True,
    )
    assert outcome is not None and outcome["changed"] is True

    index = WaitDependencyIndex.empty()
    index.add_scan_record(
        Path(f"/artifacts/{MEMBER_TS}"),
        _wait_meta(f"{CLAN}.worker"),
        project_name="proj",
    )
    assert index.effective_clan_tribes[(CLAN, GENERATION)] == TRIBE


def test_wait_index_tombstone_clears_effective_tribe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.core.wait_dependency_resolution import WaitDependencyIndex

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    outcome = record_clan_attributes(
        {
            "clan": CLAN,
            "generation": GENERATION,
            "tribe": clan_attribute_update(None, "edited", source_identity="tui"),
        },
        strict=True,
    )
    assert outcome is not None and outcome["changed"] is True

    index = WaitDependencyIndex.empty()
    index.add_scan_record(
        Path(f"/artifacts/{MEMBER_TS}"),
        _wait_meta(f"{CLAN}.worker"),
        project_name="proj",
    )
    assert (CLAN, GENERATION) not in index.effective_clan_tribes


def test_wait_index_loads_each_clan_record_once_per_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.core import agent_clan_record
    from sase.core.wait_dependency_resolution import WaitDependencyIndex

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    calls: list[str] = []
    real_load = agent_clan_record.load_clan_record

    def _counting_load(clan: str, **kwargs: Any) -> Any:
        calls.append(clan)
        return real_load(clan, **kwargs)

    monkeypatch.setattr(agent_clan_record, "load_clan_record", _counting_load)
    index = WaitDependencyIndex.empty()
    index.add_scan_record(
        Path(f"/artifacts/{MEMBER_TS}"),
        _wait_meta(f"{CLAN}.one"),
        project_name="proj",
    )
    index.add_scan_record(
        Path(f"/artifacts/{JOINER_TS}"),
        _wait_meta(f"{CLAN}.two"),
        project_name="proj",
    )
    assert calls == [CLAN]


def test_refresh_records_script_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    outcome = record_clan_attributes(
        {
            "clan": CLAN,
            "generation": GENERATION,
            "summary": clan_attribute_update(
                SUMMARY, "script", source_identity="launch"
            ),
        },
        strict=True,
    )
    assert outcome is not None
    record = load_clan_record(CLAN, strict=True)
    assert record is not None
    assert record["generations"][GENERATION]["summary"]["value"] == SUMMARY


def test_scan_echo_parses_records_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    projects_root = _make_projects_root(tmp_path)
    _write_meta(_ace_dir(projects_root, MEMBER_TS), _member_meta())
    snapshot = scan_agent_artifacts(projects_root)
    assert snapshot.options.clan_records_dir == str(clan_records_dir())
    again = scan_agent_artifacts(
        projects_root,
        replace(snapshot.options, clan_records_dir=snapshot.options.clan_records_dir),
    )
    assert again.options.clan_records_dir == snapshot.options.clan_records_dir

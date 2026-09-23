"""Launch-default inheritance for new clan generations (bead sase-170.5).

When a launch creates a new generation of a previously recorded clan without
explicit tribe or summary, the remembered tribe is inherited, the remembered
summary script is re-run (falling back to the remembered text), both are
recorded as ``inherited``, and an agent-log line names the source
generations.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.axe.run_agent_directive_clans import (
    apply_clan_launch_defaults,
    _is_new_clan_generation,
)
from sase.core.agent_clan_record import (
    clan_attribute_update,
    load_clan_record,
    record_clan_attributes,
)

CLAN = "launch-defaults-clan"
OLD_GEN = "20260504120000"
NEW_GEN = "20260601120000"
OTHER_GEN = "20260602120000"
TRIBE = "study"
SUMMARY = "Audit authentication and authorization"


def _directives(
    *,
    tribe: str | None = None,
    summary: str | None = None,
    script: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        clan_tribe=tribe,
        clan_summary=summary,
        clan_summary_script=script,
    )


def _plan(generation: str = NEW_GEN) -> SimpleNamespace:
    return SimpleNamespace(clan_name=CLAN, generation=generation)


def _apply_kwargs(
    tmp_path: Path,
    *,
    plan: SimpleNamespace,
    directives: SimpleNamespace,
    agent_meta: dict[str, Any],
    preserved: dict[str, Any] | None = None,
    epic_tribe: str | None = None,
    epic_script: str | None = None,
    log_name: str = "agent.log",
) -> dict[str, Any]:
    artifacts_dir = tmp_path / "artifacts" / plan.generation
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(tmp_path / log_name)
    return {
        "artifacts_dir": str(artifacts_dir),
        "workspace_dir": str(tmp_path),
        "output_path": output_path,
        "launch_environment": dict(os.environ),
        "clan_membership_plan": plan,
        "directives": directives,
        "epic_work_metadata": {"clan_tribe": epic_tribe} if epic_tribe else {},
        "epic_clan_summary_script": epic_script,
        "preserved_metadata": dict(preserved or {}),
        "agent_meta": agent_meta,
    }


def _record_old(
    old_artifacts: str,
    *,
    tribe: str | None = TRIBE,
    summary: str | None = SUMMARY,
    script: str | None = None,
    tribe_source: str = "declared",
    summary_source: str = "declared",
) -> None:
    update: dict[str, Any] = {"clan": CLAN, "generation": OLD_GEN}
    if tribe is not None:
        update["tribe"] = clan_attribute_update(
            tribe, tribe_source, source_identity=old_artifacts
        )
    if script is not None:
        update["summary_script"] = clan_attribute_update(
            script, "declared", source_identity=old_artifacts
        )
    if summary is not None:
        update["summary"] = clan_attribute_update(
            summary, summary_source, source_identity=old_artifacts
        )
    outcome = record_clan_attributes(update, strict=True)
    assert outcome is not None and outcome["changed"] is True


def test_is_new_generation_compares_artifacts_basename() -> None:
    assert _is_new_clan_generation(
        clan_membership_plan=_plan(NEW_GEN),
        artifacts_dir=f"/tmp/artifacts/{NEW_GEN}",
    )
    assert not _is_new_clan_generation(
        clan_membership_plan=_plan(OLD_GEN),
        artifacts_dir=f"/tmp/artifacts/{NEW_GEN}",
    )


def test_new_generation_inherits_tribe_and_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    _record_old(str(tmp_path / "artifacts" / OLD_GEN))

    agent_meta: dict[str, Any] = {}
    kwargs = _apply_kwargs(
        tmp_path,
        plan=_plan(),
        directives=_directives(),
        agent_meta=agent_meta,
    )
    resolution, summary, script = apply_clan_launch_defaults(**kwargs)

    assert agent_meta["clan_tribe"] == TRIBE
    assert agent_meta["clan_summary"] == SUMMARY
    assert summary == SUMMARY
    assert script is None
    assert resolution is None
    record = load_clan_record(CLAN, strict=True)
    assert record is not None
    inherited = record["generations"][NEW_GEN]
    assert inherited["tribe"]["value"] == TRIBE
    assert inherited["tribe"]["source"] == "inherited"
    assert inherited["summary"]["value"] == SUMMARY
    assert inherited["summary"]["source"] == "inherited"
    log_text = Path(kwargs["output_path"]).read_text(encoding="utf-8")
    assert CLAN in log_text and OLD_GEN in log_text and NEW_GEN in log_text


def test_explicit_values_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    _record_old(str(tmp_path / "artifacts" / OLD_GEN))

    agent_meta: dict[str, Any] = {"clan_tribe": "explicit"}
    kwargs = _apply_kwargs(
        tmp_path,
        plan=_plan(),
        directives=_directives(tribe="explicit", summary="mine"),
        agent_meta=agent_meta,
    )
    # Explicit summary already in meta simulates the explicit launch block.
    agent_meta["clan_summary"] = "mine"
    resolution, summary, script = apply_clan_launch_defaults(**kwargs)

    assert (resolution, summary, script) == (None, None, None)
    assert agent_meta == {"clan_tribe": "explicit", "clan_summary": "mine"}
    assert load_clan_record(CLAN, strict=True)["generations"].get(NEW_GEN) is None


def test_remembered_script_is_rerun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    script_path = tmp_path / "describe"
    script_path.write_text("#!/bin/sh\necho fresh-output\n", encoding="utf-8")
    script_path.chmod(0o755)
    _record_old(
        str(tmp_path / "artifacts" / OLD_GEN),
        summary="stale",
        script=str(script_path),
    )

    agent_meta: dict[str, Any] = {}
    kwargs = _apply_kwargs(
        tmp_path,
        plan=_plan(),
        directives=_directives(),
        agent_meta=agent_meta,
    )
    resolution, summary, script = apply_clan_launch_defaults(**kwargs)

    assert summary == "fresh-output"
    assert agent_meta["clan_summary"] == "fresh-output"
    assert script == str(script_path)
    assert resolution is not None and resolution.script == str(script_path)
    record = load_clan_record(CLAN, strict=True)
    assert record is not None
    inherited = record["generations"][NEW_GEN]
    assert inherited["summary_script"]["value"] == str(script_path)
    assert inherited["summary_script"]["source"] == "inherited"
    assert inherited["summary"]["value"] == "fresh-output"


def test_script_failure_falls_back_to_remembered_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    script_path = tmp_path / "failing"
    script_path.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    script_path.chmod(0o755)
    _record_old(
        str(tmp_path / "artifacts" / OLD_GEN),
        summary=SUMMARY,
        script=str(script_path),
    )

    agent_meta: dict[str, Any] = {}
    kwargs = _apply_kwargs(
        tmp_path,
        plan=_plan(),
        directives=_directives(),
        agent_meta=agent_meta,
    )
    resolution, summary, script = apply_clan_launch_defaults(**kwargs)

    assert summary == SUMMARY
    assert agent_meta["clan_summary"] == SUMMARY
    assert script == str(script_path)
    assert resolution is not None


def test_join_existing_generation_unaffected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    _record_old(str(tmp_path / "artifacts" / OLD_GEN))

    # Joining the old generation from a newer artifacts dir is not creation.
    plan = _plan(OLD_GEN)
    agent_meta: dict[str, Any] = {}
    kwargs = _apply_kwargs(
        tmp_path,
        plan=plan,
        directives=_directives(),
        agent_meta=agent_meta,
    )
    # Point the artifacts dir at a different basename than the generation.
    kwargs["artifacts_dir"] = str(tmp_path / "artifacts" / NEW_GEN)
    Path(kwargs["artifacts_dir"]).mkdir(parents=True, exist_ok=True)
    assert apply_clan_launch_defaults(**kwargs) == (None, None, None)
    assert agent_meta == {}


def test_tombstoned_tribe_is_not_inherited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    _record_old(str(tmp_path / "artifacts" / OLD_GEN))
    tombstone = record_clan_attributes(
        {
            "clan": CLAN,
            "generation": OTHER_GEN,
            "tribe": clan_attribute_update(None, "edited", source_identity="tui"),
        },
        strict=True,
    )
    assert tombstone is not None and tombstone["changed"] is True

    agent_meta: dict[str, Any] = {}
    kwargs = _apply_kwargs(
        tmp_path,
        plan=_plan(),
        directives=_directives(),
        agent_meta=agent_meta,
    )
    _, summary, _ = apply_clan_launch_defaults(**kwargs)
    assert "clan_tribe" not in agent_meta
    # Summary has no tombstone, so it still inherits.
    assert summary == SUMMARY


def test_no_record_nothing_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    agent_meta: dict[str, Any] = {}
    kwargs = _apply_kwargs(
        tmp_path,
        plan=_plan(),
        directives=_directives(),
        agent_meta=agent_meta,
    )
    assert apply_clan_launch_defaults(**kwargs) == (None, None, None)
    assert agent_meta == {}
    assert not Path(kwargs["output_path"]).exists()


def test_reexec_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    _record_old(str(tmp_path / "artifacts" / OLD_GEN))

    agent_meta: dict[str, Any] = {}
    kwargs = _apply_kwargs(
        tmp_path,
        plan=_plan(),
        directives=_directives(),
        agent_meta=agent_meta,
    )
    first = apply_clan_launch_defaults(**kwargs)
    assert first[1] == SUMMARY
    log_path = Path(kwargs["output_path"])
    first_log = log_path.read_text(encoding="utf-8")

    # Runner re-exec: preserved metadata already carries the inherited values.
    preserved = {"clan_tribe": TRIBE, "clan_summary": SUMMARY}
    agent_meta2: dict[str, Any] = dict(preserved)
    kwargs2 = _apply_kwargs(
        tmp_path,
        plan=_plan(),
        directives=_directives(),
        agent_meta=agent_meta2,
        preserved=preserved,
        log_name="agent.log",
    )
    # Reuse the same log file to prove no second line is appended.
    kwargs2["output_path"] = str(log_path)
    assert apply_clan_launch_defaults(**kwargs2) == (None, None, None)
    assert log_path.read_text(encoding="utf-8") == first_log

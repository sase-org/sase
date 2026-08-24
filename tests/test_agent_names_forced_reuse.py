"""Tests for the shared forced-reuse cleanup primitive.

``wipe_force_reuse_owner()`` is the shared agent-name-layer operation behind
both the ACE/``sase agent restart`` launch boundary and deterministic bead
relaunch. These tests seed a real name registry (rather than mocking the
low-level wipe) to prove a family-root forced reuse replaces the newest
family generation deterministically, leaves an enclosing clan and unrelated
agents untouched, tolerates a member that a concurrent cleanup proc already
removed, and still refuses a populated clan container directly.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.names import (
    ForcedReuseCleanupError,
    get_reserved_agent_names,
    lookup_registered_name,
    rebuild_name_registry,
    wipe_force_reuse_owner,
)


def _artifact(
    home: Path,
    suffix: str,
    name: str,
    *,
    project: str = "proj",
    done: bool = False,
    meta: dict[str, object] | None = None,
) -> Path:
    workflow_dir = home / ".sase" / "projects" / project / "artifacts" / "ace-run"
    path = workflow_dir / suffix
    path.mkdir(parents=True, exist_ok=True)
    payload = {"name": name, "workflow_name": name, **(meta or {})}
    (path / "agent_meta.json").write_text(json.dumps(payload), encoding="utf-8")
    if done:
        (path / "done.json").write_text(
            json.dumps({"name": name, "outcome": "completed"}),
            encoding="utf-8",
        )
    return path


def test_wipe_force_reuse_owner_replaces_newest_family_generation(
    tmp_path: Path,
) -> None:
    family_name = "epic.phase"
    plan_name = f"{family_name}--plan"
    code_name = f"{family_name}--code"
    family_meta = {"agent_family": family_name, "agent_family_parallel": False}
    plan = _artifact(tmp_path, "20260801120000", plan_name, done=True, meta=family_meta)
    code = _artifact(
        tmp_path,
        "20260801120100",
        code_name,
        meta={**family_meta, "parent_timestamp": plan.name},
    )
    sibling = _artifact(tmp_path, "20260801120200", "unrelated", done=True)

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        assert {family_name, plan_name, code_name} <= get_reserved_agent_names()

        wipe_force_reuse_owner(family_name, allow_container_skip=False)

        assert not plan.exists()
        assert not code.exists()
        assert {family_name, plan_name, code_name}.isdisjoint(
            get_reserved_agent_names()
        )
        assert "unrelated" in get_reserved_agent_names()
        assert sibling.exists()


def test_wipe_force_reuse_owner_family_preserves_enclosing_clan(
    tmp_path: Path,
) -> None:
    clan_name = "sase-sq"
    family_name = f"{clan_name}.1"
    plan_name = f"{family_name}--plan"
    code_name = f"{family_name}--code"
    family_meta = {
        "agent_family": family_name,
        "agent_family_parallel": False,
        "agent_clan": clan_name,
        "agent_clan_generation": "gen-1",
    }
    plan = _artifact(tmp_path, "20260801130000", plan_name, done=True, meta=family_meta)
    code = _artifact(
        tmp_path,
        "20260801130100",
        code_name,
        meta={**family_meta, "parent_timestamp": plan.name},
    )
    sibling_phase = f"{clan_name}.2"
    sibling = _artifact(
        tmp_path,
        "20260801130200",
        sibling_phase,
        done=True,
        meta={"agent_clan": clan_name, "agent_clan_generation": "gen-1"},
    )

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        clan_owner = lookup_registered_name(clan_name)
        assert clan_owner is not None
        assert clan_owner["container_kind"] == "clan"

        wipe_force_reuse_owner(family_name, allow_container_skip=False)

        assert {family_name, plan_name, code_name}.isdisjoint(
            get_reserved_agent_names()
        )
        assert not plan.exists()
        assert not code.exists()
        assert sibling_phase in get_reserved_agent_names()
        assert sibling.exists()

        clan_owner_after = lookup_registered_name(clan_name)
        assert clan_owner_after is not None
        assert clan_owner_after["container_kind"] == "clan"


def test_wipe_force_reuse_owner_already_absent_name_is_a_no_op_success(
    tmp_path: Path,
) -> None:
    """A name with no registry reservation at all succeeds without a trace."""
    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        assert "epic.gone" not in get_reserved_agent_names()

        wipe_force_reuse_owner("epic.gone", allow_container_skip=False)

        assert "epic.gone" not in get_reserved_agent_names()


def test_wipe_force_reuse_owner_family_tolerates_member_removed_concurrently(
    tmp_path: Path,
) -> None:
    """A member the ACE persistence proc already removed must not abort reuse."""
    family_name = "epic.race"
    plan_name = f"{family_name}--plan"
    code_name = f"{family_name}--code"
    family_meta = {"agent_family": family_name, "agent_family_parallel": False}
    plan = _artifact(tmp_path, "20260801140000", plan_name, done=True, meta=family_meta)
    code = _artifact(
        tmp_path,
        "20260801140100",
        code_name,
        meta={**family_meta, "parent_timestamp": plan.name},
    )

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()

        # A concurrent cleanup proc (e.g. a dismissed-bundle save/delete that
        # raced the forced-reuse launch) already removed the code member's
        # artifacts before the registry caught up.
        import shutil

        shutil.rmtree(code)

        wipe_force_reuse_owner(family_name, allow_container_skip=False)

        assert not plan.exists()
        assert {family_name, plan_name, code_name}.isdisjoint(
            get_reserved_agent_names()
        )


def test_wipe_force_reuse_owner_concurrent_directory_removal_is_not_an_error(
    tmp_path: Path,
) -> None:
    """A TOCTOU race between exists() and rmtree() must count as success."""
    import shutil

    artifacts_dir = _artifact(tmp_path, "20260801150000", "foo", done=True)
    real_rmtree = shutil.rmtree

    def _rmtree_races_a_concurrent_delete(path: Path) -> None:
        # A concurrent process (another forced-reuse pass, the ACE cleanup
        # proc) removes the directory first; this rmtree() call then races
        # into "not found" the same way the real one would.
        real_rmtree(path)
        raise FileNotFoundError(path)

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        with patch(
            "sase.agent.names._wipe.shutil.rmtree",
            side_effect=_rmtree_races_a_concurrent_delete,
        ):
            result = wipe_force_reuse_owner("foo", allow_container_skip=False)

    # No error was raised and the directory is really gone: the race is a
    # success, not a cleanup failure.
    assert result is None
    assert not artifacts_dir.exists()


def test_wipe_force_reuse_owner_refuses_populated_clan_container(
    tmp_path: Path,
) -> None:
    container_name = "research"
    member_names = ("research.worker", "research.finished")
    container_meta: dict[str, object] = {
        "agent_clan": container_name,
        "agent_clan_generation": "clan-gen",
    }
    _artifact(tmp_path, "member-ts", member_names[0], done=True, meta=container_meta)
    _artifact(tmp_path, "member-ts-2", member_names[1], done=True, meta=container_meta)

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        owner = lookup_registered_name(container_name)
        assert owner is not None
        assert owner["container_kind"] == "clan"

        with pytest.raises(ForcedReuseCleanupError, match="clan"):
            wipe_force_reuse_owner(container_name, allow_container_skip=False)

        assert {container_name, *member_names} <= get_reserved_agent_names()

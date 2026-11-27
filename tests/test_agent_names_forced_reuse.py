"""Tests for the shared forced-reuse cleanup primitive.

``wipe_force_reuse_owner()`` is the shared agent-name-layer operation behind
both the ACE/``sase agent restart`` launch boundary and deterministic bead
relaunch. These tests seed a real name registry (rather than mocking the
low-level wipe) to prove an agent-session-root forced reuse replaces the newest
agent-session generation deterministically, leaves an enclosing clan and unrelated
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
    claim_registered_name,
    convert_registered_agent_to_agent_session,
    find_agent_session,
    get_reserved_agent_names,
    lookup_registered_name,
    rebuild_name_registry,
    release_stale_container,
    wipe_agent_name_for_reuse,
    wipe_force_reuse_owner,
    wipe_force_reuse_owners,
)
from tests._agent_name_wipe_helpers import make_wipe_artifact, make_wipe_bundle


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


def test_stale_session_container_skips_wipe_and_releases(tmp_path: Path) -> None:
    """A session container is never wiped in place but releases as stale."""
    root = tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / "run1"
    root.mkdir(parents=True)
    with patch.object(Path, "home", return_value=tmp_path):
        claim_registered_name("foo", root)
        convert_registered_agent_to_agent_session("foo", "foo--0", root)
        assert lookup_registered_name("foo")["container_kind"] == "session"

        skipped = wipe_agent_name_for_reuse("foo")
        assert skipped.found is True
        assert skipped.skipped_container_kind == "session"
        assert lookup_registered_name("foo") is not None

        release_stale_container("foo", container_kind="session")
        assert lookup_registered_name("foo") is None


def test_wipe_force_reuse_owner_replaces_newest_agent_session_generation(
    tmp_path: Path,
) -> None:
    agent_session_name = "epic.phase"
    plan_name = f"{agent_session_name}--plan"
    code_name = f"{agent_session_name}--code"
    agent_session_meta = {
        "agent_session": agent_session_name,
        "agent_session_parallel": False,
    }
    plan = _artifact(
        tmp_path, "20260801120000", plan_name, done=True, meta=agent_session_meta
    )
    code = _artifact(
        tmp_path,
        "20260801120100",
        code_name,
        meta={**agent_session_meta, "parent_timestamp": plan.name},
    )
    sibling = _artifact(tmp_path, "20260801120200", "unrelated", done=True)

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        assert {agent_session_name, plan_name, code_name} <= get_reserved_agent_names()

        wipe_force_reuse_owner(agent_session_name, allow_container_skip=False)

        assert not plan.exists()
        assert not code.exists()
        assert {agent_session_name, plan_name, code_name}.isdisjoint(
            get_reserved_agent_names()
        )
        assert "unrelated" in get_reserved_agent_names()
        assert sibling.exists()


def test_wipe_force_reuse_owner_agent_session_preserves_enclosing_clan(
    tmp_path: Path,
) -> None:
    clan_name = "sase-sq"
    agent_session_name = f"{clan_name}.1"
    plan_name = f"{agent_session_name}--plan"
    code_name = f"{agent_session_name}--code"
    agent_session_meta = {
        "agent_session": agent_session_name,
        "agent_session_parallel": False,
        "agent_clan": clan_name,
        "agent_clan_generation": "gen-1",
    }
    plan = _artifact(
        tmp_path, "20260801130000", plan_name, done=True, meta=agent_session_meta
    )
    code = _artifact(
        tmp_path,
        "20260801130100",
        code_name,
        meta={**agent_session_meta, "parent_timestamp": plan.name},
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

        wipe_force_reuse_owner(agent_session_name, allow_container_skip=False)

        assert {agent_session_name, plan_name, code_name}.isdisjoint(
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


def test_wipe_force_reuse_owner_agent_session_tolerates_member_removed_concurrently(
    tmp_path: Path,
) -> None:
    """A member the ACE persistence proc already removed must not abort reuse."""
    agent_session_name = "epic.race"
    plan_name = f"{agent_session_name}--plan"
    code_name = f"{agent_session_name}--code"
    agent_session_meta = {
        "agent_session": agent_session_name,
        "agent_session_parallel": False,
    }
    plan = _artifact(
        tmp_path, "20260801140000", plan_name, done=True, meta=agent_session_meta
    )
    code = _artifact(
        tmp_path,
        "20260801140100",
        code_name,
        meta={**agent_session_meta, "parent_timestamp": plan.name},
    )

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()

        # A concurrent cleanup proc (e.g. a dismissed-bundle save/delete that
        # raced the forced-reuse launch) already removed the code member's
        # artifacts before the registry caught up.
        import shutil

        shutil.rmtree(code)

        wipe_force_reuse_owner(agent_session_name, allow_container_skip=False)

        assert not plan.exists()
        assert {agent_session_name, plan_name, code_name}.isdisjoint(
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
            "sase.agent.names._wipe_execute.shutil.rmtree",
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


def _session_meta(session: str, role: str, **extra: object) -> dict[str, object]:
    return {
        "workflow_name": session,
        "agent_session": session,
        "agent_session_role": role,
        "agent_session_parallel": False,
        **extra,
    }


def _seed_observed_closure(tmp_path: Path, session: str) -> dict[str, Path]:
    """Seed the observed failure shape: root plus gate/code/mon and forks."""
    root = make_wipe_artifact(
        tmp_path,
        "20261101000000",
        f"{session}--plan",
        done=True,
        day_sharded=True,
        meta={**_session_meta(session, "root"), "plan_chain_root": True},
    )
    gate = make_wipe_artifact(
        tmp_path,
        "20261101000100",
        f"{session}--gate",
        done=True,
        day_sharded=True,
        meta=_session_meta(session, "gate", parent_timestamp=root.name),
    )
    code = make_wipe_artifact(
        tmp_path,
        "20261101000200",
        f"{session}--code",
        done=True,
        day_sharded=True,
        meta=_session_meta(session, "code", parent_timestamp=root.name),
    )
    mon = make_wipe_artifact(
        tmp_path,
        "20261101000300",
        f"{session}--mon",
        done=True,
        day_sharded=True,
        meta=_session_meta(session, "monitor", parent_timestamp=code.name),
    )
    fork1 = make_wipe_artifact(
        tmp_path,
        "20261101000400",
        f"{session}--1",
        done=True,
        day_sharded=True,
        meta=_session_meta(session, "root", parent_timestamp=root.name),
    )
    fork2 = make_wipe_artifact(
        tmp_path,
        "20261101000500",
        f"{session}--2",
        done=True,
        day_sharded=True,
        meta=_session_meta(session, "root", parent_timestamp=root.name),
    )
    mon0 = make_wipe_artifact(
        tmp_path,
        "20261101000600",
        f"{session}--mon-0",
        done=True,
        day_sharded=True,
        meta=_session_meta(session, "monitor", parent_timestamp=fork1.name),
    )
    bundle = make_wipe_bundle(
        tmp_path,
        "20261101000700",
        f"{session}--plan",
        parent_timestamp=root.name,
        **_session_meta(session, "root"),
    )
    child_bundle = make_wipe_bundle(
        tmp_path,
        "20261101000700__c0",
        f"{session}--plan",
        parent_timestamp="20261101000700",
        **_session_meta(session, "root"),
    )
    return {
        "root": root,
        "gate": gate,
        "code": code,
        "mon": mon,
        "fork1": fork1,
        "fork2": fork2,
        "mon0": mon0,
        "bundle": bundle,
        "child_bundle": child_bundle,
    }


def test_wipe_force_reuse_owner_wipes_full_closure_when_index_omits_root(
    tmp_path: Path,
) -> None:
    session = "epic.land"
    paths = _seed_observed_closure(tmp_path, session)
    member_names = {f"{session}--plan", f"{session}--gate", f"{session}--code"}

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        assert {session, *member_names} <= get_reserved_agent_names()
        real_session = find_agent_session(session)
        assert real_session is not None

        trimmed_members = tuple(
            member
            for member in real_session.members
            if member.name != f"{session}--plan"
        )
        assert trimmed_members, "seed must leave members after trimming the root"
        from sase.agent.names._lookup_groups import AgentSession as _AgentSession

        trimmed = _AgentSession(
            base_name=real_session.base_name,
            root=None,
            members=trimmed_members,
        )
        with patch("sase.agent.names.find_agent_session", return_value=trimmed):
            wipe_force_reuse_owner(session, allow_container_skip=False)

        for path in paths.values():
            assert not path.exists(), f"{path} should have been wiped"
        assert not any(
            name == session or name.startswith(f"{session}--")
            for name in get_reserved_agent_names()
        )


def test_wipe_force_reuse_owner_wipes_full_closure_normal_path(
    tmp_path: Path,
) -> None:
    session = "epic.land"
    paths = _seed_observed_closure(tmp_path, session)

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        wipe_force_reuse_owner(session, allow_container_skip=False)

        for path in paths.values():
            assert not path.exists(), f"{path} should have been wiped"
        assert not any(
            name == session or name.startswith(f"{session}--")
            for name in get_reserved_agent_names()
        )


def test_wipe_force_reuse_owner_removes_older_generation(
    tmp_path: Path,
) -> None:
    session = "epic.land"
    old_root = make_wipe_artifact(
        tmp_path,
        "20261102000000",
        f"{session}--plan",
        done=True,
        day_sharded=True,
        meta={**_session_meta(session, "root"), "plan_chain_root": True},
    )
    new_root = make_wipe_artifact(
        tmp_path,
        "20261102000100",
        f"{session}--plan",
        done=True,
        day_sharded=True,
        meta={**_session_meta(session, "root"), "plan_chain_root": True},
    )

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        assert session in get_reserved_agent_names()

        wipe_force_reuse_owner(session, allow_container_skip=False)

        assert not old_root.exists()
        assert not new_root.exists()
        assert session not in get_reserved_agent_names()
        assert f"{session}--plan" not in get_reserved_agent_names()


def test_wipe_force_reuse_owner_wipes_bundle_only_owner(
    tmp_path: Path,
) -> None:
    session = "epic.land"
    bundle = make_wipe_bundle(
        tmp_path,
        "20261103000000",
        f"{session}--plan",
        **_session_meta(session, "root"),
    )

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        assert session in get_reserved_agent_names()

        wipe_force_reuse_owner(session, allow_container_skip=False)

        assert not bundle.exists()
        assert session not in get_reserved_agent_names()


def test_wipe_force_reuse_owner_preserves_neighbors(
    tmp_path: Path,
) -> None:
    session = "epic.land"
    session_paths = _seed_observed_closure(tmp_path, session)
    nested_session = "epic.land--3"
    nested = make_wipe_artifact(
        tmp_path,
        "20261104000000",
        f"{nested_session}--plan",
        done=True,
        day_sharded=True,
        meta={**_session_meta(nested_session, "root"), "plan_chain_root": True},
    )
    sibling_session = "epic.land2"
    sibling = make_wipe_artifact(
        tmp_path,
        "20261104000100",
        f"{sibling_session}--plan",
        done=True,
        day_sharded=True,
        meta={**_session_meta(sibling_session, "root"), "plan_chain_root": True},
    )
    unrelated = make_wipe_artifact(
        tmp_path,
        "20261104000200",
        "unrelated",
        done=True,
        day_sharded=True,
    )
    clan_name = "epic"
    clan_member = make_wipe_artifact(
        tmp_path,
        "20261104000300",
        "epic.other",
        done=True,
        day_sharded=True,
        meta={"agent_clan": clan_name, "agent_clan_generation": "gen-1"},
    )

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        wipe_force_reuse_owner(session, allow_container_skip=False)

        for path in session_paths.values():
            assert not path.exists()
        assert nested.exists()
        assert sibling.exists()
        assert unrelated.exists()
        assert clan_member.exists()
        assert nested_session in get_reserved_agent_names()
        assert sibling_session in get_reserved_agent_names()
        assert "unrelated" in get_reserved_agent_names()
        assert clan_name in get_reserved_agent_names()
        assert session not in get_reserved_agent_names()


def test_wipe_force_reuse_residual_error_names_blocking_file(
    tmp_path: Path,
) -> None:
    session = "epic.land"
    _seed_observed_closure(tmp_path, session)

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        # Deterministic residual: keep one artifact on disk by refusing to
        # delete it in the wipe execution layer.
        from sase.agent.names import _wipe_execute as execute_mod

        real_remove = execute_mod._remove_artifact_dirs

        def _keep_one(paths: set[Path], errors: list[str]) -> set[Path]:
            keep = next(iter(sorted(paths)), None)
            remaining = set(paths)
            if keep is not None:
                remaining.discard(keep)
            return real_remove(remaining, errors)

        with (
            patch.object(execute_mod, "_remove_artifact_dirs", side_effect=_keep_one),
            pytest.raises(
                ForcedReuseCleanupError, match="forced reuse cleanup left"
            ) as excinfo,
        ):
            wipe_force_reuse_owner(session, allow_container_skip=False)

        message = str(excinfo.value)
        assert "source=" in message
        assert "artifacts_dir=" in message
        assert "collision_owners=" in message


def test_wipe_force_reuse_owners_retries_once_for_late_dismissed_bundle(
    tmp_path: Path,
) -> None:
    name = "bob-cli-q5"
    suffix = "20261127120000"
    artifact = make_wipe_artifact(tmp_path, suffix, name, done=True)

    from sase.agent.names import _wipe as wipe_mod

    real_execute = wipe_mod.execute_wipe_plan
    calls = {"n": 0}
    late_bundle: dict[str, Path | None] = {"path": None}

    def _execute_with_late_writer(plan: object) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            late_bundle["path"] = make_wipe_bundle(tmp_path, suffix, name)
        return real_execute(plan)

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        assert name in get_reserved_agent_names()
        with patch.object(
            wipe_mod, "execute_wipe_plan", side_effect=_execute_with_late_writer
        ):
            wipe_force_reuse_owners([name], allow_container_skip=False)

        assert not artifact.exists()
        assert late_bundle["path"] is not None
        assert not late_bundle["path"].exists()
        assert name not in get_reserved_agent_names()
        assert calls["n"] == 2


def test_wipe_force_reuse_owners_persistent_residual_retries_once(
    tmp_path: Path,
) -> None:
    name = "blocked"
    make_wipe_artifact(tmp_path, "20261127120100", name, done=True)

    from sase.agent.names import _forced_reuse as forced_mod
    from sase.agent.names import _wipe_execute as execute_mod

    real_batch = forced_mod._wipe_names_for_reuse_batch
    batch_calls = {"n": 0}

    def _keep_all(paths: set[Path], errors: list[str]) -> set[Path]:
        del paths, errors
        return set()

    def _count_batch(*args: object, **kwargs: object) -> object:
        batch_calls["n"] += 1
        return real_batch(*args, **kwargs)

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        with (
            patch.object(execute_mod, "_remove_artifact_dirs", side_effect=_keep_all),
            patch.object(
                forced_mod, "_wipe_names_for_reuse_batch", side_effect=_count_batch
            ),
            pytest.raises(
                ForcedReuseCleanupError, match="forced reuse cleanup left"
            ) as excinfo,
        ):
            wipe_force_reuse_owners([name], allow_container_skip=False)

        message = str(excinfo.value)
        assert batch_calls["n"] == 2
        assert "source=" in message
        assert "artifacts_dir=" in message


def test_wipe_force_reuse_session_retries_once_for_late_plan_bundle(
    tmp_path: Path,
) -> None:
    session = "epic.land"
    plan_name = f"{session}--plan"
    code_name = f"{session}--code"
    plan = make_wipe_artifact(
        tmp_path,
        "20261127120200",
        plan_name,
        done=True,
        day_sharded=True,
        meta={**_session_meta(session, "root"), "plan_chain_root": True},
    )
    code = make_wipe_artifact(
        tmp_path,
        "20261127120300",
        code_name,
        done=True,
        day_sharded=True,
        meta=_session_meta(session, "code", parent_timestamp=plan.name),
    )

    from sase.agent.names import _wipe as wipe_mod

    real_execute = wipe_mod.execute_wipe_plan
    calls = {"n": 0}
    late_bundle: dict[str, Path | None] = {"path": None}

    def _execute_with_late_writer(plan_arg: object) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            late_bundle["path"] = make_wipe_bundle(
                tmp_path,
                "20261127125900",
                plan_name,
                **_session_meta(session, "root"),
            )
        return real_execute(plan_arg)

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        with patch.object(
            wipe_mod, "execute_wipe_plan", side_effect=_execute_with_late_writer
        ):
            wipe_force_reuse_owner(session, allow_container_skip=False)

        assert not plan.exists()
        assert not code.exists()
        assert late_bundle["path"] is not None
        assert not late_bundle["path"].exists()
        assert session not in get_reserved_agent_names()
        assert plan_name not in get_reserved_agent_names()

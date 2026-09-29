"""Agent-session wipe tests: members, containers, batch, and guards.

Split from ``tests.test_agent_name_wipe``; the original module re-exports
these tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.names import (
    get_reserved_agent_names,
    load_name_registry,
    lookup_registered_name,
    rebuild_name_registry,
    wipe_agent_name_for_reuse,
    wipe_agent_names_for_reuse,
)
from sase.agent.names._forced_reuse import (
    ForcedReuseCleanupError,
    wipe_force_reuse_owners,
)

from tests._agent_name_wipe_helpers import make_wipe_artifact, make_wipe_bundle

__all__ = [
    "test_forced_reuse_owners_raise_and_delete_nothing_on_session_root_leak",
    "test_wipe_agent_session_member_finds_day_sharded_handoff_and_bundle",
    "test_wipe_auto_code_member_keeps_root_whose_done_marker_names_it",
    "test_wipe_code_member_preserves_plan_member_and_agent_session_container",
    "test_wipe_container_name_preserves_member_artifacts_and_registry",
    "test_wipe_refuses_member_closure_that_reaches_session_root",
    "test_wipe_whole_agent_session_batch_still_removes_root_and_members",
]


def test_wipe_agent_session_member_finds_day_sharded_handoff_and_bundle(
    tmp_path: Path,
) -> None:
    agent_session_name = "epic.phase"
    plan_name = f"{agent_session_name}--plan"
    code_name = f"{agent_session_name}--code"
    agent_session_meta = {
        "agent_session": agent_session_name,
        "agent_session_parallel": False,
    }
    plan = make_wipe_artifact(
        tmp_path,
        "20260722120000",
        plan_name,
        done=True,
        day_sharded=True,
        meta=agent_session_meta,
    )
    code = make_wipe_artifact(
        tmp_path,
        "20260722120100",
        code_name,
        day_sharded=True,
        meta={**agent_session_meta, "parent_timestamp": plan.name},
    )
    bundle_path = make_wipe_bundle(
        tmp_path,
        "20260722120200",
        f"{agent_session_name}--review",
        parent_timestamp=code.name,
        **agent_session_meta,
    )
    unrelated = make_wipe_artifact(
        tmp_path,
        "20260722120300",
        "unrelated",
        day_sharded=True,
    )

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        assert {agent_session_name, plan_name, code_name} <= get_reserved_agent_names()
        with patch(
            "sase.agent.names._wipe_execute._release_artifact_workspace"
        ) as release_workspace:
            result = wipe_agent_name_for_reuse(plan_name)

        assert {str(plan), str(code)} <= set(result.artifact_dirs_removed)
        assert str(bundle_path) in result.bundle_paths_removed
        assert {call.args[0] for call in release_workspace.call_args_list} == {
            plan,
            code,
        }
        assert unrelated.exists()
        assert agent_session_name not in get_reserved_agent_names()
        assert plan_name not in get_reserved_agent_names()
        assert code_name not in get_reserved_agent_names()
        assert "unrelated" in get_reserved_agent_names()


def _agent_session_meta(agent_session_name: str, role: str) -> dict[str, object]:
    """Meta a real agent-session member stores: ``workflow_name`` is the session."""
    return {
        "workflow_name": agent_session_name,
        "agent_session": agent_session_name,
        "agent_session_role": role,
        "agent_session_parallel": False,
    }


def test_wipe_code_member_preserves_plan_member_and_agent_session_container(
    tmp_path: Path,
) -> None:
    agent_session_name = "epic.phase"
    plan_name = f"{agent_session_name}--plan"
    code_name = f"{agent_session_name}--code"
    plan = make_wipe_artifact(
        tmp_path,
        "20260723120000",
        plan_name,
        done=True,
        meta={
            **_agent_session_meta(agent_session_name, "root"),
            "plan_chain_root": True,
        },
    )
    code = make_wipe_artifact(
        tmp_path,
        "20260723120100",
        code_name,
        done=True,
        meta={
            **_agent_session_meta(agent_session_name, "code"),
            "parent_timestamp": plan.name,
        },
    )
    descendant = make_wipe_bundle(
        tmp_path,
        "20260723120200",
        f"{agent_session_name}--code-review",
        parent_timestamp=code.name,
        **_agent_session_meta(agent_session_name, "feedback"),
    )
    sibling = make_wipe_artifact(
        tmp_path,
        "20260723120300",
        f"{agent_session_name}--reviewer",
        done=True,
        meta=_agent_session_meta(agent_session_name, "feedback"),
    )

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        result = wipe_agent_name_for_reuse(code_name)

        assert set(result.artifact_dirs_removed) == {str(code)}
        assert str(descendant) in result.bundle_paths_removed
        assert plan.exists()
        assert sibling.exists()
        assert {agent_session_name, plan_name, f"{agent_session_name}--reviewer"} <= (
            get_reserved_agent_names()
        )
        assert code_name not in get_reserved_agent_names()


def _auto_agent_session(tmp_path: Path, agent_session_name: str) -> dict[str, Path]:
    """A ``%auto`` plan chain: the root's ``done.json`` names the code member."""
    root = make_wipe_artifact(
        tmp_path,
        "20260725120000",
        f"{agent_session_name}--plan",
        done=True,
        done_name=f"{agent_session_name}--code",
        meta={
            **_agent_session_meta(agent_session_name, "root"),
            "plan_chain_root": True,
        },
    )
    gate = make_wipe_artifact(
        tmp_path,
        "20260725120050",
        f"{agent_session_name}--gate",
        done=True,
        meta={
            **_agent_session_meta(agent_session_name, "gate"),
            "parent_timestamp": root.name,
        },
    )
    code = make_wipe_artifact(
        tmp_path,
        "20260725120100",
        f"{agent_session_name}--code",
        done=True,
        meta={
            **_agent_session_meta(agent_session_name, "code"),
            "parent_timestamp": root.name,
        },
    )
    monitor = make_wipe_artifact(
        tmp_path,
        "20260725120200",
        f"{agent_session_name}--mon",
        done=True,
        meta={
            **_agent_session_meta(agent_session_name, "monitor"),
            "parent_timestamp": code.name,
        },
    )
    return {"root": root, "gate": gate, "code": code, "monitor": monitor}


def test_wipe_auto_code_member_keeps_root_whose_done_marker_names_it(
    tmp_path: Path,
) -> None:
    agent_session_name = "epic.phase"
    dirs = _auto_agent_session(tmp_path, agent_session_name)

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        owner = lookup_registered_name(f"{agent_session_name}--code")
        assert owner is not None
        assert Path(owner["artifacts_dir"]) == dirs["code"]

        result = wipe_agent_name_for_reuse(f"{agent_session_name}--code")

        assert result.errors == ()
        assert set(result.artifact_dirs_removed) == {
            str(dirs["code"]),
            str(dirs["monitor"]),
        }
        assert dirs["root"].exists()
        assert dirs["gate"].exists()
        assert {
            agent_session_name,
            f"{agent_session_name}--plan",
            f"{agent_session_name}--gate",
        } <= get_reserved_agent_names()
        assert f"{agent_session_name}--code" not in get_reserved_agent_names()


def test_wipe_whole_agent_session_batch_still_removes_root_and_members(
    tmp_path: Path,
) -> None:
    agent_session_name = "epic.phase"
    dirs = _auto_agent_session(tmp_path, agent_session_name)
    members = tuple(
        f"{agent_session_name}--{suffix}" for suffix in ("plan", "gate", "code", "mon")
    )

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        results = wipe_agent_names_for_reuse(members)

        assert all(result.errors == () for result in results)
        assert not any(path.exists() for path in dirs.values())
        assert agent_session_name not in get_reserved_agent_names()


def _leak_root_into_plan(root: Path):  # type: ignore[no-untyped-def]
    """Patch ``build_wipe_plan`` so every closure also holds *root*."""
    from sase.agent.names._wipe_plan import build_wipe_plan

    def leaky(owner, target_name, *, catalog=None):  # type: ignore[no-untyped-def]
        plan = build_wipe_plan(owner, target_name, catalog=catalog)
        plan.artifact_dirs.add(root.resolve())
        return plan

    return patch("sase.agent.names._wipe.build_wipe_plan", side_effect=leaky)


def test_wipe_refuses_member_closure_that_reaches_session_root(
    tmp_path: Path,
) -> None:
    agent_session_name = "epic.phase"
    dirs = _auto_agent_session(tmp_path, agent_session_name)
    code_name = f"{agent_session_name}--code"

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        before = load_name_registry()
        with _leak_root_into_plan(dirs["root"]):
            result = wipe_agent_name_for_reuse(code_name)

        assert result.found is True
        assert result.artifact_dirs_removed == ()
        assert len(result.errors) == 1
        assert f"forced reuse of '{code_name}'" in result.errors[0]
        assert f"agent-session root '{agent_session_name}--plan'" in result.errors[0]
        assert str(dirs["root"]) in result.errors[0]
        assert all(path.exists() for path in dirs.values())
        assert load_name_registry() == before


def test_forced_reuse_owners_raise_and_delete_nothing_on_session_root_leak(
    tmp_path: Path,
) -> None:
    agent_session_name = "epic.phase"
    dirs = _auto_agent_session(tmp_path, agent_session_name)

    with patch.object(Path, "home", return_value=tmp_path):
        rebuild_name_registry()
        with (
            _leak_root_into_plan(dirs["root"]),
            pytest.raises(ForcedReuseCleanupError, match="refusing to wipe"),
        ):
            wipe_force_reuse_owners(
                (f"{agent_session_name}--code",), allow_container_skip=False
            )

        assert all(path.exists() for path in dirs.values())


@pytest.mark.parametrize(
    ("container_kind", "container_name", "member_names", "container_meta"),
    [
        pytest.param(
            "clan",
            "research",
            ("research.worker", "research.finished"),
            {"agent_clan": "research", "agent_clan_generation": "clan-gen"},
            id="clan",
        ),
        pytest.param(
            "session",
            "review",
            ("review--0", "review--code"),
            {"agent_session": "review", "agent_session_parallel": False},
            id="session",
        ),
        # legacy agent-family spelling: pre-rename meta and bundles still
        # resolve to a session container.
        pytest.param(
            "session",
            "review",
            ("review--0", "review--code"),
            {"agent_family": "review", "agent_family_parallel": False},
            id="legacy-family-keys",
        ),
    ],
)
def test_wipe_container_name_preserves_member_artifacts_and_registry(
    tmp_path: Path,
    container_kind: str,
    container_name: str,
    member_names: tuple[str, str],
    container_meta: dict[str, object],
) -> None:
    artifacts_dir = make_wipe_artifact(
        tmp_path,
        "member-ts",
        member_names[0],
        done=True,
        meta=container_meta,
    )
    bundle_path = make_wipe_bundle(
        tmp_path,
        "bundle-ts",
        member_names[1],
        **container_meta,
    )

    with patch.object(Path, "home", return_value=tmp_path):
        before = rebuild_name_registry()
        owner = lookup_registered_name(container_name)
        assert owner is not None
        assert owner["container_kind"] == container_kind

        # Exercise both accepted owner forms across the two container kinds.
        wipe_target = container_name if container_kind == "clan" else owner
        result = wipe_agent_name_for_reuse(wipe_target)

        assert result.found is True
        assert result.skipped_container_kind == container_kind
        assert result.artifact_dirs_removed == ()
        assert result.bundle_paths_removed == ()
        assert artifacts_dir.exists()
        assert bundle_path.exists()
        assert load_name_registry() == before
        assert {container_name, *member_names} <= get_reserved_agent_names()

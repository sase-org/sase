"""Strict workspace handling for turn follow-up launches.

Phase ``strict_successor``: when ``strict_workspace`` is true, the launch
validates the positive workspace pair before spawn, allows only transfer
and one fresh claim on that same pair, and routes any further failure to
``record_not_launchable`` -- pool-workspace and workspace-``#0`` fallbacks
are never used.
"""

from __future__ import annotations

from typing import Any

import pytest

from sase.agent.launch_types import AgentLaunchResult
from sase.running_field import WorkspaceClaimError
from sase.turns.followup import (
    FollowupLaunchResult,
    TurnFollowupWorkspace,
    launch_turn_followup,
)


def _workspace_messages() -> TurnFollowupWorkspace:
    return TurnFollowupWorkspace(
        meta_pairing_reason=lambda original, primary: (
            f"unpaired {original} -> {primary}"
        ),
        fresh_claim_reason=lambda num, error: f"fresh #{num}: {error}",
        pool_claim_reason=lambda num, error, pool_num, pool_dir: (
            f"pool from #{num} to #{pool_num} ({pool_dir}): {error}"
        ),
        workspace_zero_reason=lambda num, error, directory: (
            f"zero from #{num} ({directory}): {error}"
        ),
    )


def _ok_spawn(
    *,
    fail_transfer: bool = False,
    fail_fresh: bool = False,
) -> Any:
    calls: list[dict[str, Any]] = []

    def spawn(
        prompt: str,
        workspace_dir: str,
        workspace_num: int,
        transfer_pid: int | None,
        vcs_ref: Any,
    ) -> AgentLaunchResult:
        calls.append(
            {
                "workspace_num": workspace_num,
                "workspace_dir": workspace_dir,
                "transfer_pid": transfer_pid,
            }
        )
        if transfer_pid is not None and fail_transfer:
            raise WorkspaceClaimError("transfer lost", workspace_num=workspace_num)
        if transfer_pid is None and fail_fresh:
            raise WorkspaceClaimError("fresh claim lost", workspace_num=workspace_num)
        return AgentLaunchResult(
            pid=4242,
            workspace_num=workspace_num,
            workspace_dir=workspace_dir,
            output_path="/tmp/out.txt",
            agent_name="acme--4",
        )

    spawn.calls = calls  # type: ignore[attr-defined]
    return spawn


def _record(
    launched: list[FollowupLaunchResult], not_launchable: list[tuple[str, str]]
) -> tuple[Any, Any]:
    def record_launched(*args: Any, **kwargs: Any) -> FollowupLaunchResult:
        result = FollowupLaunchResult(
            launched=True,
            degraded_reason=kwargs.get("degraded_reason"),
            agent_name=args[0] if args else None,
        )
        launched.append(result)
        return result

    def record_not_launchable(error: str, prompt: str) -> FollowupLaunchResult:
        result = FollowupLaunchResult(launched=False, error=error)
        not_launchable.append((error, prompt))
        return result

    return record_launched, record_not_launchable


def _launch(
    spawn: Any,
    *,
    workspace_num: object = 3,
    workspace_dir: str = "/ws/3",
    monkeypatch: pytest.MonkeyPatch | None = None,
) -> tuple[list[FollowupLaunchResult], list[tuple[str, str]], Any]:
    if monkeypatch is not None:
        monkeypatch.setattr(
            "sase.turns.followup_launch._workspace_dir_for_num",
            lambda project_name, num: "/ws/3" if num == 3 else "/ws/0",
        )
    launched: list[FollowupLaunchResult] = []
    not_launchable: list[tuple[str, str]] = []
    record_launched, record_not_launchable = _record(launched, not_launchable)
    launch_turn_followup(
        project_name="proj",
        meta_workspace_num=workspace_num,
        meta_workspace_dir=workspace_dir,
        transfer_from_pid=111,
        compose_prompt=lambda degraded: f"prompt:{degraded}",
        spawn=spawn,
        workspace=_workspace_messages(),
        record_launched=record_launched,
        record_not_launchable=record_not_launchable,
        strict_workspace=True,
    )
    return launched, not_launchable, spawn


class TestStrictFollowup:
    def test_transfer_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spawn = _ok_spawn()
        launched, not_launchable, _ = _launch(spawn, monkeypatch=monkeypatch)

        assert len(launched) == 1 and launched[0].launched is True
        assert not_launchable == []
        assert spawn.calls[0]["transfer_pid"] == 111
        assert spawn.calls[0]["workspace_num"] == 3

    def test_fresh_claim_on_same_pair_after_transfer_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spawn = _ok_spawn(fail_transfer=True)
        launched, not_launchable, _ = _launch(spawn, monkeypatch=monkeypatch)

        assert len(launched) == 1 and launched[0].launched is True
        assert not_launchable == []
        assert len(spawn.calls) == 2
        assert all(call["workspace_num"] == 3 for call in spawn.calls)
        assert all(call["workspace_dir"] == "/ws/3" for call in spawn.calls)
        assert spawn.calls[1]["transfer_pid"] is None

    def test_second_failure_reports_not_launchable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spawn = _ok_spawn(fail_transfer=True, fail_fresh=True)
        monkeypatch.setattr(
            "sase.turns.followup_launch._workspace_dir_for_num",
            lambda project_name, num: "/ws/3" if num == 3 else "/ws/0",
        )
        launched: list[FollowupLaunchResult] = []
        not_launchable: list[tuple[str, str]] = []
        record_launched, record_not_launchable = _record(launched, not_launchable)
        result = launch_turn_followup(
            project_name="proj",
            meta_workspace_num=3,
            meta_workspace_dir="/ws/3",
            transfer_from_pid=111,
            compose_prompt=lambda degraded: f"prompt:{degraded}",
            spawn=spawn,
            workspace=_workspace_messages(),
            record_launched=record_launched,
            record_not_launchable=record_not_launchable,
            strict_workspace=True,
        )

        assert result.launched is False
        assert len(not_launchable) == 1
        assert "strict follow-up keeps workspace #3" in not_launchable[0][0]
        assert len(spawn.calls) == 2

    @pytest.mark.parametrize("num", [0, -1, "3", None])
    def test_invalid_pair_never_spawns(
        self, monkeypatch: pytest.MonkeyPatch, num: object
    ) -> None:
        spawn = _ok_spawn()
        monkeypatch.setattr(
            "sase.turns.followup_launch._workspace_dir_for_num",
            lambda project_name, n: "/ws/3",
        )
        launched: list[FollowupLaunchResult] = []
        not_launchable: list[tuple[str, str]] = []
        record_launched, record_not_launchable = _record(launched, not_launchable)
        result = launch_turn_followup(
            project_name="proj",
            meta_workspace_num=num,
            meta_workspace_dir="/ws/3",
            transfer_from_pid=111,
            compose_prompt=lambda degraded: f"prompt:{degraded}",
            spawn=spawn,
            workspace=_workspace_messages(),
            record_launched=record_launched,
            record_not_launchable=record_not_launchable,
            strict_workspace=True,
        )

        assert result.launched is False
        assert len(not_launchable) == 1
        assert spawn.calls == []

    def test_metadata_mismatch_never_spawns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spawn = _ok_spawn()
        monkeypatch.setattr(
            "sase.turns.followup_launch._workspace_dir_for_num",
            lambda project_name, num: "/ws/other",
        )
        launched: list[FollowupLaunchResult] = []
        not_launchable: list[tuple[str, str]] = []
        record_launched, record_not_launchable = _record(launched, not_launchable)
        result = launch_turn_followup(
            project_name="proj",
            meta_workspace_num=3,
            meta_workspace_dir="/ws/3",
            transfer_from_pid=111,
            compose_prompt=lambda degraded: f"prompt:{degraded}",
            spawn=spawn,
            workspace=_workspace_messages(),
            record_launched=record_launched,
            record_not_launchable=record_not_launchable,
            strict_workspace=True,
        )

        assert result.launched is False
        assert "mismatch" in not_launchable[0][0]
        assert spawn.calls == []

    def test_default_mode_still_degrades(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Guard: strict handling is opt-in; default callers keep fallbacks.
        def spawn(
            prompt: str,
            workspace_dir: str,
            workspace_num: int,
            transfer_pid: int | None,
            vcs_ref: Any,
        ) -> AgentLaunchResult:
            spawn.calls.append(workspace_num)  # type: ignore[attr-defined]
            if workspace_num != 0:
                raise WorkspaceClaimError("claim lost", workspace_num=workspace_num)
            return AgentLaunchResult(
                pid=4242,
                workspace_num=workspace_num,
                workspace_dir=workspace_dir,
                output_path="/tmp/out.txt",
                agent_name="acme--4",
            )

        spawn.calls = []  # type: ignore[attr-defined]
        monkeypatch.setattr(
            "sase.turns.followup_launch._workspace_dir_for_num",
            lambda project_name, num: "/ws/3" if num == 3 else "/ws/0",
        )
        monkeypatch.setattr(
            "sase.turns.followup_launch._workspace_is_claimed", lambda *args: True
        )
        launched: list[FollowupLaunchResult] = []
        not_launchable: list[tuple[str, str]] = []
        record_launched, record_not_launchable = _record(launched, not_launchable)
        result = launch_turn_followup(
            project_name="proj",
            meta_workspace_num=3,
            meta_workspace_dir="/ws/3",
            transfer_from_pid=111,
            compose_prompt=lambda degraded: f"prompt:{degraded}",
            spawn=spawn,
            workspace=_workspace_messages(),
            record_launched=record_launched,
            record_not_launchable=record_not_launchable,
        )

        assert result.launched is True
        assert spawn.calls == [3, 3, 0]

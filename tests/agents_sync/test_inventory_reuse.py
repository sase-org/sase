from __future__ import annotations

from pathlib import Path
import subprocess

from sase.agents_sync import inventory_reuse
from sase.agents_sync.inventory_models import ProjectHoodInventory
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from tests.agents_sync.inventory_fixtures import make_target


def test_inventory_reuse_is_shared_across_batches_until_inputs_change(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = make_target(tmp_path)
    identity = AgentIdentitySnapshot(AgentOwnerIdentity("alice", "athena"))
    token = [("head-1", "index-generation-1")]
    monkeypatch.setattr(
        inventory_reuse,
        "_inventory_input_token",
        lambda *_args: token[0],
    )
    builds: list[frozenset[str]] = []

    def builder(_target, _identity, **kwargs):
        requested = frozenset(kwargs["requested_hoods"])
        builds.append(requested)
        return ProjectHoodInventory(
            AgentOwnerIdentity("alice", "athena"),
            "proj",
            (),
        )

    cache = inventory_reuse.ProjectHoodInventoryReuse(
        {"foo", "bar"},
        builder=builder,
    )

    first = cache.build_inventory(
        target,
        identity,
        git_runner=lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "", ""),
        requested_hoods={"foo"},
    )
    second = cache.build_inventory(
        target,
        identity,
        git_runner=lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "", ""),
        requested_hoods={"bar"},
    )
    token[0] = ("head-2", "index-generation-1")
    third = cache.build_inventory(
        target,
        identity,
        git_runner=lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "", ""),
        requested_hoods={"bar"},
    )

    assert first is second
    assert third is not second
    assert builds == [frozenset({"foo", "bar"}), frozenset({"foo", "bar"})]

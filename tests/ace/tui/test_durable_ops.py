"""Tests for ACE durable-producer encoding helpers."""

from __future__ import annotations

from sase.ace.tui.durable_ops import (
    agent_directive_concurrency_key,
    agent_tribe_concurrency_key,
    is_concurrency_collision,
    launch_concurrency_key,
    operation_fingerprint,
    patch_concurrency_key,
    sase_command_argv,
)
from sase.procs.service import ProcSubmitError


def test_sase_command_argv_uses_python_module_form() -> None:
    argv = sase_command_argv("patch", "status", "demo", "Ready")
    assert argv[1:4] == ["-m", "sase", "patch"]
    assert argv[-2:] == ["demo", "Ready"]
    assert all(isinstance(part, str) and part for part in argv)


def test_patch_keys_are_project_qualified_and_independent() -> None:
    left = patch_concurrency_key("/proj/alpha/alpha.sase", "demo")
    right = patch_concurrency_key("/proj/beta/beta.sase", "demo")
    assert left != right
    assert left == patch_concurrency_key("/proj/alpha/alpha.sase", "demo")
    assert left.startswith("ace:patch:alpha:demo")


def test_agent_keys_namespace_artifacts_and_tribes() -> None:
    first = agent_directive_concurrency_key("/tmp/agent-a")
    second = agent_directive_concurrency_key("/tmp/agent-b")
    assert first != second
    assert first.startswith("ace:agent-directive:")
    assert agent_tribe_concurrency_key() == "ace:agent-directive:tribes"
    assert launch_concurrency_key("ace(run)-1") == "ace:launch:ace(run)-1"


def test_fingerprint_excludes_volatile_and_sensitive_values() -> None:
    first = operation_fingerprint(
        "patch.reword",
        {
            "name": "demo",
            "project_file": "/p/p.sase",
            "description": "secret description",
            "workspace_dir": "/tmp/ws-1",
            "result_path": "/tmp/result.json",
        },
    )
    same_secret = operation_fingerprint(
        "patch.reword",
        {
            "name": "demo",
            "project_file": "/p/p.sase",
            "description": "secret description",
            "workspace_dir": "/tmp/ws-2",
            "result_path": "/tmp/other.json",
        },
    )
    other_secret = operation_fingerprint(
        "patch.reword",
        {
            "name": "demo",
            "project_file": "/p/p.sase",
            "description": "different description",
        },
    )
    assert first == same_secret
    assert first != other_secret
    assert "secret" not in first
    assert first.startswith("sha256:")


def test_concurrency_collision_detection() -> None:
    assert is_concurrency_collision(ProcSubmitError("concurrency key already reserved"))
    assert not is_concurrency_collision(ProcSubmitError("could not start supervisor"))
    assert not is_concurrency_collision(RuntimeError("concurrency"))

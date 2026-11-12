"""Hook-enforcement regressions: sunset flag, fresh trust, no-execution.

Phase ``hook-enforcement`` filters local executable contributions before
merging and before the file-hook loader consumes raw layers, with fresh
synchronous trust checks at every execution boundary. Tests use temporary
config/state and sentinel commands; they never touch real user trust or
execute project scripts beyond tmp sentinels.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from sase.config import local_trust_enforcement as enforcement
from sase.config.core import (
    clear_config_cache,
    load_merged_config_for_local_path,
)


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data), encoding="utf-8")


def _repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    local: dict,
    user: dict | None = None,
) -> tuple[Path, Path]:
    root = tmp_path / name
    (root / ".git").mkdir(parents=True)
    local_path = root / "sase" / "sase.yml"
    _write_yaml(local_path, local)
    config_dir = tmp_path / f"config-{name}"
    config_dir.mkdir()
    _write_yaml(config_dir / "sase.yml", user or {})
    state_dir = tmp_path / f"state-{name}"
    state_dir.mkdir()
    monkeypatch.setenv("SASE_HOME", str(state_dir))
    import sase.config.core as core

    monkeypatch.setattr(core, "CONFIG_DIR", config_dir)
    monkeypatch.chdir(root)
    clear_config_cache()
    enforcement._warned_signatures.clear()
    return root, local_path


def _allow_current(local_path: Path) -> tuple[str, str]:
    from sase.config.local_trust import LOCAL_COMMAND_TRUST_POLICY_VERSION
    from sase.core.paths import sase_home
    from sase.core.rust import require_rust_binding

    evaluation = enforcement.evaluate_local_trust_for_path(local_path, None)
    assert evaluation.identity is not None
    assert evaluation.digest
    binding = require_rust_binding("local_command_trust_store_allow")
    binding(
        str(sase_home()),
        evaluation.identity,
        evaluation.digest,
        LOCAL_COMMAND_TRUST_POLICY_VERSION,
        "test",
    )
    return evaluation.identity, evaluation.digest


def _revoke(identity: str) -> None:
    from sase.core.paths import sase_home
    from sase.core.rust import require_rust_binding

    binding = require_rust_binding("local_command_trust_store_revoke")
    binding(str(sase_home()), identity)


def test_flag_off_runs_local_in_compatibility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.feature_flags import override_flags

    _repo(
        tmp_path,
        monkeypatch,
        "off",
        {"commit_hooks": {"before": "echo local"}, "timezone": "UTC"},
        {"commit_hooks": {"before": "echo user"}},
    )
    from sase.config.core import get_local_config_path

    local_path = get_local_config_path()
    assert local_path is not None
    with override_flags(local_config_command_trust=False):
        merged = load_merged_config_for_local_path(local_path)
        assert merged["commit_hooks"]["before"] == "echo local"
        assert merged["timezone"] == "UTC"
        evaluation = enforcement.evaluate_local_trust_for_path(local_path, None)
        assert evaluation.enabled is False
        assert evaluation.trusted is True


def test_flag_on_blocks_untrusted_preserves_user_and_non_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(
        tmp_path,
        monkeypatch,
        "block",
        {"commit_hooks": {"before": "echo local"}, "timezone": "UTC"},
        {"commit_hooks": {"before": "echo user"}},
    )
    from sase.config.core import get_local_config_path

    local_path = get_local_config_path()
    assert local_path is not None
    merged = load_merged_config_for_local_path(local_path)
    assert merged["commit_hooks"]["before"] == "echo user"
    assert merged["timezone"] == "UTC"
    evaluation = enforcement.evaluate_local_trust_for_path(local_path, None)
    assert evaluation.enabled is True
    assert evaluation.trusted is False
    assert "commit_hooks" in evaluation.removed_paths


def test_flag_on_allows_acknowledged_and_blocks_after_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, local_path = _repo(
        tmp_path,
        monkeypatch,
        "ack",
        {"commit_hooks": {"before": "echo hi"}},
    )
    assert (
        load_merged_config_for_local_path(local_path)["commit_hooks"].get("before")
        != "echo hi"
    )
    _allow_current(local_path)
    assert (
        load_merged_config_for_local_path(local_path)["commit_hooks"]["before"]
        == "echo hi"
    )
    _write_yaml(local_path, {"commit_hooks": {"before": "echo yo"}})
    clear_config_cache()
    assert (
        load_merged_config_for_local_path(local_path)["commit_hooks"].get("before", "")
        != "echo yo"
    )


def test_flag_on_blocks_after_revoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _root, local_path = _repo(
        tmp_path, monkeypatch, "revoke", {"commit_hooks": {"before": "echo hi"}}
    )
    identity, _digest = _allow_current(local_path)
    assert (
        load_merged_config_for_local_path(local_path)["commit_hooks"]["before"]
        == "echo hi"
    )
    _revoke(identity)
    assert (
        load_merged_config_for_local_path(local_path)["commit_hooks"].get("before", "")
        != "echo hi"
    )


def test_override_candidate_not_trusted_by_disk_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _root, local_path = _repo(
        tmp_path, monkeypatch, "override", {"commit_hooks": {"before": "echo hi"}}
    )
    _allow_current(local_path)
    assert (
        load_merged_config_for_local_path(local_path)["commit_hooks"]["before"]
        == "echo hi"
    )
    override = {"commit_hooks": {"before": "echo evil"}, "timezone": "UTC"}
    merged = load_merged_config_for_local_path(
        local_path, local_config_override=override
    )
    assert merged.get("commit_hooks", {}).get("before", "") != "echo evil"
    assert merged["timezone"] == "UTC"


def test_commit_hook_uses_explicit_repo_not_ambient(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ambient, _ambient_local = _repo(
        tmp_path, monkeypatch, "ambient", {"commit_hooks": {"before": "echo hi"}}
    )
    _allow_current(_ambient_local)
    other = tmp_path / "other"
    (other / ".git").mkdir(parents=True)
    other_local = other / "sase" / "sase.yml"
    _write_yaml(other_local, {"commit_hooks": {"before": "echo other"}})
    from sase.workflows.commit import command_hooks

    with (
        patch.object(
            command_hooks,
            "_run_hook_command",
            MagicMock(return_value=MagicMock(returncode=0)),
        ) as run,
        patch.object(command_hooks, "get_repo_root", return_value=str(other)),
    ):
        assert command_hooks.run_before_commit_hook(str(other)) is True
    run.assert_not_called()


def test_rebase_blocked_is_skipped_never_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _root, _local = _repo(
        tmp_path,
        monkeypatch,
        "rebase",
        {"commit_hooks": {"after_rebase": "echo local-gate"}},
    )
    from sase.workflows.commit.rebase_gate_budget import GateWorkBudget
    from sase.workflows.commit.rebase_gate_settings import (
        load_after_rebase_gate_settings,
        run_after_rebase_gate,
    )

    budget = GateWorkBudget()
    settings, warning = load_after_rebase_gate_settings(str(_root), budget)
    assert settings is not None
    assert settings.hook_command == ""
    assert warning is not None
    assert "trust allow" in warning[0]
    with patch("sase.workflows.commit.rebase_gate_settings.execute_gate") as execute:
        outcome = run_after_rebase_gate({}, str(_root))
    execute.assert_not_called()
    assert outcome.decision.get("verdict") == "warn"


def test_rebase_descriptor_blocks_retry_after_revoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, local = _repo(
        tmp_path,
        monkeypatch,
        "rebase-held",
        {"commit_hooks": {"after_rebase": "echo gate"}},
    )
    identity, _digest = _allow_current(local)
    from sase.workflows.commit.rebase_gate_budget import GateWorkBudget
    from sase.workflows.commit.rebase_gate_settings import (
        load_after_rebase_gate_settings,
        run_after_rebase_gate,
    )

    settings, warning = load_after_rebase_gate_settings(str(root), GateWorkBudget())
    assert warning is None
    assert settings is not None
    assert settings.hook_command == "echo gate"
    assert settings.trust is not None
    _revoke(identity)
    with patch("sase.workflows.commit.rebase_gate_settings.execute_gate") as execute:
        outcome = run_after_rebase_gate({}, str(root), settings=settings)
    execute.assert_not_called()
    assert outcome.decision.get("verdict") == "warn"


def test_file_hooks_block_untrusted_literal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(
        tmp_path,
        monkeypatch,
        "fh",
        {"file_hooks": [{"name": "local-hook", "command": "echo local"}]},
        {"file_hooks": [{"name": "user-hook", "command": "echo user"}]},
    )
    from sase.config.file_hooks import _load_file_hooks

    hooks = _load_file_hooks()
    assert [hook.name for hook in hooks] == ["user-hook"]


def test_file_hook_runner_skips_revoked_local_without_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, local = _repo(
        tmp_path,
        monkeypatch,
        "fh-run",
        {"file_hooks": [{"name": "local-hook", "command": "echo local"}]},
    )
    _allow_current(local)
    from sase.config.file_hooks import _load_file_hooks

    hooks = _load_file_hooks()
    assert [hook.name for hook in hooks] == ["local-hook"]
    evaluation = enforcement.evaluate_local_trust_for_path(local, None)
    assert evaluation.identity is not None
    _revoke(evaluation.identity)
    from sase.file_hooks.runner import _execute_run

    sentinel = root / "sentinel"
    run = {
        "index": 0,
        "hook_name": "local-hook",
        "command": f"touch {sentinel}",
        "timeout_seconds": 5,
        "source_layer": "local",
        "trust": {
            "identity": evaluation.identity,
            "config_path": evaluation.config_path,
            "logical_path": evaluation.logical_path,
            "digest": evaluation.digest,
            "status": "trusted",
            "enabled": True,
        },
        "abs_path": str(root / "report.md"),
        "repo_root": str(root),
        "project": "sase",
        "repo_kind": "primary",
        "sidecar_role": None,
        "rel_path": "report.md",
        "op": "ADD",
        "cause": "user",
        "agent_name": None,
    }
    finished = _execute_run("batch-test", run)
    assert finished["status"] == "finished"
    assert "trust" in (finished.get("failure") or "")
    assert not sentinel.exists()


def test_file_hooks_flag_off_includes_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.feature_flags import override_flags

    _repo(
        tmp_path,
        monkeypatch,
        "fh-off",
        {"file_hooks": [{"name": "local-hook", "command": "echo local"}]},
    )
    from sase.config.file_hooks import _load_file_hooks

    with override_flags(local_config_command_trust=False):
        hooks = _load_file_hooks()
    assert [hook.name for hook in hooks] == ["local-hook"]


def test_status_compatibility_flag_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    import io

    from sase.feature_flags import override_flags

    _root, local = _repo(
        tmp_path,
        monkeypatch,
        "status-off",
        {"commit_hooks": {"before": "echo hi"}},
    )
    from sase.config import local_trust_management as trust

    with override_flags(local_config_command_trust=False):
        stream = io.StringIO()
        code = trust.print_trust_status(local, stdout=stream)
        output = stream.getvalue()
    assert code == 0
    assert "compatibility" in output
    assert "compatibility mode" in output


def test_file_hooks_template_blocked_untrusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests._file_hooks_helpers import _registry_with_file_hook_provider

    _repo(
        tmp_path,
        monkeypatch,
        "fh-template",
        {
            "file_hooks": [
                {
                    "use": "sase-research-artifacts@research-highlights",
                    "command": "bob highlights create",
                    "filters": {"path_globs": ["final/**/*.md"]},
                }
            ]
        },
    )
    monkeypatch.setattr(
        "sase.artifact_providers.get_artifact_provider_registry",
        _registry_with_file_hook_provider,
    )
    monkeypatch.setattr("sase.macro.loader.detect_project", lambda: "sase")
    from sase.config.file_hooks import _load_file_hooks

    hooks = _load_file_hooks()
    assert hooks == []


def test_raw_file_hooks_preserved_when_untrusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(
        tmp_path,
        monkeypatch,
        "fh-raw",
        {"file_hooks": [{"name": "local-hook", "command": "echo local"}]},
    )
    from sase.config.core import load_config_layers

    layers = load_config_layers()
    local = next(layer for layer in layers if layer.name == "local")
    assert local.exists
    assert any(
        isinstance(item, dict) and item.get("name") == "local-hook"
        for item in local.data.get("file_hooks", [])
    )


def test_canonical_to_fallback_requires_new_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "fallback"
    (root / ".git").mkdir(parents=True)
    canonical = root / "sase" / "sase.yml"
    _write_yaml(canonical, {"commit_hooks": {"before": "echo hi"}})
    config_dir = tmp_path / "config-fallback"
    config_dir.mkdir()
    _write_yaml(config_dir / "sase.yml", {})
    state_dir = tmp_path / "state-fallback"
    state_dir.mkdir()
    monkeypatch.setenv("SASE_HOME", str(state_dir))
    import sase.config.core as core

    monkeypatch.setattr(core, "CONFIG_DIR", config_dir)
    monkeypatch.chdir(root)
    clear_config_cache()
    enforcement._warned_signatures.clear()
    assert (
        load_merged_config_for_local_path(canonical)["commit_hooks"].get("before", "")
        != "echo hi"
    )
    _allow_current(canonical)
    assert (
        load_merged_config_for_local_path(canonical)["commit_hooks"]["before"]
        == "echo hi"
    )
    canonical.unlink()
    (root / "sase").rmdir()
    legacy = root / "sase.yml"
    _write_yaml(legacy, {"commit_hooks": {"before": "echo hi"}})
    clear_config_cache()
    assert (
        load_merged_config_for_local_path(legacy)["commit_hooks"].get("before", "")
        != "echo hi"
    )


def test_stale_token_same_size_mtime_still_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _root, local = _repo(
        tmp_path, monkeypatch, "stale", {"commit_hooks": {"before": "echo hi"}}
    )
    _allow_current(local)
    assert (
        load_merged_config_for_local_path(local)["commit_hooks"]["before"] == "echo hi"
    )
    before_stat = local.stat()
    assert len("echo hi") == len("echo yo")
    local.write_text("commit_hooks:\n  before: echo yo\n", encoding="utf-8")
    os.utime(local, ns=(before_stat.st_atime_ns, before_stat.st_mtime_ns))
    assert local.stat().st_size == before_stat.st_size
    assert local.stat().st_mtime_ns == before_stat.st_mtime_ns
    clear_config_cache()
    assert (
        load_merged_config_for_local_path(local)
        .get("commit_hooks", {})
        .get("before", "")
        != "echo yo"
    )
    from sase.config.file_hooks import _load_file_hooks  # noqa: F401  (cache key uses digest)

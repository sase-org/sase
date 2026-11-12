"""Macro-enforcement regressions: loaders, namesakes, bash/python revalidation.

Phase ``macro-enforcement`` applies the shared local-command trust policy to
config macro sources and ``load_project_local_macros``, converts trusted
executable config entries into workflows, and revalidates before script
steps. Tests use temporary config/state and sentinel commands.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from sase.config import local_trust_enforcement as enforcement
from sase.config.core import clear_config_cache
from sase.macro.loader import load_macros_from_config, load_project_local_macros
from sase.macro.loader_sources import load_project_local_workflows
from sase.macro.local_trust import LocalMacroTrustError
from sase.macro.processor import process_macro_references
from sase.macro.workflow_executor import WorkflowExecutor
from sase.macro.workflow_loader import get_all_workflows
from sase.macro.workflow_models import WorkflowExecutionError


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
    monkeypatch.setattr("sase.macro.loader.detect_project", lambda: None)
    monkeypatch.setattr("sase.macro.workflow_loader.detect_project", lambda: None)
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


def _run_bash_workflow(workflow: object, artifacts: Path) -> None:
    executor = WorkflowExecutor(
        workflow=workflow,  # type: ignore[arg-type]
        args={},
        artifacts_dir=str(artifacts),
        hitl_override=False,
    )
    executor.execute()


def test_flag_off_loads_local_executable_macros(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.feature_flags import override_flags

    _repo(
        tmp_path,
        monkeypatch,
        "off",
        {
            "macros": {
                "lct_hello": "world",
                "lct_tool": {"content": "hi", "bash": "echo hi"},
            }
        },
    )
    with override_flags(local_config_command_trust=False):
        macros = load_macros_from_config()
        workflows = get_all_workflows()
    assert macros["lct_hello"].content == "world"
    assert "lct_tool" not in macros
    assert workflows["lct_tool"].steps[0].bash == "echo hi"


def test_untrusted_keeps_prompt_only_and_drops_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(
        tmp_path,
        monkeypatch,
        "block",
        {
            "macros": {
                "lct_hello": "world",
                "lct_tool": {"content": "hi", "bash": "echo hi"},
            },
            "timezone": "UTC",
        },
        {"macros": {"shared": "user"}},
    )
    macros = load_macros_from_config()
    workflows = get_all_workflows()
    assert macros["lct_hello"].content == "world"
    assert macros["shared"].content == "user"
    assert "lct_tool" not in macros
    assert "lct_tool" not in workflows


def test_untrusted_explicit_request_is_trust_error_not_namesake(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(
        tmp_path,
        monkeypatch,
        "namesake",
        {"macros": {"lct_tool": {"content": "local", "bash": "echo local"}}},
        {"macros": {"lct_tool": "user prompt"}},
    )
    macros = load_macros_from_config()
    assert macros["lct_tool"].content == "user prompt"
    with pytest.raises(LocalMacroTrustError, match="trust allow"):
        process_macro_references("#lct_tool", raise_on_error=True)


def test_acknowledged_local_bash_macro_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, local_path = _repo(
        tmp_path,
        monkeypatch,
        "ack",
        {
            "macros": {
                "lct_tool": {
                    "steps": [
                        {"name": "run", "bash": f"touch {tmp_path / 'ack-ran'}"},
                    ]
                }
            }
        },
    )
    assert "lct_tool" not in get_all_workflows()
    _allow_current(local_path)
    workflows = get_all_workflows()
    assert "lct_tool" in workflows
    assert workflows["lct_tool"].trust is not None
    _run_bash_workflow(workflows["lct_tool"], root / "artifacts")
    assert (tmp_path / "ack-ran").exists()


def test_change_after_ack_blocks_local_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _root, local_path = _repo(
        tmp_path,
        monkeypatch,
        "stale",
        {"macros": {"lct_tool": {"content": "hi", "bash": "echo hi"}}},
    )
    _allow_current(local_path)
    assert "lct_tool" in get_all_workflows()
    _write_yaml(
        local_path,
        {"macros": {"lct_tool": {"content": "hi", "bash": "echo yo"}}},
    )
    clear_config_cache()
    assert "lct_tool" not in get_all_workflows()
    with pytest.raises(LocalMacroTrustError, match="trust allow"):
        process_macro_references("#lct_tool", raise_on_error=True)


def test_revoke_blocks_and_revalidation_skips_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, local_path = _repo(
        tmp_path,
        monkeypatch,
        "revoke",
        {
            "macros": {
                "lct_tool": {
                    "steps": [
                        {"name": "run", "bash": f"touch {tmp_path / 'revoked'}"},
                    ]
                }
            }
        },
    )
    identity, _digest = _allow_current(local_path)
    workflow = get_all_workflows()["lct_tool"]
    _revoke(identity)
    with pytest.raises(WorkflowExecutionError, match="current trust"):
        _run_bash_workflow(workflow, root / "artifacts")
    assert not (tmp_path / "revoked").exists()
    assert "lct_tool" not in get_all_workflows()


def test_python_step_revalidates_before_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, local_path = _repo(
        tmp_path,
        monkeypatch,
        "py",
        {
            "macros": {
                "lct_tool": {
                    "python": (
                        f"from pathlib import Path; "
                        f"Path({str(tmp_path / 'py-ran')!r}).write_text('x')"
                    )
                }
            }
        },
    )
    identity, _digest = _allow_current(local_path)
    workflow = get_all_workflows()["lct_tool"]
    assert workflow.steps[0].python
    _revoke(identity)
    with pytest.raises(WorkflowExecutionError, match="current trust"):
        _run_bash_workflow(workflow, root / "artifacts")
    assert not (tmp_path / "py-ran").exists()


def test_nested_parallel_bash_is_command_bearing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(
        tmp_path,
        monkeypatch,
        "nested",
        {
            "macros": {
                "lct_deploy": {
                    "steps": [
                        {
                            "name": "fan",
                            "parallel": [
                                {"name": "a", "agent": "review"},
                                {"name": "b", "bash": "echo hi"},
                            ],
                        }
                    ]
                }
            }
        },
    )
    assert "lct_deploy" not in load_macros_from_config()
    assert "lct_deploy" not in get_all_workflows()
    with pytest.raises(LocalMacroTrustError, match="trust allow"):
        process_macro_references("#lct_deploy", raise_on_error=True)


def test_sparse_override_of_user_executable_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(
        tmp_path,
        monkeypatch,
        "sparse",
        {"macros": {"lct_tool": {"input": {"q": "word"}}}},
        {"macros": {"lct_tool": {"content": "hi", "bash": "echo hi"}}},
    )
    macros = load_macros_from_config()
    workflows = get_all_workflows()
    assert "lct_tool" not in macros
    assert workflows["lct_tool"].steps[0].bash == "echo hi"
    with pytest.raises(LocalMacroTrustError, match="trust allow"):
        process_macro_references("#lct_tool", raise_on_error=True)


def test_load_project_local_macros_filters_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, local_path = _repo(
        tmp_path,
        monkeypatch,
        "other",
        {
            "macros": {
                "lct_docs": "Write docs",
                "lct_tool": {"content": "hi", "bash": "echo hi"},
            }
        },
    )
    loaded = load_project_local_macros(root, "other")
    assert "other/lct_docs" in loaded
    assert loaded["other/lct_docs"].source_path == "project_local_config:other"
    assert "other/lct_tool" not in loaded
    assert load_project_local_workflows(root, "other") == {}
    _allow_current(local_path)
    trusted_macros = load_project_local_macros(root, "other")
    trusted_workflows = load_project_local_workflows(root, "other")
    assert "other/lct_docs" in trusted_macros
    assert "other/lct_tool" in trusted_workflows
    assert trusted_workflows["other/lct_tool"].trust is not None


def test_prompt_only_local_macro_still_expands_when_untrusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(
        tmp_path,
        monkeypatch,
        "prompt",
        {"macros": {"lct_hello": "from local"}},
    )
    with patch("sase.macro.processor.get_all_macros", load_macros_from_config):
        expanded = process_macro_references("#lct_hello", raise_on_error=True)
    assert expanded == "from local"


def test_inherited_reference_step_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(
        tmp_path,
        monkeypatch,
        "use",
        {"macros": {"lct_tool": {"steps": [{"name": "s", "use": "steps@shared"}]}}},
    )
    assert "lct_tool" not in get_all_workflows()
    with pytest.raises(LocalMacroTrustError, match="trust allow"):
        process_macro_references("#lct_tool", raise_on_error=True)

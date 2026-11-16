"""Trust-root: enforcement and acknowledgment share one checkout identity."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.config import local_trust_enforcement as enforcement
from sase.config import local_trust_enforcement_flag_on as enforcement_flag_on
from sase.config._local_trust_enforcement_shared import (
    checkout_root_for_local_path as enforcement_checkout_root,
)
from sase.config import local_trust_management as trust
from sase.config.core import clear_config_cache
from sase.config.local_trust import LOCAL_COMMAND_TRUST_POLICY_VERSION
from sase.content_layout import LayoutCollisionError, owning_checkout_root_for_config
from sase.core.paths import sase_home
from sase.core.rust import require_rust_binding


_COMMANDS = "commit_hooks:\n  before: echo hi\n"


def _canonical_checkout(root: Path, extra: str = "") -> Path:
    (root / ".git").mkdir(parents=True)
    config = root / "sase" / "sase.yml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(_COMMANDS + extra, encoding="utf-8")
    return root


def _legacy_checkout(root: Path) -> Path:
    (root / ".git").mkdir(parents=True)
    (root / "sase.yml").write_text(_COMMANDS, encoding="utf-8")
    return root


def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = tmp_path / "state"
    config_dir = tmp_path / "user-config"
    state.mkdir()
    config_dir.mkdir()
    (config_dir / "sase.yml").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("SASE_HOME", str(state))
    monkeypatch.delenv("SASE_WORKSPACE_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    import sase.config.core as core

    monkeypatch.setattr(core, "CONFIG_DIR", config_dir)
    clear_config_cache()
    enforcement_flag_on._warned_signatures.clear()


def _no_projects(monkeypatch: pytest.MonkeyPatch) -> None:
    from sase.core import project_lifecycle_facade

    monkeypatch.setattr(
        project_lifecycle_facade,
        "list_project_records",
        lambda *_args, **_kwargs: [],
    )


def _record(primary: Path, project_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(
        is_project=True,
        system_managed=False,
        workspace_dir=str(primary),
        project_dir=str(project_dir),
        project_name=project_dir.name,
        state="enabled",
        project_file=str(project_dir) + ".sase",
    )


def _assert_parity(root: Path, config: Path) -> tuple[str, str, str]:
    via_root = trust._resolve_local_command_trust_context(root)
    via_file = trust._resolve_local_command_trust_context(config)
    evaluation = enforcement.evaluate_local_trust_for_path(config, None)
    owned = owning_checkout_root_for_config(config)
    assert owned is not None
    assert via_root.checkout_root == via_file.checkout_root == owned.resolve()
    assert via_root.project_identity == via_file.project_identity == evaluation.identity
    assert via_root.logical_config_path == via_file.logical_config_path
    assert via_root.logical_config_path == evaluation.logical_path
    assert via_root.projection.digest == via_file.projection.digest == evaluation.digest
    assert evaluation.identity is not None
    assert evaluation.logical_path is not None
    return via_root.project_identity, evaluation.logical_path, evaluation.digest


def test_unregistered_canonical_checkout_is_repo_not_sase_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    _no_projects(monkeypatch)
    root = _canonical_checkout(tmp_path / "repo")
    config = root / "sase" / "sase.yml"

    identity, logical, _digest = _assert_parity(root, config)

    assert identity == f"checkout:v1:{root.resolve()}"
    assert logical == "sase/sase.yml"
    assert "/sase:" not in identity
    enforcement_flag_on._warned_signatures.clear()
    evaluation = enforcement.evaluate_local_trust_for_path(config, None)
    assert evaluation.trusted is False
    assert evaluation.warning is not None
    assert f"sase config trust allow {root.resolve()}" in evaluation.warning
    assert str(config) not in evaluation.warning.split("sase config trust allow ", 1)[1]


def test_unregistered_legacy_checkout_uses_sase_yml_logical_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    _no_projects(monkeypatch)
    root = _legacy_checkout(tmp_path / "repo")
    identity, logical, _digest = _assert_parity(root, root / "sase.yml")
    assert identity == f"checkout:v1:{root.resolve()}"
    assert logical == "sase.yml"


def test_registered_primary_matches_project_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    primary = _canonical_checkout(tmp_path / "primary")
    project_dir = tmp_path / "host-project-record"
    project_dir.mkdir()
    record = _record(primary, project_dir)
    from sase.core import project_lifecycle_facade

    monkeypatch.setattr(
        project_lifecycle_facade,
        "list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    identity, logical, _digest = _assert_parity(primary, primary / "sase" / "sase.yml")
    expected = f"project:v1:{project_dir.resolve()}:{primary.resolve()}"
    assert identity == expected
    assert logical == "sase/sase.yml"
    enforcement_flag_on._warned_signatures.clear()
    evaluation = enforcement.evaluate_local_trust_for_path(
        primary / "sase" / "sase.yml", None
    )
    assert evaluation.warning is not None
    assert f"sase config trust allow {primary.resolve()}" in evaluation.warning


def test_numbered_workspace_inherits_primary_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    workspace_root = tmp_path / "workspace-root"
    extra = f"workspace:\n  root: {workspace_root}\n  project_key: alpha\n"
    primary = _canonical_checkout(tmp_path / "primary", extra)
    numbered = _canonical_checkout(tmp_path / "sase_4", extra)
    project_dir = tmp_path / "host-project-record"
    project_dir.mkdir()
    record = _record(primary, project_dir)
    from sase.core import project_lifecycle_facade
    from sase.workspace_provider.store import WorkspaceStore

    monkeypatch.setattr(
        project_lifecycle_facade,
        "list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    store = WorkspaceStore(
        str(primary),
        config={
            "workspace": {
                "root": str(workspace_root),
                "project_key": "alpha",
            }
        },
    )
    registry_file = Path(store.root_dir) / "registry.json"
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_key": store.project_key,
                "primary_workspace_dir": str(primary),
                "workspaces": {
                    "4": {
                        "checkout_dir": str(numbered),
                        "materialization": "clone",
                        "role": "agent",
                        "created_at": 0,
                        "last_used_at": 0,
                        "pinned": False,
                        "generation": 0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    clear_config_cache()

    expected = f"project:v1:{project_dir.resolve()}:{primary.resolve()}"
    primary_identity, _logical, digest = _assert_parity(
        primary, primary / "sase" / "sase.yml"
    )
    numbered_identity, numbered_logical, numbered_digest = _assert_parity(
        numbered, numbered / "sase" / "sase.yml"
    )
    assert primary_identity == numbered_identity == expected
    assert numbered_logical == "sase/sase.yml"
    assert numbered_digest == digest

    enforcement_flag_on._warned_signatures.clear()
    numbered_eval = enforcement.evaluate_local_trust_for_path(
        numbered / "sase" / "sase.yml", None
    )
    assert numbered_eval.warning is not None
    assert f"sase config trust allow {primary.resolve()}" in numbered_eval.warning
    assert (
        str(numbered)
        not in numbered_eval.warning.split("sase config trust allow ", 1)[1]
    )

    binding = require_rust_binding("local_command_trust_store_allow")
    binding(
        str(sase_home()),
        expected,
        digest,
        LOCAL_COMMAND_TRUST_POLICY_VERSION,
        "test",
    )
    enforcement_flag_on._warned_signatures.clear()
    clear_config_cache()
    trusted = enforcement.evaluate_local_trust_for_path(
        numbered / "sase" / "sase.yml", None
    )
    assert trusted.trusted is True
    assert trusted.identity == expected


def test_symlinked_checkout_canonicalizes_to_real_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    _no_projects(monkeypatch)
    real = _canonical_checkout(tmp_path / "real" / "repo")
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    identity, logical, _digest = _assert_parity(alias, alias / "sase" / "sase.yml")
    assert identity == f"checkout:v1:{real.resolve()}"
    assert logical == "sase/sase.yml"


def test_repo_named_sase_legacy_and_canonical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    _no_projects(monkeypatch)

    legacy_named = _legacy_checkout(tmp_path / "x" / "sase")
    identity, logical, _digest = _assert_parity(legacy_named, legacy_named / "sase.yml")
    assert identity == f"checkout:v1:{legacy_named.resolve()}"
    assert logical == "sase.yml"

    parent = tmp_path / "parent"
    canonical_named = _canonical_checkout(parent / "sase")
    identity, logical, _digest = _assert_parity(
        canonical_named, canonical_named / "sase" / "sase.yml"
    )
    assert identity == f"checkout:v1:{canonical_named.resolve()}"
    assert logical == "sase/sase.yml"


def test_collision_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    _no_projects(monkeypatch)
    root = _canonical_checkout(tmp_path / "repo")
    (root / "sase.yml").write_text(_COMMANDS, encoding="utf-8")
    config = root / "sase" / "sase.yml"

    with pytest.raises(LayoutCollisionError):
        owning_checkout_root_for_config(config)
    assert enforcement_checkout_root(config) is None
    with pytest.raises(trust._LocalCommandTrustManagementError, match="multiple"):
        trust._requested_checkout(config)

    evaluation = enforcement.evaluate_local_trust_for_path(config, None)
    assert evaluation.trusted is False
    assert evaluation.identity is not None
    assert not evaluation.identity.startswith("project:v1:")
    assert evaluation.identity != f"checkout:v1:{root.resolve()}"


def test_legacy_key_is_not_honored_under_cutover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    _no_projects(monkeypatch)
    root = _canonical_checkout(tmp_path / "repo")
    config = root / "sase" / "sase.yml"
    evaluation = enforcement.evaluate_local_trust_for_path(config, None)
    assert evaluation.digest
    binding = require_rust_binding("local_command_trust_store_allow")
    binding(
        str(sase_home()),
        f"checkout:v1:{root.resolve() / 'sase'}",
        evaluation.digest,
        LOCAL_COMMAND_TRUST_POLICY_VERSION,
        "test",
    )
    enforcement_flag_on._warned_signatures.clear()
    clear_config_cache()
    after = enforcement.evaluate_local_trust_for_path(config, None)
    assert after.trusted is False
    assert after.identity == f"checkout:v1:{root.resolve()}"
    assert after.warning is not None
    assert f"sase config trust allow {root.resolve()}" in after.warning


def test_requested_checkout_from_sase_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    _no_projects(monkeypatch)
    root = _canonical_checkout(tmp_path / "repo")
    monkeypatch.chdir(root / "sase")
    checkout, selected = trust._requested_checkout(None)
    assert checkout == root.resolve()
    assert selected.resolve() == (root / "sase" / "sase.yml").resolve()


def test_acknowledgment_target_path_names_primary_for_project_identity(
    tmp_path: Path,
) -> None:
    root = tmp_path / "ws"
    primary = tmp_path / "primary"
    identity = f"project:v1:{tmp_path / 'proj'}:{primary}"
    assert trust.acknowledgment_target_path(root, identity) == primary
    checkout_identity = f"checkout:v1:{root}"
    assert trust.acknowledgment_target_path(root, checkout_identity) == root

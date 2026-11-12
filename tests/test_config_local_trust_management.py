"""Host identity, filesystem and acknowledgment CLI tests for local trust."""

from __future__ import annotations

from dataclasses import replace as dataclass_replace
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.config import local_trust_management as trust
from sase.config.local_trust import LocalCommandProjection
from sase.main.parser import create_parser


def _checkout(root: Path, config: str = "") -> Path:
    (root / ".git").mkdir(parents=True)
    config_path = root / "sase" / "sase.yml"
    config_path.parent.mkdir()
    config_path.write_text(config, encoding="utf-8")
    return root


def _projection(
    *, digest: str = "a" * 64, canonical_json: str = "{}"
) -> LocalCommandProjection:
    return LocalCommandProjection(
        projection={"commit_hooks": {"before": "echo hi"}},
        blocked_paths=("commit_hooks",),
        diagnostics=(),
        digest=digest,
        canonical_json=canonical_json,
        config_path="sase/sase.yml",
    )


def _context(root: Path, *, digest: str = "a" * 64) -> trust._LocalCommandTrustContext:
    return trust._LocalCommandTrustContext(
        checkout_root=root,
        selected_config_path=root / "sase" / "sase.yml",
        logical_config_path="sase/sase.yml",
        project_identity=f"checkout:v1:{root}",
        projection=_projection(digest=digest),
    )


def test_context_binds_logical_config_location_into_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _checkout(
        tmp_path / "repo",
        "commit_hooks:\n  before: echo hi\nalias: local-name\n",
    )
    monkeypatch.setattr(trust, "load_merged_config_for_local_path", lambda _path: {})
    monkeypatch.setattr(
        trust,
        "_project_identity",
        lambda checkout, _config: f"checkout:v1:{checkout}",
    )
    seen: list[str | None] = []

    def project(_layer, **kwargs):
        seen.append(kwargs.get("config_path"))
        return _projection()

    monkeypatch.setattr(trust, "project_local_commands", project)
    canonical = trust._resolve_local_command_trust_context(root)
    assert canonical.logical_config_path == "sase/sase.yml"
    assert canonical.selected_config_path == root / "sase" / "sase.yml"

    canonical.selected_config_path.unlink()
    (root / "sase").rmdir()
    (root / "sase.yml").write_text(
        "commit_hooks:\n  before: echo hi\nalias: local-name\n", encoding="utf-8"
    )
    legacy = trust._resolve_local_command_trust_context(root)
    assert legacy.logical_config_path == "sase.yml"
    assert seen == ["sase/sase.yml", "sase.yml"]


def test_path_must_select_checkout_or_its_effective_config(tmp_path: Path) -> None:
    root = _checkout(tmp_path / "repo")
    unrelated = root / "notes.txt"
    unrelated.write_text("not a config", encoding="utf-8")
    with pytest.raises(RuntimeError, match="PATH must"):
        trust._resolve_local_command_trust_context(unrelated)


def test_registered_primary_uses_project_record_and_canonical_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _checkout(tmp_path / "primary")
    project_dir = tmp_path / "host-project-record"
    record = SimpleNamespace(
        is_project=True,
        system_managed=False,
        workspace_dir=str(primary),
        project_dir=str(project_dir),
    )
    from sase.core import project_lifecycle_facade

    monkeypatch.setattr(
        project_lifecycle_facade,
        "list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    identity = trust._project_identity(primary.resolve(), primary / "sase" / "sase.yml")
    assert identity == f"project:v1:{project_dir.resolve()}:{primary.resolve()}"


def test_managed_identity_requires_workspace_registry_membership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _checkout(tmp_path / "primary")
    managed = _checkout(tmp_path / "managed-checkout")
    spoofed = _checkout(tmp_path / "spoofed-checkout")
    spoof_marker = spoofed / ".sase"
    spoof_marker.mkdir()
    (spoof_marker / "checkout.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_name": "alpha",
                "project_key": "alpha",
                "workspace_num": 4,
                "primary_workspace_dir": str(primary),
                "registry_path": str(
                    tmp_path / "workspace-root" / "alpha" / "registry.json"
                ),
            }
        ),
        encoding="utf-8",
    )
    record = SimpleNamespace(
        is_project=True,
        system_managed=False,
        workspace_dir=str(primary),
        project_dir=str(tmp_path / "host-project-record"),
    )
    from sase.core import project_lifecycle_facade
    from sase.workspace_provider.store import WorkspaceStore

    monkeypatch.setattr(
        project_lifecycle_facade,
        "list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    monkeypatch.setattr(trust, "resolve_project_config_read_path", lambda _root: None)
    monkeypatch.setattr(
        trust,
        "load_merged_config_for_local_path",
        lambda _path: {
            "workspace": {
                "root": str(tmp_path / "workspace-root"),
                "project_key": "alpha",
            }
        },
    )
    monkeypatch.delenv("SASE_WORKSPACE_ROOT", raising=False)
    store = WorkspaceStore(
        str(primary),
        config={
            "workspace": {
                "root": str(tmp_path / "workspace-root"),
                "project_key": "alpha",
            }
        },
    )
    registry_path = Path(store.root_dir) / "registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_key": store.project_key,
                "primary_workspace_dir": str(primary),
                "workspaces": {
                    "4": {
                        "checkout_dir": str(managed),
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

    managed_identity = trust._project_identity(
        managed.resolve(), managed / "sase" / "sase.yml"
    )
    spoofed_identity = trust._project_identity(
        spoofed.resolve(), spoofed / "sase" / "sase.yml"
    )
    expected = f"project:v1:{Path(record.project_dir).resolve()}:{primary.resolve()}"
    assert managed_identity == expected
    assert spoofed_identity == f"checkout:v1:{spoofed.resolve()}"


def test_agent_cannot_acknowledge_through_public_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _checkout(tmp_path / "repo", "commit_hooks:\n  before: echo hi\n")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("SASE_AGENT_NAME", "reviewer-agent")

    assert trust.allow_local_commands(root) == 1
    assert "only be changed by a human" in capsys.readouterr().err
    assert not (tmp_path / "state" / "local_config_trust" / "records.json").exists()


def test_direct_mutation_adapter_repeats_human_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse() -> str:
        raise RuntimeError("human terminal required")

    monkeypatch.setattr(trust, "_require_human_terminal", refuse)
    monkeypatch.setattr(
        trust,
        "require_rust_binding",
        lambda _name: pytest.fail("Rust store must not be called"),
    )
    with pytest.raises(RuntimeError, match="human terminal"):
        trust._store_allow("checkout:v1:/repo", "a" * 64)
    with pytest.raises(RuntimeError, match="human terminal"):
        trust._store_revoke("checkout:v1:/repo")


def test_allow_refuses_if_config_changes_after_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "repo"
    reviewed = _context(root)
    changed = _context(root, digest="b" * 64)
    contexts = iter((reviewed, changed))
    stored: list[tuple[str, str]] = []
    monkeypatch.setattr(trust, "_require_human_terminal", lambda: "human")
    monkeypatch.setattr(
        trust, "_resolve_local_command_trust_context", lambda _path=None: next(contexts)
    )
    monkeypatch.setattr(
        trust,
        "_status_payload",
        lambda _context: {"status": "review_required"},
    )
    monkeypatch.setattr(
        trust,
        "_store_allow",
        lambda identity, digest: stored.append((identity, digest)),
    )
    monkeypatch.setattr(trust.sys, "stdin", io.StringIO("allow\n"))

    assert trust.allow_local_commands(root) == 1
    assert "configuration changed; review again" in capsys.readouterr().err
    assert stored == []


def test_confirmation_preview_escapes_terminal_controls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "repo"
    context = _context(root)
    context = dataclass_replace(
        context,
        projection=_projection(canonical_json='{"commands":{"bash":"\\u001b[31m"}}'),
    )
    monkeypatch.setattr(trust, "_require_human_terminal", lambda: "human")
    monkeypatch.setattr(
        trust, "_resolve_local_command_trust_context", lambda _path=None: context
    )
    monkeypatch.setattr(
        trust,
        "_status_payload",
        lambda _context: {"status": "review_required"},
    )
    monkeypatch.setattr(trust, "_store_allow", lambda *_args: {"changed": True})
    monkeypatch.setattr(trust.sys, "stdin", io.StringIO("allow\n"))

    assert trust.allow_local_commands(root) == 0
    output = capsys.readouterr().out
    assert "\\u001b" in output
    assert "\x1b" not in output


def test_status_json_distinguishes_operational_error(
    tmp_path: Path,
) -> None:
    stream = io.StringIO()
    result = trust.print_trust_status(
        tmp_path / "no-checkout", as_json=True, stdout=stream
    )
    payload = json.loads(stream.getvalue())
    assert result == 2
    assert payload["status"] == "operational_error"
    assert payload["reason"]


def test_config_trust_cli_arguments() -> None:
    parser = create_parser(only="config")
    args = parser.parse_args(["config", "trust", "status", "--json", "/repo"])
    assert args.config_subcommand == "trust"
    assert args.config_trust_subcommand == "status"
    assert args.path == "/repo"
    assert args.json is True


def test_bare_config_trust_prints_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main.config_handler import handle_config_command

    parser = create_parser(only="config")
    args = parser.parse_args(["config", "trust"])
    with pytest.raises(SystemExit) as exit_info:
        handle_config_command(args)
    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "{allow,revoke,status}" in output

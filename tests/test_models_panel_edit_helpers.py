"""Tests for the Models panel's persistent alias edit/reset helpers.

Phase 3 (epic sase-5e): cover the pure pieces around the Rust-backed config-edit
path — planning a ``llm_provider.model_aliases.builtin.<alias>`` set/unset edit
(including the chezmoi source remap of the write target) and deciding whether to
offer a commit+push for the file that was actually written (git-root detection
across the ``use_chezmoi`` on/off branches).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from sase.ace.tui.modals.models_panel_edit_helpers import (
    AliasCommitOffer,
    _alias_field_path,
    alias_model_edit_path,
    alias_reset_path,
    build_alias_commit_offer,
    plan_alias_edit,
)
from sase.config import ConfigEditError, ConfigEditOp
from sase.config.core import ConfigLayer
from sase.config.inventory import build_config_inventory


ALIAS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "llm_provider": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "model_aliases": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "builtin": {
                            "type": "object",
                            "additionalProperties": {"type": "string"},
                        },
                        "custom": {
                            "type": "object",
                            "additionalProperties": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["model", "description"],
                                "properties": {
                                    "model": {"type": "string", "minLength": 1},
                                    "description": {
                                        "type": "string",
                                        "minLength": 1,
                                        "maxLength": 160,
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    },
}


def _layer(
    name: str,
    *,
    path: str | None = None,
    strategy: str = "concatenate",
    data: dict[str, Any] | None = None,
    exists: bool = True,
) -> ConfigLayer:
    return ConfigLayer(
        name=name,
        path=path,
        exists=exists,
        list_strategy=strategy,
        data=data or {},
    )


def _inventory(layers: list[ConfigLayer], schema: dict[str, Any] | None = None) -> Any:
    with patch("sase.config.inventory.load_config_layers", return_value=layers):
        return build_config_inventory(schema=schema or ALIAS_SCHEMA)


def _alias_inventory(tmp_path: Path, user_text: str) -> tuple[Any, Path]:
    """Build a [default, user] inventory backed by a real user ``sase.yml``."""
    user_file = tmp_path / "sase.yml"
    user_file.write_text(user_text, encoding="utf-8")
    user_data = yaml.safe_load(user_text) if user_text.strip() else {}
    layers = [
        _layer("default", data={}),
        _layer("user", path=str(user_file), strategy="replace", data=user_data or {}),
    ]
    return _inventory(layers), user_file


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=Test",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    )


# --- _alias_field_path ----------------------------------------------------


def test_alias_field_path_builds_map_key_path() -> None:
    assert (
        _alias_field_path("medium_worker")
        == "llm_provider.model_aliases.builtin.medium_worker"
    )


def test_alias_field_path_strips_and_rejects_empty() -> None:
    assert _alias_field_path("  worker  ") == (
        "llm_provider.model_aliases.builtin.worker"
    )
    with pytest.raises(ValueError):
        _alias_field_path("   ")


def test_alias_model_edit_path_routes_by_kind_and_source() -> None:
    assert (
        alias_model_edit_path(
            "medium_worker",
            kind="role",
            configured_source="builtin",
        )
        == "llm_provider.model_aliases.builtin.medium_worker"
    )
    assert (
        alias_model_edit_path(
            "blogger",
            kind="user",
            configured_source="custom",
        )
        == "llm_provider.model_aliases.custom.blogger.model"
    )
    assert (
        alias_model_edit_path(
            "blogger",
            kind="user",
            configured_source="builtin",
        )
        == "llm_provider.model_aliases.builtin.blogger"
    )


def test_alias_reset_path_deletes_custom_user_alias_entry() -> None:
    assert (
        alias_reset_path(
            "blogger",
            kind="user",
            configured_source="custom",
        )
        == "llm_provider.model_aliases.custom.blogger"
    )
    assert (
        alias_reset_path(
            "medium_worker",
            kind="role",
            configured_source="custom",
        )
        == "llm_provider.model_aliases.builtin.medium_worker"
    )


# --- plan_alias_edit ------------------------------------------------------


def test_plan_alias_edit_set(tmp_path: Path) -> None:
    inventory, user_file = _alias_inventory(tmp_path, "")
    plan = plan_alias_edit(
        "medium_worker",
        ConfigEditOp.set_value("opus"),
        inventory=inventory,
        use_chezmoi=False,
    )
    assert plan.write_plan.key_path == (
        "llm_provider",
        "model_aliases",
        "builtin",
        "medium_worker",
    )
    assert plan.write_plan.op == "set"
    assert plan.write_plan.new_value == "opus"
    assert plan.target_path == str(user_file)
    assert plan.is_valid is True
    assert "medium_worker: opus" in plan.new_text
    assert "+" in plan.text_diff


def test_plan_alias_edit_custom_model_path(tmp_path: Path) -> None:
    inventory, user_file = _alias_inventory(
        tmp_path,
        "llm_provider:\n"
        "  model_aliases:\n"
        "    custom:\n"
        "      blogger:\n"
        "        model: claude/haiku\n"
        "        description: Draft posts.\n",
    )
    plan = plan_alias_edit(
        "blogger",
        ConfigEditOp.set_value("claude/opus"),
        path="llm_provider.model_aliases.custom.blogger.model",
        inventory=inventory,
        use_chezmoi=False,
    )
    assert plan.write_plan.key_path == (
        "llm_provider",
        "model_aliases",
        "custom",
        "blogger",
        "model",
    )
    assert plan.write_plan.op == "set"
    assert plan.write_plan.new_value == "claude/opus"
    assert plan.target_path == str(user_file)
    assert "model: claude/opus" in plan.new_text


def test_plan_alias_edit_rejects_descriptionless_custom_entry(tmp_path: Path) -> None:
    inventory, _ = _alias_inventory(tmp_path, "")

    plan = plan_alias_edit(
        "blogger",
        ConfigEditOp.set_value("claude/opus"),
        path="llm_provider.model_aliases.custom.blogger.model",
        inventory=inventory,
        use_chezmoi=False,
    )

    assert plan.is_valid is False
    assert any("description" in diagnostic.message for diagnostic in plan.validation)


def test_plan_alias_edit_unset(tmp_path: Path) -> None:
    inventory, _ = _alias_inventory(
        tmp_path,
        "llm_provider:\n  model_aliases:\n    builtin:\n      medium_worker: opus\n",
    )
    plan = plan_alias_edit(
        "medium_worker",
        ConfigEditOp.unset(),
        inventory=inventory,
        use_chezmoi=False,
    )
    assert plan.write_plan.op == "unset"
    assert plan.effective_preview.has_before is True
    assert plan.effective_preview.before == "opus"
    # Resetting removes the configured key, so the alias falls back to implicit.
    assert plan.effective_preview.has_after is False
    assert "medium_worker: opus" not in plan.new_text


def test_plan_alias_edit_chezmoi_remaps_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    chezmoi = tmp_path / "chezmoi" / "home"
    config_dir = home / ".config" / "sase"
    config_dir.mkdir(parents=True)
    user_file = config_dir / "sase.yml"
    user_file.write_text(
        "llm_provider:\n  model_aliases:\n    builtin:\n      medium_worker: opus\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr("sase.config.targets.CHEZMOI_HOME", chezmoi)

    layers = [
        _layer("default", data={}),
        _layer(
            "user",
            path=str(user_file),
            strategy="replace",
            data={
                "llm_provider": {
                    "model_aliases": {"builtin": {"medium_worker": "opus"}}
                }
            },
        ),
    ]
    inventory = _inventory(layers)
    plan = plan_alias_edit(
        "medium_worker",
        ConfigEditOp.set_value("sonnet"),
        inventory=inventory,
        use_chezmoi=True,
    )
    assert plan.used_chezmoi is True
    assert plan.target_path == str(chezmoi / "dot_config" / "sase" / "sase.yml")


def test_plan_alias_edit_no_writable_layer_raises() -> None:
    inventory = _inventory([_layer("default", data={})])
    with pytest.raises(ConfigEditError):
        plan_alias_edit(
            "medium_worker",
            ConfigEditOp.set_value("opus"),
            inventory=inventory,
            use_chezmoi=False,
        )


# --- build_alias_commit_offer ---------------------------------------------


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")


def test_commit_offer_set_in_repo_with_changes(tmp_path: Path) -> None:
    """A written user sase.yml inside a git repo (chezmoi off) yields an offer."""
    repo = tmp_path / "userconfig"
    _init_repo(repo)
    target = repo / "sase.yml"
    target.write_text(
        "llm_provider:\n  model_aliases:\n    builtin:\n      medium_worker: opus\n"
    )

    offer = build_alias_commit_offer(str(target), op="set", alias="medium_worker")

    assert isinstance(offer, AliasCommitOffer)
    assert offer.git_root == str(repo)
    assert offer.file_path == str(target)
    assert offer.rel_path == "sase.yml"
    assert offer.message.startswith("chore: Update model alias @medium_worker")
    assert "SASE_TYPE=config" in offer.message


def test_commit_offer_reset_uses_reset_verb(tmp_path: Path) -> None:
    repo = tmp_path / "userconfig"
    _init_repo(repo)
    target = repo / "sase.yml"
    target.write_text("llm_provider: {}\n")

    offer = build_alias_commit_offer(str(target), op="unset", alias="medium_worker")

    assert offer is not None
    assert offer.message.startswith("chore: Reset model alias @medium_worker")


def test_commit_offer_chezmoi_source_repo(tmp_path: Path) -> None:
    """chezmoi-on branch: the written chezmoi source lives in the chezmoi repo."""
    repo = tmp_path / "chezmoi"
    _init_repo(repo)
    source = repo / "home" / "dot_config" / "sase" / "sase.yml"
    source.parent.mkdir(parents=True)
    source.write_text(
        "llm_provider:\n  model_aliases:\n    builtin:\n      medium_worker: opus\n"
    )

    offer = build_alias_commit_offer(str(source), op="set", alias="medium_worker")

    assert offer is not None
    assert offer.git_root == str(repo)
    assert offer.rel_path == "home/dot_config/sase/sase.yml"


def test_commit_offer_not_in_repo_returns_none(tmp_path: Path) -> None:
    """A target outside any git repo skips the offer gracefully."""
    target = tmp_path / "loose" / "sase.yml"
    target.parent.mkdir(parents=True)
    target.write_text("llm_provider: {}\n")

    assert (
        build_alias_commit_offer(str(target), op="set", alias="medium_worker") is None
    )


def test_commit_offer_no_pending_changes_returns_none(tmp_path: Path) -> None:
    """A clean, fully-committed target produces no offer."""
    repo = tmp_path / "userconfig"
    _init_repo(repo)
    target = repo / "sase.yml"
    target.write_text("llm_provider: {}\n")
    _git(repo, "add", "sase.yml")
    _git(repo, "commit", "-q", "-m", "init")

    assert (
        build_alias_commit_offer(str(target), op="set", alias="medium_worker") is None
    )

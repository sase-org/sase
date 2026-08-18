"""Tests for ``plugins.required`` resolution and fail-closed helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from sase.plugins import required as required_plugins
from sase.plugins.required import (
    RequiredPluginError,
    fail_closed_required_plugins,
    missing_required_plugin_message,
    required_plugin_blockers,
    required_plugin_distribution_names,
    required_plugin_requirement_strings,
    resolve_required_plugins,
)
from sase.project_management import load_local_config


def _config(
    required: list[Any] | None = None,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if required is not None:
        data["plugins"] = {"required": required}
    if extra:
        data.update(extra)
    return data


def test_required_plugin_distribution_names_normalizes_and_skips_invalid() -> None:
    names = required_plugin_distribution_names(
        _config(["sase-github", "Sase_Research_Artifacts>=0.2", "not a requirement!!!"])
    )
    assert names == frozenset({"sase-github", "sase-research-artifacts"})
    assert required_plugin_distribution_names({}) == frozenset()


def test_required_plugin_requirement_strings_keeps_version_specifiers() -> None:
    assert required_plugin_requirement_strings(
        _config(
            ["sase-github>=0.2.5", "sase-research-artifacts", "not a requirement!!!"]
        )
    ) == ("sase-github>=0.2.5", "sase-research-artifacts")
    assert required_plugin_requirement_strings({}) == ()


def test_plugin_install_command_names_the_distribution() -> None:
    assert required_plugins._plugin_install_command("sase-github") == (
        "sase plugin install sase-github"
    )


def test_missing_required_plugin_message_names_install_command() -> None:
    assert missing_required_plugin_message("sase-github") == (
        "required plugin `sase-github` is not installed; "
        "run `sase plugin install sase-github`"
    )


def test_iter_plugin_qualified_use_values_walks_sidecars_and_hooks() -> None:
    config = {
        "repos": {
            "sidecar": {
                "builtin": {"plans": {"ref": {"use": "builtin@plan"}}},
                "custom": {
                    "research": {"ref": {"use": "sase-research-artifacts@research"}}
                },
            }
        },
        "file_hooks": [{"use": "sase-research-artifacts@research-highlights"}],
    }

    found = required_plugins._iter_plugin_qualified_use_values(config)

    assert found == (
        ("repos.sidecar.builtin.plans.ref.use", "builtin", "plan"),
        (
            "repos.sidecar.custom.research.ref.use",
            "sase-research-artifacts",
            "research",
        ),
        ("file_hooks[0].use", "sase-research-artifacts", "research-highlights"),
    )


def test_iter_plugin_qualified_use_values_skips_unprefixed() -> None:
    assert required_plugins._iter_plugin_qualified_use_values({"use": "research"}) == ()


def test_resolve_required_plugins_reports_invalid_and_duplicate_entries() -> None:
    report = resolve_required_plugins(
        _config(["sase-github", "not a requirement!!!", "sase-github>=1", 3]),
        installed_versions={"sase-github": "1.0.0"},
    )

    kinds = [issue.kind for issue in report.issues]
    assert "invalid" in kinds
    assert "duplicate" in kinds
    assert any(
        "not a valid PEP 508 requirement" in issue.message for issue in report.issues
    )
    assert any(
        "duplicated distribution name" in issue.message for issue in report.issues
    )


def test_resolve_required_plugins_reports_missing_and_version_mismatch() -> None:
    report = resolve_required_plugins(
        _config(["sase-github", "sase-research-artifacts>=2"]),
        installed_versions={"sase-research-artifacts": "0.1.0"},
    )

    assert not report.ok
    assert [issue.kind for issue in report.issues] == ["missing", "version_mismatch"]
    assert [issue.kind for issue in report.installable] == [
        "missing",
        "version_mismatch",
    ]
    assert report.issues[0].message == (
        "required plugin `sase-github` is not installed; "
        "run `sase plugin install sase-github`"
    )
    assert "sase plugin install sase-github" in report.issues[0].message
    assert "installed as 0.1.0" in report.issues[1].message
    assert (
        report.issues[1].install_command
        == "sase plugin install sase-research-artifacts"
    )


def test_resolve_required_plugins_satisfied_when_installed() -> None:
    report = resolve_required_plugins(
        _config(["sase-github", "sase-research-artifacts>=0.2"]),
        installed_versions={
            "sase-github": "1.4.0",
            "sase-research-artifacts": "0.2.1",
        },
    )

    assert report.ok
    assert len(report.satisfied) == 2


def test_resolve_required_plugins_cross_checks_use_prefixes() -> None:
    report = resolve_required_plugins(
        _config(
            ["sase-github"],
            extra={
                "repos": {
                    "sidecar": {
                        "custom": {
                            "research": {
                                "ref": {"use": "sase-research-artifacts@research"}
                            }
                        }
                    }
                }
            },
        ),
        installed_versions={"sase-github": "1.0.0"},
    )

    assert not report.ok
    undeclared = [issue for issue in report.issues if issue.kind == "undeclared_prefix"]
    assert len(undeclared) == 1
    assert undeclared[0].config_path == "repos.sidecar.custom.research.ref.use"
    assert "sase-research-artifacts" in undeclared[0].message
    assert "plugins.required" in undeclared[0].message
    assert report.installable == ()


def test_resolve_required_plugins_ignores_builtin_prefixes() -> None:
    report = resolve_required_plugins(
        {
            "repos": {
                "sidecar": {"builtin": {"plans": {"ref": {"use": "builtin@plan"}}}}
            }
        },
        installed_versions={},
    )

    assert report.ok
    assert report.prefixes == ()


def test_required_plugin_blockers_prefix_command_label() -> None:
    blockers = required_plugin_blockers(
        _config(["sase-github"]),
        installed_versions={},
    )

    assert blockers == (
        "init memory: required plugin `sase-github` is not installed; "
        "run `sase plugin install sase-github`",
    )


def test_fail_closed_required_plugins_raises_without_installing() -> None:
    report = resolve_required_plugins(_config(["sase-github"]), installed_versions={})

    with pytest.raises(RequiredPluginError, match="sase plugin install sase-github"):
        fail_closed_required_plugins(report)

    assert "required plugin `sase-github` is not installed" in (
        required_plugins._fail_closed_required_plugins_text(report)
    )


def test_fail_closed_required_plugins_is_noop_when_ok() -> None:
    report = resolve_required_plugins(_config([]), installed_versions={})
    fail_closed_required_plugins(report)


def test_empty_config_is_ok() -> None:
    assert resolve_required_plugins({}, installed_versions={}).ok
    assert resolve_required_plugins(None, installed_versions={}).ok


def test_project_sase_yml_required_covers_its_use_prefixes() -> None:
    config_path = Path(__file__).resolve().parents[1] / "sase" / "sase.yml"
    loaded = load_local_config(config_path)
    assert loaded.valid
    report = resolve_required_plugins(
        loaded.config,
        installed_versions={
            "sase-github": "0.0.0",
            "sase-research-artifacts": "0.0.0",
        },
    )
    assert report.config_errors == ()
    prefixes = {prefix.normalized_plugin for prefix in report.prefixes}
    required = {item.normalized_name for item in report.requirements}
    assert prefixes <= required
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert raw["plugins"]["required"] == [
        "sase-github>=0.2.5",
        "sase-research-artifacts>=0.2.0",
    ]

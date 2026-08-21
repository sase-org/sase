"""Tests for doctor sidecar repo config checks."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from sase.artifact_providers import (
    ArtifactProviderRegistry,
    reset_artifact_provider_registry_cache,
)
from sase.doctor.checks_config_repos import check_config_repos


def _empty_artifact_provider_registry(
    *,
    disabled_env: tuple[str, ...] = (),
) -> ArtifactProviderRegistry:
    return ArtifactProviderRegistry(
        ref_providers=(),
        file_hook_providers=(),
        entry_kinds=(),
        diagnostics=(),
        disabled_env=disabled_env,
    )


@pytest.fixture(autouse=True)
def _isolate_artifact_provider_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    reset_artifact_provider_registry_cache()
    monkeypatch.setattr(
        "sase.artifact_providers.get_artifact_provider_registry",
        lambda: _empty_artifact_provider_registry(),
    )
    yield
    reset_artifact_provider_registry_cache()


def _patch_config(monkeypatch: pytest.MonkeyPatch, config: dict[str, Any]) -> None:
    monkeypatch.setattr("sase.config.core.load_merged_config", lambda: config)


@pytest.mark.parametrize("disable_plugins", [False, True])
def test_repos_reports_ok_for_canonical_bucketed_config(
    monkeypatch: pytest.MonkeyPatch, disable_plugins: bool
) -> None:
    """The canonical mapping shape produces no problems."""
    if disable_plugins:
        monkeypatch.setenv("SASE_DISABLE_PLUGINS", "1")
    else:
        monkeypatch.delenv("SASE_DISABLE_PLUGINS", raising=False)
    _patch_config(
        monkeypatch,
        {
            "repos": {
                "sidecar": {
                    "builtin": {
                        "plans": {"auto_clone": True},
                        "beads": {"auto_clone": True},
                        "agents": {"description": "Hidden agent data."},
                    },
                    "custom": {"research": {"description": "Durable research."}},
                }
            }
        },
    )

    check = check_config_repos()

    assert check.status == "OK"
    assert check.data["problems"] == ()
    assert check.next_steps == ()


def test_repos_reports_removed_list_with_target_buckets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each stale list entry names the bucket it must move to."""
    _patch_config(
        monkeypatch,
        {
            "repos": {
                "sidecar": [
                    {"name": "plans", "auto_clone": True},
                    {"name": "research", "description": "Durable research."},
                ]
            }
        },
    )

    check = check_config_repos()

    assert check.status == "WARN"
    messages = [row["message"] for row in check.data["problems"]]
    assert "repos.sidecar.builtin.plans" in messages[0]
    assert "repos.sidecar.custom.research" in messages[1]


def test_repos_reports_empty_removed_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty list still needs migrating to the mapping form."""
    _patch_config(monkeypatch, {"repos": {"sidecar": []}})

    check = check_config_repos()

    assert check.status == "WARN"
    assert check.data["problems"][0]["key"] == "repos.sidecar"


def test_repos_reports_mis_bucketed_roles(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reserved roles under custom and document roles under builtin are flagged."""
    _patch_config(
        monkeypatch,
        {
            "repos": {
                "sidecar": {
                    "builtin": {"research": {"description": "Durable research."}},
                    "custom": {"beads": {}},
                }
            }
        },
    )

    check = check_config_repos()

    by_key = {row["key"]: row["message"] for row in check.data["problems"]}
    assert "repos.sidecar.custom.research" in by_key["repos.sidecar.builtin.research"]
    assert "repos.sidecar.builtin.beads" in by_key["repos.sidecar.custom.beads"]


def test_repos_reports_role_declared_in_both_buckets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A duplicated role is reported with the custom-wins resolution."""
    _patch_config(
        monkeypatch,
        {
            "repos": {
                "sidecar": {
                    "builtin": {"plans": {}},
                    "custom": {"plans": {"description": "Plans."}},
                }
            }
        },
    )

    check = check_config_repos()

    messages = [row["message"] for row in check.data["problems"]]
    assert any("custom wins" in message for message in messages)


def test_repos_reports_leftover_name_field(monkeypatch: pytest.MonkeyPatch) -> None:
    """An entry that still carries ``name`` is called out explicitly."""
    _patch_config(
        monkeypatch,
        {
            "repos": {
                "sidecar": {
                    "custom": {
                        "research": {
                            "name": "research",
                            "description": "Durable research.",
                        }
                    }
                }
            }
        },
    )

    check = check_config_repos()

    keys = {row["key"] for row in check.data["problems"]}
    assert keys == {"repos.sidecar.custom.research.name"}


@pytest.mark.parametrize(
    ("sidecar", "expected_key"),
    [
        pytest.param({"builtin": ["plans"]}, "repos.sidecar.builtin", id="bucket"),
        pytest.param(
            {"custom": {"research": "nope"}},
            "repos.sidecar.custom.research",
            id="entry",
        ),
        pytest.param({"notes": {}}, "repos.sidecar.notes", id="unknown-bucket"),
    ],
)
def test_repos_reports_non_mapping_shapes(
    monkeypatch: pytest.MonkeyPatch, sidecar: dict[str, Any], expected_key: str
) -> None:
    _patch_config(monkeypatch, {"repos": {"sidecar": sidecar}})

    check = check_config_repos()

    assert expected_key in {row["key"] for row in check.data["problems"]}


def test_repos_reports_scalar_sidecar_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ``repos.sidecar`` scalar is neither shape and is reported as such."""
    _patch_config(monkeypatch, {"repos": {"sidecar": "research"}})

    check = check_config_repos()

    assert [row["key"] for row in check.data["problems"]] == ["repos.sidecar"]


def test_repos_reports_undescribed_enabled_lazy_custom_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An enabled lazy custom entry with no description fails memory generation."""
    _patch_config(
        monkeypatch,
        {
            "repos": {
                "sidecar": {
                    "custom": {
                        "research": {},
                        "designs": {"auto_clone": True},
                        "notes": {"disabled": True},
                    }
                }
            }
        },
    )

    check = check_config_repos()

    keys = {row["key"] for row in check.data["problems"]}
    assert keys == {"repos.sidecar.custom.research.description"}


def test_repos_reports_invalid_sidecar_ref_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_config(
        monkeypatch,
        {
            "repos": {
                "sidecar": {
                    "builtin": {
                        "beads": {
                            "ref": {
                                "filters": {"path_globs": ["**/*.md"]},
                            }
                        },
                    },
                    "custom": {
                        "research": {
                            "description": "Durable research.",
                            "ref": {
                                "xprompt": "",
                                "filters": {"path_globs": ["", 42]},
                            },
                        },
                    },
                },
            }
        },
    )

    check = check_config_repos()

    keys = {row["key"] for row in check.data["problems"]}
    assert keys == {
        "repos.sidecar.builtin.beads.ref.filters",
        "repos.sidecar.custom.research.ref.xprompt",
        "repos.sidecar.custom.research.ref.filters.path_globs",
    }


def test_repos_reports_missing_sidecar_ref_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_config(
        monkeypatch,
        {
            "repos": {
                "sidecar": {
                    "custom": {
                        "research": {
                            "description": "Durable research.",
                            "ref": {"use": "builtin@missing-provider"},
                        }
                    }
                }
            }
        },
    )

    check = check_config_repos()

    problems = {row["key"]: row["message"] for row in check.data["problems"]}
    message = problems["repos.sidecar.custom.research.ref.use"]
    assert "missing artifact ref provider 'missing-provider'" in message
    assert "cloned sidecar repo is not an installed plugin" in message


def test_repos_reports_sidecar_ref_use_missing_plugin_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_config(
        monkeypatch,
        {
            "repos": {
                "sidecar": {
                    "custom": {
                        "research": {
                            "description": "Durable research.",
                            "ref": {"use": "research"},
                        }
                    }
                }
            }
        },
    )

    check = check_config_repos()

    problems = {row["key"]: row["message"] for row in check.data["problems"]}
    message = problems["repos.sidecar.custom.research.ref.use"]
    assert "is missing its" in message and "plugin prefix" in message
    assert check.status == "WARN"


@pytest.mark.parametrize("disable_plugins", [False, True])
def test_repos_reports_ok_when_sidecar_is_unset(
    monkeypatch: pytest.MonkeyPatch, disable_plugins: bool
) -> None:
    if disable_plugins:
        monkeypatch.setenv("SASE_DISABLE_PLUGINS", "1")
    else:
        monkeypatch.delenv("SASE_DISABLE_PLUGINS", raising=False)
    _patch_config(monkeypatch, {})

    assert check_config_repos().status == "OK"


def test_repos_reports_disabled_artifact_provider_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.artifact_providers.get_artifact_provider_registry",
        lambda: _empty_artifact_provider_registry(
            disabled_env=("SASE_DISABLE_PLUGINS",)
        ),
    )
    _patch_config(monkeypatch, {})

    check = check_config_repos()

    assert check.status == "WARN"
    assert check.data["problems"] == (
        {
            "key": "artifact_providers.disabled",
            "message": (
                "artifact provider plugin discovery is disabled by SASE_DISABLE_PLUGINS"
            ),
        },
    )


def test_only_config_repos_doctor_check_reads_artifact_provider_registry() -> None:
    doctor_dir = Path(__file__).resolve().parents[2] / "src/sase/doctor"

    offenders = sorted(
        path.name
        for path in doctor_dir.glob("*.py")
        if path.name != "checks_config_repos.py"
        and "get_artifact_provider_registry" in path.read_text(encoding="utf-8")
    )
    assert offenders == []

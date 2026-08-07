"""Tests for doctor sidecar repo config checks."""

from __future__ import annotations

from typing import Any

import pytest

from sase.doctor.checks_config_repos import check_config_repos


def _patch_config(monkeypatch: pytest.MonkeyPatch, config: dict[str, Any]) -> None:
    monkeypatch.setattr("sase.config.core.load_merged_config", lambda: config)


def test_repos_reports_ok_for_canonical_bucketed_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The canonical mapping shape produces no problems."""
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


def test_repos_reports_legacy_list_with_target_buckets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each legacy list entry names the bucket it must move to."""
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


def test_repos_reports_empty_legacy_list(monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_repos_reports_ok_when_sidecar_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_config(monkeypatch, {})

    assert check_config_repos().status == "OK"

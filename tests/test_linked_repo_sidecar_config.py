"""Tests for parsing the bucketed ``repos.sidecar`` configuration form."""

from __future__ import annotations

from pathlib import Path

from sase._linked_repo_config import (
    _merge_resolution_config,
    configured_sidecar_roles,
    merged_sidecar_entries_from_config,
)
from tests._linked_repo_resolution_helpers import _set_github_origin


def test_removed_legacy_sidecar_list_form_yields_no_entries(tmp_path: Path) -> None:
    """The list form is gone; the parser reads nothing from it."""
    primary = tmp_path / "widget"
    primary.mkdir()
    _set_github_origin(primary, "git@github.com:acme/widget.git")
    legacy = {
        "repos": {
            "sidecar": [
                {"name": "plans", "auto_clone": True},
                {"name": "research", "description": "Durable research."},
            ]
        }
    }

    assert (
        merged_sidecar_entries_from_config(legacy, primary_workspace_dir=str(primary))
        == []
    )


def test_bucketed_sidecar_roles_emit_builtin_order_then_configured_custom_order(
    tmp_path: Path,
) -> None:
    """Builtin roles emit in canonical order; custom roles keep config order."""
    primary = tmp_path / "widget"
    primary.mkdir()
    _set_github_origin(primary, "git@github.com:acme/widget.git")
    config = {
        "repos": {
            "sidecar": {
                # Deliberately authored out of canonical order.
                "builtin": {
                    "agents": {},
                    "beads": {"auto_clone": True},
                    "plans": {"auto_clone": True},
                },
                "custom": {"designs": {}, "research": {}},
            }
        }
    }

    assert configured_sidecar_roles(
        config, primary_workspace_dir=str(primary), include_hidden=True
    ) == ("plans", "beads", "agents", "designs", "research")


def test_bucketed_sidecar_layers_merge_per_role_key(tmp_path: Path) -> None:
    """A later layer's ``disabled`` merges into the inherited custom entry."""
    primary = tmp_path / "widget"
    primary.mkdir()
    _set_github_origin(primary, "git@github.com:acme/widget.git")
    merged = _merge_resolution_config(
        {
            "repos": {
                "sidecar": {
                    "custom": {
                        "research": {
                            "repo": "sase-org/shared-research",
                            "visibility": "public",
                        }
                    }
                }
            }
        },
        {"repos": {"sidecar": {"custom": {"research": {"disabled": True}}}}},
    )

    entries = merged_sidecar_entries_from_config(
        merged, primary_workspace_dir=str(primary)
    )

    assert len(entries) == 1
    assert entries[0]["repo"] == "sase-org/shared-research"
    assert entries[0]["visibility"] == "public"
    assert entries[0]["disabled"] is True


def test_bucketed_sidecar_role_in_both_buckets_resolves_to_custom(
    tmp_path: Path,
) -> None:
    """``custom`` wins for a role mis-declared in both buckets."""
    primary = tmp_path / "widget"
    primary.mkdir()
    _set_github_origin(primary, "git@github.com:acme/widget.git")
    config = {
        "repos": {
            "sidecar": {
                "builtin": {"plans": {"repo": "acme/builtin-plans"}},
                "custom": {"plans": {"repo": "acme/custom-plans"}},
            }
        }
    }

    entries = merged_sidecar_entries_from_config(
        config, primary_workspace_dir=str(primary)
    )

    assert len(entries) == 1
    assert entries[0]["repo"] == "acme/custom-plans"


def test_bucketed_sidecar_skips_non_mapping_values(tmp_path: Path) -> None:
    """Runtime parsing stays forgiving; doctor is what reports bad shapes."""
    primary = tmp_path / "widget"
    primary.mkdir()
    _set_github_origin(primary, "git@github.com:acme/widget.git")
    config = {
        "repos": {
            "sidecar": {
                "builtin": "nope",
                "custom": {"research": {}, "designs": "nope"},
            }
        }
    }

    entries = merged_sidecar_entries_from_config(
        config, primary_workspace_dir=str(primary)
    )

    assert [entry["name"] for entry in entries] == ["research"]

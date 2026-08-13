"""Pin the naming rule: a sidecar's ref kind is independent of its role name.

A sidecar role (``plans``, ``beads``, ``agents``, or a custom role) identifies
the sidecar's storage location and directory; its document ref *kind* (what
``@<kind>:<path>`` resolves through) is a separate, independently
configurable string. The builtin roles ship with a kind that differs from
the role name (``plans`` -> ``plan``, ``beads`` -> ``bead``,
``agents`` -> ``agent``); any custom role can do the same with ``ref.kind``.
"""

from __future__ import annotations

from pathlib import Path

from sase.sidecar_ref_config import effective_sidecar_ref_policies


def test_plans_role_defaults_to_plan_kind_with_no_config(tmp_path: Path) -> None:
    policies = effective_sidecar_ref_policies(
        {},
        primary_workspace_dir=tmp_path / "workspace",
        roles=("plans",),
    )

    assert policies["plans"].ref_kind == "plan"


def test_custom_role_configures_a_ref_kind_independent_of_its_name(
    tmp_path: Path,
) -> None:
    config = {
        "repos": {
            "sidecar": {
                "custom": {
                    "notebooks": {
                        "description": "Lab notebooks.",
                        "ref": {"kind": "note", "icon": "◆"},
                    },
                },
            },
        },
    }

    policies = effective_sidecar_ref_policies(
        config,
        primary_workspace_dir=tmp_path / "workspace",
        roles=("notebooks",),
    )

    assert policies["notebooks"].ref_kind == "note"


def test_custom_ref_kind_override_wins_over_a_used_provider(tmp_path: Path) -> None:
    config = {
        "repos": {
            "sidecar": {
                "custom": {
                    "notebooks": {
                        "description": "Lab notebooks.",
                        "ref": {"use": "plan", "kind": "note", "icon": "◆"},
                    },
                },
            },
        },
    }

    policies = effective_sidecar_ref_policies(
        config,
        primary_workspace_dir=tmp_path / "workspace",
        roles=("notebooks",),
    )

    assert policies["notebooks"].ref_kind == "note"


def test_unknown_role_with_no_ref_config_falls_back_to_its_own_role_name(
    tmp_path: Path,
) -> None:
    policies = effective_sidecar_ref_policies(
        {},
        primary_workspace_dir=tmp_path / "workspace",
        roles=("notebooks",),
    )

    assert policies["notebooks"].ref_kind == "notebooks"

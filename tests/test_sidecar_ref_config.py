from __future__ import annotations

from pathlib import Path

from sase.artifact_providers import builtin_plan_ref_provider_spec
from sase.sidecar_ref_config import (
    DEFAULT_DOCUMENT_REF_PATH_GLOBS,
    effective_sidecar_ref_policies,
    _sidecar_ref_policy_report,
)


def test_effective_sidecar_ref_policies_apply_document_defaults_and_overrides(
    tmp_path: Path,
) -> None:
    config = {
        "repos": {
            "sidecar": {
                "builtin": {
                    "beads": {"ref": {"filters": {"path_globs": ["ignored/**"]}}},
                },
                "custom": {
                    "research": {
                        "description": "Research docs.",
                        "ref": {
                            "inventory": {"globs": ["reports/**/*.md"]},
                        },
                    },
                    "notes": {
                        "description": "Disabled notes.",
                        "disabled": True,
                    },
                },
            },
        },
    }

    policies = effective_sidecar_ref_policies(
        config,
        primary_workspace_dir=tmp_path / "workspace",
        roles=("plans", "research", "notes", "beads", "agents"),
    )

    assert "notes" not in policies
    assert policies["plans"].is_document is True
    assert policies["plans"].provider_id == "plan"
    assert policies["plans"].ref_kind == "plan"
    assert policies["plans"].path_globs == DEFAULT_DOCUMENT_REF_PATH_GLOBS
    assert policies["research"].provider_id == "research"
    assert policies["research"].ref_kind == "research"
    assert policies["research"].path_globs == ("reports/**/*.md",)
    assert policies["beads"].is_document is False
    assert policies["beads"].ref_kind == "bead"
    assert policies["beads"].path_globs is None
    assert policies["agents"].ref_kind == "agent"


def test_sidecar_ref_use_and_equivalent_inline_normalize_identically(
    tmp_path: Path,
) -> None:
    provider_ref = builtin_plan_ref_provider_spec()["ref"]
    use_report = _sidecar_ref_policy_report(
        {
            "repos": {
                "sidecar": {
                    "builtin": {
                        "plans": {
                            "ref": {
                                "use": "plan",
                                "inventory": {"globs": ["2026/**/*.md"]},
                            }
                        }
                    }
                }
            }
        },
        primary_workspace_dir=tmp_path / "workspace",
        roles=("plans",),
    )
    inline_report = _sidecar_ref_policy_report(
        {
            "repos": {
                "sidecar": {
                    "builtin": {
                        "plans": {
                            "ref": {
                                **provider_ref,
                                "inventory": {"globs": ["2026/**/*.md"]},
                            }
                        }
                    }
                }
            }
        },
        primary_workspace_dir=tmp_path / "workspace",
        roles=("plans",),
    )

    use_policy = use_report.policies["plans"]
    inline_policy = inline_report.policies["plans"]
    assert use_policy.spec == inline_policy.spec
    assert use_policy.digest == inline_policy.digest
    assert use_policy.path_globs == ("2026/**/*.md",)


def test_sidecar_ref_deprecated_path_globs_alias_is_reported(
    tmp_path: Path,
) -> None:
    report = _sidecar_ref_policy_report(
        {
            "repos": {
                "sidecar": {
                    "custom": {
                        "research": {
                            "description": "Research docs.",
                            "ref": {"filters": {"path_globs": ["reports/**/*.md"]}},
                        }
                    }
                }
            }
        },
        primary_workspace_dir=tmp_path / "workspace",
        roles=("research",),
    )

    assert report.policies["research"].path_globs == ("reports/**/*.md",)
    assert [diagnostic.code for diagnostic in report.diagnostics] == [
        "deprecated_ref_path_globs"
    ]


def test_sidecar_ref_invalid_provider_use_fails_soft(tmp_path: Path) -> None:
    report = _sidecar_ref_policy_report(
        {
            "repos": {
                "sidecar": {
                    "custom": {
                        "research": {
                            "description": "Research docs.",
                            "ref": {"use": "missing-provider"},
                        }
                    }
                }
            }
        },
        primary_workspace_dir=tmp_path / "workspace",
        roles=("research",),
    )

    assert "research" not in report.policies
    assert report.diagnostics[0].code == "missing_ref_provider"

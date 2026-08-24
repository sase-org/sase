from __future__ import annotations

import logging
from pathlib import Path

import pytest

from sase.artifact_providers import builtin_plan_ref_provider_spec
from sase.sidecar_ref_config import (
    DEFAULT_DOCUMENT_REF_EXPANSION_FORMAT,
    DEFAULT_DOCUMENT_REF_PATH_GLOBS,
    DEFAULT_DOCUMENT_TAB_ICON,
    effective_sidecar_ref_policies,
    sidecar_role_for_ref_kind,
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
                            "icon": "∴",
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
        roles=("plans", "research", "docs", "notes", "beads", "agents"),
    )

    assert "notes" not in policies
    assert policies["plans"].is_document is True
    assert policies["plans"].provider_id == "plan"
    assert policies["plans"].ref_kind == "plan"
    assert policies["plans"].path_globs == DEFAULT_DOCUMENT_REF_PATH_GLOBS
    assert policies["research"].provider_id == "research"
    assert policies["research"].ref_kind == "research"
    assert policies["research"].path_globs == ("reports/**/*.md",)
    assert policies["research"].spec is not None
    assert policies["research"].spec["ref"]["icon"] == "∴"
    assert policies["docs"].is_document is True
    assert policies["docs"].spec is not None
    assert policies["docs"].spec["ref"]["icon"] == DEFAULT_DOCUMENT_TAB_ICON
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
                                "use": "builtin@plan",
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


def test_sidecar_ref_pane_normalizes_without_changing_provider_digest(
    tmp_path: Path,
) -> None:
    pane = {
        "label": "Plans",
        "row": {"badges": ["status"], "secondary": ["updated_time"]},
        "empty_state": {"body": "No matching plans."},
    }
    base_report = _sidecar_ref_policy_report(
        {
            "repos": {
                "sidecar": {
                    "builtin": {"plans": {"ref": {"use": "builtin@plan"}}},
                }
            }
        },
        primary_workspace_dir=tmp_path / "workspace",
        roles=("plans",),
    )
    use_report = _sidecar_ref_policy_report(
        {
            "repos": {
                "sidecar": {
                    "builtin": {
                        "plans": {"ref": {"use": "builtin@plan", "pane": pane}}
                    },
                }
            }
        },
        primary_workspace_dir=tmp_path / "workspace",
        roles=("plans",),
    )
    inline_ref = {**builtin_plan_ref_provider_spec()["ref"], "pane": pane}
    inline_report = _sidecar_ref_policy_report(
        {
            "repos": {
                "sidecar": {
                    "builtin": {"plans": {"ref": inline_ref}},
                }
            }
        },
        primary_workspace_dir=tmp_path / "workspace",
        roles=("plans",),
    )

    base_policy = base_report.policies["plans"]
    use_policy = use_report.policies["plans"]
    inline_policy = inline_report.policies["plans"]
    assert use_policy.spec == inline_policy.spec
    assert use_policy.digest == inline_policy.digest == base_policy.digest
    assert use_policy.spec is not None
    assert use_policy.spec["ref"]["pane"] == pane


def test_sidecar_ref_icon_override_beats_provider_icon(tmp_path: Path) -> None:
    report = _sidecar_ref_policy_report(
        {
            "repos": {
                "sidecar": {
                    "builtin": {
                        "plans": {
                            "ref": {
                                "use": "builtin@plan",
                                "icon": "∴",
                            }
                        }
                    }
                }
            }
        },
        primary_workspace_dir=tmp_path / "workspace",
        roles=("plans",),
    )

    policy = report.policies["plans"]
    assert report.diagnostics == ()
    assert policy.spec is not None
    assert policy.spec["ref"]["icon"] == "∴"


def test_inline_relations_and_grouping_are_preserved(tmp_path: Path) -> None:
    report = _sidecar_ref_policy_report(
        {
            "repos": {
                "sidecar": {
                    "custom": {
                        "research": {
                            "description": "Research docs.",
                            "ref": {
                                "kind": "research",
                                "properties": {
                                    "status": {
                                        "type": "string",
                                        "source": "markdown_frontmatter",
                                    }
                                },
                                "relations": [
                                    {
                                        "name": "parent",
                                        "kind": "hierarchy",
                                        "label": "Parent",
                                        "source": "status",
                                        "target_pane": None,
                                        "inverse": "children",
                                        "directed": True,
                                        "transitive": True,
                                    }
                                ],
                                "grouping": {
                                    "default_mode": "by_status",
                                    "modes": [
                                        {
                                            "id": "by_status",
                                            "label": "Status",
                                            "keys": ["status"],
                                        }
                                    ],
                                },
                            },
                        }
                    }
                }
            }
        },
        primary_workspace_dir=tmp_path / "workspace",
        roles=("research",),
    )

    assert report.diagnostics == ()
    policy = report.policies["research"]
    assert policy.spec is not None
    assert policy.spec["ref"]["relations"][0]["name"] == "parent"
    assert policy.spec["ref"]["grouping"]["default_mode"] == "by_status"


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
                            "ref": {"use": "builtin@missing-provider"},
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


def test_sidecar_ref_use_without_plugin_prefix_fails_soft(tmp_path: Path) -> None:
    report = _sidecar_ref_policy_report(
        {
            "repos": {
                "sidecar": {
                    "builtin": {"plans": {"ref": {"use": "plan"}}},
                }
            }
        },
        primary_workspace_dir=tmp_path / "workspace",
        roles=("plans",),
    )

    assert "plans" not in report.policies
    assert report.diagnostics[0].code == "missing_use_prefix"
    assert "builtin@plan" in report.diagnostics[0].message


def test_sidecar_ref_warning_names_source_key_and_message(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    source_path = tmp_path / "sase.yml"

    with caplog.at_level(logging.WARNING, logger="sase.sidecar_ref_config"):
        effective_sidecar_ref_policies(
            {
                "repos": {
                    "sidecar": {
                        "builtin": {"plans": {"ref": {"use": "plan"}}},
                    }
                }
            },
            primary_workspace_dir=tmp_path / "workspace",
            roles=("plans",),
            source_path=source_path,
        )

    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert ".plans.ref.use" in message
    assert str(source_path) in message
    assert "'plan' is missing its plugin prefix; use 'builtin@plan'" in message


def test_sidecar_ref_use_with_mismatched_plugin_prefix_fails_soft(
    tmp_path: Path,
) -> None:
    report = _sidecar_ref_policy_report(
        {
            "repos": {
                "sidecar": {
                    "builtin": {
                        "plans": {"ref": {"use": "sase-research-artifacts@plan"}}
                    },
                }
            }
        },
        primary_workspace_dir=tmp_path / "workspace",
        roles=("plans",),
    )

    assert "plans" not in report.policies
    assert report.diagnostics[0].code == "mismatched_use_prefix"
    assert "builtin@plan" in report.diagnostics[0].message


def test_unconfigured_document_sidecar_defaults_to_sidecar_pointer_expansion(
    tmp_path: Path,
) -> None:
    policies = effective_sidecar_ref_policies(
        {},
        primary_workspace_dir=tmp_path / "workspace",
        roles=("docs",),
    )

    policy = policies["docs"]
    assert (
        policy.expansion_format
        == DEFAULT_DOCUMENT_REF_EXPANSION_FORMAT
        == "the {repo_relative_path} file in the {sidecar_role} sidecar repo"
    )
    assert policy.is_pointer_expansion is True


def test_builtin_plan_spec_expansion_is_sidecar_pointer(tmp_path: Path) -> None:
    policies = effective_sidecar_ref_policies(
        {},
        primary_workspace_dir=tmp_path / "workspace",
        roles=("plans",),
    )

    policy = policies["plans"]
    assert policy.expansion_format == DEFAULT_DOCUMENT_REF_EXPANSION_FORMAT
    assert (
        policy.expansion_format
        == (builtin_plan_ref_provider_spec()["ref"]["expansion_format"])
    )
    assert policy.is_pointer_expansion is True
    assert policy.ref_kind == "plan"


def test_plan_research_and_unconfigured_docs_select_sidecar_pointer_role(
    tmp_path: Path,
) -> None:
    policies = effective_sidecar_ref_policies(
        {},
        primary_workspace_dir=tmp_path / "workspace",
        roles=("plans", "research", "docs"),
    )

    assert policies["plans"].role == "plans"
    assert policies["plans"].ref_kind == "plan"
    assert policies["research"].role == "research"
    assert policies["docs"].role == "docs"
    assert policies["docs"].ref_kind == "docs"
    for role in ("plans", "research", "docs"):
        assert policies[role].is_pointer_expansion is True
        assert "{sidecar_role}" in policies[role].expansion_format
        assert "{repo_relative_path}" in policies[role].expansion_format


def test_pointer_expansion_format_is_classified_correctly(tmp_path: Path) -> None:
    report = _sidecar_ref_policy_report(
        {
            "repos": {
                "sidecar": {
                    "custom": {
                        "research": {
                            "description": "Research docs.",
                            "ref": {
                                "kind": "research",
                                "expansion_format": (
                                    "the {repo_relative_path} file in the "
                                    "{sidecar_role} sidecar repo"
                                ),
                            },
                        }
                    }
                }
            }
        },
        primary_workspace_dir=tmp_path / "workspace",
        roles=("research",),
    )

    assert report.diagnostics == ()
    policy = report.policies["research"]
    assert policy.is_pointer_expansion is True


def test_expansion_format_with_unsupported_placeholder_is_rejected(
    tmp_path: Path,
) -> None:
    report = _sidecar_ref_policy_report(
        {
            "repos": {
                "sidecar": {
                    "custom": {
                        "research": {
                            "description": "Research docs.",
                            "ref": {
                                "kind": "research",
                                "expansion_format": "stitch {captured_revision}",
                            },
                        }
                    }
                }
            }
        },
        primary_workspace_dir=tmp_path / "workspace",
        roles=("research",),
    )

    assert "research" not in report.policies
    assert report.diagnostics[0].code == "invalid_sidecar_ref"
    assert "captured_revision" in report.diagnostics[0].message


def test_kind_only_expansion_format_normalizes_cleanly(tmp_path: Path) -> None:
    report = _sidecar_ref_policy_report(
        {
            "repos": {
                "sidecar": {
                    "custom": {
                        "research": {
                            "description": "Research docs.",
                            "ref": {
                                "kind": "research",
                                "expansion_format": "{kind}",
                            },
                        }
                    }
                }
            }
        },
        primary_workspace_dir=tmp_path / "workspace",
        roles=("research",),
    )

    assert report.diagnostics == ()
    policy = report.policies["research"]
    assert policy.expansion_format == "{kind}"
    assert policy.is_pointer_expansion is True


def test_sidecar_role_for_ref_kind_inverts_builtin_mapping() -> None:
    assert sidecar_role_for_ref_kind("plan") == "plans"
    assert sidecar_role_for_ref_kind("research") == "research"
    assert sidecar_role_for_ref_kind("docs") == "docs"

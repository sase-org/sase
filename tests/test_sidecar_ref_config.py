from __future__ import annotations

from pathlib import Path

from sase.sidecar_ref_config import (
    DEFAULT_DOCUMENT_REF_PATH_GLOBS,
    canonical_ref_input,
    effective_sidecar_ref_policies,
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
                            "xprompt": "Research {{ file_path }}",
                            "filters": {"path_globs": ["reports/**/*.md"]},
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
    assert policies["plans"].path_globs == DEFAULT_DOCUMENT_REF_PATH_GLOBS
    assert policies["research"].xprompt == "Research {{ file_path }}"
    assert policies["research"].path_globs == ("reports/**/*.md",)
    assert policies["beads"].is_document is False
    assert policies["beads"].ref_kind == "bead"
    assert policies["beads"].path_globs is None
    assert policies["agents"].ref_kind == "agent"
    assert canonical_ref_input("research") == "file_path"

"""SASE's builtin declarative artifact providers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._hookspec import hookimpl

ARTIFACT_REF_PROVIDER_SPEC_SCHEMA_VERSION = 1


def builtin_plan_ref_provider_spec() -> dict[str, Any]:
    """Return the builtin plans sidecar document-ref provider spec."""

    return {
        "schema_version": ARTIFACT_REF_PROVIDER_SPEC_SCHEMA_VERSION,
        "provider": "plan",
        "ref": {
            "kind": "plan",
            "icon": "✎",
            "expansion_format": (
                "the {repo_relative_path} file in the {sidecar_role} sidecar repo"
            ),
            "properties": {
                "tier": {
                    "type": "string",
                    "source": "markdown_frontmatter",
                },
                "title": {
                    "type": "string",
                    "source": "markdown_frontmatter",
                },
                "status": {
                    "type": "string",
                    "source": "markdown_frontmatter",
                },
                "bead": {
                    "type": "string",
                    "source": "markdown_frontmatter",
                },
            },
            "detail": {"fields": ["tier", "title", "status"]},
            "identity": {},
            "inventory": {"globs": ["**/*.md"]},
            "publication": {
                "link": "vcs_permalink",
                "referenced_by": "markdown_table",
            },
        },
    }


class BuiltinArtifactProviders:
    """Builtin providers registered through the artifact-provider host path."""

    @hookimpl
    def artifact_ref_provider_specs(self) -> tuple[Mapping[str, Any], ...]:
        return (builtin_plan_ref_provider_spec(),)


__all__ = [
    "ARTIFACT_REF_PROVIDER_SPEC_SCHEMA_VERSION",
    "BuiltinArtifactProviders",
    "builtin_plan_ref_provider_spec",
]

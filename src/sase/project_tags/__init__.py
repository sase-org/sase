"""Project tags (``+<project>``): catalog, expansion, and validation (D2–D4)."""

from __future__ import annotations

from sase.project_tags.catalog import (
    ProjectTagCatalog as ProjectTagCatalog,
    ProjectTagTarget as ProjectTagTarget,
    build_targets as build_targets,
    ensure_project_tag_catalog as ensure_project_tag_catalog,
    is_project_tag_name as is_project_tag_name,
    load_project_tag_catalog as load_project_tag_catalog,
    peek_project_tag_catalog as peek_project_tag_catalog,
    peek_project_tag_catalog_signature as peek_project_tag_catalog_signature,
)
from sase.project_tags.tags import (
    ProjectTagError as ProjectTagError,
    apply_project_tag_selection as apply_project_tag_selection,
    effective_find_vcs_workflow_tag as effective_find_vcs_workflow_tag,
    effective_vcs_workflow_tag as effective_vcs_workflow_tag,
    expand_project_tags as expand_project_tags,
    expand_project_tags_report as expand_project_tags_report,
    expand_project_tags_with_catalog as expand_project_tags_with_catalog,
    find_project_tag_trigger as find_project_tag_trigger,
    find_project_tags as find_project_tags,
    known_project_tag_for as known_project_tag_for,
    project_tag_for as project_tag_for,
    validate_project_tags_for_launch as validate_project_tags_for_launch,
    validate_project_tags_with_catalog as validate_project_tags_with_catalog,
)


__all__ = [
    "ProjectTagCatalog",
    "ProjectTagError",
    "ProjectTagTarget",
    "apply_project_tag_selection",
    "build_targets",
    "effective_find_vcs_workflow_tag",
    "effective_vcs_workflow_tag",
    "ensure_project_tag_catalog",
    "expand_project_tags",
    "expand_project_tags_report",
    "expand_project_tags_with_catalog",
    "find_project_tag_trigger",
    "find_project_tags",
    "is_project_tag_name",
    "known_project_tag_for",
    "load_project_tag_catalog",
    "peek_project_tag_catalog",
    "peek_project_tag_catalog_signature",
    "project_tag_for",
    "validate_project_tags_for_launch",
    "validate_project_tags_with_catalog",
]

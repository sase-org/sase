"""Tests for the new simple workflows (crs)."""

import os
import tempfile

import pytest

from sase.workflows.crs import (
    CrsWorkflow,
    _build_crs_prompt,
    _build_crs_prompt_invocation,
)


class TestCrsWorkflow:
    """Tests for the CRS (change requests) workflow."""

    def test_workflow_description(self) -> None:
        """Test that the workflow has a description."""
        workflow = CrsWorkflow()
        assert "Critique" in workflow.description
        assert "change request" in workflow.description

    def test_build_crs_prompt_basic(self) -> None:
        """Test building a CRS prompt.

        The crs xprompt may be provided by a plugin. When the plugin is not
        installed, process_xprompt_references returns the raw reference string.
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"comments": []}\n')
            comments_file = f.name

        try:
            prompt = _build_crs_prompt(comments_file)
            # The prompt should contain the comments file path reference
            assert comments_file in prompt
            # When a plugin provides crs.md, expanded prompt contains
            # @file and Critique text; otherwise the raw #crs(...) reference
            assert "#crs" in prompt or "Critique" in prompt
        finally:
            os.unlink(comments_file)

    def test_build_crs_prompt_requires_provider_with_patch(self) -> None:
        with pytest.raises(
            ValueError,
            match="vcs_type is required when cl_name is provided",
        ):
            _build_crs_prompt_invocation("comments.json", cl_name="feature")

    def test_build_crs_prompt_uses_supplied_registered_provider(self) -> None:
        invocation = _build_crs_prompt_invocation(
            "comments.json",
            cl_name="feature",
            vcs_type="spy",
        )

        assert 'cl_name="feature"' in invocation
        assert 'vcs_type="spy"' in invocation

    def test_build_crs_prompt_ref_free_invocation_has_no_provider(self) -> None:
        invocation = _build_crs_prompt_invocation("comments.json")

        assert "cl_name=" not in invocation
        assert "vcs_type=" not in invocation


class TestCrsWorkflowAdvanced:
    """Additional tests for the CRS workflow."""

    def test_workflow_init_with_project_name(self) -> None:
        """Test that workflow can be initialized with project name."""
        workflow = CrsWorkflow(project_name="my_project")
        assert workflow.project_name == "my_project"
        assert workflow.name == "crs"

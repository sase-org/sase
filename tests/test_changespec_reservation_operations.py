"""Tests for ChangeSpec reservation lifecycle operations."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from sase.ace.changespec.parser import parse_project_file
from sase.workflows.commit.changespec_operations import (
    add_changespec_to_project_file,
    compute_suffixed_cl_name,
    remove_reservation,
)


def test_reservation_replaced_by_add_changespec(tmp_path: Path) -> None:
    """Reservation created by compute_suffixed_cl_name is replaced by add_changespec."""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", suffix=".sase", delete=False
    ) as f:
        f.write("")
        project_file = f.name

    try:
        with patch(
            "sase.workflows.commit.changespec_operations.get_project_file_path",
            return_value=project_file,
        ):
            # Step 1: create reservation
            reserved = compute_suffixed_cl_name(
                "test_project", "test_project_res_feature"
            )
            assert reserved == "test_project_res_feature_1"

            # Verify reservation exists in file
            with open(project_file, encoding="utf-8") as f:
                content = f.read()
            assert "NAME: test_project_res_feature_1" in content
            assert "STATUS: Reserved" in content

            # Step 2: add full ChangeSpec with reserved_name
            result = add_changespec_to_project_file(
                project="test_project",
                cl_name="test_project_res_feature",
                description="Full description",
                parent=None,
                pr_url="http://cl/44444",
                reserved_name="test_project_res_feature_1",
            )

        assert result == "test_project_res_feature_1"

        # Verify reservation stub is gone and full ChangeSpec exists
        changespecs = parse_project_file(project_file)
        cs = next(c for c in changespecs if c.name == "test_project_res_feature_1")
        assert cs.status == "Draft"
        assert cs.pr_url == "http://cl/44444"

        # No Reserved entries should remain
        with open(project_file, encoding="utf-8") as f:
            content = f.read()
        assert "STATUS: Reserved" not in content
    finally:
        os.unlink(project_file)


def test_remove_reservation_cleans_up_stub(tmp_path: Path) -> None:
    """remove_reservation correctly removes a Reserved stub from the project file."""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", suffix=".sase", delete=False
    ) as f:
        f.write("")
        project_file = f.name

    try:
        with patch(
            "sase.workflows.commit.changespec_operations.get_project_file_path",
            return_value=project_file,
        ):
            # Create reservation
            reserved = compute_suffixed_cl_name(
                "test_project", "test_project_cleanup_feat"
            )
            assert reserved == "test_project_cleanup_feat_1"

            # Verify it exists
            with open(project_file, encoding="utf-8") as f:
                content = f.read()
            assert "NAME: test_project_cleanup_feat_1" in content

            # Remove it (simulating ChangeSpec creation failure)
            remove_reservation("test_project", "test_project_cleanup_feat_1")

        # Verify stub is gone
        with open(project_file, encoding="utf-8") as f:
            content = f.read()
        assert "test_project_cleanup_feat_1" not in content
        assert "Reserved" not in content
    finally:
        os.unlink(project_file)


def test_suffix_slot_reused_after_reservation_cleanup(tmp_path: Path) -> None:
    """After removing a reservation, compute_suffixed_cl_name reuses the same suffix."""
    with tempfile.NamedTemporaryFile(
        dir=tmp_path, mode="w", suffix=".sase", delete=False
    ) as f:
        f.write("")
        project_file = f.name

    try:
        with patch(
            "sase.workflows.commit.changespec_operations.get_project_file_path",
            return_value=project_file,
        ):
            # Reserve _1
            reserved = compute_suffixed_cl_name(
                "test_project", "test_project_reuse_feat"
            )
            assert reserved == "test_project_reuse_feat_1"

            # Clean it up
            remove_reservation("test_project", "test_project_reuse_feat_1")

            # Reserve again — should get _1 again since the slot is free
            reserved2 = compute_suffixed_cl_name(
                "test_project", "test_project_reuse_feat"
            )
            assert reserved2 == "test_project_reuse_feat_1"
    finally:
        os.unlink(project_file)

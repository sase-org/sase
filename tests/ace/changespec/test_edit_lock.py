"""Tests for edit lock functions."""

import os
import tempfile

from sase.ace.changespec.locking import (
    acquire_edit_lock,
    is_edit_locked,
    release_edit_lock,
)


def test_acquire_creates_lock_file() -> None:
    """Verify .edit_lock is created with current PID."""
    with tempfile.NamedTemporaryFile(suffix=".gp", delete=False) as f:
        project_file = f.name
    try:
        acquire_edit_lock(project_file)
        lock_file = f"{project_file}.edit_lock"
        assert os.path.exists(lock_file)
        with open(lock_file) as lf:
            assert lf.read().strip() == str(os.getpid())
    finally:
        os.unlink(project_file)
        try:
            os.unlink(f"{project_file}.edit_lock")
        except FileNotFoundError:
            pass


def test_release_removes_lock_file() -> None:
    """Verify release removes the .edit_lock file."""
    with tempfile.NamedTemporaryFile(suffix=".gp", delete=False) as f:
        project_file = f.name
    try:
        acquire_edit_lock(project_file)
        assert os.path.exists(f"{project_file}.edit_lock")
        release_edit_lock(project_file)
        assert not os.path.exists(f"{project_file}.edit_lock")
    finally:
        os.unlink(project_file)
        try:
            os.unlink(f"{project_file}.edit_lock")
        except FileNotFoundError:
            pass


def test_is_edit_locked_returns_true_for_active_lock() -> None:
    """Active lock (current PID) returns True."""
    with tempfile.NamedTemporaryFile(suffix=".gp", delete=False) as f:
        project_file = f.name
    try:
        acquire_edit_lock(project_file)
        assert is_edit_locked(project_file) is True
    finally:
        os.unlink(project_file)
        try:
            os.unlink(f"{project_file}.edit_lock")
        except FileNotFoundError:
            pass


def test_is_edit_locked_cleans_stale_lock() -> None:
    """Dead PID lock is removed and returns False."""
    with tempfile.NamedTemporaryFile(suffix=".gp", delete=False) as f:
        project_file = f.name
    lock_file = f"{project_file}.edit_lock"
    try:
        # Write a PID that doesn't exist (use a very high PID)
        with open(lock_file, "w") as lf:
            lf.write("999999999")
        assert is_edit_locked(project_file) is False
        assert not os.path.exists(lock_file)
    finally:
        os.unlink(project_file)
        try:
            os.unlink(lock_file)
        except FileNotFoundError:
            pass


def test_is_edit_locked_returns_false_when_no_lock() -> None:
    """No lock file returns False."""
    with tempfile.NamedTemporaryFile(suffix=".gp", delete=False) as f:
        project_file = f.name
    try:
        assert is_edit_locked(project_file) is False
    finally:
        os.unlink(project_file)


def test_release_nonexistent_lock_is_noop() -> None:
    """Releasing a lock that doesn't exist doesn't raise."""
    release_edit_lock("/tmp/nonexistent_project_file.gp")

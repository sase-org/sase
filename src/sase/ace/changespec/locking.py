"""Legacy locking names backed by :mod:`sase.ace.patch.locking`."""

from sase.ace.patch.locking import (
    LockTimeoutError,
    acquire_edit_lock,
    changespec_lock,
    is_edit_locked,
    patch_lock,
    release_edit_lock,
    wait_for_edit_lock_release,
    write_changespec_atomic,
    write_patch_atomic,
)

__all__ = [
    "LockTimeoutError",
    "acquire_edit_lock",
    "changespec_lock",
    "is_edit_locked",
    "patch_lock",
    "release_edit_lock",
    "wait_for_edit_lock_release",
    "write_changespec_atomic",
    "write_patch_atomic",
]

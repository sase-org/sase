"""Git blob OID helpers shared by launch and read evidence capture.

Blob OIDs use git's blob hashing (sha1 over ``b"blob <len>\\0" + bytes``),
matching ``git hash-object`` for the repo's object format. All helpers are
in-process with no subprocess.
"""

from __future__ import annotations

import hashlib


def git_blob_oid(data: bytes) -> str:
    """Return the git blob OID for *data*."""
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()  # noqa: S324


__all__ = ["git_blob_oid"]

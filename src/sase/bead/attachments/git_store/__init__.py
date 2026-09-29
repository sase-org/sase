"""Git-backed blob store over a bare partial clone.

This package was split out from a single ``git_store.py`` module. The
submodules group related concerns; the public API re-exported here is
unchanged.
"""

from __future__ import annotations

from sase.bead.attachments.git_store.store import GitAttachmentStore

__all__ = [
    "GitAttachmentStore",
]

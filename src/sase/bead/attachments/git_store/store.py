"""Git-backed blob store over a bare partial clone.

:class:`GitAttachmentStore` implements the :class:`BlobStore` protocol over a
bare ``--filter=blob:none`` clone (the ``attachments-private`` sidecar owned
by phase ``sidecar_role``). The class is composed here from the tip,
read, and write mixins (:mod:`tips`, :mod:`reads`, :mod:`writes`); only
the constructor and identity helpers live in this module so every file
stays under the line limit. Git-tree plumbing lives in :mod:`plumbing`
and shared paths and bounds in the private :mod:`_common` module.

This module keeps the original public import path: only public names are
re-exported from this facade.
"""

from __future__ import annotations

from pathlib import Path

from sase.bead.attachments.blob_store import BlobStoreError
from sase.bead.attachments.git_store.writes import GitStoreWrites

__all__ = [
    "GitAttachmentStore",
]


class GitAttachmentStore(GitStoreWrites):
    """A :class:`BlobStore` over a bare partial clone, written with plumbing."""

    def __init__(
        self,
        repo: Path | str,
        label: str,
        *,
        fetch_timeout: float | None = None,
        name: str = "git",
        layout: str = "private",
    ) -> None:
        """Point at the bare repo at *repo*; *label* feeds :meth:`describe`."""

        path = Path(repo).expanduser()
        if (
            not path.is_dir()
            or not (path / "HEAD").is_file()
            or not (path / "objects").is_dir()
        ):
            raise BlobStoreError(f"not a bare git repository: {path}")
        self._repo = path
        self._label = label
        self._store_name = name
        self._layout = layout
        if fetch_timeout is not None:
            self._fetch_timeout = fetch_timeout
        else:  # Same bound as every other SDD network git command.
            from sase.sdd._git import network_git_timeout

            self._fetch_timeout = network_git_timeout()

    @property
    def name(self) -> str:
        """Short stable identifier used in logs, badges, and the outbox."""

        return self._store_name

    def describe(self) -> str:
        """Human-readable destination/visibility label for the write echo."""

        return self._label

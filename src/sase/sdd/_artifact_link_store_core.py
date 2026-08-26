"""Shared sidecar/bead-authority predicates for :class:`ArtifactLinkStore`."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
import subprocess
from typing import Any

from sase.sdd._artifact_link_store_support import (
    BEAD_KIND,
    kind_of_ref,
    sidecar_index_path,
    writes_sidecar_json,
)


class ArtifactLinkStoreCoreMixin:
    """Predicates over sidecar ownership and bead authority."""

    sidecar_roots: Mapping[str, Path]
    beads_dir: Path | None

    def sidecar_root_for(self, artifact_ref: str) -> Path | None:
        """Return the sidecar root that should store *artifact_ref*, if any."""

        if not writes_sidecar_json(artifact_ref):
            return None
        return self.sidecar_roots.get(kind_of_ref(artifact_ref))

    def _is_aggregate_only(self, row: Mapping[str, Any]) -> bool:
        """Return whether neither endpoint owns sidecar ``links/`` JSON."""

        source = str(row.get("source_ref") or "")
        target = str(row.get("target_ref") or "")
        return (
            self.sidecar_root_for(source) is None
            and self.sidecar_root_for(target) is None
        )

    def _bead_endpoint_is_authoritative(
        self, row: Mapping[str, Any], *, freshness: _FreshnessEvidence
    ) -> bool:
        """Return whether this workspace has bead truth for either endpoint.

        A bead re-derives both its outbound and inbound link events from
        its own event stream, so a bead in either endpoint position is
        proof this workspace can confirm a prior row's deletion once the
        bead store is at least as fresh as the row.
        """

        if self.beads_dir is None:
            return False
        source = str(row.get("source_ref") or "")
        target = str(row.get("target_ref") or "")
        if kind_of_ref(source) != BEAD_KIND and kind_of_ref(target) != BEAD_KIND:
            return False
        return _source_is_fresh_for_row(
            freshness.observed_tree_at(self.beads_dir),
            row,
        )

    def _sidecar_truth_was_consulted(
        self, row: Mapping[str, Any], *, freshness: _FreshnessEvidence
    ) -> bool:
        """Return whether a fresh companion index can prove row deletion."""

        for ref in (str(row.get("source_ref") or ""), str(row.get("target_ref") or "")):
            root = self.sidecar_root_for(ref)
            if root is None:
                continue
            path = sidecar_index_path(root, ref)
            if path.is_file() and _source_is_fresh_for_row(
                freshness.observed_file_at(root, path),
                row,
            ):
                return True
        return False

    def _authoritative_source_was_consulted_for_pass(
        self,
        stores: Iterable[ArtifactLinkStoreCoreMixin] | None = None,
    ) -> Callable[[Mapping[str, Any]], bool]:
        """Return a row predicate with pass-local freshness caches."""

        freshness = _FreshnessEvidence()
        observed_stores = tuple(stores or (self,))

        def predicate(row: Mapping[str, Any]) -> bool:
            return any(
                store._authoritative_source_was_consulted(  # noqa: SLF001
                    row,
                    freshness=freshness,
                )
                for store in observed_stores
            )

        return predicate

    def _authoritative_source_was_consulted(
        self,
        row: Mapping[str, Any],
        *,
        freshness: _FreshnessEvidence | None = None,
    ) -> bool:
        """Return whether a missing prior row is proven deleted here."""

        active_freshness = freshness or _FreshnessEvidence()
        return self._bead_endpoint_is_authoritative(
            row,
            freshness=active_freshness,
        ) or self._sidecar_truth_was_consulted(
            row,
            freshness=active_freshness,
        )


class _FreshnessEvidence:
    """Per-projection cache of committed or filesystem observation times."""

    def __init__(self) -> None:
        self._git_roots: dict[Path, Path | None] = {}
        self._file_observed_at: dict[tuple[Path, Path], float | None] = {}
        self._tree_observed_at: dict[Path, float | None] = {}

    def observed_file_at(self, repo_hint: Path, path: Path) -> float | None:
        root = repo_hint.expanduser().resolve(strict=False)
        resolved = path.expanduser().resolve(strict=False)
        key = (root, resolved)
        if key not in self._file_observed_at:
            self._file_observed_at[key] = self._committed_path_at(
                root,
                resolved,
            )
            if self._file_observed_at[key] is None:
                self._file_observed_at[key] = _file_mtime(resolved)
        return self._file_observed_at[key]

    def observed_tree_at(self, path: Path) -> float | None:
        resolved = path.expanduser().resolve(strict=False)
        if resolved not in self._tree_observed_at:
            self._tree_observed_at[resolved] = self._committed_path_at(
                resolved,
                resolved,
            )
            if self._tree_observed_at[resolved] is None:
                self._tree_observed_at[resolved] = _tree_mtime(resolved)
        return self._tree_observed_at[resolved]

    def _committed_path_at(self, repo_hint: Path, path: Path) -> float | None:
        git_root = self._git_root(repo_hint)
        if git_root is None:
            return None
        try:
            relpath = path.relative_to(git_root).as_posix() or "."
        except ValueError:
            return None
        try:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(git_root),
                    "log",
                    "-1",
                    "--format=%ct",
                    "--",
                    relpath,
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        text = result.stdout.strip()
        if not text:
            return None
        try:
            return float(int(text.splitlines()[0]))
        except ValueError:
            return None

    def _git_root(self, path: Path) -> Path | None:
        key = path.expanduser().resolve(strict=False)
        if key in self._git_roots:
            return self._git_roots[key]
        try:
            result = subprocess.run(
                ["git", "-C", str(key), "rev-parse", "--show-toplevel"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired):
            self._git_roots[key] = None
            return None
        if result.returncode != 0:
            self._git_roots[key] = None
            return None
        root = result.stdout.strip()
        self._git_roots[key] = Path(root) if root else None
        return self._git_roots[key]


def _source_is_fresh_for_row(observed_at: float | None, row: Mapping[str, Any]) -> bool:
    if observed_at is None:
        return False
    return observed_at >= _row_created_at(row)


def _row_created_at(row: Mapping[str, Any]) -> float:
    text = str(row.get("created_at") or "").strip()
    if not text:
        return 0.0
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).timestamp()


def _file_mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _tree_mtime(path: Path) -> float | None:
    latest = _file_mtime(path)
    try:
        paths = path.rglob("*")
    except OSError:
        return latest
    for child in paths:
        child_mtime = _file_mtime(child)
        if child_mtime is not None:
            latest = child_mtime if latest is None else max(latest, child_mtime)
    return latest

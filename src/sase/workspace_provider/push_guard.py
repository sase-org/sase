"""Read-only repository identity checks at Git publication boundaries."""

from __future__ import annotations

from pathlib import Path

from sase._git_remote import git_remotes_match
from sase._git_worktree import require_worktree_root
from sase.workspace_provider._utils_git import (
    git_remote_get_origin_push_urls,
    output_lines,
    read_required_origin_url,
    remote_urls_match,
)


def _primary_origin(path: str) -> str:
    require_worktree_root(path)
    return read_required_origin_url(path)


def _expected_origin(checkout: Path) -> str | None:
    from sase._linked_repo_env import linked_repo_metadata_from_env
    from sase.workspace_provider.marker import read_marker

    for metadata in linked_repo_metadata_from_env():
        path = metadata.get("workspace_dir")
        if not isinstance(path, str) or Path(path).resolve() != checkout:
            continue
        remote = metadata.get("remote_url")
        if isinstance(remote, str) and remote.strip():
            return remote.strip()
        primary = metadata.get("primary_dir")
        if isinstance(primary, str) and primary.strip():
            return _primary_origin(primary)
        raise RuntimeError(f"Missing expected origin for linked checkout {checkout}")

    marker = read_marker(str(checkout))
    if marker is not None:
        if not marker.primary_workspace_dir:
            raise RuntimeError(f"Missing primary identity for checkout {checkout}")
        return _primary_origin(marker.primary_workspace_dir)

    # Inventory is read-only: never materialize/heal the checkout to learn its
    # expected identity, since doing so could conceal the wrong-origin failure.
    from sase.repo_inventory import collect_repo_inventory

    inventory = collect_repo_inventory(include_disabled=True)
    for repo in inventory.records:
        paths = [repo.path, *(clone.path for clone in repo.clones)]
        if not any(Path(path).resolve() == checkout for path in paths):
            continue
        if repo.remote_url:
            return repo.remote_url
        if repo.kind != "external":
            return _primary_origin(repo.path)
        if repo.name.startswith("gh:"):
            return f"git@github.com:{repo.name.removeprefix('gh:')}.git"
        primary = next(
            (
                item
                for item in inventory.records
                if item.kind == "primary" and item.project == repo.name
            ),
            None,
        )
        if primary is not None:
            return _primary_origin(primary.path)
        raise RuntimeError(f"Missing expected origin for external checkout {checkout}")

    if (checkout / ".sase" / "checkout.json").exists() or any(
        parent.name == "repos" and parent.parent.name == "sase"
        for parent in checkout.parents
    ):
        raise RuntimeError(
            f"Cannot establish expected origin for managed checkout {checkout}"
        )
    # A user-owned, unregistered checkout has no independent SASE remote pin.
    return None


def require_push_identity(cwd: str) -> None:
    """Refuse publication from another worktree or to an unexpected origin."""
    require_worktree_root(cwd)
    checkout = Path(cwd).expanduser().resolve()
    actual = read_required_origin_url(str(checkout))
    try:
        expected = _expected_origin(checkout)
    except Exception as exc:
        raise RuntimeError(
            f"Refusing Git push from {checkout}: origin={actual!r}, "
            f"expected=<unresolved>: {exc}"
        ) from exc
    if expected is None:
        return
    push_urls = output_lines(git_remote_get_origin_push_urls(str(checkout)))
    for url in [actual, *(push_urls or ["<unreadable push URL>"])]:
        if not (
            remote_urls_match(url, expected, cwd=str(checkout))
            or git_remotes_match(url, expected)
        ):
            raise RuntimeError(
                f"Refusing Git push from {checkout}: origin/destination={url!r}, "
                f"expected={expected!r}. Repair the checkout's origin before retrying."
            )

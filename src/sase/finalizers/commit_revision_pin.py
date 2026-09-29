"""Host-owned ``revision_pin`` follow for the builtin commit finalizer.

When one accepted declaration commits both the primary checkout and a
linked repo whose ``repos.linked[].revision_pin`` names a pin file, the
host commits the pinned sibling first and writes its pushed SHA into the
primary's pin file before the primary commit. That makes the change one
green commit per repo with no follow-up turn.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import logging
import re
import subprocess
from pathlib import Path
from typing import Any

from sase.llm_provider.commit_finalizer_types import DirtyRepo

_logger = logging.getLogger(__name__)

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHORT = 12


def _is_pin_sha(value: str) -> bool:
    """Return whether *value* is a full 40-character hex SHA."""

    return bool(_SHA_RE.match(value.strip()))


def _short_sha(value: str) -> str:
    """Return the 12-character abbreviation used in evidence strings."""

    return value.strip()[:_SHORT]


def revision_pins_for_project(
    project_dir: str,
    *,
    config: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Return ``{linked repo name: normalized pin path}`` for *project_dir*.

    Pins are read from the primary checkout's own project-local config
    (``sase/sase.yml``), or from the explicit *config* mapping when given.
    Global merged config is deliberately not consulted: it is keyed off the
    process working directory, so a tmp-dir finalizer test running inside
    the sase checkout would otherwise inherit sase's own pin.
    """

    try:
        from sase._linked_repo_config import (
            merged_linked_entries_from_config,
            read_project_local_config,
            revision_pin_for_entry,
        )
    except Exception:  # noqa: BLE001 - config must never fail the finalizer
        return {}
    try:
        if config is not None:
            entries, _warnings = merged_linked_entries_from_config(config)
        else:
            local_config = read_project_local_config(project_dir)
            entries, _warnings = merged_linked_entries_from_config(local_config)
    except Exception:  # noqa: BLE001 - config must never fail the finalizer
        return {}
    pins: dict[str, str] = {}
    for entry in entries:
        try:
            if entry.get("_sase_sidecar_repo") is True:
                continue
            name = entry.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            pin = revision_pin_for_entry(entry)
        except ValueError:
            continue
        except Exception:  # noqa: BLE001 - one bad entry skips, not the run
            continue
        if pin is not None:
            pins[name.strip()] = pin
    return pins


def _repo_id(repo: DirtyRepo) -> str:
    from sase.finalizers.commit_declaration import repository_decision_id

    return repository_decision_id(repo)


def _decision_action(decision: Mapping[str, Any] | None) -> str:
    if not isinstance(decision, Mapping):
        return ""
    return str(decision.get("action", ""))


def order_pinned_siblings_first(
    ordered: Sequence[DirtyRepo],
    decisions: Mapping[str, Mapping[str, Any]],
    *,
    pins: Mapping[str, str] | None = None,
    accepted_deferrals: Mapping[str, Any] | None = None,
) -> list[DirtyRepo]:
    """Move committed pinned siblings ahead of the main repo.

    Every other repo keeps its current context order. Declarations without
    a committed pinned sibling keep today's order exactly.
    """

    items = list(ordered)
    if pins is None:
        try:
            pins = {}
        except Exception:  # noqa: BLE001 - defensive; never fail ordering
            return items
    if not pins:
        return items
    deferrals = accepted_deferrals or {}

    def _is_commit(repo: DirtyRepo) -> bool:
        repo_id = _repo_id(repo)
        if repo_id in deferrals:
            return False
        return _decision_action(decisions.get(repo_id)) == "commit"

    main_ids = {
        _repo_id(repo) for repo in items if repo.kind == "main" and _is_commit(repo)
    }
    if not main_ids:
        return items
    pinned_ids = {
        _repo_id(repo)
        for repo in items
        if repo.kind != "main" and repo.name in pins and _is_commit(repo)
    }
    if not pinned_ids:
        return items
    pinned = [repo for repo in items if _repo_id(repo) in pinned_ids]
    rest = [repo for repo in items if _repo_id(repo) not in pinned_ids]
    first_main = next(
        (index for index, repo in enumerate(rest) if _repo_id(repo) in main_ids),
        None,
    )
    if first_main is None:
        return items
    return [*rest[:first_main], *pinned, *rest[first_main:]]


def order_with_project_pins(
    ordered: Sequence[DirtyRepo],
    decisions: Mapping[str, Mapping[str, Any]],
    *,
    project_dir: str,
    accepted_deferrals: Mapping[str, Any] | None = None,
    config: Mapping[str, Any] | None = None,
) -> list[DirtyRepo]:
    """Order *ordered* with the project's ``revision_pin`` map applied."""

    pins = revision_pins_for_project(project_dir, config=config)
    return order_pinned_siblings_first(
        ordered,
        decisions,
        pins=pins,
        accepted_deferrals=accepted_deferrals,
    )


def without_pin_protected(
    protected: Sequence[str],
    pin_rel: str | None,
) -> tuple[str, ...]:
    """Drop the host-owned pin path from a protected-path exclude list.

    The pin file is host-authored: the main stitch must commit it together
    with the agent's work, never exclude it as pre-existing dirt.
    Rewriting the pin is idempotent, and an already-written pin is expected
    state, not stale dirt.
    """

    if not pin_rel:
        return tuple(protected)
    normalized = pin_rel.strip().replace("\\", "/").lstrip("./")
    cleaned: list[str] = []
    for path in protected:
        candidate = str(path).replace("\\", "/").lstrip("./")
        if candidate == normalized or candidate.endswith(f"/{normalized}"):
            continue
        cleaned.append(str(path))
    return tuple(cleaned)


def _read_pin_value(pin_path: Path) -> str | None:
    try:
        text = pin_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def _git(
    argv: list[str],
    *,
    cwd: str,
    timeout_seconds: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )


def _default_branch_remote_ref(sibling_dir: str) -> str | None:
    """Resolve the sibling's remote default branch ref, e.g. ``origin/main``."""

    head = _git(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
        cwd=sibling_dir,
    )
    if head.returncode == 0:
        ref = head.stdout.strip()
        if ref.startswith("refs/remotes/"):
            return ref[len("refs/remotes/") :]
    for candidate in ("origin/main", "origin/master"):
        probe = _git(
            ["git", "show-ref", "--verify", f"refs/remotes/{candidate}"],
            cwd=sibling_dir,
        )
        if probe.returncode == 0:
            return candidate
    return None


def _sha_reachable_from_default_branch(
    sibling_dir: str,
    sha: str,
    *,
    fetch: bool = True,
) -> bool:
    if fetch:
        try:
            _git(["git", "fetch", "origin"], cwd=sibling_dir)
        except Exception:  # noqa: BLE001 - fetch failure means try anyway
            _logger.debug("revision_pin fetch failed; continuing", exc_info=True)
    ref = _default_branch_remote_ref(sibling_dir)
    if ref is None:
        contained = _git(
            ["git", "branch", "-r", "--contains", sha],
            cwd=sibling_dir,
        )
        return contained.returncode == 0 and bool(contained.stdout.strip())
    ancestor = _git(
        ["git", "merge-base", "--is-ancestor", sha, ref],
        cwd=sibling_dir,
    )
    return ancestor.returncode == 0


def _pin_is_ancestor(
    sibling_dir: str,
    old_sha: str,
    new_sha: str,
) -> bool:
    if old_sha == new_sha:
        return True
    probe = _git(
        ["git", "merge-base", "--is-ancestor", old_sha, new_sha],
        cwd=sibling_dir,
    )
    return probe.returncode == 0


def _pin_escape_reason(project_dir: str, pin_rel: str) -> str | None:
    """Return the skip reason when *pin_rel* leaves *project_dir*.

    Lexical escapes (absolute paths, ``..``) are rejected by the config
    normalizer; physical escapes through a symlinked parent component or
    a symlinked pin file are detected with realpath. Returns ``None``
    when the pin stays inside the primary checkout.
    """

    try:
        from sase._linked_repo_config import (
            normalize_revision_pin,
            revision_pin_escapes_primary,
        )
    except Exception:  # noqa: BLE001 - fail closed when helpers unavailable
        return "pin-escapes-checkout"
    try:
        normalized = normalize_revision_pin(pin_rel)
    except ValueError:
        return "pin-escapes-checkout"
    except Exception:  # noqa: BLE001 - fail closed
        return "pin-escapes-checkout"
    if normalized is None:
        return "pin-escapes-checkout"
    try:
        if revision_pin_escapes_primary(project_dir, normalized):
            return "pin-escapes-checkout"
    except Exception:  # noqa: BLE001 - fail closed
        return "pin-escapes-checkout"
    return None


def maybe_write_revision_pin(
    *,
    project_dir: str,
    sibling_name: str,
    sibling_dir: str,
    pin_rel: str,
    commit_sha: str,
    main_is_commit: bool,
    fetch: bool = True,
) -> tuple[str, str | None]:
    """Write a pinned sibling's pushed SHA into the primary pin file.

    Returns ``(evidence_value, diagnostic)``. A skipped pin never fails
    the run: the skip reason is recorded as a finalizer diagnostic and as
    ``revision_pin`` evidence.
    """

    sha = commit_sha.strip()
    if not main_is_commit:
        reason = "main-deferred-or-not-dirty"
        return f"{sibling_name}:{pin_rel}:skipped:{reason}", (
            f"revision_pin for {sibling_name} skipped: {reason}"
        )
    if not _is_pin_sha(sha):
        reason = "sha-not-40-hex"
        return f"{sibling_name}:{pin_rel}:skipped:{reason}", (
            f"revision_pin for {sibling_name} skipped: {reason}"
        )
    escape_reason = _pin_escape_reason(project_dir, pin_rel)
    if escape_reason is not None:
        reason = escape_reason
        return f"{sibling_name}:{pin_rel}:skipped:{reason}", (
            f"revision_pin for {sibling_name} skipped: {reason}"
        )
    from sase._linked_repo_config import normalize_revision_pin as _normalize_pin

    try:
        _normalized = _normalize_pin(pin_rel)
    except ValueError:
        _normalized = None
    pin_path = (
        Path(project_dir) / _normalized if _normalized is not None else Path(pin_rel)
    )
    current = _read_pin_value(pin_path)
    if current == sha:
        reason = "already-equal"
        return f"{sibling_name}:{pin_rel}:skipped:{reason}", (
            f"revision_pin for {sibling_name} already at {_short_sha(sha)}"
        )
    if not _sha_reachable_from_default_branch(sibling_dir, sha, fetch=fetch):
        reason = "sha-not-on-default-branch"
        return f"{sibling_name}:{pin_rel}:skipped:{reason}", (
            f"revision_pin for {sibling_name} skipped: {reason}"
        )
    if current is not None and _is_pin_sha(current):
        if not _pin_is_ancestor(sibling_dir, current, sha):
            reason = "pin-not-ancestor"
            return f"{sibling_name}:{pin_rel}:skipped:{reason}", (
                f"revision_pin for {sibling_name} skipped: {reason}"
            )
    elif current is not None:
        reason = "pin-not-40-hex"
        return f"{sibling_name}:{pin_rel}:skipped:{reason}", (
            f"revision_pin for {sibling_name} skipped: {reason}"
        )
    old12 = _short_sha(current) if current is not None else "missing"
    try:
        pin_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = pin_path.with_name(f".{pin_path.name}.pin.tmp")
        tmp_path.write_text(f"{sha}\n", encoding="utf-8")
        tmp_path.replace(pin_path)
    except OSError as exc:
        reason = "pin-write-failed"
        return f"{sibling_name}:{pin_rel}:skipped:{reason}", (
            f"revision_pin for {sibling_name} skipped: {exc}"
        )
    return f"{sibling_name}:{pin_rel}:{old12}->{_short_sha(sha)}", None


__all__ = [
    "maybe_write_revision_pin",
    "order_pinned_siblings_first",
    "order_with_project_pins",
    "revision_pins_for_project",
    "without_pin_protected",
]

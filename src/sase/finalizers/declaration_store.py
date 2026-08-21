"""Host-owned declaration lock, host snapshots, and obligation helpers.

Context publication and submission acceptance share one lock order so a
successful ``sase final submit`` cannot land against an already stale
context:

1. the in-process declaration mutex (threads in one interpreter)
2. ``final_declaration.lock`` flock (separate processes)
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Any

from sase.core.finalizer_facade import finalizer_json_digest
from sase.core.finalizer_wire import (
    FinalizerContextWire,
    FinalizerObligationWire,
    FinalizerPayloadRequirementWire,
    FinalizerPlanWire,
    finalizer_context_from_dict,
)
from sase.llm_provider.commit_finalizer_git import dirty_path_fingerprints
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.memory.locks import locked_file

FINAL_CONTEXT_HOST_FILENAME = "final_context_host.json"
FINAL_SUBMISSION_HOST_FILENAME = "final_submission_host.json"
FINAL_DECLARATION_LOCK_FILENAME = "final_declaration.lock"

_HOST_REPO_KINDS = frozenset({"main", "sibling", "external", "sdd"})
_DECLARATION_THREAD_LOCK = threading.Lock()


class FinalizerDeclarationError(RuntimeError):
    """Raised when a finalizer declaration command cannot complete."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class HostRepositoryRecord:
    """Host-only identity for one accepted repository obligation."""

    obligation_id: str
    kind: str
    name: str
    path: str


@contextmanager
def acquire_declaration_locks(root: Path) -> Iterator[None]:
    """Acquire the in-process mutex and declaration flock for *root*."""

    with _DECLARATION_THREAD_LOCK:
        with locked_file(root / FINAL_DECLARATION_LOCK_FILENAME, fcntl.LOCK_EX):
            yield


def accepted_context_from_submission(
    submission: Mapping[str, Any],
    *,
    fallback: FinalizerContextWire,
) -> FinalizerContextWire:
    """Return the context snapshotted at accept time, else *fallback*."""

    raw = submission.get("accepted_context")
    if not isinstance(raw, Mapping):
        return fallback
    try:
        return finalizer_context_from_dict(dict(raw))
    except Exception as exc:
        raise FinalizerDeclarationError(
            f"accepted finalizer context snapshot is invalid: {exc}",
            code="malformed_accepted_context",
        ) from exc


def load_accepted_host_repositories(root: Path) -> tuple[HostRepositoryRecord, ...]:
    """Load host-only repository identities snapshotted with the submission."""

    path = root / FINAL_SUBMISSION_HOST_FILENAME
    if not path.is_file():
        path = root / FINAL_CONTEXT_HOST_FILENAME
    return read_host_repository_file(path)


def host_repository_records(
    dirty_state: DirtyState,
) -> tuple[HostRepositoryRecord, ...]:
    return tuple(
        HostRepositoryRecord(
            obligation_id=repository_obligation_id(repo),
            kind=repo.kind,
            name=repo.name,
            path=repo.path,
        )
        for repo in dirty_state.repos
    )


def write_host_repository_file(
    path: Path,
    *,
    context_digest: str,
    records: Sequence[HostRepositoryRecord],
) -> None:
    write_json_atomic(
        path,
        {
            "schema_version": 1,
            "context_digest": context_digest,
            "repositories": [
                {
                    "obligation_id": record.obligation_id,
                    "kind": record.kind,
                    "name": record.name,
                    "path": record.path,
                }
                for record in records
            ],
        },
    )


def read_host_repository_file(path: Path) -> tuple[HostRepositoryRecord, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ()
    except (OSError, json.JSONDecodeError) as exc:
        raise FinalizerDeclarationError(
            "finalizer host repository snapshot is malformed",
            code="malformed_host_repositories",
        ) from exc
    if not isinstance(payload, Mapping):
        raise FinalizerDeclarationError(
            "finalizer host repository snapshot is malformed",
            code="malformed_host_repositories",
        )
    raw_records = payload.get("repositories")
    if not isinstance(raw_records, list):
        raise FinalizerDeclarationError(
            "finalizer host repository snapshot is malformed",
            code="malformed_host_repositories",
        )
    records: list[HostRepositoryRecord] = []
    for item in raw_records:
        if not isinstance(item, Mapping):
            continue
        obligation_id = item.get("obligation_id")
        kind = item.get("kind")
        name = item.get("name")
        repo_path = item.get("path")
        if not (
            isinstance(obligation_id, str)
            and isinstance(kind, str)
            and kind in _HOST_REPO_KINDS
            and isinstance(name, str)
            and isinstance(repo_path, str)
        ):
            raise FinalizerDeclarationError(
                "finalizer host repository snapshot has an invalid record",
                code="malformed_host_repositories",
            )
        records.append(
            HostRepositoryRecord(
                obligation_id=obligation_id,
                kind=kind,
                name=name,
                path=repo_path,
            )
        )
    return tuple(records)


def build_context_requirements(
    plan: FinalizerPlanWire,
    dirty_state: DirtyState,
) -> tuple[list[FinalizerPayloadRequirementWire], list[FinalizerObligationWire]]:
    requirements: list[FinalizerPayloadRequirementWire] = []
    obligations: list[FinalizerObligationWire] = []
    repository_obligations: list[FinalizerObligationWire] | None = None

    for entry in plan.entries:
        if entry.provider_ref == "builtin@commit":
            if repository_obligations is None:
                repository_obligations = [
                    _repository_obligation(repo) for repo in dirty_state.repos
                ]
                obligations.extend(repository_obligations)
            trigger = "dirty_repository" if repository_obligations else "not_triggered"
            requirements.append(
                FinalizerPayloadRequirementWire(
                    instance_id=entry.instance_id,
                    trigger=trigger,
                    submission_required=bool(repository_obligations),
                    requirement_digest=finalizer_json_digest(
                        {
                            "instance_id": entry.instance_id,
                            "trigger": trigger,
                            "repositories": [
                                {
                                    "id": obligation.obligation_id,
                                    "digest": obligation.digest,
                                }
                                for obligation in repository_obligations
                            ],
                        }
                    ),
                )
            )
            continue
        if entry.provider_ref == "builtin@command":
            requirements.append(
                FinalizerPayloadRequirementWire(
                    instance_id=entry.instance_id,
                    trigger="always",
                    submission_required=False,
                    requirement_digest=finalizer_json_digest(
                        {
                            "instance_id": entry.instance_id,
                            "trigger": "always",
                            "submission_required": False,
                        }
                    ),
                )
            )
            continue
        requirements.append(
            FinalizerPayloadRequirementWire(
                instance_id=entry.instance_id,
                trigger="provider_requested",
                submission_required=True,
                requirement_digest=finalizer_json_digest(
                    {
                        "instance_id": entry.instance_id,
                        "trigger": "provider_requested",
                    }
                ),
            )
        )
    return requirements, obligations


def repository_obligation_id(repo: DirtyRepo) -> str:
    raw = json.dumps(
        {
            "kind": repo.kind,
            "name": repo.name,
            "path": repo.path,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"repo-{hashlib.sha256(raw).hexdigest()[:12]}"


def repository_state_digest(
    repo_id: str,
    repo: DirtyRepo,
    paths: Sequence[str],
) -> str:
    fingerprints = dirty_path_fingerprints(repo.path)
    return finalizer_json_digest(
        {
            "repo_id": repo_id,
            "kind": repo.kind,
            "name": repo.name,
            "paths": list(paths),
            "fingerprints": {
                path: list(fingerprints[path]) for path in paths if path in fingerprints
            },
        }
    )


def _repository_obligation(repo: DirtyRepo) -> FinalizerObligationWire:
    repo_id = repository_obligation_id(repo)
    paths = list(repo.changed_files)
    state_digest = repository_state_digest(repo_id, repo, paths)
    return FinalizerObligationWire(
        obligation_id=repo_id,
        kind="repository",
        display_name=_repository_display_name(repo),
        paths=paths,
        digest=state_digest,
    )


def _repository_display_name(repo: DirtyRepo) -> str:
    if repo.kind == "main":
        return "main"
    if repo.name:
        return f"{repo.kind}:{repo.name}"
    return repo.kind


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    write_text_atomic(path, text)


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


__all__ = [
    "FINAL_CONTEXT_HOST_FILENAME",
    "FINAL_DECLARATION_LOCK_FILENAME",
    "FINAL_SUBMISSION_HOST_FILENAME",
    "FinalizerDeclarationError",
    "HostRepositoryRecord",
    "accepted_context_from_submission",
    "acquire_declaration_locks",
    "build_context_requirements",
    "host_repository_records",
    "load_accepted_host_repositories",
    "read_host_repository_file",
    "repository_obligation_id",
    "repository_state_digest",
    "write_host_repository_file",
    "write_json_atomic",
    "write_text_atomic",
]

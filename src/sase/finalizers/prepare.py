"""Prepare host-sealed conditional completion intents without finalizing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import shlex
import subprocess
from typing import Any

from sase.core.continuation_facade import (
    bind_conditional_completion,
    preview_conditional_completion,
    rollback_conditional_completion_binding,
    seal_conditional_completion,
    validate_conditional_completion_intent,
)
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.core.finalizer_wire import FinalizerPlanWire
from sase.finalizers.commit_validation import protected_baseline_paths
from sase.finalizers.declaration import (
    FinalizerDeclarationError,
    hold_finalizer_declaration_lock,
    load_finalizer_plan,
    publish_final_context,
    require_artifacts_dir,
)
from sase.finalizers.declaration_recovery_evidence import (
    direct_written_paths,
    written_paths_from_tool_calls,
)
from sase.finalizers.declaration_store import (
    repository_obligation_id,
    write_json_atomic,
)
from sase.finalizers.providers import BUILTIN_PROVIDER_REFS
from sase.linked_repos import opened_external_repo_records, opened_linked_repo_records
from sase.llm_provider.commit_finalizer_config import resolve_finalizer_project_dir
from sase.llm_provider.commit_finalizer_git import git_changed_files, normalize_path
from sase.llm_provider.commit_finalizer_git_status import (
    UNKNOWN_HEAD_SENTINEL,
    dirty_path_fingerprints,
    git_head_commit_id,
)
from sase.llm_provider.commit_finalizer_state import (
    collect_baseline_repositories,
    collect_dirty_state,
)
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.memory.locks import locked_file

COMPLETION_INTENTS_DIRNAME = "completion_intents"
COMPLETION_INDEX_FILENAME = "index.json"
COMPLETION_LOCK_FILENAME = "completion_intents.lock"
_GIT_TIMEOUT_SECONDS = 5
_MAX_PREPARE_BYTES = 256 * 1024


@dataclass(frozen=True)
class PreparedCompletion:
    """One persisted, host-sealed conditional completion intent."""

    intent: dict[str, Any]
    preview: dict[str, Any]
    intent_ref: str
    path: Path


def prepare_conditional_completion(
    wrapper: Mapping[str, Any],
    *,
    artifacts_dir: str | None = None,
) -> PreparedCompletion:
    """Validate, seal, and persist a conditional completion intent.

    Publishes the current host-issued finalizer context and observes opened
    repositories. Does not submit a declaration, commit, or end the turn.
    """

    root = require_artifacts_dir(artifacts_dir, "sase final prepare")
    success_message, verification_command, declaration = _parse_wrapper(wrapper)
    publication = publish_final_context(artifacts_dir=str(root))
    context = publication.context
    plan = load_finalizer_plan(root)
    if context.context_digest:
        declaration.setdefault("context_digest", context.context_digest)
    declaration.setdefault("plan_digest", plan.plan_digest)
    observations = observe_completion_repositories(root)
    creator: dict[str, str] = {
        "project": os.environ.get("SASE_PROJECT")
        or os.environ.get("SASE_PROJECT_NAME")
        or "sase",
        "run_id": context.run_id,
        "agent_name": context.agent_id,
    }
    workspace_id = (os.environ.get("SASE_WORKSPACE_NUM") or "").strip()
    if workspace_id:
        creator["workspace_id"] = workspace_id
    request = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "creator": creator,
        "context": {
            "run_id": context.run_id,
            "agent_id": context.agent_id,
            "turn_nonce": context.turn_nonce,
            "plan_digest": plan.plan_digest,
            "context_digest": context.context_digest or "",
            "obligation_ids": [
                obligation.obligation_id
                for obligation in context.obligations
                if obligation.kind == "repository"
            ],
        },
        "success_message": success_message,
        "verification_command": verification_command,
        "declaration": declaration,
        "observations": observations,
        "executors": _executor_capabilities(plan),
    }
    try:
        intent = seal_conditional_completion(request)
    except ValueError as exc:
        raise FinalizerDeclarationError(
            str(exc), code="conditional_completion_invalid"
        ) from exc
    stored = persist_prepared_completion(intent, artifacts_dir=root)
    preview = preview_conditional_completion(stored.intent)
    return PreparedCompletion(
        intent=stored.intent,
        preview=preview,
        intent_ref=stored.intent_ref,
        path=stored.path,
    )


def persist_prepared_completion(
    intent: Mapping[str, Any],
    *,
    artifacts_dir: str | Path,
) -> PreparedCompletion:
    """Write a sealed intent under the agent's continuation store."""

    root = Path(artifacts_dir)
    intent_id = str(intent["intent_id"])
    directory = _intents_dir(root)
    path = directory / f"{_safe_filename(intent_id)}.json"
    with _intent_lock(root):
        write_json_atomic(path, intent)
        local_ref = f"local:continuation/{COMPLETION_INTENTS_DIRNAME}/{path.name}"
        artifact_ref = _register_explicit_artifact(path, root)
        refs = [local_ref, intent_id]
        if artifact_ref is not None:
            refs.insert(0, artifact_ref)
        _index_put(directory, intent_id, path.name, refs)
    intent_ref = refs[0]
    preview = preview_conditional_completion(dict(intent))
    return PreparedCompletion(
        intent=dict(intent),
        preview=preview,
        intent_ref=intent_ref,
        path=path,
    )


def load_prepared_completion(
    reference: str,
    *,
    artifacts_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Load a sealed intent by artifact ref, local ref, or intent id."""

    root = require_artifacts_dir(
        str(artifacts_dir) if artifacts_dir is not None else None,
        "conditional completion bind",
    )
    with _intent_lock(root):
        path = _resolve_intent_path(root, reference)
        payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise FinalizerDeclarationError(
            f"conditional completion intent at {path} is not an object",
            code="malformed_completion_intent",
        )
    return validate_conditional_completion_intent(payload)


def bind_prepared_completion(
    reference: str,
    *,
    monitor_id: str,
    command: str | Sequence[str],
    request_fingerprint: str,
    artifacts_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Atomically bind a prepared intent to one monitor start."""

    root = require_artifacts_dir(
        str(artifacts_dir) if artifacts_dir is not None else None,
        "conditional completion bind",
    )
    argv = _command_argv(command)
    with _intent_lock(root):
        path = _resolve_intent_path(root, reference)
        current = json.loads(path.read_text(encoding="utf-8"))
        try:
            bound = bind_conditional_completion(
                {
                    "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
                    "intent": current,
                    "monitor_id": monitor_id,
                    "command": argv,
                    "request_fingerprint": request_fingerprint,
                }
            )
        except ValueError as exc:
            raise FinalizerDeclarationError(
                str(exc),
                code="conditional_completion_bind_failed",
            ) from exc
        write_json_atomic(path, bound)
        return bound


def rollback_prepared_completion(
    reference: str,
    *,
    monitor_id: str,
    artifacts_dir: str | Path | None = None,
) -> dict[str, Any] | None:
    """Restore a bound intent after a failed monitor start."""

    try:
        root = require_artifacts_dir(
            str(artifacts_dir) if artifacts_dir is not None else None,
            "conditional completion rollback",
        )
    except FinalizerDeclarationError:
        return None
    with _intent_lock(root):
        try:
            path = _resolve_intent_path(root, reference)
            current = json.loads(path.read_text(encoding="utf-8"))
            restored = rollback_conditional_completion_binding(
                {
                    "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
                    "intent": current,
                    "monitor_id": monitor_id,
                }
            )
        except (FinalizerDeclarationError, OSError, ValueError, json.JSONDecodeError):
            return None
        write_json_atomic(path, restored)
        return restored


def observe_completion_repositories(root: Path) -> list[dict[str, Any]]:
    """Observe HEAD, index, and dirty paths for every relevant opened repo."""

    project_dir = resolve_finalizer_project_dir()
    dirty = collect_dirty_state(project_dir, artifact_root=root)
    dirty_by_path = {normalize_path(repo.path): repo for repo in dirty.repos}
    written = written_paths_from_tool_calls(root)
    observations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for repo in _observation_repos(project_dir, root, dirty.repos):
        path = normalize_path(repo.path)
        if path in seen:
            continue
        seen.add(path)
        dirty_repo = dirty_by_path.get(path, repo)
        observations.append(
            _observe_one_repository(
                dirty_repo,
                artifacts=root,
                written_paths=written,
            )
        )
    return observations


def format_prepare_preview(
    prepared: PreparedCompletion,
    *,
    json_output: bool,
) -> str:
    """Render the prepare command's user-facing preview."""

    if json_output:
        payload = {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "intent_id": prepared.intent["intent_id"],
            "intent_ref": prepared.intent_ref,
            "preview": prepared.preview,
        }
        return json.dumps(payload, indent=2, sort_keys=True)
    preview = prepared.preview
    checks = preview.get("required_checks") or {}
    command = " ".join(str(part) for part in checks.get("command") or ())
    lines = [
        f"Prepared conditional completion {prepared.intent['intent_id']}",
        f"  ref           {prepared.intent_ref}",
        f"  success       {preview.get('success_action')}",
        f"  checks        {command} ({checks.get('level')})",
        f"  message       {preview.get('prepared_message')}",
        f"  on failure    {preview.get('failure_timeout_routing')}",
    ]
    for decision in preview.get("repository_decisions") or ():
        lines.append(
            f"  repository    {decision.get('repo_id')} {decision.get('action')} "
            f"{decision.get('message')}"
        )
    lines.append(
        "This does not submit, commit, or end the turn. Bind the ref with "
        "`sase monitor start -f <ref>`."
    )
    return "\n".join(lines)


def read_prepare_manifest(path: str) -> dict[str, Any]:
    """Read one JSON prepare wrapper from a file or stdin."""

    if path == "-":
        import sys

        raw = sys.stdin.buffer.read(_MAX_PREPARE_BYTES + 1)
    else:
        try:
            raw = Path(path).read_bytes()
        except OSError as exc:
            raise FinalizerDeclarationError(
                f"could not read completion prepare manifest: {exc}",
                code="manifest_read_failed",
            ) from exc
    if len(raw) > _MAX_PREPARE_BYTES:
        raise FinalizerDeclarationError(
            "completion prepare manifest is too large",
            code="manifest_too_large",
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinalizerDeclarationError(
            f"completion prepare manifest is not valid JSON: {exc}",
            code="manifest_invalid_json",
        ) from exc
    if not isinstance(payload, dict):
        raise FinalizerDeclarationError(
            "completion prepare manifest must be a JSON object",
            code="manifest_invalid_json",
        )
    return payload


def _parse_wrapper(
    wrapper: Mapping[str, Any],
) -> tuple[str, list[str], dict[str, Any]]:
    success_message = wrapper.get("success_message") or wrapper.get("prepared_message")
    if not isinstance(success_message, str) or not success_message.strip():
        raise FinalizerDeclarationError(
            "prepare manifest requires success_message",
            code="missing_success_message",
        )
    verification = wrapper.get("verification")
    command: object
    if isinstance(verification, Mapping):
        command = verification.get("command")
    else:
        command = wrapper.get("verification_command")
    argv = _command_argv(command)
    declaration = wrapper.get("declaration")
    if not isinstance(declaration, dict):
        if "payloads" in wrapper:
            declaration = {
                key: value
                for key, value in wrapper.items()
                if key
                not in {
                    "success_message",
                    "prepared_message",
                    "verification",
                    "verification_command",
                    "kind",
                }
            }
        else:
            raise FinalizerDeclarationError(
                "prepare manifest requires a declaration object",
                code="missing_declaration",
            )
    return success_message, argv, dict(declaration)


def _command_argv(command: object) -> list[str]:
    if isinstance(command, str):
        parts = shlex.split(command)
    elif isinstance(command, Sequence) and not isinstance(command, bytes | bytearray):
        parts = [str(part) for part in command]
    else:
        raise FinalizerDeclarationError(
            "verification command must be an argv list or a shell string",
            code="invalid_verification_command",
        )
    if not parts:
        raise FinalizerDeclarationError(
            "verification command must not be empty",
            code="invalid_verification_command",
        )
    return parts


def _executor_capabilities(plan: FinalizerPlanWire) -> list[dict[str, Any]]:
    capabilities: list[dict[str, Any]] = []
    for entry in plan.entries:
        builtin = entry.provider_ref in BUILTIN_PROVIDER_REFS
        capabilities.append(
            {
                "instance_id": entry.instance_id,
                "provider_ref": entry.provider_ref,
                "headless": builtin,
                "durable_replay": builtin,
                "requires_model": not builtin,
            }
        )
    return capabilities


def _observation_repos(
    project_dir: str,
    artifacts: Path,
    dirty_repos: Sequence[DirtyRepo],
) -> list[DirtyRepo]:
    repos: list[DirtyRepo] = list(dirty_repos)
    for baseline in collect_baseline_repositories(project_dir):
        repos.append(
            DirtyRepo(
                name=baseline.name,
                path=baseline.path,
                changed_files=(),
                kind=baseline.kind,
            )
        )
    for name, record in opened_linked_repo_records(artifacts).items():
        workspace = record.get("workspace_dir") or record.get("path")
        if not workspace:
            continue
        repos.append(
            DirtyRepo(
                name=name,
                path=workspace,
                changed_files=(),
                kind="sibling",
            )
        )
    for name, record in opened_external_repo_records(artifacts).items():
        workspace = record.get("workspace_dir") or record.get("path")
        if not workspace:
            continue
        repos.append(
            DirtyRepo(
                name=name,
                path=workspace,
                changed_files=(),
                kind="external",
            )
        )
    return repos


def _observe_one_repository(
    repo: DirtyRepo,
    *,
    artifacts: Path,
    written_paths: tuple[str, ...],
) -> dict[str, Any]:
    head = git_head_commit_id(repo.path)
    head_tree = (
        _git_output(repo.path, ["rev-parse", "HEAD^{tree}"]) or UNKNOWN_HEAD_SENTINEL
    )
    index_tree = _git_output(repo.path, ["write-tree"]) or UNKNOWN_HEAD_SENTINEL
    fingerprints = dirty_path_fingerprints(repo.path)
    protected = set(
        protected_baseline_paths(
            artifacts,
            repo.path,
            get_changed_files=git_changed_files,
        )
    )
    run_written = set(
        direct_written_paths(
            repo_path=repo.path,
            written_paths=written_paths,
            named_paths=tuple(fingerprints),
        )
    )
    paths: list[dict[str, Any]] = []
    complete = (
        head not in {"", UNKNOWN_HEAD_SENTINEL}
        and head_tree not in {"", UNKNOWN_HEAD_SENTINEL}
        and index_tree not in {"", UNKNOWN_HEAD_SENTINEL}
    )
    for rel_path, (xy, content_hash) in sorted(fingerprints.items()):
        kind, mode = _path_kind_and_mode(repo.path, rel_path, xy)
        if kind != "deleted" and content_hash is None:
            complete = False
        paths.append(
            {
                "path": rel_path,
                "xy": xy,
                "content_hash": content_hash,
                "mode": mode,
                "kind": kind,
                "protected": rel_path in protected,
                "foreign": rel_path not in run_written and rel_path in protected,
            }
        )
    return {
        "repo_id": repository_obligation_id(repo),
        "kind": repo.kind,
        "name": repo.name,
        "head": head,
        "head_tree": head_tree,
        "index_tree": index_tree,
        "paths": paths,
        "complete": complete,
    }


def _path_kind_and_mode(
    repo_dir: str,
    rel_path: str,
    xy: str,
) -> tuple[str, str | None]:
    if "D" in xy:
        return "deleted", None
    full = Path(repo_dir) / rel_path.split(" -> ", 1)[0]
    try:
        if full.is_symlink():
            return "symlink", f"{full.lstat().st_mode:o}"
        if not full.exists():
            return "deleted", None
        if full.is_file():
            kind = "untracked" if "?" in xy else "file"
            return kind, f"{full.stat().st_mode:o}"
    except OSError:
        return "other", None
    return "other", None


def _git_output(repo_dir: str, args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _intents_dir(root: Path) -> Path:
    directory = root / "continuation" / COMPLETION_INTENTS_DIRNAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _intent_lock(root: Path) -> AbstractContextManager[None]:
    directory = _intents_dir(root)
    return locked_file(directory / COMPLETION_LOCK_FILENAME, fcntl.LOCK_EX)


def _index_put(
    directory: Path,
    intent_id: str,
    filename: str,
    refs: Sequence[str],
) -> None:
    index_path = directory / COMPLETION_INDEX_FILENAME
    index: dict[str, Any]
    if index_path.is_file():
        try:
            loaded = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
        index = loaded if isinstance(loaded, dict) else {}
    else:
        index = {}
    intents = index.setdefault("intents", {})
    intents[intent_id] = {"filename": filename, "refs": list(refs)}
    aliases = index.setdefault("aliases", {})
    for ref in refs:
        aliases[ref] = intent_id
    write_json_atomic(index_path, index)


def _resolve_intent_path(root: Path, reference: str) -> Path:
    directory = _intents_dir(root)
    index_path = directory / COMPLETION_INDEX_FILENAME
    intent_id = reference
    if index_path.is_file():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            index = {}
        if isinstance(index, dict):
            aliases = index.get("aliases")
            if isinstance(aliases, dict) and reference in aliases:
                intent_id = str(aliases[reference])
            intents = index.get("intents")
            if isinstance(intents, dict) and intent_id in intents:
                record = intents[intent_id]
                if isinstance(record, dict) and isinstance(record.get("filename"), str):
                    path = directory / record["filename"]
                    if path.is_file():
                        return path
    candidate = directory / f"{_safe_filename(reference)}.json"
    if candidate.is_file():
        return candidate
    raise FinalizerDeclarationError(
        f"conditional completion intent {reference!r} was not found",
        code="missing_completion_intent",
    )


def _register_explicit_artifact(path: Path, artifacts_dir: Path) -> str | None:
    if os.environ.get("SASE_AGENT") != "1":
        return None
    try:
        from sase.core.artifact_file_facade import store_explicit_artifact_file

        artifact = store_explicit_artifact_file(
            path,
            artifacts_dir,
            label=f"conditional completion {path.stem}",
            kind="file",
        )
    except Exception:
        return None
    return f"file:{artifact.id}"


def _safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._:-" else "_" for ch in value)


__all__ = [
    "COMPLETION_INTENTS_DIRNAME",
    "PreparedCompletion",
    "bind_prepared_completion",
    "format_prepare_preview",
    "load_prepared_completion",
    "observe_completion_repositories",
    "persist_prepared_completion",
    "prepare_conditional_completion",
    "read_prepare_manifest",
    "rollback_prepared_completion",
]

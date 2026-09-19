"""Bounded pre/post ToolRun fingerprints.

Observation reuses the porcelain/dirty-path mapping behind
``finalizers/prepare.py`` (via ``commit_finalizer_git_status`` helpers) but
never mutates inputs, never clones, and never waits indefinitely for git
locks. Missing facts stay null plus a typed explanation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any

from sase.config.tools import ToolCatalogError, load_project_tool_catalog
from sase.content_layout import discover_project_root
from sase.core.tool_run import (
    tool_run_canonicalize_fingerprint,
    tool_run_unknown_evidence,
)
from sase.llm_provider.commit_finalizer_git_paths import normalize_status_path
from sase.llm_provider.commit_finalizer_git_status import dirty_path_fingerprints
from sase.telemetry.metrics import TOOL_RUN_RECORDING_ERRORS
from sase.tool.argv import ResolvedToolArgv

_REPO_PASS_SECONDS = 4.0
_INPUT_PASS_SECONDS = 4.0
_HASH_BUDGET_BYTES = 64 * 1024 * 1024
_PROBE_SECONDS = 1.0
_PROBE_OUTPUT_BYTES = 4096
_ALL_PROBES_SECONDS = 2.0

_SECRET_NAME = re.compile(
    r"(?i)^(password|passwd|secret|token|api[_-]?key|authorization|bearer|"
    r"credential)$"
)
_LINKED_CLONE = ("sase", "repos", "linked")


@dataclass
class _Budget:
    """One observation deadline plus remaining content-hash bytes."""

    end: float
    hash_bytes: int = _HASH_BUDGET_BYTES
    missing: list[str] = field(default_factory=list)

    def remaining(self) -> float:
        return max(0.0, self.end - time.monotonic())

    def expired(self) -> bool:
        return self.remaining() <= 0

    def note(self, reason: str) -> None:
        if reason and reason not in self.missing:
            self.missing.append(reason)


def observe_fingerprint(resolved: ResolvedToolArgv) -> dict[str, Any]:
    """Observe one complete-or-explicitly-incomplete fingerprint."""

    try:
        raw = _observe_raw(resolved)
        canonical = tool_run_canonicalize_fingerprint(raw)
        fingerprint = dict(canonical.get("fingerprint") or raw)
        fingerprint["schema_version"] = 1
        return fingerprint
    except Exception as exc:  # noqa: BLE001 - observation cannot change the child.
        inc_tool_metric(TOOL_RUN_RECORDING_ERRORS, op="fingerprint")
        return tool_run_unknown_evidence(f"fingerprint observation failed: {exc}")


def inc_tool_metric(metric: Any, **labels: str) -> None:
    """Increment a ToolRun metric; failures never affect the child."""

    try:
        metric.labels(**labels).inc()
    except Exception:  # noqa: BLE001 - metrics cannot change the child.
        pass


def fingerprints_mutated(
    before: Mapping[str, Any] | None, after: Mapping[str, Any] | None
) -> bool | None:
    """Return whether complete fingerprints differ; None if either is incomplete."""

    if not isinstance(before, Mapping) or not isinstance(after, Mapping):
        return None
    before_complete = bool((before.get("completeness") or {}).get("complete"))
    after_complete = bool((after.get("completeness") or {}).get("complete"))
    if not before_complete or not after_complete:
        return None
    try:
        left = tool_run_canonicalize_fingerprint(dict(before))["digest"]
        right = tool_run_canonicalize_fingerprint(dict(after))["digest"]
    except Exception:  # noqa: BLE001 - incompleteness is safer than a guess.
        return None
    return left != right


def _observe_raw(resolved: ResolvedToolArgv) -> dict[str, Any]:
    missing: list[str] = []
    project = _project_identity()
    definition = resolved.definition if isinstance(resolved.definition, dict) else {}
    raw_spec = definition.get("fingerprint")
    spec: dict[str, Any] = raw_spec if isinstance(raw_spec, dict) else {}
    repo_names = [str(name) for name in spec.get("repos") or () if str(name).strip()]
    raw_toolchain = spec.get("toolchain")
    toolchain_spec: dict[str, Any] = (
        raw_toolchain if isinstance(raw_toolchain, dict) else {}
    )
    inputs = [str(item) for item in definition.get("inputs") or () if str(item).strip()]
    env_names = [str(item) for item in definition.get("env") or () if str(item).strip()]
    root = _observation_root(resolved)
    repos, repo_missing = _observe_repos(root, project, repo_names)
    missing.extend(repo_missing)
    input_records, input_missing = _observe_inputs(root, inputs)
    missing.extend(input_missing)
    env_values = _observe_env(env_names)
    toolchain, probe_missing = _observe_toolchain(toolchain_spec)
    missing.extend(probe_missing)
    complete = not missing
    return {
        "schema_version": 1,
        "project_identity": project,
        "definition_digest": resolved.digest or _canonical_digest(list(resolved.argv)),
        "extra_args_digest": _canonical_digest(list(resolved.extra_args)),
        "repos": repos,
        "inputs": input_records,
        "env": env_values,
        "toolchain": toolchain,
        "completeness": {"complete": complete, "missing": missing},
        "diagnostics": list(missing),
    }


def _observation_root(resolved: ResolvedToolArgv) -> Path:
    if resolved.cwd:
        return Path(resolved.cwd)
    found = discover_project_root()
    if found is not None:
        return found
    return Path.cwd()


def _observe_repos(
    root: Path, project: str, names: Sequence[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    identities = list(names) or [project]
    current_path = _git_root(root)
    repos: list[dict[str, Any]] = []
    missing: list[str] = []
    configured = _configured_repo_paths(root)
    for identity in identities:
        current_identity = identity == project or identity in {"current", "."}
        path = current_path if current_identity else None
        if path is None and not current_identity:
            path = configured.get(identity)
            if path is None:
                clone = root.joinpath(*_LINKED_CLONE, identity)
                if _is_git_dir(clone):
                    path = clone
        if path is None:
            reason = "non-Git cwd" if current_identity else f"missing repo {identity}"
            missing.append(reason)
            repos.append(
                {
                    "identity": identity,
                    "dirty_paths": [],
                    "incomplete": reason,
                }
            )
            continue
        if not _is_git_dir(path):
            reason = "non-Git cwd" if current_identity else f"missing repo {identity}"
            missing.append(reason)
            repos.append(
                {
                    "identity": identity,
                    "dirty_paths": [],
                    "incomplete": reason,
                }
            )
            continue
        repos.append(_observe_one_repo(identity, path, missing))
    return repos, missing


def _observe_one_repo(identity: str, repo: Path, missing: list[str]) -> dict[str, Any]:
    budget = _Budget(end=time.monotonic() + _REPO_PASS_SECONDS)
    head = _git_text(repo, ["rev-parse", "HEAD"], budget)
    index_tree = _git_text(repo, ["write-tree"], budget)
    dirty: list[dict[str, Any]] = []
    fingerprints: dict[str, tuple[str, str | None]] = {}
    status_error = False
    if not budget.expired():
        try:
            fingerprints = dirty_path_fingerprints(str(repo))
        except Exception:  # noqa: BLE001 - git status failures are incompleteness.
            fingerprints = {}
            status_error = True
    if not fingerprints:
        status = _git_text(
            repo,
            ["status", "--porcelain=v1", "--untracked-files=all"],
            budget,
        )
        if status is None:
            if budget.expired():
                budget.note("repository observation timed out")
            elif (repo / ".git" / "index.lock").exists():
                budget.note("git lock")
            elif status_error:
                budget.note("repository observation failed")
        for raw_line in (status or "").splitlines():
            if len(raw_line.rstrip()) < 4:
                continue
            xy, path_text = raw_line[:2], raw_line[3:]
            fingerprints[normalize_status_path(path_text)] = (xy, None)
    for rel, (xy, content_hash) in sorted(fingerprints.items()):
        if budget.expired():
            budget.note("repository observation timed out")
            break
        if rel.startswith("/") or rel.startswith("../"):
            budget.note("fingerprint dirty path must not be a physical checkout path")
            continue
        dirty.append(_observe_dirty_path(repo, rel, xy, budget, content_hash))
    if budget.missing:
        missing.extend(budget.missing)
    incomplete = budget.missing[0] if budget.missing else None
    if head is None:
        reason = "HEAD unavailable"
        if reason not in missing:
            missing.append(reason)
        incomplete = incomplete or reason
    if index_tree is None:
        reason = "index tree unavailable"
        if reason not in missing:
            missing.append(reason)
        incomplete = incomplete or reason
    return {
        "identity": identity,
        "head": head,
        "index_tree": index_tree,
        "dirty_paths": dirty,
        "incomplete": incomplete,
    }


def _observe_dirty_path(
    repo: Path,
    rel: str,
    xy: str,
    budget: _Budget,
    content_hash: str | None,
) -> dict[str, Any]:
    kind, mode = _path_kind_and_mode(repo, rel, xy)
    payload: dict[str, Any] = {
        "path": rel,
        "status": _status_label(xy),
        "kind": kind,
    }
    if mode is not None:
        payload["mode"] = mode
    if kind == "deleted":
        return payload
    target = repo / rel
    if _symlink_escapes(repo, target):
        payload["incomplete"] = "symlink outside declared root"
        budget.note("symlink outside declared root")
        return payload
    size = 0
    try:
        size = target.lstat().st_size
    except OSError:
        payload["incomplete"] = "unreadable input"
        budget.note("unreadable input")
        return payload
    if size > budget.hash_bytes:
        payload["incomplete"] = "content hashing budget exceeded"
        budget.note("content hashing budget exceeded")
        return payload
    digest = content_hash
    incomplete: str | None = None
    if digest is None:
        digest, incomplete = _hash_path(target, budget)
    else:
        budget.hash_bytes -= size
    if digest is not None:
        payload["content_hash"] = digest
    if incomplete:
        payload["incomplete"] = incomplete
        budget.note(incomplete)
    return payload


def _observe_inputs(
    root: Path, patterns: Sequence[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    missing: list[str] = []
    budget = _Budget(end=time.monotonic() + _INPUT_PASS_SECONDS)
    for pattern in patterns:
        if budget.expired():
            missing.append("input observation timed out")
            records.append(
                {
                    "pattern": pattern,
                    "matches": [],
                    "incomplete": "input observation timed out",
                }
            )
            continue
        matches: list[dict[str, Any]] = []
        incomplete: str | None = None
        found = False
        try:
            candidates = sorted(root.glob(pattern))
        except Exception as exc:  # noqa: BLE001 - glob failure is incompleteness.
            incomplete = f"unreadable input {pattern}: {exc}"
            candidates = []
        for candidate in candidates:
            if budget.expired():
                incomplete = "input observation timed out"
                break
            rel = _relative_to(root, candidate)
            if rel is None:
                continue
            found = True
            if candidate.is_dir() and not candidate.is_symlink():
                continue
            if _symlink_escapes(root, candidate):
                matches.append(
                    {
                        "path": rel,
                        "incomplete": "symlink outside declared root",
                    }
                )
                incomplete = incomplete or "symlink outside declared root"
                continue
            digest, hash_incomplete = _hash_path(candidate, budget)
            match: dict[str, Any] = {"path": rel}
            if digest is not None:
                match["content_hash"] = digest
            if hash_incomplete:
                match["incomplete"] = hash_incomplete
                incomplete = incomplete or hash_incomplete
            matches.append(match)
        if not found and incomplete is None:
            incomplete = f"missing input {pattern}"
        if incomplete:
            missing.append(incomplete)
        records.append(
            {
                "pattern": pattern,
                "matches": matches,
                "incomplete": incomplete,
            }
        )
    return records, missing


def _observe_env(names: Sequence[str]) -> dict[str, str | None]:
    values: dict[str, str | None] = {}
    for name in names:
        raw = os.environ.get(name)
        if raw is None:
            values[name] = None
            continue
        if _SECRET_NAME.match(name):
            values[name] = "<redacted>"
        else:
            values[name] = raw
    return values


def _observe_toolchain(
    spec: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    probes: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    deadline = time.monotonic() + _ALL_PROBES_SECONDS
    for name in sorted(spec):
        argv = spec[name]
        if not isinstance(argv, Sequence) or isinstance(argv, (str, bytes)):
            missing.append(f"malformed toolchain probe {name}")
            probes[name] = {
                "argv": [],
                "incomplete": f"malformed toolchain probe {name}",
            }
            continue
        tokens = [str(part) for part in argv]
        remaining = min(_PROBE_SECONDS, max(0.0, deadline - time.monotonic()))
        if remaining <= 0:
            missing.append("probe timeout")
            probes[name] = {"argv": tokens, "incomplete": "probe timeout"}
            continue
        probes[name] = _run_probe(tokens, remaining, missing)
    return probes, missing


def _run_probe(argv: list[str], timeout: float, missing: list[str]) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        missing.append("absent executable")
        return {"argv": argv, "incomplete": "absent executable"}
    except subprocess.TimeoutExpired:
        missing.append("probe timeout")
        return {"argv": argv, "incomplete": "probe timeout"}
    except Exception as exc:  # noqa: BLE001 - probes fail open.
        reason = f"toolchain probe failed: {exc}"
        missing.append(reason)
        return {"argv": argv, "incomplete": reason}
    blob = (proc.stdout or b"") + (proc.stderr or b"")
    output = blob[:_PROBE_OUTPUT_BYTES].decode("utf-8", "replace")
    return {
        "argv": argv,
        "output": output,
        "exit_code": int(proc.returncode),
    }


def _hash_path(path: Path, budget: _Budget) -> tuple[str | None, str | None]:
    try:
        stat_before = path.lstat()
    except OSError:
        return None, "unreadable input"
    if stat_before.st_size > budget.hash_bytes:
        return None, "too-large input"
    if budget.expired():
        return None, "content hashing timed out"
    digest = hashlib.sha256()
    hashed = 0
    try:
        with path.open("rb") as handle:
            while True:
                if budget.expired():
                    return None, "content hashing timed out"
                chunk = handle.read(1024 * 64)
                if not chunk:
                    break
                hashed += len(chunk)
                if hashed > budget.hash_bytes:
                    return None, "content hashing budget exceeded"
                digest.update(chunk)
        stat_after = path.lstat()
    except OSError:
        return None, "unreadable input"
    if (stat_after.st_mtime_ns, stat_after.st_size) != (
        stat_before.st_mtime_ns,
        stat_before.st_size,
    ):
        return None, "changed during read"
    budget.hash_bytes -= hashed
    return digest.hexdigest(), None


def _path_kind_and_mode(repo: Path, rel: str, xy: str) -> tuple[str, str | None]:
    if "D" in xy:
        return "deleted", None
    full = repo / rel.split(" -> ", 1)[0]
    try:
        st = full.lstat()
    except OSError:
        return "deleted", None
    mode = f"{st.st_mode:o}"
    if Path(full).is_symlink():
        return "symlink", mode
    if full.is_dir():
        return "directory", mode
    if full.is_file():
        kind = "untracked" if "?" in xy else "file"
        return kind, mode
    return "other", mode


def _status_label(xy: str) -> str:
    if "?" in xy:
        return "untracked"
    if "D" in xy:
        return "deleted"
    if "M" in xy or "T" in xy:
        return "modified"
    if "A" in xy:
        return "added"
    stripped = xy.strip()
    return stripped or "modified"


def _git_text(repo: Path, args: Sequence[str], budget: _Budget) -> str | None:
    timeout = budget.remaining()
    if timeout <= 0:
        budget.note("repository observation timed out")
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        budget.note("repository observation timed out")
        return None
    except Exception:  # noqa: BLE001 - git failures are incompleteness.
        return None
    if proc.returncode != 0:
        detail = (proc.stderr or "") + (proc.stdout or "")
        if "index.lock" in detail or "unable to create" in detail.lower():
            budget.note("git lock")
        return None
    return proc.stdout.strip()


def _git_root(start: Path) -> Path | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.0,
        )
    except Exception:  # noqa: BLE001
        return None
    if proc.returncode != 0:
        return None
    text = proc.stdout.strip()
    return Path(text) if text else None


def _is_git_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    return (
        (path / ".git").exists()
        or (path / "HEAD").is_file()
        and (path / "objects").is_dir()
    )


def _configured_repo_paths(root: Path) -> dict[str, Path]:
    config_path = root / "sase" / "sase.yml"
    if not config_path.is_file():
        return {}
    try:
        from sase._yaml_safe import yaml_safe_load

        data = yaml_safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - catalog observation is best-effort.
        return {}
    if not isinstance(data, dict):
        return {}
    repos = data.get("repos") if isinstance(data.get("repos"), dict) else {}
    found: dict[str, Path] = {}
    for kind in ("linked", "sidecar"):
        entries = repos.get(kind) if isinstance(repos, dict) else None
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            raw_path = entry.get("path")
            if isinstance(raw_path, str) and raw_path.strip():
                candidate = (root / raw_path).resolve(strict=False)
                if _is_git_dir(candidate):
                    found[name] = candidate
                    continue
            clone = root.joinpath(*_LINKED_CLONE, name)
            if _is_git_dir(clone):
                found[name] = clone
    return found


def _symlink_escapes(root: Path, path: Path) -> bool:
    try:
        if not path.is_symlink():
            return False
        resolved = path.resolve()
        root_resolved = root.resolve()
    except OSError:
        return True
    return not _is_relative_to(resolved, root_resolved)


def _relative_to(root: Path, path: Path) -> str | None:
    try:
        resolved = path.resolve()
        root_resolved = root.resolve()
        if not _is_relative_to(resolved, root_resolved):
            return None
        return str(resolved.relative_to(root_resolved))
    except OSError:
        return None


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _project_identity() -> str:
    try:
        return load_project_tool_catalog().project
    except ToolCatalogError:
        pass
    except Exception:  # noqa: BLE001
        pass
    return (
        os.environ.get("SASE_PROJECT")
        or os.environ.get("SASE_PROJECT_NAME")
        or "unknown"
    ).strip() or "unknown"


__all__ = [
    "fingerprints_mutated",
    "inc_tool_metric",
    "observe_fingerprint",
]

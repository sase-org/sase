"""Content-addressed bundle store and input-digest render cache.

The store (``<sase home>/instructions/bundles/<sha[:2]>/<sha>.md``) holds
bundle bytes under their sha256; the cache
(``<sase home>/instructions/cache/<key>.json``) holds the compiled section
table so a warm render skips composition. A missing or corrupt entry or store
blob is a miss. This module imports only the standard library at top level so
the cache-hit path never pulls in the heavy composition modules
(``sase.amd``, ``sase.main.init_memory``, ``sase.memory.web``).
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Cache entry schema version (bumped when the entry layout changes).
CACHE_ENTRY_VERSION = 1

#: Maximum retained cache entries; the store is not pruned in E2.
MAX_CACHE_ENTRIES = 512

#: Task-type entry-point group whose distributions feed the key.
TASK_TYPE_ENTRY_POINT_GROUP = "sase_task_types"

#: Code packages fingerprinted (path, mtime, size per ``.py`` file).
CODE_PACKAGES = (
    "sase.instructions",
    "sase.amd",
    "sase.memory",
    "sase.main.init_memory",
)

#: Memory globs hashed for each root (canonical plus the legacy layout).
MEMORY_GLOBS = ("sase/memory", "memory")

#: Project-root singleton files hashed by content (class label, filename).
PROJECT_SINGLETONS = (
    ("project-agents-md", "AGENTS.md"),
    ("project-config", "sase.yml"),
    ("project-config-alt", "sase/sase.yml"),
)

#: Home-root singleton files hashed by content.
HOME_SINGLETONS = (("home-agents-md", "AGENTS.md"),)

#: Template override keys read from a project config mapping.
_TEMPLATE_OVERRIDE_KEYS = (
    ("memory", "sase_template"),
    ("memory_sase_template",),
)

#: Packaged contract template resource.
_PACKAGE_TEMPLATE_RESOURCE = ("templates", "memory-sase.template.md")

#: Packaged helper template resource.
_HELPER_TEMPLATE_RESOURCE = ("templates", "claude_helper_instructions.md")


@dataclass(frozen=True)
class _CacheKeyInputs:
    """Resolved inputs hashed into one render-cache key."""

    compiler_version: int
    sase_version: str
    actor: str
    mode: str
    provider: str
    project: str | None
    directive_file: str
    directive_sha256: str
    files: tuple[tuple[str, str], ...]
    distributions: tuple[tuple[str, str], ...]
    code: tuple[tuple[str, str], ...]


def instructions_home() -> Path:
    """Return the ``instructions/`` home holding the store and cache.

    ``SASE_INSTRUCTIONS_HOME`` overrides the location (the tests use this as
    their seam); otherwise the store and cache live under the SASE state
    home (``sase_home()``, ``~/.sase`` by default).
    """
    override = os.environ.get("SASE_INSTRUCTIONS_HOME")
    if override:
        return Path(override)
    from sase.core.paths import sase_home

    return sase_home() / "instructions"


def bundle_store_path(home: Path, sha256: str) -> Path:
    """Return the store path for bundle *sha256* under *home*."""
    return home / "bundles" / sha256[:2] / f"{sha256}.md"


def _cache_entry_path(home: Path, key: str) -> Path:
    """Return the cache entry path for *key* under *home*."""
    return home / "cache" / f"{key}.json"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str | None:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError:
        return None


def _package_dir(package: str) -> Path | None:
    try:
        spec = importlib.util.find_spec(package)
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.submodule_search_locations:
        return None
    return Path(spec.submodule_search_locations[0])


def _code_fingerprint() -> tuple[tuple[str, str], ...]:
    """Return sorted ``(label, "mtime_ns:size")`` for every package ``.py``."""
    entries: list[tuple[str, str]] = []
    for package in CODE_PACKAGES:
        directory = _package_dir(package)
        if directory is None or not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.py")):
            try:
                relative = path.relative_to(directory).as_posix()
                stat = path.stat()
            except OSError:
                continue
            entries.append(
                (f"code:{package}/{relative}", f"{stat.st_mtime_ns}:{stat.st_size}")
            )
    return tuple(sorted(entries))


def _memory_files(root: Path, scope: str) -> list[tuple[str, str]]:
    """Return sorted ``(label, content-sha256)`` for root memory files."""
    entries: list[tuple[str, str]] = []
    for glob in MEMORY_GLOBS:
        base = root / glob
        if not base.is_dir():
            continue
        try:
            paths = sorted(
                path
                for path in base.rglob("*")
                if path.is_file() and not path.is_symlink()
            )
        except OSError:
            continue
        for path in paths:
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                continue
            digest = _sha256_file(path)
            if digest is None:
                continue
            entries.append((f"{scope}-memory:{relative}", digest))
    return sorted(entries)


def _singleton_files(
    root: Path, singletons: tuple[tuple[str, str], ...]
) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for label, filename in singletons:
        digest = _sha256_file(root / filename)
        if digest is not None:
            entries.append((label, digest))
    return entries


def _read_yaml_mapping(path: Path) -> dict[str, Any] | None:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _declared_template_override(project_root: Path) -> Path | None:
    """Return the config-declared contract template override, if any."""
    for filename in ("sase/sase.yml", "sase.yml"):
        config = project_root / filename
        if not config.is_file():
            continue
        data = _read_yaml_mapping(config)
        if not data:
            continue
        for keys in _TEMPLATE_OVERRIDE_KEYS:
            node: Any = data
            for key in keys:
                if not isinstance(node, dict):
                    node = None
                    break
                node = node.get(key)
            if isinstance(node, str) and node.strip():
                candidate = (project_root / node.strip()).resolve(strict=False)
                return candidate
    return None


def _global_config_files() -> list[tuple[str, str]]:
    """Return ``(label, content-sha256)`` for existing global config files."""
    from sase.config.core import CHEZMOI_HOME, CONFIG_DIR

    entries: list[tuple[str, str]] = []
    candidates: list[Path] = [CONFIG_DIR / "sase.yml"]
    try:
        entries_overlays = sorted(CONFIG_DIR.glob("sase_*.yml"))
    except OSError:
        entries_overlays = []
    candidates.extend(path for path in entries_overlays if path.name != "sase.yml")
    chezmoi_config = CHEZMOI_HOME / "dot_config" / "sase"
    candidates.append(chezmoi_config / "sase.yml")
    try:
        candidates.extend(sorted(chezmoi_config.glob("sase_*.yml")))
    except OSError:
        pass
    seen: set[str] = set()
    for path in candidates:
        digest = _sha256_file(path)
        if digest is None:
            continue
        label = f"global-config:{path.name}"
        if label in seen:
            continue
        seen.add(label)
        entries.append((label, digest))
    return sorted(entries)


def _resource_file(package: str, resource: tuple[str, ...]) -> Path | None:
    directory = _package_dir(package)
    if directory is None:
        return None
    candidate = directory.joinpath(*resource)
    return candidate if candidate.is_file() else None


def _task_type_distributions() -> tuple[tuple[str, str], ...]:
    """Return sorted ``(label, "name@version")`` for task-type distributions."""
    entries: list[tuple[str, str]] = []
    try:
        entry_points = importlib.metadata.entry_points(
            group=TASK_TYPE_ENTRY_POINT_GROUP
        )
    except Exception:
        return ()
    for entry_point in entry_points:
        dist = entry_point.dist
        if dist is None:
            continue
        try:
            name = dist.metadata["Name"] or "unknown"
            version = dist.version or "unknown"
        except Exception:
            continue
        entries.append((f"task-type-dist:{name}", f"{name}@{version}"))
    return tuple(sorted(set(entries)))


def _sase_version() -> str:
    try:
        import sase

        return str(sase.__version__)
    except Exception:
        return "unknown"


def collect_key_inputs(
    *,
    compiler_version: int,
    actor: str,
    mode: str,
    provider: str,
    project: str | None,
    project_root: Path,
    home_root: Path,
) -> _CacheKeyInputs:
    """Enumerate every key input class for one render (no heavy imports)."""
    files: list[tuple[str, str]] = []
    files.extend(_memory_files(project_root, "project"))
    files.extend(_memory_files(home_root, "home"))
    files.extend(_singleton_files(project_root, PROJECT_SINGLETONS))
    files.extend(_singleton_files(home_root, HOME_SINGLETONS))
    files.extend(_global_config_files())
    package_template = _resource_file(
        "sase.main.init_memory", _PACKAGE_TEMPLATE_RESOURCE
    )
    if package_template is not None:
        digest = _sha256_file(package_template)
        if digest is not None:
            files.append(("package-template", digest))
    helper_template = _resource_file("sase.llm_provider", _HELPER_TEMPLATE_RESOURCE)
    helper_digest: str | None = None
    if helper_template is not None:
        helper_digest = _sha256_file(helper_template)
        if helper_digest is not None:
            files.append(("helper-template", helper_digest))
    override = _declared_template_override(project_root)
    override_digest: str | None = None
    if override is not None:
        override_digest = _sha256_file(override)
        if override_digest is not None:
            files.append(("template-override", override_digest))
    adapter_file = _package_dir("sase.llm_provider")
    directive_label = f"provider-directive:{provider}"
    directive_digest = ""
    if adapter_file is not None:
        for name in (
            provider,
            provider.replace("-", "_"),
        ):
            candidate = adapter_file / f"{name}.py"
            if name == "muse":
                candidate = adapter_file / "_muse_directive.py"
            digest = _sha256_file(candidate)
            if digest is not None:
                directive_digest = digest
                break
    return _CacheKeyInputs(
        compiler_version=compiler_version,
        sase_version=_sase_version(),
        actor=actor,
        mode=mode,
        provider=provider,
        project=project,
        directive_file=directive_label,
        directive_sha256=directive_digest,
        files=tuple(sorted(files)),
        distributions=_task_type_distributions(),
        code=_code_fingerprint(),
    )


def compute_cache_key(inputs: _CacheKeyInputs) -> str:
    """Return the sha256 cache key for resolved *inputs*."""
    canonical = json.dumps(
        {
            "cache_entry": CACHE_ENTRY_VERSION,
            "code": [list(part) for part in inputs.code],
            "compiler": inputs.compiler_version,
            "directive": [inputs.directive_file, inputs.directive_sha256],
            "dists": [list(part) for part in inputs.distributions],
            "facts": {
                "actor": inputs.actor,
                "mode": inputs.mode,
                "project": inputs.project or "",
                "provider": inputs.provider,
            },
            "files": [list(part) for part in inputs.files],
            "sase": inputs.sase_version,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256_bytes(canonical.encode("utf-8"))


def read_store_blob(home: Path, sha256: str) -> str | None:
    """Return store bundle text for *sha256*, or null on miss/corruption."""
    path = bundle_store_path(home, sha256)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if _sha256_bytes(text.encode("utf-8")) != sha256:
        return None
    return text


def write_store_blob(home: Path, sha256: str, text: str) -> Path:
    """Write bundle *text* to the store once (mode 0444); skip if present."""
    path = bundle_store_path(home, sha256)
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".tmp-{os.getpid()}-{time.time_ns()}"
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.chmod(0o444)
        try:
            os.replace(tmp, path)
        except FileExistsError:
            pass
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
    try:
        path.chmod(0o444)
    except OSError:
        pass
    return path


def read_cache_entry(home: Path, key: str) -> dict[str, Any] | None:
    """Return the cache entry for *key*, or null when missing/corrupt."""
    path = _cache_entry_path(home, key)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        entry = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(entry, dict):
        return None
    if entry.get("version") != CACHE_ENTRY_VERSION:
        return None
    sections = entry.get("sections")
    bundle_sha256 = entry.get("bundle_sha256")
    if not isinstance(sections, list) or not isinstance(bundle_sha256, str):
        return None
    if not all(isinstance(section, dict) for section in sections):
        return None
    return entry


def write_cache_entry(home: Path, key: str, entry: Mapping[str, Any]) -> Path:
    """Write *entry* atomically and prune to the newest entries."""
    cache_dir = home / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_entry_path(home, key)
    payload = dict(entry)
    payload["version"] = CACHE_ENTRY_VERSION
    tmp = cache_dir / f".tmp-{os.getpid()}-{time.time_ns()}"
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    _prune_cache_entries(home)
    return path


def _prune_cache_entries(home: Path, *, limit: int = MAX_CACHE_ENTRIES) -> int:
    """Drop the oldest cache entries beyond *limit*; return removals."""
    cache_dir = home / "cache"
    try:
        entries = [
            path
            for path in cache_dir.iterdir()
            if path.is_file()
            and path.suffix == ".json"
            and not path.name.startswith(".tmp-")
        ]
    except OSError:
        return 0
    if len(entries) <= limit:
        return 0

    def _mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    entries.sort(key=_mtime)
    removed = 0
    for stale in entries[: len(entries) - limit]:
        try:
            stale.unlink()
            removed += 1
        except OSError:
            continue
    return removed


__all__ = [
    "CACHE_ENTRY_VERSION",
    "CODE_PACKAGES",
    "MAX_CACHE_ENTRIES",
    "TASK_TYPE_ENTRY_POINT_GROUP",
    "_CacheKeyInputs",
    "bundle_store_path",
    "_cache_entry_path",
    "collect_key_inputs",
    "compute_cache_key",
    "instructions_home",
    "_prune_cache_entries",
    "read_cache_entry",
    "read_store_blob",
    "write_cache_entry",
    "write_store_blob",
]

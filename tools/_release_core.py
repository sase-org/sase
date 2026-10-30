#!/usr/bin/env python3
"""Shared core-ensure rule for exact ``sase-core-rs`` pins.

Pick ``X.Y.Z`` as the newest *complete* published ``sase-core-rs`` whose tag
``vX.Y.Z`` contains the candidate's ``sase-core-revision.txt`` commit.

Complete means every ``EXPECTED_DIST_SUFFIXES`` file from sase-core's
``release-plz.yml`` *at that tag* is present on PyPI and none of those files is
yanked. The suffix set is never copied into this repo.

Containment is GitHub compare ``<pin>...vX.Y.Z`` in ``{ahead, identical}``,
with a local-git ancestor fallback when GitHub is unreachable.

Returns ``Pinned`` or ``CoreLag``. Unreadable input raises ``CoreEnsureError``
and is never a pick.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REVISION_FILE = REPO_ROOT / "sase-core-revision.txt"
DEFAULT_SASE_CORE_DIR = Path(
    os.environ.get("SASE_CORE_DIR", REPO_ROOT.parent / "sase-core")
)
CORE_REPO = "sase-org/sase-core"
DEPENDENCY_NAME = "sase-core-rs"
FILENAME_STEM = "sase_core_rs"
WORKFLOW_PATH = ".github/workflows/release-plz.yml"
PYPI_URL = f"https://pypi.org/pypi/{DEPENDENCY_NAME}/json"
PYPI_TIMEOUT_SECONDS = 5.0
PYPI_ATTEMPTS = 3
GITHUB_TIMEOUT_SECONDS = 10.0
_TRANSIENT_HTTP_CODES = frozenset({408, 429, 500, 502, 503, 504})
_VERSION_RE = re.compile(r"^\d+(?:\.\d+)*$")
_PIN_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
_SUFFIXES_BLOCK_RE = re.compile(
    r"(?m)^([ \t]*)EXPECTED_DIST_SUFFIXES: \|(?:\n((?:\1[ \t]+[^\n]*(?:\n|$))*))?"
)
_CONTAINING_STATUSES = frozenset({"ahead", "identical"})
_NON_CONTAINING_STATUSES = frozenset({"behind", "diverged"})
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

UrlOpenFn = Callable[..., Any]
SleepFn = Callable[[float], None]
CompareFn = Callable[[str, str], str]
WorkflowFn = Callable[[str], str]
GitContainsFn = Callable[[str, str], bool]
PypiFetcher = Callable[[], dict[str, object]]


class CoreEnsureError(ValueError):
    """Raised when an input is unreadable. Never a version pick."""


class CoreEnsureNetworkError(CoreEnsureError):
    """Transient network failure that may fall back to local git."""


@dataclass(frozen=True)
class ParsedVersion:
    raw: str
    parts: tuple[int, ...]


@dataclass(frozen=True)
class Pinned:
    """Newest complete published core whose tag contains the source pin."""

    version: str
    files: tuple[str, ...]

    def typed(self) -> str:
        return f"PINNED({self.version}, files={','.join(self.files)})"


@dataclass(frozen=True)
class CoreLag:
    """No complete published core contains the source pin."""

    pin: str
    newest_complete: str | None

    def typed(self) -> str:
        newest = self.newest_complete if self.newest_complete is not None else "none"
        return f"CORE_LAG(pin={self.pin}, newest_complete={newest})"


CoreEnsureResult = Pinned | CoreLag


def parse_version(value: object, label: str = "version") -> ParsedVersion:
    if not isinstance(value, str) or not _VERSION_RE.fullmatch(value.strip()):
        raise CoreEnsureError(
            f"unsupported {label} {value!r}; expected a numeric dot-separated version"
        )
    raw = value.strip()
    return ParsedVersion(raw=raw, parts=tuple(int(part) for part in raw.split(".")))


def read_source_pin(path: Path = DEFAULT_REVISION_FILE) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CoreEnsureError(f"unreadable source pin {path}: {exc}") from exc
    pin = text.strip().splitlines()[0].strip() if text.strip() else ""
    if not _PIN_RE.fullmatch(pin):
        raise CoreEnsureError(f"unreadable source pin {path}: {pin!r}")
    return pin


def parse_expected_suffixes(workflow_text: str) -> tuple[str, ...]:
    match = _SUFFIXES_BLOCK_RE.search(workflow_text)
    if match is None:
        raise CoreEnsureError(f"cannot find EXPECTED_DIST_SUFFIXES in {WORKFLOW_PATH}")
    suffixes = (match.group(2) or "").split()
    if not suffixes:
        raise CoreEnsureError(f"EXPECTED_DIST_SUFFIXES in {WORKFLOW_PATH} is empty")
    if len(suffixes) != len(set(suffixes)):
        raise CoreEnsureError(
            f"EXPECTED_DIST_SUFFIXES in {WORKFLOW_PATH} lists a duplicate: {suffixes}"
        )
    return tuple(suffixes)


def _stem(version: str) -> str:
    return f"{FILENAME_STEM}-{version}"


def matches_suffix(filename: str, version: str, suffix: str) -> bool:
    """Match a core dist the way sase-core's ``pypi_release_files.matches`` does.

    A wheel entry names one compressed platform tag, not the file's literal
    tail, so maturin's tag order does not matter. A ``.whl`` file matches a
    ``.whl`` suffix when one of its dot-separated platform tags plus ``".whl"``
    ends with the suffix (with an exact match on the distribution name and
    version). Anything else (the sdist) matches only ``stem(version) + suffix``.
    """
    if filename.endswith(".whl"):
        if not suffix.endswith(".whl"):
            return False
        stemmed = filename[: -len(".whl")]
        parts = stemmed.split("-")
        if len(parts) == 6:
            name, file_version, _build, _py, _abi, plat = parts
        elif len(parts) == 5:
            name, file_version, _py, _abi, plat = parts
        else:
            return False
        if name != FILENAME_STEM or file_version != version:
            return False
        return any((tag + ".whl").endswith(suffix) for tag in plat.split("."))
    return filename == _stem(version) + suffix


def _file_is_yanked(file_info: Mapping[str, object]) -> bool:
    return bool(file_info.get("yanked"))


def complete_files_for_version(
    version: str,
    files: object,
    suffixes: tuple[str, ...],
) -> tuple[str, ...] | None:
    """Return matching non-yanked filenames, or ``None`` if the version is incomplete."""

    if not isinstance(files, list):
        return None
    entries = [file_info for file_info in files if isinstance(file_info, dict)]
    matched: list[str] = []
    for suffix in suffixes:
        candidates = [
            file_info
            for file_info in entries
            if isinstance(file_info.get("filename"), str)
            and matches_suffix(str(file_info["filename"]), version, suffix)
        ]
        live = [
            str(file_info["filename"])
            for file_info in candidates
            if not _file_is_yanked(file_info)
        ]
        if not live:
            return None
        matched.append(live[0])
    return tuple(matched)


def fetch_pypi_metadata(
    *,
    urlopen_fn: UrlOpenFn | None = None,
    sleep_fn: SleepFn = time.sleep,
    attempts: int = PYPI_ATTEMPTS,
) -> dict[str, object]:
    opener = urlopen_fn or urllib.request.urlopen
    delay = 0.5
    last_error: str | None = None
    for attempt in range(1, attempts + 1):
        try:
            with opener(PYPI_URL, timeout=PYPI_TIMEOUT_SECONDS) as response:  # noqa: S310
                payload = response.read()
            loaded = json.loads(payload.decode("utf-8"))
            if not isinstance(loaded, dict):
                raise CoreEnsureError("PyPI response root is not a JSON object")
            return loaded
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
            if exc.code not in _TRANSIENT_HTTP_CODES:
                break
        except (OSError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = str(exc)
        if attempt < attempts:
            sleep_fn(delay)
            delay *= 2
    raise CoreEnsureError(
        f"could not read {DEPENDENCY_NAME} releases from PyPI: "
        f"{last_error or 'unknown error'}"
    )


def _release_map(metadata: dict[str, object]) -> dict[str, object]:
    releases = metadata.get("releases")
    if not isinstance(releases, dict):
        raise CoreEnsureError("PyPI response is missing a releases object")
    return releases


def _github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "sase-release-core",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = (
        os.environ.get("GH_TOKEN")
        or os.environ.get("GITHUB_TOKEN")
        or os.environ.get("SASE_RELEASE_TOKEN")
    )
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _gh_env() -> dict[str, str]:
    """Force ``gh api`` to emit plain JSON even when FORCE_COLOR is inherited."""

    env = dict(os.environ)
    env["NO_COLOR"] = "1"
    env["CLICOLOR"] = "0"
    env["CLICOLOR_FORCE"] = "0"
    env["FORCE_COLOR"] = "0"
    env.pop("GH_FORCE_TTY", None)
    return env


def _parse_json_object(text: str) -> dict[str, object] | None:
    stripped = _ANSI_RE.sub("", text).strip()
    if not stripped:
        return None
    try:
        loaded = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _github_api(
    path: str,
    *,
    urlopen_fn: UrlOpenFn | None = None,
) -> dict[str, object]:
    gh_result = subprocess.run(
        ["gh", "api", path],
        check=False,
        capture_output=True,
        text=True,
        env=_gh_env(),
    )
    if gh_result.returncode == 0:
        loaded = _parse_json_object(gh_result.stdout)
        if loaded is not None:
            return loaded
    return _github_api_urllib(path, urlopen_fn=urlopen_fn)


def _github_api_urllib(
    path: str,
    *,
    urlopen_fn: UrlOpenFn | None = None,
) -> dict[str, object]:
    opener = urlopen_fn or urllib.request.urlopen
    url = f"https://api.github.com/{path}"
    request = urllib.request.Request(url, headers=_github_headers())
    try:
        with opener(request, timeout=GITHUB_TIMEOUT_SECONDS) as response:  # noqa: S310
            payload = response.read()
        loaded = json.loads(payload.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in _TRANSIENT_HTTP_CODES:
            raise CoreEnsureNetworkError(
                f"unreadable GitHub API {path}: HTTP {exc.code}"
            ) from exc
        raise CoreEnsureError(f"unreadable GitHub API {path}: HTTP {exc.code}") from exc
    except (OSError, TimeoutError, json.JSONDecodeError) as exc:
        raise CoreEnsureNetworkError(f"unreadable GitHub API {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise CoreEnsureError(f"unreadable GitHub API {path}: not a JSON object")
    return loaded


def github_compare_status(
    pin: str,
    version: str,
    *,
    urlopen_fn: UrlOpenFn | None = None,
) -> str:
    payload = _github_api(
        f"repos/{CORE_REPO}/compare/{pin}...v{version}",
        urlopen_fn=urlopen_fn,
    )
    status = payload.get("status")
    if not isinstance(status, str) or not status.strip():
        raise CoreEnsureError(f"unreadable compare {pin}...v{version}: missing status")
    return status.strip().lower()


def github_workflow_text(
    version: str,
    *,
    urlopen_fn: UrlOpenFn | None = None,
) -> str:
    payload = _github_api(
        f"repos/{CORE_REPO}/contents/{WORKFLOW_PATH}?ref=v{version}",
        urlopen_fn=urlopen_fn,
    )
    content = payload.get("content")
    encoding = payload.get("encoding")
    if not isinstance(content, str) or encoding != "base64":
        raise CoreEnsureError(
            f"unreadable {WORKFLOW_PATH} at v{version}: missing base64 content"
        )
    try:
        return base64.b64decode(content, validate=False).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise CoreEnsureError(
            f"unreadable {WORKFLOW_PATH} at v{version}: {exc}"
        ) from exc


def git_contains_pin(
    pin: str,
    version: str,
    git_dir: Path,
) -> bool:
    if not git_dir.is_dir():
        raise CoreEnsureError(
            f"unreadable compare {pin}...v{version}: local git dir {git_dir} is missing"
        )
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", pin, f"v{version}"],
        cwd=git_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    detail = (result.stderr or result.stdout).strip()
    raise CoreEnsureError(
        f"unreadable compare {pin}...v{version} via local git: "
        f"{detail or result.returncode}"
    )


def git_workflow_text(version: str, git_dir: Path) -> str:
    if not git_dir.is_dir():
        raise CoreEnsureError(
            f"unreadable {WORKFLOW_PATH} at v{version}: local git dir {git_dir} is missing"
        )
    result = subprocess.run(
        ["git", "show", f"v{version}:{WORKFLOW_PATH}"],
        cwd=git_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise CoreEnsureError(
            f"unreadable {WORKFLOW_PATH} at v{version} via local git: "
            f"{detail or result.returncode}"
        )
    return result.stdout


def _contains_pin(
    pin: str,
    version: str,
    *,
    compare_fn: CompareFn | None,
    git_contains_fn: GitContainsFn | None,
    git_dir: Path,
    urlopen_fn: UrlOpenFn | None,
) -> bool:
    try:
        if compare_fn is not None:
            status = compare_fn(pin, version)
        else:
            status = github_compare_status(pin, version, urlopen_fn=urlopen_fn)
        return _status_contains(status, pin, version)
    except CoreEnsureNetworkError:
        contains_fn = git_contains_fn or (
            lambda candidate_pin, candidate_version: git_contains_pin(
                candidate_pin, candidate_version, git_dir
            )
        )
        return contains_fn(pin, version)


def _status_contains(status: str, pin: str, version: str) -> bool:
    normalized = status.strip().lower()
    if normalized in _CONTAINING_STATUSES:
        return True
    if normalized in _NON_CONTAINING_STATUSES:
        return False
    raise CoreEnsureError(
        f"unreadable compare {pin}...v{version}: unknown status {status!r}"
    )


def _workflow_at_tag(
    version: str,
    *,
    workflow_fn: WorkflowFn | None,
    git_dir: Path,
    urlopen_fn: UrlOpenFn | None,
) -> str:
    if workflow_fn is not None:
        return workflow_fn(version)
    try:
        return github_workflow_text(version, urlopen_fn=urlopen_fn)
    except CoreEnsureNetworkError:
        return git_workflow_text(version, git_dir)


def _numeric_versions(releases: dict[str, object]) -> list[ParsedVersion]:
    versions: list[ParsedVersion] = []
    for raw in releases:
        if not isinstance(raw, str) or not _VERSION_RE.fullmatch(raw):
            continue
        versions.append(parse_version(raw, "PyPI release"))
    versions.sort(key=lambda version: version.parts, reverse=True)
    return versions


def ensure_core(
    pin: str,
    *,
    pypi_metadata: dict[str, object] | None = None,
    pypi_fetcher: PypiFetcher | None = None,
    compare_fn: CompareFn | None = None,
    workflow_fn: WorkflowFn | None = None,
    git_contains_fn: GitContainsFn | None = None,
    git_dir: Path | None = None,
    urlopen_fn: UrlOpenFn | None = None,
) -> CoreEnsureResult:
    """Return ``Pinned`` or ``CoreLag`` for *pin*. Unreadable input raises."""

    if not _PIN_RE.fullmatch(pin.strip() if isinstance(pin, str) else ""):
        raise CoreEnsureError(f"unreadable source pin: {pin!r}")
    pin = pin.strip()
    core_dir = git_dir if git_dir is not None else DEFAULT_SASE_CORE_DIR
    if pypi_metadata is not None:
        metadata = pypi_metadata
    elif pypi_fetcher is not None:
        metadata = pypi_fetcher()
    else:
        metadata = fetch_pypi_metadata(urlopen_fn=urlopen_fn)
    releases = _release_map(metadata)
    newest_complete: str | None = None
    for version in _numeric_versions(releases):
        files = releases.get(version.raw)
        if not isinstance(files, list) or not files:
            continue
        workflow_text = _workflow_at_tag(
            version.raw,
            workflow_fn=workflow_fn,
            git_dir=core_dir,
            urlopen_fn=urlopen_fn,
        )
        if _SUFFIXES_BLOCK_RE.search(workflow_text) is None:
            # Tags from before the completeness contract cannot be proven
            # complete; skip them rather than raising, so CORE_LAG stays
            # reachable when no newer complete tag contains the pin.
            continue
        suffixes = parse_expected_suffixes(workflow_text)
        complete = complete_files_for_version(version.raw, files, suffixes)
        if complete is None:
            continue
        if newest_complete is None:
            newest_complete = version.raw
        if _contains_pin(
            pin,
            version.raw,
            compare_fn=compare_fn,
            git_contains_fn=git_contains_fn,
            git_dir=core_dir,
            urlopen_fn=urlopen_fn,
        ):
            return Pinned(version=version.raw, files=complete)
    return CoreLag(pin=pin, newest_complete=newest_complete)

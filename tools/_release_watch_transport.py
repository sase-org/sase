#!/usr/bin/env python3
"""Bounded, injectable, read-only transports for the release steward.

The client deliberately exposes only reads. GitHub pagination is handled by
``gh api --paginate --slurp`` and PyPI reads use the public JSON API. Callers
must provide explicit time bounds when asking for history through the facts
reader; transport methods never maintain state between ticks.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib.parse import urlencode


GH_TIMEOUT_SECONDS = 20.0
PYPI_TIMEOUT_SECONDS = 15.0
PYPI_ATTEMPTS = 3


class ReleaseTransportError(RuntimeError):
    """A bounded remote read failed or returned malformed data."""

    def __init__(self, source: str, message: str) -> None:
        self.source = source
        super().__init__(f"{source}: {message}")


Runner = Callable[..., subprocess.CompletedProcess[str]]
UrlOpen = Callable[..., Any]
Sleep = Callable[[float], None]


def run_process(
    argv: Sequence[str],
    *,
    timeout: float,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one argument-vector command with a hard timeout."""
    merged_env = None if env is None else {**os.environ, **env}
    return subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        env=merged_env,
    )


class GithubTransport:
    """Read GitHub REST resources through ``gh`` with pagination and timeouts."""

    def __init__(
        self,
        repo: str,
        *,
        runner: Runner = run_process,
        executable: str = "gh",
        timeout: float = GH_TIMEOUT_SECONDS,
    ) -> None:
        self.repo = repo
        self.runner = runner
        self.executable = executable
        self.timeout = timeout

    def _env(self) -> dict[str, str]:
        return {
            "GH_REPO": self.repo,
            "GH_PROMPT_DISABLED": "1",
            "GH_NO_UPDATE_NOTIFIER": "1",
            "GH_FORCE_TTY": "0",
            "NO_COLOR": "1",
            "CLICOLOR": "0",
            "CLICOLOR_FORCE": "0",
            "FORCE_COLOR": "0",
        }

    @staticmethod
    def _with_query(path: str, params: Mapping[str, object] | None) -> str:
        if not params:
            return path
        suffix = urlencode([(key, str(value)) for key, value in sorted(params.items())])
        return f"{path}{'&' if '?' in path else '?'}{suffix}"

    def _call(
        self,
        path: str,
        *,
        paginate: bool = False,
        accept: str = "application/vnd.github+json",
    ) -> str:
        argv = [self.executable, "api"]
        if paginate:
            argv.extend(["--paginate", "--slurp"])
        argv.extend(["--header", f"Accept: {accept}", path])
        try:
            result = self.runner(argv, timeout=self.timeout, env=self._env())
        except (OSError, subprocess.SubprocessError) as exc:
            raise ReleaseTransportError(path, f"GitHub read failed: {exc}") from exc
        if result.returncode:
            details = (result.stderr or result.stdout or "").strip().replace("\n", " ")
            raise ReleaseTransportError(
                path,
                f"gh api exited {result.returncode}"
                + (f": {details[:400]}" if details else ""),
            )
        return result.stdout or ""

    def json(
        self,
        path: str,
        *,
        params: Mapping[str, object] | None = None,
    ) -> object:
        """Read one JSON resource. Errors remain attributed to the endpoint."""
        endpoint = self._with_query(path, params)
        raw = self._call(endpoint)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ReleaseTransportError(
                endpoint, f"GitHub returned malformed JSON at byte {exc.pos}"
            ) from exc

    def pages(
        self,
        path: str,
        *,
        params: Mapping[str, object] | None = None,
    ) -> list[object]:
        """Read and flatten every page of a GitHub JSON list endpoint."""
        query = {"page": 1, "per_page": 100, **(params or {})}
        endpoint = self._with_query(path, query)
        raw = self._call(endpoint, paginate=True)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ReleaseTransportError(
                endpoint, f"GitHub returned malformed paginated JSON at byte {exc.pos}"
            ) from exc
        if payload == []:
            return []
        if not isinstance(payload, list):
            raise ReleaseTransportError(endpoint, "paginated response must be a list")
        # --slurp wraps each API page in one list or object. Reject a raw page
        # here: accepting it would hide a broken pagination invocation.
        page_types = {type(page) for page in payload}
        if page_types - {list, dict} or len(page_types) > 1:
            raise ReleaseTransportError(
                endpoint, "paginated response must contain list or object pages"
            )
        if page_types == {list}:
            return [item for page in payload for item in page]
        return payload

    def asset_json(self, asset_id: int, *, source: str) -> object:
        """Download a JSON release asset without using a write-capable command."""
        path = f"repos/{self.repo}/releases/assets/{asset_id}"
        raw = self._call(path, accept="application/octet-stream")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ReleaseTransportError(
                source, f"release asset is not valid JSON at byte {exc.pos}"
            ) from exc


class PypiTransport:
    """Fetch complete, read-only PyPI project inventories with bounded retries."""

    def __init__(
        self,
        *,
        opener: UrlOpen | None = None,
        timeout: float = PYPI_TIMEOUT_SECONDS,
        attempts: int = PYPI_ATTEMPTS,
        sleep: Sleep = time.sleep,
    ) -> None:
        self.opener = opener or urllib.request.urlopen
        self.timeout = timeout
        self.attempts = max(1, attempts)
        self.sleep = sleep

    def project(self, name: str) -> object:
        """Return the full PyPI JSON response for *name*."""
        project = name.lower().replace("_", "-")
        url = f"https://pypi.org/pypi/{project}/json"
        delay = 0.25
        last_error = "unknown error"
        for attempt in range(1, self.attempts + 1):
            request = urllib.request.Request(
                url, headers={"User-Agent": "sase-release-steward/1"}
            )
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    raw = response.read()
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ReleaseTransportError(
                        url, "PyPI response root is not an object"
                    )
                return payload
            except urllib.error.HTTPError as exc:
                last_error = f"HTTP {exc.code}"
                if exc.code not in {408, 429, 500, 502, 503, 504}:
                    break
            except (
                OSError,
                TimeoutError,
                UnicodeDecodeError,
                json.JSONDecodeError,
            ) as exc:
                last_error = str(exc)
            if attempt < self.attempts:
                self.sleep(delay)
                delay = min(delay * 2, 2.0)
        raise ReleaseTransportError(url, last_error)


__all__ = [
    "GH_TIMEOUT_SECONDS",
    "PYPI_ATTEMPTS",
    "PYPI_TIMEOUT_SECONDS",
    "GithubTransport",
    "PypiTransport",
    "ReleaseTransportError",
    "run_process",
]

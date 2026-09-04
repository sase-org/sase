"""Read untrusted agents payloads from one fetched commit without checkout."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
from typing import Any

from sase.agents_sync.git import GitRunner, noninteractive_git_env, run_git
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.v2_io import validate_relative_path
from sase.sdd._git import sdd_git_command

_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class _CatFileStreamClosed(AgentsSyncFormatError):
    """The ``git cat-file`` pipe ended before a framed object was complete."""

    def __init__(self) -> None:
        super().__init__("git cat-file batch stream closed")


@dataclass(frozen=True, slots=True)
class FetchedAgentsCommit:
    """An exact local remote-tracking ref and the commit it resolved to."""

    ref: str
    sha: str


class LocalGitObjectReader:
    """Injectable local-only Git object reader.

    Every command is explicitly marked non-network. The reader never invokes
    checkout-like commands and therefore cannot alter HEAD, the index, or the
    sidecar worktree.
    """

    def __init__(
        self,
        repo: Path,
        *,
        git_runner: GitRunner = run_git,
    ) -> None:
        self.repo = repo
        self.git_runner = git_runner
        self._batch: _CatFileBatch | None = None

    def close(self) -> None:
        if self._batch is not None:
            self._batch.close()
            self._batch = None

    def __enter__(self) -> LocalGitObjectReader:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def resolve_fetched_commit(self) -> FetchedAgentsCommit:
        upstream = self.git_runner(
            self.repo,
            ["rev-parse", "--symbolic-full-name", "@{upstream}"],
            op="agents_sync.object_upstream_ref",
        )
        if upstream.returncode != 0:
            raise AgentsSyncFormatError(
                _git_error("agents sidecar has no configured upstream", upstream)
            )
        ref = upstream.stdout.strip()
        if not _valid_fetched_ref(ref):
            raise AgentsSyncFormatError(f"unsafe fetched upstream ref: {ref!r}")
        resolved = self.git_runner(
            self.repo,
            ["rev-parse", "--verify", f"{ref}^{{commit}}"],
            op="agents_sync.object_upstream_sha",
        )
        sha = resolved.stdout.strip().lower()
        if resolved.returncode != 0 or _SHA_RE.fullmatch(sha) is None:
            raise AgentsSyncFormatError(
                _git_error("could not resolve fetched upstream commit", resolved)
            )
        return FetchedAgentsCommit(ref, sha)

    def manifest_paths(self, sha: str) -> tuple[str, ...]:
        _validate_sha(sha)
        result = self.git_runner(
            self.repo,
            [
                "ls-tree",
                "-r",
                "--name-only",
                "-z",
                sha,
                "--",
                "manifest.json",
                "users",
            ],
            op="agents_sync.object_manifest_paths",
        )
        if result.returncode != 0:
            raise AgentsSyncFormatError(
                _git_error("could not list fetched agents manifests", result)
            )
        paths: list[str] = []
        for raw in result.stdout.split("\x00"):
            if not raw:
                continue
            parts = PurePosixPath(raw).parts
            is_owner_manifest = (
                len(parts) == 5
                and parts[0] == "users"
                and parts[2] == "machines"
                and parts[4] == "manifest.json"
            )
            if raw != "manifest.json" and not is_owner_manifest:
                continue
            paths.append(validate_relative_path(raw))
        return tuple(sorted(set(paths)))

    def read_bytes(self, sha: str, relative: str, *, maximum: int) -> bytes:
        _validate_sha(sha)
        validate_relative_path(relative)
        payload = self._cat_file_batch().read_blob(
            f"{sha}:{relative}",
            relative=relative,
            maximum=maximum,
        )
        if len(payload) > maximum:
            raise AgentsSyncFormatError(
                f"fetched object {relative!r} exceeds the byte limit"
            )
        return payload

    def owner_manifest_divergence_diagnostic(
        self,
        sha: str,
        relative: str,
    ) -> str | None:
        """Explain when an owner manifest references a file absent from its commit."""

        _validate_sha(sha)
        validate_relative_path(relative)
        listed = self.git_runner(
            self.repo,
            ["ls-tree", "-r", "--name-only", "-z", sha, "--", relative],
            op="agents_sync.object_manifest_reference",
        )
        if listed.returncode != 0 or relative in listed.stdout.split("\x00"):
            return None
        message = (
            f"owner manifest references {relative!r}, but it is missing from "
            f"commit {sha}"
        )
        ignored = self.git_runner(
            self.repo,
            ["check-ignore", "-v", "--no-index", "--", relative],
            op="agents_sync.object_manifest_reference_ignore",
        )
        if ignored.returncode != 0 or not ignored.stdout.strip():
            return message
        rule = ignored.stdout.strip().splitlines()[0]
        return f"{message}; local ignore rule: {rule}"

    def _cat_file_batch(self) -> _CatFileBatch:
        if self._batch is None:
            self._batch = _CatFileBatch(self.repo)
        return self._batch


class _CatFileStream:
    """Buffered reader for NUL-framed ``git cat-file --batch -Z`` output.

    ``BufferedReader.read(n)`` on a pipe waits for *n* bytes or EOF, so a
    large ``read()`` while scanning for the header NUL would block until git
    wrote that many bytes. ``read1()`` returns whatever one raw read already
    has; leftover bytes after the header stay in this buffer so the
    length-prefixed body is consumed exactly, not byte-wise.
    """

    _CHUNK_SIZE = 64 * 1024
    _MAX_HEADER_BYTES = 4096
    _DRAIN_CHUNK_SIZE = 1024 * 1024

    def __init__(self, stdout: Any) -> None:
        self._stdout = stdout
        self._buffer = bytearray()

    def read_until_nul(self) -> bytes:
        while True:
            nul = self._buffer.find(b"\0", 0, self._MAX_HEADER_BYTES + 1)
            if nul != -1:
                result = bytes(self._buffer[:nul])
                del self._buffer[: nul + 1]
                return result
            if len(self._buffer) > self._MAX_HEADER_BYTES:
                raise AgentsSyncFormatError("git cat-file batch header is too large")
            chunk = self._read_available(self._CHUNK_SIZE)
            if not chunk:
                raise _CatFileStreamClosed()
            self._buffer.extend(chunk)

    def read_exact(self, size: int) -> bytes:
        if size < 0:
            raise _CatFileStreamClosed()
        if size == 0:
            return b""
        out = bytearray()
        taken = self._consume_buffer(size)
        if taken:
            out += taken
        remaining = size - len(out)
        while remaining:
            chunk = self._read_blocking(remaining)
            if not chunk:
                break
            out += chunk
            remaining = size - len(out)
        return bytes(out)

    def drain(self, size: int) -> None:
        remaining = size
        if remaining < 0:
            raise _CatFileStreamClosed()
        discarded = self._consume_buffer(remaining)
        remaining -= len(discarded)
        while remaining:
            chunk = self._read_blocking(min(remaining, self._DRAIN_CHUNK_SIZE))
            if not chunk:
                raise _CatFileStreamClosed()
            remaining -= len(chunk)

    def _consume_buffer(self, size: int) -> bytes:
        if size <= 0 or not self._buffer:
            return b""
        take = min(size, len(self._buffer))
        result = bytes(self._buffer[:take])
        del self._buffer[:take]
        return result

    def _read_available(self, size: int) -> bytes:
        read1 = getattr(self._stdout, "read1", None)
        if callable(read1):
            return _require_bytes(read1(size))
        return self._read_blocking(size)

    def _read_blocking(self, size: int) -> bytes:
        return _require_bytes(self._stdout.read(size))


class _CatFileBatch:
    """One NUL-framed ``git cat-file --batch`` session for fetched blobs."""

    def __init__(self, repo: Path) -> None:
        self.repo = repo
        self._process = subprocess.Popen(
            sdd_git_command(["cat-file", "--batch", "-Z"]),
            cwd=repo,
            env=noninteractive_git_env(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            start_new_session=True,
        )
        stdout = self._process.stdout
        self._stream = None if stdout is None else _CatFileStream(stdout)

    def read_blob(self, spec: str, *, relative: str, maximum: int) -> bytes:
        process = self._process
        stream = self._stream
        if process.stdin is None or process.stdout is None or stream is None:
            raise AgentsSyncFormatError("git cat-file batch stream is unavailable")
        if process.poll() is not None:
            raise AgentsSyncFormatError(self._closed_stream_error(relative))
        try:
            process.stdin.write(spec.encode("utf-8") + b"\0")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise AgentsSyncFormatError(self._closed_stream_error(relative)) from exc

        header = self._read_until_nul()
        missing_suffix = b" missing"
        if header.endswith(missing_suffix):
            raise AgentsSyncFormatError(f"could not read fetched object {relative!r}")
        parts = header.rsplit(b" ", 2)
        if len(parts) != 3:
            raise AgentsSyncFormatError(
                f"could not parse fetched object header for {relative!r}"
            )
        try:
            size = int(parts[2])
        except ValueError as exc:
            raise AgentsSyncFormatError(
                f"could not parse fetched object size for {relative!r}"
            ) from exc
        if size < 0:
            raise AgentsSyncFormatError(
                f"could not parse fetched object size for {relative!r}"
            )
        object_type = _decode_header(parts[1], relative)
        if object_type != "blob":
            self._drain_object(size, relative)
            raise AgentsSyncFormatError(
                f"fetched object {relative!r} is a {object_type}, not a blob"
            )
        if size > maximum:
            self._drain_object(size, relative)
            raise AgentsSyncFormatError(
                f"fetched object {relative!r} exceeds the byte limit"
            )
        payload = stream.read_exact(size)
        if len(payload) != size:
            raise AgentsSyncFormatError(self._closed_stream_error(relative))
        self._read_object_separator(relative)
        return payload

    def close(self) -> None:
        process = self._process
        if process.poll() is None:
            try:
                if process.stdin is not None:
                    process.stdin.close()
            except OSError:
                pass
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                _terminate_process(process)

    def _read_until_nul(self) -> bytes:
        stream = self._stream
        if stream is None:
            raise AgentsSyncFormatError("git cat-file batch stream is unavailable")
        return stream.read_until_nul()

    def _drain_object(self, size: int, relative: str) -> None:
        stream = self._stream
        if stream is None:
            raise AgentsSyncFormatError("git cat-file batch stream is unavailable")
        try:
            stream.drain(size)
        except _CatFileStreamClosed as exc:
            raise AgentsSyncFormatError(self._closed_stream_error(relative)) from exc
        self._read_object_separator(relative)

    def _read_object_separator(self, relative: str) -> None:
        stream = self._stream
        if stream is None:
            raise AgentsSyncFormatError("git cat-file batch stream is unavailable")
        separator = stream.read_exact(1)
        if separator != b"\0":
            raise AgentsSyncFormatError(
                f"could not parse fetched object boundary for {relative!r}"
            )

    def _closed_stream_error(self, relative: str) -> str:
        stderr = ""
        pipe = self._process.stderr
        if pipe is not None and self._process.poll() is not None:
            try:
                stderr = pipe.read().decode("utf-8", errors="replace").strip()
            except OSError:
                stderr = ""
        detail = f": {stderr}" if stderr else ""
        return f"could not read fetched object {relative!r}{detail}"


def _require_bytes(chunk: object) -> bytes:
    if not chunk:
        return b""
    if isinstance(chunk, (bytes, bytearray, memoryview)):
        return bytes(chunk)
    raise _CatFileStreamClosed()


def _validate_sha(value: str) -> None:
    if _SHA_RE.fullmatch(value) is None:
        raise AgentsSyncFormatError(f"invalid fetched commit SHA: {value!r}")


def _valid_fetched_ref(value: str) -> bool:
    return (
        value.startswith("refs/remotes/")
        and len(value.encode("utf-8")) <= 1024
        and not any(ord(char) <= 32 or char in "~^:?*[\\" for char in value)
        and ".." not in value
        and not value.endswith((".", "/"))
    )


def _git_error(prefix: str, result: object) -> str:
    stderr = getattr(result, "stderr", "")
    stdout = getattr(result, "stdout", "")
    detail = (stderr or stdout or "unknown git error").strip()
    return f"{prefix}: {detail}"


def _decode_header(value: bytes, relative: str) -> str:
    try:
        return value.decode("ascii")
    except UnicodeDecodeError as exc:
        raise AgentsSyncFormatError(
            f"could not parse fetched object header for {relative!r}"
        ) from exc


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        try:
            process.terminate()
        except ProcessLookupError:
            return
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        except OSError:
            try:
                process.kill()
            except ProcessLookupError:
                return
        process.wait()


__all__ = ["FetchedAgentsCommit", "LocalGitObjectReader"]

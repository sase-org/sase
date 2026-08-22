"""LSP harness and normalized rows for directive completion parity tests."""

from __future__ import annotations

import json
import os
import select
import shlex
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tests._xprompt_directive_completion_parity_helpers import (
    _finalizer_catalog_payload,
    _write_helper,
)


@dataclass(frozen=True, slots=True)
class SurfaceRow:
    label: str
    insertion: str
    documentation: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class LspSurfaceRow(SurfaceRow):
    raw: dict[str, Any] | None = None


def _surface_rows(rows: Iterable[SurfaceRow]) -> list[SurfaceRow]:
    return [
        SurfaceRow(
            label=row.label,
            insertion=row.insertion,
            documentation=row.documentation,
            detail=_comparison_detail(row.detail),
        )
        for row in rows
    ]


def _comparison_detail(detail: str) -> str:
    if detail in {
        "agent",
        "bead",
        "clan",
        "family",
        "keyword",
        "model",
        "role",
        "tribe",
        "value",
    }:
        return "" if detail != "keyword" else detail
    return detail


def _only_lsp(rows: list[LspSurfaceRow]) -> LspSurfaceRow:
    assert len(rows) == 1
    return rows[0]


class LspSession:
    def __init__(
        self,
        tmp_path: Path,
        *,
        helper: Path | None = None,
        finalizer_catalog: dict[str, Any]
        | Sequence[Mapping[str, object]]
        | None = None,
    ) -> None:
        self._tmp_path = tmp_path
        self._helper = helper
        self._finalizer_catalog = finalizer_catalog
        self._proc: subprocess.Popen[bytes] | None = None
        self._version = 0
        self._opened = False
        self._uri = "file:///tmp/sase_directive_parity.md"

    def __enter__(self) -> LspSession:
        binary = Path(sys.executable).with_name("sase-xprompt-lsp")
        if not binary.is_file():
            pytest.fail(f"sase-xprompt-lsp binary is missing at {binary}")

        helper = self._helper or _write_helper(self._tmp_path)
        model_catalog = self._tmp_path / "model_catalog.json"
        model_catalog.write_text(json.dumps(_model_catalog_payload()), encoding="utf-8")
        finalizer_catalog = self._tmp_path / "finalizer_catalog.json"
        finalizer_catalog.write_text(
            json.dumps(_finalizer_catalog_payload(self._finalizer_catalog)),
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["SASE_MOBILE_HELPER_BRIDGE_COMMAND"] = shlex.join(
            [sys.executable, str(helper)]
        )
        env["SASE_XPROMPT_MODEL_CATALOG"] = str(model_catalog)
        env["SASE_PARITY_FINALIZER_CATALOG"] = str(finalizer_catalog)
        self._proc = subprocess.Popen(
            [str(binary)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            env=env,
        )
        self._send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "processId": None,
                    "rootUri": None,
                    "capabilities": {
                        "textDocument": {
                            "completion": {"completionItem": {"snippetSupport": False}}
                        }
                    },
                },
            }
        )
        self._read_response(1)
        self._send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        return self

    def __exit__(self, *_exc: object) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": 99,
                    "method": "shutdown",
                    "params": None,
                }
            )
            self._read_response(99)
            self._send({"jsonrpc": "2.0", "method": "exit", "params": {}})
            _stdout, stderr = proc.communicate(timeout=5)
        except Exception:
            proc.kill()
            _stdout, stderr = proc.communicate(timeout=5)
            raise
        finally:
            self._proc = None
        assert proc.returncode == 0, stderr.decode(errors="replace")

    def complete(self, text: str) -> list[LspSurfaceRow]:
        self._version += 1
        method = "textDocument/didChange" if self._opened else "textDocument/didOpen"
        params: dict[str, Any]
        if self._opened:
            params = {
                "textDocument": {"uri": self._uri, "version": self._version},
                "contentChanges": [{"text": text}],
            }
        else:
            self._opened = True
            params = {
                "textDocument": {
                    "uri": self._uri,
                    "languageId": "sase",
                    "version": self._version,
                    "text": text,
                }
            }
        self._send({"jsonrpc": "2.0", "method": method, "params": params})
        request_id = self._version + 10
        self._send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "textDocument/completion",
                "params": {
                    "textDocument": {"uri": self._uri},
                    "position": {"line": 0, "character": _utf16_len(text)},
                },
            }
        )
        response = self._read_response(request_id)
        result = response.get("result")
        if isinstance(result, list):
            items = result
        elif isinstance(result, dict):
            items = result.get("items", [])
        else:
            items = []
        return [_lsp_surface_row(item) for item in items if isinstance(item, dict)]

    def _send(self, payload: dict[str, Any]) -> None:
        assert self._proc is not None
        assert self._proc.stdin is not None
        body = json.dumps(payload).encode()
        header = f"Content-Length: {len(body)}\r\n\r\n".encode()
        self._proc.stdin.write(header + body)
        self._proc.stdin.flush()

    def _read_response(self, request_id: int) -> dict[str, Any]:
        while True:
            message = self._read_message()
            if message.get("id") == request_id:
                return message

    def _read_message(self) -> dict[str, Any]:
        assert self._proc is not None
        assert self._proc.stdout is not None
        header = b""
        while b"\r\n\r\n" not in header:
            if not _wait_readable(self._proc.stdout.fileno()):
                raise TimeoutError("timed out waiting for LSP response header")
            chunk = self._proc.stdout.read(1)
            if not chunk:
                raise RuntimeError("LSP exited before a response header")
            header += chunk
        head, rest = header.split(b"\r\n\r\n", 1)
        length = None
        for line in head.split(b"\r\n"):
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":", 1)[1].strip())
                break
        if length is None:
            raise RuntimeError(f"LSP response missing Content-Length: {head!r}")
        body = rest
        while len(body) < length:
            if not _wait_readable(self._proc.stdout.fileno()):
                raise TimeoutError("timed out waiting for LSP response body")
            chunk = self._proc.stdout.read(length - len(body))
            if not chunk:
                raise RuntimeError("LSP exited before a complete response body")
            body += chunk
        return json.loads(body)


def _model_catalog_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "entries": [
            {
                "value": "claude-fable-5",
                "display": "claude-fable-5",
                "description": "Claude (fable)",
                "kind": "model",
                "provider": "claude",
                "aliases": ["fable"],
            },
            {
                "value": "@medium",
                "display": "@medium",
                "description": "Medium phase worker model.",
                "kind": "implicit_alias",
                "aliases": ["medium"],
                "alias_kind": "role",
                "target_provider": "claude",
                "target_model": "claude-fable-5",
                "target_effort": "high",
                "provenance": "configured",
            },
        ],
    }


def _lsp_surface_row(item: dict[str, Any]) -> LspSurfaceRow:
    documentation = item.get("documentation")
    if isinstance(documentation, dict):
        doc_text = str(documentation.get("value") or "")
    else:
        doc_text = str(documentation or "")
    text_edit = item.get("textEdit")
    insertion = ""
    if isinstance(text_edit, dict):
        insertion = str(text_edit.get("newText") or "")
    return LspSurfaceRow(
        label=str(item.get("label") or ""),
        insertion=insertion,
        documentation=doc_text,
        detail=_lsp_row_detail(item),
        raw=item,
    )


def _lsp_row_detail(item: dict[str, Any]) -> str:
    label_details = item.get("labelDetails")
    description = ""
    policy = ""
    if isinstance(label_details, dict):
        description = str(label_details.get("description") or "")
        policy = str(label_details.get("detail") or "")
    if policy.startswith(" · ") and description:
        status = policy.strip(" ·")
        parts = [part for part in description.split(" · ") if part]
        if status and status not in parts:
            parts.append(status)
        return " · ".join(parts)
    return str(item.get("detail") or description or "")


def _wait_readable(fd: int) -> bool:
    readable, _, _ = select.select([fd], [], [], 10.0)
    return bool(readable)


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2

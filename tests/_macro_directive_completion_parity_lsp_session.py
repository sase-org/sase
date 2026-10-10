"""LSP test session for directive completion parity tests."""

from __future__ import annotations

import json
import os
import select
import shlex
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from tests._macro_directive_completion_parity_helpers import (
    _finalizer_catalog_payload,
    _write_helper,
)
from tests._macro_directive_completion_parity_lsp_protocol import (
    completion_position,
    decode_semantic_tokens,
    lsp_surface_row,
    machine_catalog_payload,
    model_catalog_payload,
    macro_catalog_payload,
)
from tests._macro_directive_completion_parity_lsp_rows import (
    LspCompletionList,
    LspSemanticToken,
    LspSurfaceRow,
)


class LspSession:
    def __init__(
        self,
        tmp_path: Path,
        *,
        helper: Path | None = None,
        finalizer_catalog: dict[str, Any]
        | Sequence[Mapping[str, object]]
        | None = None,
        macro_catalog: dict[str, Any] | Sequence[Mapping[str, object]] | None = None,
        artifact_ref_catalog: Mapping[str, object] | None = None,
        model_catalog: Mapping[str, Any] | None = None,
        model_catalog_text: str | None = None,
        omit_model_catalog: bool = False,
        uri: str | None = None,
        language_id: str = "sase",
    ) -> None:
        self._tmp_path = tmp_path
        self._helper = helper
        self._finalizer_catalog = finalizer_catalog
        self._macro_catalog = macro_catalog
        self._artifact_ref_catalog = artifact_ref_catalog
        self._model_catalog = model_catalog
        self._model_catalog_text = model_catalog_text
        self._omit_model_catalog = omit_model_catalog
        self._proc: subprocess.Popen[bytes] | None = None
        self._version = 0
        self._request_id = 10
        self._opened = False
        self._uri = uri or "file:///tmp/sase_directive_parity.md"
        self._language_id = language_id
        self._buffered_messages: list[dict[str, Any]] = []
        self.initialize_result: dict[str, Any] = {}

    def __enter__(self) -> LspSession:
        binary = Path(sys.executable).with_name("sase-macro-lsp")
        if not binary.is_file():
            legacy = Path(sys.executable).with_name("sase-xprompt-lsp")
            if legacy.is_file():
                binary = legacy
            else:
                pytest.fail(f"sase-macro-lsp binary is missing at {binary}")

        helper = self._helper or _write_helper(self._tmp_path)
        model_catalog = self._tmp_path / "model_catalog.json"
        if not self._omit_model_catalog:
            if self._model_catalog_text is not None:
                model_catalog.write_text(self._model_catalog_text, encoding="utf-8")
            else:
                payload = self._model_catalog or model_catalog_payload()
                model_catalog.write_text(json.dumps(payload), encoding="utf-8")
        machine_catalog = self._tmp_path / "machine_catalog.json"
        machine_catalog.write_text(
            json.dumps(machine_catalog_payload()),
            encoding="utf-8",
        )
        finalizer_catalog = self._tmp_path / "finalizer_catalog.json"
        finalizer_catalog.write_text(
            json.dumps(_finalizer_catalog_payload(self._finalizer_catalog)),
            encoding="utf-8",
        )
        macro_catalog = self._tmp_path / "xprompt_catalog.json"
        macro_catalog.write_text(
            json.dumps(macro_catalog_payload(self._macro_catalog)),
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["SASE_MOBILE_HELPER_BRIDGE_COMMAND"] = shlex.join(
            [sys.executable, str(helper)]
        )
        env["SASE_PARITY_XPROMPT_CATALOG"] = str(macro_catalog)
        if self._omit_model_catalog:
            env.pop("SASE_XPROMPT_MODEL_CATALOG", None)
            env.pop("SASE_MACRO_MODEL_CATALOG", None)
        else:
            env["SASE_XPROMPT_MODEL_CATALOG"] = str(model_catalog)
            env["SASE_MACRO_MODEL_CATALOG"] = str(model_catalog)
        env["SASE_XPROMPT_MACHINE_CATALOG"] = str(machine_catalog)
        env["SASE_MACRO_MACHINE_CATALOG"] = str(machine_catalog)
        env["SASE_PARITY_FINALIZER_CATALOG"] = str(finalizer_catalog)
        if self._artifact_ref_catalog is not None:
            artifact_ref_catalog = self._tmp_path / "artifact_ref_catalog.json"
            artifact_ref_catalog.write_text(
                json.dumps(self._artifact_ref_catalog),
                encoding="utf-8",
            )
            env["SASE_XPROMPT_ARTIFACT_REF_CATALOG"] = str(artifact_ref_catalog)
            env["SASE_MACRO_ARTIFACT_REF_CATALOG"] = str(artifact_ref_catalog)
        initialization_options = {}
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
                            "completion": {"completionItem": {"snippetSupport": False}},
                            "semanticTokens": {
                                "requests": {"full": True},
                                "formats": ["relative"],
                                "tokenTypes": [],
                                "tokenModifiers": [],
                            },
                        }
                    },
                    "initializationOptions": initialization_options,
                },
            }
        )
        initialize = self._read_response(1)
        result = initialize.get("result")
        self.initialize_result = result if isinstance(result, dict) else {}
        self._send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        return self

    @property
    def trigger_characters(self) -> list[str]:
        capabilities = self.initialize_result.get("capabilities")
        if not isinstance(capabilities, dict):
            return []
        provider = capabilities.get("completionProvider")
        if not isinstance(provider, dict):
            return []
        triggers = provider.get("triggerCharacters")
        if not isinstance(triggers, list):
            return []
        return [str(item) for item in triggers]

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

    def complete(
        self,
        text: str,
        *,
        character: int | None = None,
        cursor: tuple[int, int] | None = None,
    ) -> list[LspSurfaceRow]:
        return self.complete_list(text, character=character, cursor=cursor).items

    def complete_list(
        self,
        text: str,
        *,
        character: int | None = None,
        cursor: tuple[int, int] | None = None,
    ) -> LspCompletionList:
        self._sync_text(text)
        request_id = self._next_request_id()
        self._send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "textDocument/completion",
                "params": {
                    "textDocument": {"uri": self._uri},
                    "position": completion_position(
                        text, character=character, cursor=cursor
                    ),
                },
            }
        )
        response = self._read_response(request_id)
        result = response.get("result")
        if isinstance(result, list):
            items = result
            is_incomplete = False
        elif isinstance(result, dict):
            raw_items = result.get("items", [])
            items = raw_items if isinstance(raw_items, list) else []
            is_incomplete = bool(result.get("isIncomplete"))
        else:
            items = []
            is_incomplete = False
        return LspCompletionList(
            is_incomplete=is_incomplete,
            items=[lsp_surface_row(item) for item in items if isinstance(item, dict)],
            raw=result,
        )

    def semantic_tokens(self, text: str) -> list[LspSemanticToken]:
        self._sync_text(text)
        request_id = self._next_request_id()
        self._send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "textDocument/semanticTokens/full",
                "params": {"textDocument": {"uri": self._uri}},
            }
        )
        response = self._read_response(request_id)
        result = response.get("result")
        data = result.get("data") if isinstance(result, dict) else []
        raw_data = [int(item) for item in data] if isinstance(data, list) else []
        token_types, token_modifiers = self.semantic_token_legend()
        return decode_semantic_tokens(
            raw_data,
            token_types=token_types,
            token_modifiers=token_modifiers,
        )

    def semantic_token_legend(self) -> tuple[list[str], list[str]]:
        capabilities = self.initialize_result.get("capabilities")
        if not isinstance(capabilities, dict):
            return ([], [])
        provider = capabilities.get("semanticTokensProvider")
        if not isinstance(provider, dict):
            provider = capabilities.get("semantic_tokens_provider")
        if not isinstance(provider, dict):
            return ([], [])
        legend = provider.get("legend")
        if not isinstance(legend, dict):
            return ([], [])
        token_types = legend.get("tokenTypes")
        if not isinstance(token_types, list):
            token_types = legend.get("token_types")
        token_modifiers = legend.get("tokenModifiers")
        if not isinstance(token_modifiers, list):
            token_modifiers = legend.get("token_modifiers")
        return (
            [str(item) for item in token_types]
            if isinstance(token_types, list)
            else [],
            [str(item) for item in token_modifiers]
            if isinstance(token_modifiers, list)
            else [],
        )

    def published_diagnostics(
        self,
        text: str,
        *,
        expected_codes: frozenset[str] | None = None,
    ) -> list[dict[str, Any]]:
        self._sync_text(text)
        deadline = time.monotonic() + 10.0
        latest: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            message = self._pop_buffered_message()
            if message is None:
                message = self._read_message()
            params = message.get("params")
            if (
                message.get("method") != "textDocument/publishDiagnostics"
                or not isinstance(params, dict)
                or params.get("uri") != self._uri
            ):
                continue
            diagnostics = params.get("diagnostics")
            latest = (
                [item for item in diagnostics if isinstance(item, dict)]
                if isinstance(diagnostics, list)
                else []
            )
            codes = {
                str(code)
                for item in latest
                if (code := _diagnostic_code(item)) is not None
            }
            if expected_codes is None or expected_codes <= codes:
                return latest
        return latest

    def _sync_text(self, text: str) -> None:
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
                    "languageId": self._language_id,
                    "version": self._version,
                    "text": text,
                }
            }
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _send(self, payload: dict[str, Any]) -> None:
        assert self._proc is not None
        assert self._proc.stdin is not None
        body = json.dumps(payload).encode()
        header = f"Content-Length: {len(body)}\r\n\r\n".encode()
        self._proc.stdin.write(header + body)
        self._proc.stdin.flush()

    def _read_response(self, request_id: int) -> dict[str, Any]:
        while True:
            message = self._pop_buffered_message()
            if message is None:
                message = self._read_message()
            if message.get("id") == request_id:
                return message

    def _pop_buffered_message(self) -> dict[str, Any] | None:
        if not self._buffered_messages:
            return None
        return self._buffered_messages.pop(0)

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


def _wait_readable(fd: int) -> bool:
    readable, _, _ = select.select([fd], [], [], 10.0)
    return bool(readable)


def _diagnostic_code(item: Mapping[str, object]) -> object | None:
    code = item.get("code")
    if isinstance(code, Mapping):
        return code.get("value")
    return code

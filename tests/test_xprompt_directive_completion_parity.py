"""Parity coverage for runtime, ACE, and LSP directive completion."""

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
from unittest.mock import patch

import pytest
import sase_core_rs

from sase.ace.tui.agent_completion import AgentCompletionCandidate
from sase.ace.tui.widgets.directive_completion import (
    BeadCompletionMetadata,
    DirectiveArgCompletionMetadata,
    DirectiveCatalogPlaceholder,
    DirectiveCompletionMetadata,
    FinalizerCompletionMetadata,
    FinalizersState,
    ModelCompletionMetadata,
    build_directive_clause_candidates,
    build_directive_completion_candidates,
    classify_directive_completion,
)
from sase.xprompt._directive_types import (
    _DIRECTIVE_ALIASES,
    _KNOWN_DIRECTIVES,
    _MULTI_VALUE_DIRECTIVES,
    AUTO_COMPATIBILITY_ARGUMENT_SUGGESTIONS,
)
from sase.xprompt.effort import EFFORT_LEVELS_ORDERED
from sase.xprompt.model_completion import _ModelCompletionEntry
from tests._xprompt_directive_completion_parity_helpers import (
    _FINALIZER_ROWS,
    _OPTIONAL_FINALIZER_ROWS,
    _finalizer_catalog_payload,
    _write_failing_helper,
    _write_helper,
)

MODEL_CATALOG_PATCH = (
    "sase.ace.tui.widgets.directive_completion.build_model_completion_catalog"
)
MODEL_ALIAS_NAMES_PATCH = "sase.llm_provider.config.model_alias_names"
MODEL_ALIAS_DESCRIPTION_PATCH = "sase.llm_provider.config.model_alias_description"
_SPECIAL_RUNTIME_DIRECTIVES = frozenset({"alt", "xprompts_enabled"})
_AGENT_ROWS = (
    AgentCompletionCandidate("planner", "planner", "RUNNING"),
    AgentCompletionCandidate("coder", "coder", "RUNNING"),
    AgentCompletionCandidate("review", "review", "RUNNING", kind="clan"),
    AgentCompletionCandidate("ship", "ship", "RUNNING", kind="family"),
    AgentCompletionCandidate("@builders", "builders", "RUNNING", kind="tribe"),
)
_BEAD_ROWS = (
    {
        "id": "sase-a",
        "title": "Active bug",
        "status": "in_progress",
        "type_label": "task",
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-20T12:00:00Z",
        "task_type": "bug",
        "project": "sase",
    },
)


@dataclass(frozen=True, slots=True)
class SurfaceRow:
    label: str
    insertion: str
    documentation: str
    detail: str = ""


def test_runtime_directive_vocabulary_matches_core_contract() -> None:
    contract = _contract_by_name()
    runtime_names = set(_KNOWN_DIRECTIVES) | set(_SPECIAL_RUNTIME_DIRECTIVES)

    assert set(contract) == runtime_names
    assert _contract_aliases(contract) == {
        alias: name
        for alias, name in _DIRECTIVE_ALIASES.items()
        if name in runtime_names
    }
    assert {
        name for name, row in contract.items() if bool(row["allows_multiple"])
    } == set(_MULTI_VALUE_DIRECTIVES) | {"alt", "xprompts_enabled"}
    assert _contract_keywords(contract) == {
        "alt": (),
        "auto": (),
        "clan": ("summary", "summary_script", "tribe"),
        "effort": (),
        "final": (),
        "hide": (),
        "id": ("bead", "clan", "family", "tribe"),
        "model": (),
        "repeat": (),
        "wait": ("bead", "priority", "runners", "time"),
        "xprompts_enabled": (),
    }
    assert contract["model"]["dynamic_keyword_role"] == "model_alias_key"
    assert (
        _suggested_values(contract["auto"]) == AUTO_COMPATIBILITY_ARGUMENT_SUGGESTIONS
    )
    assert _suggested_values(contract["effort"]) == tuple(EFFORT_LEVELS_ORDERED)
    assert _suggested_values(contract["repeat"]) == ("2", "3")
    assert _suggested_values(contract["xprompts_enabled"]) == ("false", "true")
    assert _contract_syntax_forms(contract) == {
        "alt": ("brace_shorthand", "colon", "parenthesized"),
        "auto": ("colon", "bare", "plus"),
        "clan": ("colon", "parenthesized"),
        "effort": ("colon",),
        "final": ("colon", "parenthesized"),
        "hide": ("bare", "plus"),
        "id": ("colon", "parenthesized", "bare"),
        "model": ("colon", "parenthesized"),
        "repeat": ("colon",),
        "wait": ("colon", "parenthesized", "bare"),
        "xprompts_enabled": ("colon",),
    }


def test_ace_and_lsp_directive_name_rows_match(tmp_path: Path) -> None:
    ace_candidates, shared = build_directive_completion_candidates("%")
    assert shared == ""
    ace_rows = _ace_surface_rows(ace_candidates)
    contract_order = [f"%{row['name']}" for row in sase_core_rs.directive_contract()]

    with LspSession(tmp_path) as lsp:
        lsp_rows = lsp.complete("%")

    assert {row.label for row in ace_rows} == set(contract_order)
    assert _surface_rows(lsp_rows) == _surface_rows(ace_rows)


@pytest.mark.parametrize(
    "text",
    [
        "%effort:",
        "%auto:",
        "%repeat:",
        "%xprompts_enabled:",
        "%id(worker, be",
        "%id(worker, cl",
        "%id(worker, fa",
        "%id(worker, tr",
        "%clan(research, su",
        "%clan(research, tr",
        "%wait(",
        "%wait:",
        "%wait(bead=",
        "%model:",
        "%model(me",
        "%model(opus, medium=",
    ],
)
def test_ace_and_lsp_directive_argument_rows_match(
    tmp_path: Path,
    text: str,
) -> None:
    with (
        patch(MODEL_CATALOG_PATCH, return_value=_model_entries()),
        patch(MODEL_ALIAS_NAMES_PATCH, return_value=("medium",)),
        patch(MODEL_ALIAS_DESCRIPTION_PATCH, side_effect=_model_alias_description),
    ):
        ace_rows = _ace_clause_rows(text)
        with LspSession(tmp_path) as lsp:
            lsp_rows = lsp.complete(text)

    assert _surface_rows(lsp_rows) == _surface_rows(ace_rows)


def test_wait_colon_form_never_advertises_structured_keywords(
    tmp_path: Path,
) -> None:
    with LspSession(tmp_path) as lsp:
        lsp_rows = lsp.complete("%wait:")

    with patch(MODEL_CATALOG_PATCH, return_value=_model_entries()):
        ace_rows = _ace_clause_rows("%wait:")

    assert _surface_rows(lsp_rows) == _surface_rows(ace_rows)
    assert all(not row.insertion.endswith("=") for row in lsp_rows)


def test_failure_degradation_retains_static_directive_rows(tmp_path: Path) -> None:
    helper = _write_failing_helper(tmp_path)

    with LspSession(tmp_path, helper=helper) as lsp:
        rows = lsp.complete("%wait(")

    assert [row.insertion for row in rows] == [
        "bead=",
        "priority=",
        "runners=",
        "time=",
    ]


def test_lsp_uses_utf16_replacement_ranges(tmp_path: Path) -> None:
    with LspSession(tmp_path) as lsp:
        rows = lsp.complete("🙂 %mod")

    model = _only_lsp(rows)
    assert model.label == "%model"
    assert model.insertion == "%model"

    raw = model.raw
    assert raw is not None
    assert raw["textEdit"]["range"] == {
        "start": {"line": 0, "character": 3},
        "end": {"line": 0, "character": 7},
    }


def test_ace_and_lsp_finalizer_add_rows_match(tmp_path: Path) -> None:
    ace_rows, lsp_rows = _ace_and_lsp_rows(tmp_path, "%final:")

    assert [row.insertion for row in ace_rows] == ["commit", "lint", "zoom"]
    assert _surface_rows(lsp_rows) == _surface_rows(ace_rows)
    assert ace_rows[0].detail == "builtin@commit · required"
    assert ace_rows[1].detail == "builtin@command · default"
    assert ace_rows[2].detail == "plugin@zoom · optional"
    assert "Required for this launch." in ace_rows[0].documentation
    assert "Provider: `builtin@commit`" in ace_rows[0].documentation
    assert "Depends on: `format`" in ace_rows[1].documentation
    assert "Retry policy: 2 attempts" in ace_rows[1].documentation
    assert "Retry policy: 1 attempt" in ace_rows[2].documentation


def test_ace_and_lsp_finalizer_remove_omits_required(tmp_path: Path) -> None:
    ace_rows, lsp_rows = _ace_and_lsp_rows(tmp_path, "%final:!")

    assert [row.insertion for row in ace_rows] == ["!lint", "!zoom"]
    assert _surface_rows(lsp_rows) == _surface_rows(ace_rows)
    assert all(row.detail.startswith("remove · ") for row in ace_rows)
    assert "Remove `lint` from the launch selection." in ace_rows[0].documentation
    assert not any(row.insertion in {"!commit", "none"} for row in ace_rows)


def test_ace_and_lsp_none_suppressed_when_required_exists(tmp_path: Path) -> None:
    ace_rows, lsp_rows = _ace_and_lsp_rows(tmp_path, "%final:n")

    assert [row.insertion for row in ace_rows] == []
    assert _surface_rows(lsp_rows) == _surface_rows(ace_rows)


def test_ace_and_lsp_none_available_when_clear_is_legal(tmp_path: Path) -> None:
    ace_rows, lsp_rows = _ace_and_lsp_rows(
        tmp_path,
        "%final:n",
        finalizer_inventory=_OPTIONAL_FINALIZER_ROWS,
    )

    assert [row.insertion for row in ace_rows] == ["none"]
    assert _surface_rows(lsp_rows) == _surface_rows(ace_rows)
    assert ace_rows[0].detail == "clear"
    assert "Clear the configured finalizer selection" in ace_rows[0].documentation


def test_ace_and_lsp_finalizer_repeated_directive_matches(tmp_path: Path) -> None:
    ace_rows, lsp_rows = _ace_and_lsp_rows(tmp_path, "%final:none %final:l")

    assert [row.insertion for row in ace_rows] == ["lint"]
    assert _surface_rows(lsp_rows) == _surface_rows(ace_rows)


def test_ace_and_lsp_finalizer_parenthesized_clause_replacement(
    tmp_path: Path,
) -> None:
    text = "%final(commit, !l"
    ace_rows, lsp_rows = _ace_and_lsp_rows(tmp_path, text)

    assert [row.insertion for row in ace_rows] == ["!lint"]
    assert _surface_rows(lsp_rows) == _surface_rows(ace_rows)
    lsp = _only_lsp(lsp_rows)
    assert lsp.raw is not None
    assert lsp.raw["textEdit"]["range"] == {
        "start": {"line": 0, "character": 15},
        "end": {"line": 0, "character": _utf16_len(text)},
    }


def test_ace_and_lsp_finalizer_utf16_replacement_next_to_non_ascii(
    tmp_path: Path,
) -> None:
    text = "🙂 %final(café, c"
    ace_rows, lsp_rows = _ace_and_lsp_rows(tmp_path, text)

    assert [row.insertion for row in ace_rows] == ["commit"]
    assert _surface_rows(lsp_rows) == _surface_rows(ace_rows)
    lsp = _only_lsp(lsp_rows)
    assert lsp.raw is not None
    prefix = "🙂 %final(café, "
    assert lsp.raw["textEdit"]["range"] == {
        "start": {"line": 0, "character": _utf16_len(prefix)},
        "end": {"line": 0, "character": _utf16_len(text)},
    }


def test_finalizer_helper_failure_degrades_without_invented_rows(
    tmp_path: Path,
) -> None:
    helper = _write_failing_helper(tmp_path)
    clause = classify_directive_completion("%final:", len("%final:"))
    assert clause is not None
    ace_candidates, _ = build_directive_clause_candidates(
        clause,
        finalizers_state="unavailable",
    )
    with LspSession(tmp_path, helper=helper) as lsp:
        lsp_rows = lsp.complete("%final:")

    assert len(ace_candidates) == 1
    placeholder = ace_candidates[0].metadata
    assert isinstance(placeholder, DirectiveCatalogPlaceholder)
    assert placeholder.kind == "unavailable"
    assert placeholder.catalog == "finalizers"
    assert ace_candidates[0].insertion == ""
    assert [row.insertion for row in lsp_rows] == []
    assert _selectable_surface_rows(_ace_surface_rows(ace_candidates)) == []
    assert _selectable_surface_rows(lsp_rows) == []


def _contract_by_name() -> dict[str, dict[str, Any]]:
    rows = sase_core_rs.directive_contract()
    return {str(row["name"]): row for row in rows}


def _contract_aliases(contract: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {
        str(row["alias"]): name
        for name, row in contract.items()
        if isinstance(row.get("alias"), str) and row["alias"]
    }


def _contract_keywords(
    contract: dict[str, dict[str, Any]],
) -> dict[str, tuple[str, ...]]:
    return {
        name: tuple(str(keyword["name"]) for keyword in row["keywords"])
        for name, row in contract.items()
    }


def _contract_syntax_forms(
    contract: dict[str, dict[str, Any]],
) -> dict[str, tuple[str, ...]]:
    return {
        name: tuple(str(syntax) for syntax in row["syntax_forms"])
        for name, row in contract.items()
    }


def _suggested_values(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(item["value"])
        for item in row.get("positional_suggestions", [])
        if isinstance(item, dict)
    )


def _ace_and_lsp_rows(
    tmp_path: Path,
    text: str,
    *,
    finalizer_inventory: Sequence[Mapping[str, object]] = _FINALIZER_ROWS,
    finalizers_state: FinalizersState = "warm",
    helper: Path | None = None,
) -> tuple[list[SurfaceRow], list[LspSurfaceRow]]:
    ace_rows = _ace_clause_rows(
        text,
        finalizer_inventory=finalizer_inventory,
        finalizers_state=finalizers_state,
    )
    with LspSession(
        tmp_path,
        helper=helper,
        finalizer_catalog=None if helper is not None else finalizer_inventory,
    ) as lsp:
        lsp_rows = lsp.complete(text)
    return ace_rows, lsp_rows


def _ace_clause_rows(
    text: str,
    *,
    finalizer_inventory: Sequence[Mapping[str, object]] = _FINALIZER_ROWS,
    finalizers_state: FinalizersState = "warm",
) -> list[SurfaceRow]:
    clause = classify_directive_completion(text, len(text))
    assert clause is not None
    candidates, _shared = build_directive_clause_candidates(
        clause,
        agent_candidates=_AGENT_ROWS,
        bead_inventory=_BEAD_ROWS,
        beads_state="warm",
        finalizer_inventory=finalizer_inventory,
        finalizers_state=finalizers_state,
    )
    return _ace_surface_rows(candidates)


def _ace_surface_rows(candidates: Iterable[Any]) -> list[SurfaceRow]:
    rows: list[SurfaceRow] = []
    for candidate in candidates:
        metadata = candidate.metadata
        documentation = ""
        detail = ""
        if isinstance(metadata, DirectiveCompletionMetadata):
            documentation = metadata.description
            if metadata.aliases:
                detail = f"alias %{metadata.aliases[0]}"
        elif isinstance(metadata, DirectiveArgCompletionMetadata):
            documentation = metadata.description
            detail = "keyword" if candidate.insertion.endswith("=") else ""
        elif isinstance(metadata, AgentCompletionCandidate):
            detail = metadata.status
            if metadata.kind != "agent":
                detail = metadata.kind
        elif isinstance(metadata, BeadCompletionMetadata):
            documentation = metadata.documentation
            detail = " · ".join(
                part
                for part in (
                    metadata.status,
                    metadata.type_label,
                    metadata.task_type,
                )
                if part
            )
        elif isinstance(metadata, ModelCompletionMetadata):
            documentation = _model_documentation(metadata)
            detail = _model_detail(metadata)
        elif isinstance(metadata, FinalizerCompletionMetadata):
            documentation = metadata.documentation
            detail = _finalizer_surface_detail(
                kind=metadata.kind,
                status=metadata.status,
                provider=metadata.provider,
            )
        elif isinstance(metadata, DirectiveCatalogPlaceholder):
            documentation = metadata.message
            detail = metadata.kind
        rows.append(
            SurfaceRow(
                label=candidate.display,
                insertion=candidate.insertion,
                documentation=documentation,
                detail=detail,
            )
        )
    return rows


def _model_detail(metadata: ModelCompletionMetadata) -> str:
    if metadata.kind not in {"implicit_alias", "user_alias"}:
        return metadata.provider
    if metadata.target_provider and metadata.target_model:
        target = f"{metadata.target_provider.upper()}({metadata.target_model})"
    elif metadata.target_model:
        target = metadata.target_model
    else:
        target = metadata.target_provider.upper()
    if target and metadata.target_effort:
        target = f"{target} @ {metadata.target_effort}"
    if target:
        return target
    return "  ".join(part for part in (metadata.provider, metadata.description) if part)


def _model_documentation(metadata: ModelCompletionMetadata) -> str:
    sections = []
    if metadata.description:
        sections.append(metadata.description)
    if metadata.provenance:
        provenance = metadata.provenance
        if metadata.reference:
            provenance = f"{provenance} \u2192 @{metadata.reference.lstrip('@')}"
            if metadata.reference_effort:
                provenance = f"{provenance} @ {metadata.reference_effort}"
        sections.append(f"**Provenance:** {provenance}")
    if metadata.config_source:
        alias = metadata.value.lstrip("@")
        sections.append(
            f"**Config:** `llm_provider.model_aliases.{metadata.config_source}.{alias}`"
        )
    return "\n\n".join(sections)


def _model_entries() -> list[_ModelCompletionEntry]:
    return [
        _ModelCompletionEntry(
            value="claude-fable-5",
            display="claude-fable-5",
            description="Claude (fable)",
            provider="claude",
            aliases=("fable",),
        ),
        _ModelCompletionEntry(
            value="@medium",
            display="@medium",
            description="Medium phase worker model.",
            kind="implicit_alias",
            aliases=("medium",),
            alias_kind="role",
            target_provider="claude",
            target_model="claude-fable-5",
            target_effort="high",
            provenance="configured",
        ),
    ]


def _model_alias_description(alias: str) -> str:
    assert alias == "medium"
    return "Medium phase worker model."


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


def _only_lsp(rows: list[LspSurfaceRow]) -> LspSurfaceRow:
    assert len(rows) == 1
    return rows[0]


def _finalizer_surface_detail(*, kind: str, status: str, provider: str) -> str:
    if kind == "finalizer_remove":
        head = f"remove · {provider}" if provider else "remove"
    elif kind == "finalizer_clear":
        head = "clear"
    else:
        head = provider
    if status and status not in head.split(" · "):
        return f"{head} · {status}" if head else status
    return head


def _selectable_surface_rows(rows: Iterable[SurfaceRow]) -> list[SurfaceRow]:
    return _surface_rows(row for row in rows if row.insertion)


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


def _label_detail(item: dict[str, Any]) -> str:
    label_details = item.get("labelDetails")
    if not isinstance(label_details, dict):
        return ""
    return str(label_details.get("description") or "")


def _wait_readable(fd: int) -> bool:
    readable, _, _ = select.select([fd], [], [], 10.0)
    return bool(readable)


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2

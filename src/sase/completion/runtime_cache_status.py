"""Read-only runtime grammar cache assessment."""

from __future__ import annotations

import json
from pathlib import Path

from sase.completion.install_models import ExpectedCompletion
from sase.completion.install_scripts import zwc_freshness
from sase.completion.install_targets import SUPPORTED_SHELLS
from sase.completion.runtime_cache_models import (
    CACHE_FORMAT_REVISION,
    CACHE_SCHEMA_VERSION,
    CompletionCacheError,
    RuntimeGrammarStatus,
)
from sase.completion.runtime_cache_support import read_text, sha256_text


def assess_cached_grammar(
    shell: str,
    *,
    runtime_key: str,
    fingerprint: str,
    grammar: Path,
    expected: ExpectedCompletion | None = None,
) -> RuntimeGrammarStatus:
    """Assess a cache without generating its parser or grammar."""
    if shell not in SUPPORTED_SHELLS:
        raise CompletionCacheError(f"unsupported shell: {shell}")
    path = str(grammar.resolve(strict=False))
    try:
        data = json.loads(
            (grammar.parent / "manifest.json").read_text(encoding="utf-8")
        )
    except FileNotFoundError:
        return _result(
            shell, "missing", path, None, "runtime grammar cache manifest is missing"
        )
    except json.JSONDecodeError:
        return _result(
            shell,
            "corrupt",
            path,
            None,
            "runtime grammar cache manifest is not valid JSON",
        )
    except OSError as exc:
        return _result(
            shell,
            "missing",
            path,
            None,
            f"runtime grammar cache manifest cannot be read: {exc}",
        )
    if not isinstance(data, dict):
        return _result(
            shell,
            "corrupt",
            path,
            None,
            "runtime grammar cache manifest is not an object",
        )

    status, reasons = "current", []
    for field, value, reason in (
        (
            "schema_version",
            CACHE_SCHEMA_VERSION,
            "runtime grammar manifest schema is stale",
        ),
        (
            "cache_format_revision",
            CACHE_FORMAT_REVISION,
            "runtime grammar cache format is stale",
        ),
        ("runtime_key", runtime_key, "runtime grammar runtime identity is stale"),
        (
            "source_fingerprint",
            fingerprint,
            "runtime grammar source fingerprint is stale",
        ),
    ):
        if data.get(field) != value:
            status = "stale"
            reasons.append(reason)
    if data.get("shell") != shell:
        status = "corrupt"
        reasons.append("runtime grammar manifest shell does not match")
    if data.get("grammar_path") is not None and Path(
        str(data["grammar_path"])
    ) != grammar.resolve(strict=False):
        status = "stale"
        reasons.append("runtime grammar manifest points at another path")
    digest = (
        None
        if data.get("structural_digest") is None
        else str(data["structural_digest"])
    )
    if expected is not None and digest != expected.digest:
        status = "stale"
        reasons.append(
            f"runtime grammar digest {digest or '<missing>'} differs from running {expected.digest}"
        )
    payload = read_text(grammar)
    if payload is None:
        status = "missing" if status == "current" else status
        reasons.append("runtime grammar file is missing or unreadable")
    elif data.get("content_checksum") != sha256_text(payload):
        status = "corrupt"
        reasons.append("runtime grammar checksum does not match manifest")
    if shell == "zsh":
        freshness = zwc_freshness(shell, grammar)
        if freshness != "fresh":
            status = "zwc stale" if status == "current" else status
            reasons.append(f"runtime grammar .zwc is {freshness}")
    return RuntimeGrammarStatus(shell, status, path, digest, tuple(reasons))


def _result(
    shell: str, status: str, path: str, digest: str | None, reason: str
) -> RuntimeGrammarStatus:
    return RuntimeGrammarStatus(shell, status, path, digest, (reason,))

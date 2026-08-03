"""Structured and textual rewrites for identity migration."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import re
from typing import Any

from sase.agent.names._identity_migration_common import merge_counts
from sase.agent.names._identity_migration_types import RewriteContext
from sase.core.bead_prefix_migration import rewrite_id_tokens


_BEAD_KEYS = frozenset({"bead_id", "epic_bead_id", "phase_bead_id"})
_NAME_KEYS = frozenset(
    {
        "agent_clan",
        "agent_family",
        "agent_name",
        "canonical_global_name",
        "cl_name",
        "global_name",
        "local_name",
        "name",
        "parent_agent_name",
        "source_agent_name",
        "target_agent_name",
        "workflow_name",
    }
)
_REF_KEYS = frozenset(
    {
        "agent_names",
        "family_name",
        "lane_name",
        "member_name",
        "source_global_name",
        "target_global_name",
        "wait_for",
        "waiting_for",
    }
)
_PATH_KEYS = frozenset({"chat_path", "response_path"})
_PROMPT_DIRECTIVE_RE = r"(?:%id|%name|%n|%w|%wait|#fork|#resume)"


def rewrite_json_payload(
    data: dict[str, Any],
    context: RewriteContext,
    *,
    rewrite_keys: bool = False,
) -> tuple[dict[str, Any], dict[str, int]]:
    counts: dict[str, int] = {}
    rewritten = _rewrite_json_value(
        data, context, counts, key=None, rewrite_keys=rewrite_keys
    )
    assert isinstance(rewritten, dict)
    return rewritten, counts


def _rewrite_json_value(
    value: Any,
    context: RewriteContext,
    counts: dict[str, int],
    *,
    key: str | None,
    rewrite_keys: bool,
) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for item_key, item in value.items():
            new_key = str(item_key)
            if rewrite_keys:
                new_key, key_counts = rewrite_text_tokens(
                    new_key, context.all_text_replacements
                )
                merge_counts(counts, key_counts)
            result[new_key] = _rewrite_json_value(
                item,
                context,
                counts,
                key=str(item_key),
                rewrite_keys=rewrite_keys,
            )
        return result
    if isinstance(value, list):
        return [
            _rewrite_json_value(
                item, context, counts, key=key, rewrite_keys=rewrite_keys
            )
            for item in value
        ]
    if not isinstance(value, str):
        return value
    if key in _PATH_KEYS and value:
        replacement = context.chat_path_map.get(value)
        replacement = replacement or context.chat_path_map.get(
            str(Path(value).expanduser())
        )
        if replacement is not None:
            merge_counts(counts, {value: 1})
            return replacement
        return value
    replacements: Mapping[str, str] | None = None
    if key in _BEAD_KEYS:
        replacements = context.bead_map
    elif key in (_NAME_KEYS | _REF_KEYS):
        replacements = context.all_text_replacements
    if replacements is None:
        return value
    updated, text_counts = _rewrite_structured_string(value, replacements)
    merge_counts(counts, text_counts)
    return updated


def _rewrite_structured_string(
    value: str,
    replacements: Mapping[str, str],
) -> tuple[str, dict[str, int]]:
    exact = replacements.get(value)
    if exact is not None:
        return exact, {value: 1}
    return rewrite_text_tokens(value, replacements)


def rewrite_prompt_references(
    text: str,
    context: RewriteContext,
) -> tuple[str, dict[str, int]]:
    replacements = context.all_text_replacements
    if not replacements or not any(
        token in text
        for token in ("%id", "%name", "%n", "%w", "%wait", "#fork", "#resume")
    ):
        return text, {}
    counts: dict[str, int] = {}

    def replace_quoted_colon(match: re.Match[str]) -> str:
        arg, arg_counts = _rewrite_ref_arg(match.group("arg"), replacements)
        merge_counts(counts, arg_counts)
        return f"{match.group('prefix')}`{arg}`"

    def replace_colon(match: re.Match[str]) -> str:
        arg, arg_counts = _rewrite_ref_arg(match.group("arg"), replacements)
        merge_counts(counts, arg_counts)
        return f"{match.group('prefix')}{arg}"

    def replace_paren(match: re.Match[str]) -> str:
        arg, arg_counts = _rewrite_ref_arg(match.group("arg"), replacements)
        merge_counts(counts, arg_counts)
        return f"{match.group('prefix')}{arg})"

    updated = re.sub(
        rf"(?P<prefix>{_PROMPT_DIRECTIVE_RE}:)`(?P<arg>[^`]+)`",
        replace_quoted_colon,
        text,
    )
    updated = re.sub(
        rf"(?P<prefix>{_PROMPT_DIRECTIVE_RE}:)(?P<arg>[^`\s)]+)",
        replace_colon,
        updated,
    )
    updated = re.sub(
        rf"(?P<prefix>{_PROMPT_DIRECTIVE_RE}\()(?P<arg>[^)]*)\)",
        replace_paren,
        updated,
    )
    return updated, counts


def _rewrite_ref_arg(
    arg: str,
    replacements: Mapping[str, str],
) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    parts = arg.split(",")
    out: list[str] = []
    for part in parts:
        leading_len = len(part) - len(part.lstrip())
        trailing_len = len(part) - len(part.rstrip())
        leading = part[:leading_len]
        trailing = part[len(part) - trailing_len :] if trailing_len else ""
        core = part.strip()
        updated, item_counts = _rewrite_structured_string(core, replacements)
        merge_counts(counts, item_counts)
        out.append(f"{leading}{updated}{trailing}")
    return ",".join(out), counts


def rewrite_text_tokens(
    text: str,
    replacements: Mapping[str, str],
) -> tuple[str, dict[str, int]]:
    if not replacements:
        return text, {}
    outcome = rewrite_id_tokens(text, dict(replacements))
    return outcome.text, outcome.replacement_counts


def contains_any_old_token(text: str, context: RewriteContext) -> bool:
    return any(token in text for token in context.all_text_replacements)

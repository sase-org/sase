"""JSON encoding and validation for ACE update-toast receipts."""

from __future__ import annotations

from typing import Any

from sase.ace._update_receipt_models import (
    FORMAT_VERSION,
    LEGACY_FORMAT_VERSION,
    MAX_COMMIT_GROUPS,
    MAX_PROVIDER_LINES,
    ProviderUpdateReceiptResult,
    ProviderReceiptStatus,
    ReceiptKind,
    RepoCommitGroup,
    UpdateToastReceipt,
    UpdateVersionTransition,
)
from sase.agent_clis.models import UpdateResultStatus
from sase.dev_update.models import RepoCommit, RepoCommitLog, RepoDiffStat


def receipt_to_json(receipt: UpdateToastReceipt) -> dict[str, Any]:
    return {
        "format": receipt.format,
        "created_at": receipt.created_at,
        "kind": receipt.kind,
        "primary": _transition_to_json(receipt.primary),
        "plugins": [_transition_to_json(plugin) for plugin in receipt.plugins],
        "plugin_overflow": receipt.plugin_overflow,
        "plugin_overflow_diffstat": _diffstat_to_json(receipt.plugin_overflow_diffstat),
        "dependency_count": receipt.dependency_count,
        "commit_groups": [
            _commit_group_to_json(group) for group in receipt.commit_groups
        ],
        "commit_group_overflow": receipt.commit_group_overflow,
        "provider_results": [
            _provider_result_to_json(result) for result in receipt.provider_results
        ],
        "provider_overflow": receipt.provider_overflow,
    }


def _commit_group_to_json(group: RepoCommitGroup) -> dict[str, object]:
    return {
        "label": group.label,
        "total": group.commits.total,
        "commits": [
            {"short_sha": commit.short_sha, "subject": commit.subject}
            for commit in group.commits.commits
        ],
    }


def _provider_result_to_json(
    result: ProviderUpdateReceiptResult,
) -> dict[str, object]:
    return {
        "name": result.name,
        "display_name": result.display_name,
        "status": result.status,
        "old_version": result.old_version,
        "new_version": result.new_version,
        "reason": result.reason,
        "docs_url": result.docs_url,
        "command": list(result.command) if result.command is not None else None,
        "suggested_command": (
            list(result.suggested_command)
            if result.suggested_command is not None
            else None
        ),
    }


def _transition_to_json(
    transition: UpdateVersionTransition | None,
) -> dict[str, object] | None:
    if transition is None:
        return None
    return {
        "name": transition.name,
        "old": transition.old,
        "new": transition.new,
        "diffstat": _diffstat_to_json(transition.diffstat),
    }


def receipt_from_json(payload: object) -> UpdateToastReceipt | None:
    if not isinstance(payload, dict):
        return None
    format_version = payload.get("format")
    if (
        isinstance(format_version, bool)
        or not isinstance(format_version, int)
        or not LEGACY_FORMAT_VERSION <= format_version <= FORMAT_VERSION
    ):
        return None
    created_at = _float_value(payload.get("created_at"))
    kind = payload.get("kind")
    if created_at is None or kind not in {
        "managed",
        "dev",
        "mode_switch_dev",
        "mode_switch_pypi",
    }:
        return None
    receipt_kind: ReceiptKind = kind  # type: ignore[assignment]
    primary = _transition_from_json(payload.get("primary"))
    if payload.get("primary") is not None and primary is None:
        return None
    plugins_payload = payload.get("plugins")
    if not isinstance(plugins_payload, list):
        return None
    plugins: list[UpdateVersionTransition] = []
    for item in plugins_payload:
        plugin = _transition_from_json(item)
        if plugin is None:
            return None
        plugins.append(plugin)
    plugin_overflow = _nonnegative_int(payload.get("plugin_overflow"))
    dependency_count = _nonnegative_int(payload.get("dependency_count"))
    if plugin_overflow is None or dependency_count is None:
        return None
    plugin_overflow_diffstat = _diffstat_from_json(
        payload.get("plugin_overflow_diffstat")
    )
    commit_groups: tuple[RepoCommitGroup, ...] = ()
    commit_group_overflow = 0
    if "commit_groups" in payload:
        groups_payload = payload.get("commit_groups")
        if (
            not isinstance(groups_payload, list)
            or len(groups_payload) > MAX_COMMIT_GROUPS
        ):
            return None
        decoded_groups: list[RepoCommitGroup] = []
        for item in groups_payload:
            group = _commit_group_from_json(item)
            if group is None:
                return None
            decoded_groups.append(group)
        decoded_commit_overflow = _nonnegative_int(payload.get("commit_group_overflow"))
        if decoded_commit_overflow is None:
            return None
        commit_groups = tuple(decoded_groups)
        commit_group_overflow = decoded_commit_overflow
    provider_results: tuple[ProviderUpdateReceiptResult, ...] = ()
    provider_overflow = 0
    if format_version >= 2:
        provider_payload = payload.get("provider_results")
        if (
            not isinstance(provider_payload, list)
            or len(provider_payload) > MAX_PROVIDER_LINES
        ):
            return None
        decoded_provider_results: list[ProviderUpdateReceiptResult] = []
        for item in provider_payload:
            provider_result = _provider_result_from_json(item)
            if provider_result is None:
                return None
            decoded_provider_results.append(provider_result)
        provider_results = tuple(decoded_provider_results)
        decoded_overflow = _nonnegative_int(payload.get("provider_overflow"))
        if decoded_overflow is None:
            return None
        provider_overflow = decoded_overflow
    return UpdateToastReceipt(
        kind=receipt_kind,
        created_at=created_at,
        primary=primary,
        plugins=tuple(plugins),
        plugin_overflow=plugin_overflow,
        plugin_overflow_diffstat=plugin_overflow_diffstat,
        dependency_count=dependency_count,
        commit_groups=commit_groups,
        commit_group_overflow=commit_group_overflow,
        provider_results=provider_results,
        provider_overflow=provider_overflow,
        format=format_version,
    )


def _commit_group_from_json(payload: object) -> RepoCommitGroup | None:
    if not isinstance(payload, dict):
        return None
    label = payload.get("label")
    total = _nonnegative_int(payload.get("total"))
    commits_payload = payload.get("commits")
    if (
        not isinstance(label, str)
        or not label
        or total is None
        or not isinstance(commits_payload, list)
        or len(commits_payload) > total
    ):
        return None
    commits: list[RepoCommit] = []
    for item in commits_payload:
        if not isinstance(item, dict):
            return None
        short_sha = item.get("short_sha")
        subject = item.get("subject")
        if (
            not isinstance(short_sha, str)
            or not short_sha
            or not isinstance(subject, str)
            or not subject
        ):
            return None
        commits.append(RepoCommit(short_sha=short_sha, subject=subject))
    return RepoCommitGroup(
        label=label,
        commits=RepoCommitLog(total=total, commits=tuple(commits)),
    )


def _provider_result_from_json(
    payload: object,
) -> ProviderUpdateReceiptResult | None:
    if not isinstance(payload, dict):
        return None
    name = payload.get("name")
    display_name = payload.get("display_name")
    status = payload.get("status")
    if (
        not isinstance(name, str)
        or not name
        or not isinstance(display_name, str)
        or not display_name
        or status not in {item.value for item in UpdateResultStatus}
    ):
        return None
    command = _command_from_json(payload.get("command"))
    if payload.get("command") is not None and command is None:
        return None
    suggested = _command_from_json(payload.get("suggested_command"))
    if payload.get("suggested_command") is not None and suggested is None:
        return None
    for key in ("old_version", "new_version", "reason", "docs_url"):
        value = payload.get(key)
        if value is not None and (not isinstance(value, str) or not value):
            return None
    typed_status: ProviderReceiptStatus = status  # type: ignore[assignment]
    return ProviderUpdateReceiptResult(
        name=name,
        display_name=display_name,
        status=typed_status,
        old_version=_optional_str(payload.get("old_version")),
        new_version=_optional_str(payload.get("new_version")),
        reason=_optional_str(payload.get("reason")),
        docs_url=_optional_str(payload.get("docs_url")),
        command=command,
        suggested_command=suggested,
    )


def _command_from_json(payload: object) -> tuple[str, ...] | None:
    if not isinstance(payload, list) or not payload:
        return None
    if any(not isinstance(part, str) or not part for part in payload):
        return None
    return tuple(payload)


def _transition_from_json(payload: object) -> UpdateVersionTransition | None:
    if not isinstance(payload, dict):
        return None
    name = payload.get("name")
    old = _optional_str(payload.get("old"))
    new = _optional_str(payload.get("new"))
    if not isinstance(name, str) or not name:
        return None
    if old is None and new is None:
        return None
    return UpdateVersionTransition(
        name=name,
        old=old,
        new=new,
        diffstat=_diffstat_from_json(payload.get("diffstat")),
    )


def _diffstat_to_json(diffstat: RepoDiffStat | None) -> dict[str, int] | None:
    if diffstat is None:
        return None
    return {
        "files_changed": diffstat.files_changed,
        "insertions": diffstat.insertions,
        "deletions": diffstat.deletions,
    }


def _diffstat_from_json(payload: object) -> RepoDiffStat | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        return None
    files_changed = _nonnegative_int(payload.get("files_changed"))
    insertions = _nonnegative_int(payload.get("insertions"))
    deletions = _nonnegative_int(payload.get("deletions"))
    if files_changed is None or insertions is None or deletions is None:
        return None
    return RepoDiffStat(
        files_changed=files_changed,
        insertions=insertions,
        deletions=deletions,
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value:
        return value
    return None


def _float_value(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None

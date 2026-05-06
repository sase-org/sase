"""Attachment manifest building for mobile notification bridge rows."""

from __future__ import annotations

import json
from pathlib import Path

from sase.integrations._mobile_notification_models import (
    MobileAttachmentManifest,
    MobileNotificationBridgeRow,
)
from sase.integrations._mobile_notification_paths import normalize_home_path


def build_mobile_attachment_manifests(
    notification: MobileNotificationBridgeRow,
    *,
    max_attachment_bytes: int = 20 * 1024 * 1024,
) -> list[MobileAttachmentManifest]:
    """Build conservative mobile attachment manifests for a bridge row."""
    manifests: list[MobileAttachmentManifest] = []
    for index, path in enumerate(_attachment_candidate_paths(notification)):
        display_name = normalize_home_path(path)
        kind, content_type, can_inline = _classify_attachment(display_name)
        host_path = Path(path).expanduser()
        path_available = host_path.exists()
        byte_size: int | None = None
        downloadable = False
        if (
            path_available
            and host_path.is_file()
            and not _unsafe_attachment_path(host_path)
        ):
            try:
                byte_size = host_path.stat().st_size
            except OSError:
                byte_size = None
            else:
                downloadable = byte_size <= max_attachment_bytes
        elif path_available and host_path.is_dir():
            kind = "directory"
            content_type = None
            can_inline = False

        manifests.append(
            MobileAttachmentManifest(
                id=f"att_{index:03}",
                token=None,
                display_name=display_name,
                kind=kind,
                content_type=content_type,
                byte_size=byte_size,
                source_notification_id=notification.id,
                downloadable=downloadable,
                download_requires_auth=True,
                can_inline=can_inline,
                path_available=path_available,
            )
        )
    return manifests


def _attachment_candidate_paths(
    notification: MobileNotificationBridgeRow,
) -> list[str]:
    paths: list[str] = []
    for path in notification.host_files:
        _append_unique_path(paths, path)
    for key in (
        "plan_file",
        "pdf_path",
        "plan_pdf_path",
        "diff_path",
        "error_report_path",
        "project_file",
        "agent_project_file",
        "output_path",
        "response_path",
        "image_path",
    ):
        action_path = notification.host_action_data.get(key)
        if action_path:
            _append_unique_path(paths, action_path)

    if notification.action == "PlanApproval":
        if response_dir := notification.host_action_data.get("response_dir"):
            _append_unique_path(
                paths, str(Path(response_dir).expanduser() / "plan_request.json")
            )
    elif notification.action == "HITL":
        if artifacts_dir := notification.host_action_data.get("artifacts_dir"):
            request_path = Path(artifacts_dir).expanduser() / "hitl_request.json"
            _append_unique_path(paths, str(request_path))
            for path in _hitl_path_typed_outputs(request_path):
                _append_unique_path(paths, path)
    elif notification.action == "UserQuestion":
        if response_dir := notification.host_action_data.get("response_dir"):
            _append_unique_path(
                paths, str(Path(response_dir).expanduser() / "question_request.json")
            )
    return paths


def _append_unique_path(paths: list[str], path: str) -> None:
    value = path.strip()
    if value and value not in paths:
        paths.append(value)


def _hitl_path_typed_outputs(request_path: Path) -> list[str]:
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    if not isinstance(request, dict):
        return []
    output_types = request.get("output_types")
    output = request.get("output")
    if not isinstance(output_types, dict) or not isinstance(output, dict):
        return []
    paths: list[str] = []
    for field_name, field_type in output_types.items():
        if field_type != "path":
            continue
        value = output.get(field_name)
        if isinstance(value, str):
            paths.append(value)
    return paths


def _unsafe_attachment_path(path: Path) -> bool:
    if any(part == ".." for part in path.parts):
        return True
    try:
        if path.is_symlink():
            return True
        for parent in path.parents:
            if parent.is_symlink():
                return True
    except OSError:
        return True
    return False


def _classify_attachment(display_name: str) -> tuple[str, str | None, bool]:
    lower = display_name.lower()
    if lower.endswith((".md", ".markdown")):
        return "markdown", "text/markdown", True
    if lower.endswith(".pdf"):
        return "pdf", "application/pdf", True
    if lower.endswith((".diff", ".patch")):
        return "diff", "text/x-diff", True
    if lower.endswith(".png"):
        return "image", "image/png", True
    if lower.endswith((".jpg", ".jpeg")):
        return "image", "image/jpeg", True
    if lower.endswith(".json"):
        return "json", "application/json", True
    if lower.endswith((".txt", ".log")):
        return "text", "text/plain", True
    return "unknown", None, False

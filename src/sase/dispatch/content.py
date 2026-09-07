"""Explicit-open remote content client for fleet handles."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sase.dispatch.config import require_remote_dispatch_enabled
from sase.dispatch.federation import build_federation_facade

_FLEET_SCHEMA_VERSION = 1
_DEFAULT_LIMIT = 64 * 1024
_MAX_LIMIT = 256 * 1024


class RemoteContentError(RuntimeError):
    """Raised when remote content cannot be fetched or validated."""


@dataclass(frozen=True)
class RemoteContentChunk:
    """One digest-validated content range."""

    handle_id: str
    kind: str | None
    offset: int
    data: bytes
    digest: str
    eof: bool
    next_offset: int | None
    supports_growth: bool
    origin_alias: str | None
    observed_at_unix: float | None


class RemoteContentClient:
    """Fetch bounded remote content ranges and cache validated chunks."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str, str, int, int], RemoteContentChunk] = {}

    def open_handle(
        self,
        handle: Mapping[str, Any],
        *,
        row_revision: Mapping[str, Any],
        offset: int = 0,
        limit: int | None = None,
        origin_alias: str | None = None,
        observed_at_unix: float | None = None,
        timeout_seconds: float | None = None,
    ) -> RemoteContentChunk:
        """Read one bounded range for *handle* and validate its digest."""
        require_remote_dispatch_enabled()
        handle_id = str(handle.get("id") or "")
        if not handle_id:
            raise RemoteContentError("content handle id is required")
        digest = str(handle.get("digest") or "")
        revision_key = str(row_revision.get("revision") or "")
        byte_limit = min(limit or _DEFAULT_LIMIT, _MAX_LIMIT)
        cache_key = (handle_id, revision_key, digest, offset, byte_limit)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        response = build_federation_facade().content_range_sync(
            {
                "schema_version": _FLEET_SCHEMA_VERSION,
                "handle_id": handle_id,
                "row_revision": dict(row_revision),
                "offset": offset,
                "limit": byte_limit,
            },
            timeout_seconds=timeout_seconds,
        )
        payload = _first_host_payload(response)
        data = _decode_and_validate(payload, expected_digest=digest or None)
        chunk = RemoteContentChunk(
            handle_id=handle_id,
            kind=str(handle.get("kind")) if handle.get("kind") else None,
            offset=int(payload.get("offset") or offset),
            data=data,
            digest=str(payload.get("sha256") or digest),
            eof=bool(payload.get("eof")),
            next_offset=(
                int(payload["next_offset"])
                if payload.get("next_offset") is not None
                else None
            ),
            supports_growth=bool(
                payload.get("supports_growth") or handle.get("supports_growth")
            ),
            origin_alias=origin_alias,
            observed_at_unix=observed_at_unix,
        )
        self._cache[cache_key] = chunk
        return chunk

    def continue_tail(
        self,
        previous: RemoteContentChunk,
        handle: Mapping[str, Any],
        *,
        row_revision: Mapping[str, Any],
        timeout_seconds: float | None = None,
    ) -> RemoteContentChunk:
        """Fetch the next growing range without refetching history."""
        if previous.eof and not previous.supports_growth:
            return previous
        next_offset = previous.next_offset
        if next_offset is None:
            next_offset = previous.offset + len(previous.data)
        return self.open_handle(
            handle,
            row_revision=row_revision,
            offset=next_offset,
            origin_alias=previous.origin_alias,
            observed_at_unix=previous.observed_at_unix,
            timeout_seconds=timeout_seconds,
        )


def _first_host_payload(response: Mapping[str, Any]) -> dict[str, Any]:
    hosts = response.get("hosts")
    if isinstance(hosts, list) and hosts and isinstance(hosts[0], Mapping):
        host = hosts[0]
        error = host.get("error")
        if isinstance(error, Mapping):
            raise RemoteContentError(str(error.get("message") or "content read failed"))
        payload = host.get("payload")
        if isinstance(payload, Mapping):
            return dict(payload)
    if isinstance(response.get("data_base64"), str):
        return dict(response)
    raise RemoteContentError("federation content range returned no payload")


def _decode_and_validate(
    payload: Mapping[str, Any],
    *,
    expected_digest: str | None,
) -> bytes:
    encoded = payload.get("data_base64")
    if not isinstance(encoded, str):
        raise RemoteContentError("content range is missing data_base64")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise RemoteContentError("content range is not valid base64") from exc
    digest = hashlib.sha256(data).hexdigest()
    reported = str(payload.get("sha256") or "")
    if reported and reported != digest:
        raise RemoteContentError("content digest does not match returned bytes")
    if expected_digest and expected_digest != digest and not reported:
        raise RemoteContentError("content digest does not match handle")
    return data


__all__ = ["RemoteContentChunk", "RemoteContentClient", "RemoteContentError"]

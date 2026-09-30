"""Anonymous remote-visibility probe for attachment provenance.

A remote is public iff an unauthenticated smart-HTTP
``GET <https-url>/info/refs?service=git-upload-pack`` succeeds. The probe
runs with no credentials, no netrc, and a three-second timeout. Results
cache under the SASE home: public for 24 h, private for 1 h, unknown not
at all. Any uncertainty resolves to ``unknown`` (which means private).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from collections.abc import Callable

_PUBLIC_TTL_SECONDS = 24 * 3600
_PRIVATE_TTL_SECONDS = 3600

_PROBER: Callable[[str], str] | None = None


def set_remote_visibility_prober(
    prober: Callable[[str], str] | None,
) -> None:
    """Inject a fake ``origin_url -> visibility`` prober (tests only)."""
    global _PROBER
    _PROBER = prober


def resolve_remote_visibility(origin_url: str | None) -> str:
    """Return ``public`` | ``private`` | ``unknown`` for *origin_url*."""
    if not origin_url or not origin_url.strip():
        return "unknown"
    if _PROBER is not None:
        try:
            result = _PROBER(origin_url)
        except Exception:
            return "unknown"
        return result if result in ("public", "private", "unknown") else "unknown"
    from sase._git_remote import parse_hosted_git_remote

    parsed = parse_hosted_git_remote(origin_url)
    if parsed is None:
        return "unknown"
    https_url = f"https://{parsed.host}/{parsed.repo}/info/refs?service=git-upload-pack"
    cached = _read_cache(https_url)
    if cached is not None:
        return cached
    visibility = _probe_https(https_url)
    _write_cache(https_url, visibility)
    return visibility


def _probe_https(url: str) -> str:
    """Probe one smart-HTTP URL without credentials; unknown on any doubt."""
    try:
        opener = urllib.request.build_opener(
            urllib.request.HTTPHandler(),
            urllib.request.HTTPSHandler(),
        )
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "sase-attachment-probe"},
            unverifiable=False,
        )
        with opener.open(request, timeout=3) as response:
            status = int(getattr(response, "status", 200) or 200)
            content_type = str(
                response.headers.get("Content-Type", "")
                if hasattr(response, "headers")
                else ""
            )
            if status == 200 and (
                "application/x-git-upload-pack-advertisement" in content_type
            ):
                return "public"
            if status in (401, 403, 404):
                return "private"
            return "unknown"
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 404):
            return "private"
        return "unknown"
    except Exception:
        return "unknown"


def _cache_path() -> Path:
    from sase.core.paths import sase_home

    return sase_home() / "remote_visibility_cache.json"


def _read_cache(url: str) -> str | None:
    try:
        raw = _cache_path().read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    entry = data.get(url)
    if not isinstance(entry, dict):
        return None
    visibility = entry.get("visibility")
    expires_at = entry.get("expires_at")
    if visibility not in ("public", "private"):
        return None
    if not isinstance(expires_at, (int, float)):
        return None
    if time.time() >= float(expires_at):
        return None
    return str(visibility)


def _write_cache(url: str, visibility: str) -> None:
    if visibility == "unknown":
        return
    ttl = _PUBLIC_TTL_SECONDS if visibility == "public" else _PRIVATE_TTL_SECONDS
    try:
        path = _cache_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        data[url] = {"visibility": visibility, "expires_at": time.time() + ttl}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


__all__ = [
    "resolve_remote_visibility",
    "set_remote_visibility_prober",
]

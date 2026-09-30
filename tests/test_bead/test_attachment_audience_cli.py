"""Audience CLI: beta flag, config, validation, fast path, and provenance.

Synthetic inputs only; no network. The core decision table itself lives in
sase-core and is covered there; these tests cover the Python wiring both
with the flag on and off.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_public_max_bytes_default_and_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    from sase.bead import config as bead_config

    monkeypatch.delenv("SASE_HOME", raising=False)
    # Default is 25 MiB.
    assert bead_config.DEFAULT_ATTACHMENT_PUBLIC_MAX_BYTES == 26214400
    assert bead_config.get_attachment_public_max_bytes() == 26214400


def test_public_max_bytes_upper_bound_falls_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.bead import config as bead_config

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    # Above 95 MiB fails open to the default.
    monkeypatch.setattr(
        bead_config,
        "_attachment_config",
        lambda: {"public_max_bytes": 100 * 1024 * 1024},
    )
    assert bead_config.get_attachment_public_max_bytes() == 26214400
    # Malformed values fail open too.
    monkeypatch.setattr(
        bead_config, "_attachment_config", lambda: {"public_max_bytes": True}
    )
    assert bead_config.get_attachment_public_max_bytes() == 26214400
    monkeypatch.setattr(
        bead_config, "_attachment_config", lambda: {"public_max_bytes": -5}
    )
    assert bead_config.get_attachment_public_max_bytes() == 26214400


def test_audience_flag_validation() -> None:
    from sase.bead.attachments import audience as _audience

    # Mutually exclusive.
    with pytest.raises(SystemExit):
        _audience.validate_audience_flags(
            private=True,
            public=True,
            allow_sensitive=False,
            local_only=False,
            has_attachments=True,
        )
    # -W with -L is an error.
    with pytest.raises(SystemExit):
        _audience.validate_audience_flags(
            private=False,
            public=True,
            allow_sensitive=False,
            local_only=True,
            has_attachments=True,
        )
    # -W with -S is an error (-S is private only).
    with pytest.raises(SystemExit):
        _audience.validate_audience_flags(
            private=False,
            public=True,
            allow_sensitive=True,
            local_only=False,
            has_attachments=True,
        )
    # -K with -L is fine.
    assert (
        _audience.validate_audience_flags(
            private=True,
            public=False,
            allow_sensitive=False,
            local_only=True,
            has_attachments=True,
        )
        == []
    )
    # Dim warning when flags given but nothing attached.
    warnings = _audience.validate_audience_flags(
        private=True,
        public=False,
        allow_sensitive=False,
        local_only=False,
        has_attachments=False,
    )
    assert warnings and warnings[0].startswith("hint: ")
    # No warning when attachments present.
    assert (
        _audience.validate_audience_flags(
            private=True,
            public=False,
            allow_sensitive=False,
            local_only=False,
            has_attachments=True,
        )
        == []
    )


def test_requested_from_flags() -> None:
    from sase.bead.attachments import audience as _audience

    assert _audience.requested_from_flags() == "auto"
    assert _audience.requested_from_flags(private=True) == "private"
    assert _audience.requested_from_flags(public=True) == "public"
    assert _audience.requested_from_flags(local_only=True) == "local_only"
    # -K with -L resolves to local-only (which implies private).
    assert _audience.requested_from_flags(private=True, local_only=True) == "local_only"


def test_fast_path_falls_through_for_audience_flags() -> None:
    from sase.main.bead_fast_path import _argv_has_audience_flag

    # Audience flags must stay on the Python surface; the detector drives
    # the fallthrough in try_handle_bead_fast_path.
    for verb in ("note", "close", "update", "+1", "attach"):
        for flag in ("-K", "--private", "-W", "--public", "-y", "--yes"):
            assert _argv_has_audience_flag([verb, "sase-ab", flag])
    assert _argv_has_audience_flag(["note", "sase-ab", "-K"])
    assert _argv_has_audience_flag(["attach", "sase-ab", "--public"])
    assert not _argv_has_audience_flag(["note", "sase-ab", "hello"])
    assert not _argv_has_audience_flag(["note", "sase-ab", "-n", "hi"])


def test_visibility_model_and_codec() -> None:
    from sase.bead.model import BeadNoteAttachment
    from sase.bead import note_codec as codec

    public = BeadNoteAttachment(
        name="a.txt",
        sha256="a" * 64,
        size_bytes=3,
        mime_type="text/plain",
        visibility="public",
    )
    assert public.effective_visibility() == "public"
    encoded = codec.attachment_to_dict(public)
    assert encoded["visibility"] == "public"
    decoded = codec.attachments_from_list([encoded])
    assert decoded[0].visibility == "public"
    # Absent means private; unknown values reduce to private (None).
    legacy = {
        "name": "b.txt",
        "sha256": "b" * 64,
        "size_bytes": 1,
        "mime_type": "text/plain",
    }
    assert codec.attachments_from_list([legacy])[0].effective_visibility() == "private"
    unknown = dict(legacy, visibility="future-value")
    assert codec.attachments_from_list([unknown])[0].visibility is None
    with pytest.raises(ValueError):
        BeadNoteAttachment(
            name="c.txt",
            sha256="c" * 64,
            size_bytes=1,
            mime_type="text/plain",
            visibility="everyone",
        ).validate()


def test_owner_only_and_actor(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from sase.bead.attachments import provenance as prov

    secret = tmp_path / "token"
    secret.write_text("x")
    secret.chmod(0o600)
    assert prov.is_owner_only(secret) is True
    open_file = tmp_path / "open.txt"
    open_file.write_text("x")
    open_file.chmod(0o644)
    assert prov.is_owner_only(open_file) is False
    # Actor fails closed to agent.
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.setattr(
        "sase.agent.identity.discover_agent_identity", lambda env=None: None
    )
    assert prov.current_actor() == "human"
    monkeypatch.setenv("SASE_AGENT_NAME", "test-agent")
    assert prov.current_actor() == "agent"


def test_remote_visibility_cache_ttls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.bead.attachments import remote_visibility as rv

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    # Unknown never caches.
    rv._write_cache("https://example.com/r", "unknown")
    assert rv._read_cache("https://example.com/r") is None
    # Public caches for 24h, private for 1h.
    rv._write_cache("https://example.com/pub", "public")
    assert rv._read_cache("https://example.com/pub") == "public"
    rv._write_cache("https://example.com/priv", "private")
    assert rv._read_cache("https://example.com/priv") == "private"
    # Expired entries read as missing.
    path = rv._cache_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["https://example.com/pub"]["expires_at"] = 0
    path.write_text(json.dumps(data), encoding="utf-8")
    assert rv._read_cache("https://example.com/pub") is None
    # Injected prober is used when set; no network in tests.
    rv.set_remote_visibility_prober(lambda url: "public")
    try:
        assert rv.resolve_remote_visibility("git@github.com:o/r.git") == "public"
    finally:
        rv.set_remote_visibility_prober(None)
    assert rv.resolve_remote_visibility(None) == "unknown"
    assert rv.resolve_remote_visibility("not a remote :::") == "unknown"


def test_flag_off_writes_no_visibility(monkeypatch: pytest.MonkeyPatch) -> None:
    from sase.bead.attachments import _authoring_audience
    from sase.bead.attachments import audience as _audience

    monkeypatch.setattr(_audience, "audience_enabled", lambda: False)
    assert _authoring_audience.decide_visibilities({}, {}, {}) == {}


def _blob(sha: str, head: bytes, object_path: str) -> object:
    from types import SimpleNamespace

    return SimpleNamespace(
        sha256=sha, head=head, object_path=object_path, size_bytes=len(head)
    )


def test_agent_widening_refuses_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.bead.attachments import _authoring_audience
    from sase.bead.attachments import audience as _audience

    target = tmp_path / "note.txt"
    target.write_bytes(b"hello audience")
    monkeypatch.setattr(_audience, "audience_enabled", lambda: True)
    monkeypatch.setattr(_audience, "scan_cas_object", lambda *a, **k: None)
    monkeypatch.setattr(
        _audience,
        "decide_audience",
        lambda facts: {
            "outcome": "refuse",
            "rule": "agent_widen",
            "reason": "agent may not widen",
        },
    )
    written: list[tuple[str, str]] = []
    monkeypatch.setattr(
        _audience,
        "write_audience_metadata",
        lambda **kw: written.append((kw["sha256"], kw["rule"])),
    )
    sha = "ab" * 32
    with pytest.raises(SystemExit):
        _authoring_audience.decide_visibilities(
            {0: target},
            {target: _blob(sha, b"hello audience", str(target))},
            {0: "note.txt"},
            audience_requested="public",
            audience_actor="agent",
        )
    # Refusal happens before any local metadata write and names the
    # exact publish command for a human to run later.
    assert written == []
    err = capsys.readouterr().err
    assert "sase bead attachment publish" in err


def test_human_confirm_and_yes_paths(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import sys

    from sase.bead.attachments import audience as _audience

    # -y skips the prompt entirely.
    assert (
        _audience.confirm_widening("a.txt", "r", confirmed=True, actor="human") is True
    )
    # An agent never gets an interactive prompt.
    assert (
        _audience.confirm_widening("a.txt", "r", confirmed=False, actor="agent")
        is False
    )
    # A human without a TTY is treated as unconfirmed.
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert (
        _audience.confirm_widening("a.txt", "r", confirmed=False, actor="human")
        is False
    )
    # A human on a TTY answers the prompt.
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")
    assert (
        _audience.confirm_widening("a.txt", "r", confirmed=False, actor="human") is True
    )
    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")
    assert (
        _audience.confirm_widening("a.txt", "r", confirmed=False, actor="human")
        is False
    )
    capsys.readouterr()


def test_duplicate_digest_intent_stays_private(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from types import SimpleNamespace

    from sase.bead.attachments import _authoring_audience
    from sase.bead.attachments import audience as _audience
    from sase.bead.model import BeadNoteAttachment

    sha = "cd" * 32
    other = "ef" * 32
    private_att = BeadNoteAttachment(
        name="old.txt",
        sha256=sha,
        size_bytes=3,
        mime_type="text/plain",
        visibility="private",
    )
    public_att = BeadNoteAttachment(
        name="pub.txt",
        sha256=other,
        size_bytes=3,
        mime_type="text/plain",
        visibility="public",
    )
    notes = [SimpleNamespace(attachments=[private_att, public_att])]
    assert _audience.duplicate_private_digest([sha, other, "00" * 32], notes) == {sha}
    # End to end: an auto decision that would go public stays private
    # when the same bytes are already stored privately.
    target = tmp_path / "note.txt"
    target.write_bytes(b"hello audience")
    monkeypatch.setattr(_audience, "audience_enabled", lambda: True)
    monkeypatch.setattr(_audience, "scan_cas_object", lambda *a, **k: None)
    monkeypatch.setattr(
        _audience,
        "decide_audience",
        lambda facts: {"outcome": "public", "rule": "table", "reason": "ok"},
    )
    monkeypatch.setattr(_audience, "write_audience_metadata", lambda **kw: None)
    vis = _authoring_audience.decide_visibilities(
        {0: target},
        {target: _blob(sha, b"hello audience", str(target))},
        {0: "note.txt"},
        notes=notes,
        audience_requested="auto",
        audience_actor="human",
    )
    assert vis[target]["visibility"] == "private"
    assert vis[target]["reason"] == "same bytes already stored privately"


def test_stdin_wire_runs_decision_and_scan_flow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import hashlib

    from sase.bead.attachments import audience as _audience
    from sase.bead.attachments import authoring as _authoring

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.setattr(_audience, "audience_enabled", lambda: True)
    data = b"stdin attachment bytes"
    digest = hashlib.sha256(data).hexdigest()
    obj = tmp_path / "cas-object"
    obj.write_bytes(data)
    wire, echo_row = _authoring.stream_attachment_wire(
        "note.txt",
        sha256=digest,
        size_bytes=len(data),
        head=data,
        object_path=obj,
        roster={},
        audience_requested="auto",
        audience_actor="human",
    )
    # The stdin path (source_path=None) runs the same scan/decision flow:
    # visibility is recorded, the echo carries a badge, and the reason
    # never leaks into the descriptor wire.
    assert wire["visibility"] in ("public", "private")
    assert "reason" not in wire
    assert ("🌐" in echo_row) or ("🔒" in echo_row)
    meta_path = _audience.audience_metadata_path(digest)
    assert meta_path.is_file()


def test_remote_https_status_mapping(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import urllib.error
    import urllib.request

    from sase.bead.attachments import remote_visibility as rv

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    seen: list[tuple[urllib.request.Request, float]] = []

    class FakeHeaders:
        def __init__(self, content_type: str) -> None:
            self._content_type = content_type

        def get(self, name: str, default: str = "") -> str:
            assert name == "Content-Type"
            return self._content_type

    class FakeResponse:
        def __init__(self, status: int, content_type: str) -> None:
            self.status = status
            self.headers = FakeHeaders(content_type)

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

    def fake_build_opener(*handlers: object) -> object:
        # No proxy, auth, or credential handlers on the probe opener.
        for handler in handlers:
            assert not isinstance(
                handler,
                (
                    urllib.request.ProxyHandler,
                    urllib.request.HTTPBasicAuthHandler,
                    urllib.request.HTTPDigestAuthHandler,
                ),
            )

        class FakeOpener:
            def open(
                self, request: urllib.request.Request, timeout: float = 0
            ) -> FakeResponse:
                seen.append((request, float(timeout)))
                url = request.full_url
                if "status200-public" in url:
                    return FakeResponse(
                        200, "application/x-git-upload-pack-advertisement"
                    )
                if "status200-other" in url:
                    return FakeResponse(200, "text/plain")
                if "status404" in url:
                    raise urllib.error.HTTPError(url, 404, "nf", None, None)
                if "status500" in url:
                    raise urllib.error.HTTPError(url, 500, "err", None, None)
                raise urllib.error.URLError("down")

        return FakeOpener()

    monkeypatch.setattr(urllib.request, "build_opener", fake_build_opener)
    assert (
        rv.resolve_remote_visibility("https://example.com/status200-public.git")
        == "public"
    )
    assert (
        rv.resolve_remote_visibility("https://example.com/status200-other.git")
        == "unknown"
    )
    assert (
        rv.resolve_remote_visibility("https://example.com/status404.git") == "private"
    )
    assert (
        rv.resolve_remote_visibility("https://example.com/status500.git") == "unknown"
    )
    assert (
        rv.resolve_remote_visibility("https://example.com/unreachable.git") == "unknown"
    )
    # Anonymous probe: no credentials anywhere, three-second timeout.
    assert seen
    for request, timeout in seen:
        assert request.get_header("Authorization") is None
        assert timeout == 3


def test_audience_metadata_written_locally(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import json

    from sase.bead.attachments import audience as _audience

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    sha = "12" * 32
    _audience.write_audience_metadata(
        sha256=sha, rule="table", reason="local reason", explicit=True
    )
    payload = json.loads(_audience.audience_metadata_path(sha).read_text())
    assert payload["rule"] == "table"
    assert payload["reason"] == "local reason"
    assert payload["explicit"] is True
    assert isinstance(payload["scanner_rules_version"], int)

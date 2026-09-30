"""Phase presentation: audience badges, access states, and bead-page embeds.

Covers the ``🌐``/``🔒`` descriptor badges, the ``no_access``/``blocked``/
``origin_only`` fetch states and their badges (plus the ``%dispatch`` hint),
the materialized JSON ``visibility``/``audience_reason`` keys, the raw-URL
builder, and mixed-audience bead pages (public links, capped image embeds,
page prose chips, and no private digests or reasons anywhere).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from sase.bead.attachments.blob_store import BlobStoreError
from sase.bead.model import (
    BeadNote,
    BeadNoteAttachment,
    Issue,
    IssueType,
    Status,
    TaskPlusOneEvidence,
)


def _attachment(
    name: str,
    digest: str,
    *,
    mime_type: str = "text/plain",
    size_bytes: int = 8,
    image: tuple[int, int] | None = None,
    visibility: str | None = None,
    origin: str | None = None,
) -> BeadNoteAttachment:
    return BeadNoteAttachment(
        name=name,
        sha256=digest,
        size_bytes=size_bytes,
        mime_type=mime_type,
        image=image,
        visibility=visibility,
        origin=origin,
    )


def _issue(
    *notes: tuple[str, tuple[BeadNoteAttachment, ...]],
    evidence: tuple[TaskPlusOneEvidence, ...] = (),
) -> Issue:
    return Issue(
        id="sase-zz.1",
        title="presentation target",
        status=Status.OPEN,
        issue_type=IssueType.TASK,
        notes=tuple(
            BeadNote(
                id=f"e{index}",
                timestamp="2026-09-30T00:00:00Z",
                author="tester",
                text=text,
                attachments=manifest,
            )
            for index, (text, manifest) in enumerate(notes, start=1)
        ),
        plus_one_evidence=list(evidence),
    )


class _StubPageLinks:
    """Stand-in attachments-repo resolver for page tests (no network)."""

    def __init__(self, urls: dict[str, str]) -> None:
        self._urls = dict(urls)

    def attachment_url(self, sha256: str, mime_type: str | None = None) -> str | None:
        return self._urls.get(sha256)


# -- descriptor badges ---------------------------------------------------


def test_descriptor_carries_audience_badge() -> None:
    from sase.bead.attachment_presentation import attachment_descriptor

    public = attachment_descriptor(
        name="log.txt",
        mime_type="text/plain",
        image=None,
        size_bytes=8,
        sha256="ab" * 32,
        visibility="public",
    )
    private = attachment_descriptor(
        name="log.txt",
        mime_type="text/plain",
        image=None,
        size_bytes=8,
        sha256="ab" * 32,
        visibility="private",
    )
    absent = attachment_descriptor(
        name="log.txt",
        mime_type="text/plain",
        image=None,
        size_bytes=8,
        sha256="ab" * 32,
    )
    assert public.startswith("🌐 ")
    assert private.startswith("🔒 ")
    assert absent.startswith("🔒 ")
    assert "sha256:" in public and "sha256:" in private


def test_dispatch_fetch_hint() -> None:
    from sase.bead.attachment_presentation import dispatch_fetch_hint

    assert dispatch_fetch_hint("athena") == "fetch via %dispatch:athena from athena"
    assert dispatch_fetch_hint(None) is None
    assert dispatch_fetch_hint("  ") is None


# -- page lines, prose, and embeds ---------------------------------------


def test_page_line_forms() -> None:
    from sase.bead.attachment_presentation import attachment_page_line

    linked = attachment_page_line(
        name="shot.png",
        mime_type="image/png",
        image=(10, 10),
        size_bytes=100,
        visibility="public",
        url="https://raw.githubusercontent.com/o/r/main/shot.png",
    )
    assert linked.startswith("🌐 [shot.png](")
    assert "sha256" not in linked
    unlinked = attachment_page_line(
        name="shot.png",
        mime_type="image/png",
        image=None,
        size_bytes=100,
        visibility="public",
        url=None,
    )
    assert unlinked.startswith("🌐 shot.png")
    assert "http" not in unlinked
    private = attachment_page_line(
        name="shot.png",
        mime_type="image/png",
        image=None,
        size_bytes=100,
    )
    assert private == "🔒 shot.png · image/png · 100 bytes (private attachment)"


def test_page_prose_links_public_and_chips_private() -> None:
    from sase.bead.attachment_presentation import page_prose_with_attachments

    entries = {
        "pub.log": ("public", "https://raw.githubusercontent.com/o/r/main/pub.log"),
        "shot.png": ("public", None),
        "secret.txt": ("private", None),
    }
    out = page_prose_with_attachments(
        "see @attachment:pub.log, @attachment:shot.png, "
        "@attachment:secret.txt, and @attachment:gone.txt.",
        entries,
    )
    assert "@attachment:" not in out
    assert "[pub.log](https://raw.githubusercontent.com/o/r/main/pub.log)" in out
    assert "[shot.png]" in out
    assert "🔒 secret.txt" in out
    assert "[gone.txt]" in out
    assert "sha256" not in out


def test_page_image_embed_gates() -> None:
    from sase.bead.attachment_presentation import page_image_embed

    url = "https://raw.githubusercontent.com/o/r/main/shot.png"
    assert (
        page_image_embed(
            name="shot.png",
            mime_type="image/png",
            size_bytes=100,
            visibility="public",
            url=url,
        )
        == f"![shot.png]({url})"
    )
    assert (
        page_image_embed(
            name="doc.pdf",
            mime_type="application/pdf",
            size_bytes=100,
            visibility="public",
            url=url,
        )
        is None
    )
    assert (
        page_image_embed(
            name="shot.png",
            mime_type="image/png",
            size_bytes=100,
            visibility="private",
            url=url,
        )
        is None
    )
    assert (
        page_image_embed(
            name="shot.png",
            mime_type="image/png",
            size_bytes=100,
            visibility="public",
            url=None,
        )
        is None
    )
    assert (
        page_image_embed(
            name="huge.png",
            mime_type="image/png",
            size_bytes=100 * 1024 * 1024,
            visibility="public",
            url=url,
        )
        is None
    )


def test_render_attachments_mixed_roster() -> None:
    from sase.bead_pages.rendering_identity import render_attachments

    pub = "aa" * 32
    priv = "bb" * 32
    issue = _issue(
        (
            "shot @attachment:pub.png and note @attachment:priv.txt",
            (
                _attachment("pub.png", pub, mime_type="image/png", visibility="public"),
                _attachment("priv.txt", priv, visibility="private"),
            ),
        )
    )
    lines = render_attachments(
        issue,
        attachment_links={
            "pub.png": ("public", "https://raw.githubusercontent.com/o/r/main/p.png"),
            "priv.txt": ("private", None),
        },
    )
    assert lines[1] == "## Attachments"
    assert any(line.startswith("- 🌐 [pub.png](https://") for line in lines)
    assert any("![pub.png](https://raw.githubusercontent.com" in line for line in lines)
    assert any("(private attachment)" in line for line in lines)
    assert not any("sha256" in line or ".sase/" in line for line in lines)


def test_render_attachments_embed_cap_is_four_per_note() -> None:
    from sase.bead_pages.rendering_identity import render_attachments

    manifest = tuple(
        _attachment(
            f"shot{n}.png",
            f"{n:02d}" * 32,
            mime_type="image/png",
            visibility="public",
        )
        for n in range(5)
    )
    issue = _issue(("five @attachment:shot0.png", manifest))
    entries = {
        f"shot{n}.png": ("public", f"https://raw.githubusercontent.com/o/r/{n}.png")
        for n in range(5)
    }
    lines = render_attachments(issue, attachment_links=entries)
    assert sum(line.startswith("![shot") for line in lines) == 4


def test_render_prose_sections_replaces_tokens() -> None:
    from sase.bead_pages.rendering_identity import render_prose_sections

    pub = "aa" * 32
    issue = _issue(
        (
            "see @attachment:pub.png here",
            (_attachment("pub.png", pub, visibility="public"),),
        )
    )
    lines = render_prose_sections(
        issue, attachment_links={"pub.png": ("public", "https://example.com/p.png")}
    )
    body = "\n".join(lines)
    assert "@attachment:" not in body
    assert "[pub.png](https://example.com/p.png)" in body


def test_render_plus_one_evidence_has_no_digest() -> None:
    from sase.bead_pages.rendering_identity import render_plus_one_evidence

    digest = "cc" * 32
    issue = _issue(
        ("plain", ()),
        evidence=(
            TaskPlusOneEvidence(
                timestamp="2026-09-30T00:00:00Z",
                reporter="tester",
                note="repro @attachment:shot.png",
                attachments=(
                    _attachment(
                        "shot.png", digest, mime_type="image/png", visibility="public"
                    ),
                ),
            ),
        ),
    )
    lines = render_plus_one_evidence(
        issue,
        plan_links=None,
        attachment_links={"shot.png": ("public", "https://example.com/s.png")},
    )
    body = "\n".join(lines)
    assert "sha256" not in body
    assert "@attachment:" not in body
    assert "[shot.png](https://example.com/s.png)" in body


def test_page_attachment_entries_only_public_resolves() -> None:
    from sase.bead_pages.rendering_identity import page_attachment_entries

    pub = "aa" * 32
    priv = "bb" * 32
    issue = _issue(
        (
            "both",
            (
                _attachment("pub.png", pub, visibility="public"),
                _attachment("priv.txt", priv, visibility="private"),
            ),
        )
    )
    entries = page_attachment_entries(
        issue, _StubPageLinks({pub: "https://example.com/p.png"})
    )
    assert entries["pub.png"] == ("public", "https://example.com/p.png")
    assert entries["priv.txt"] == ("private", None)


# -- new availability states ---------------------------------------------


class _FakeStore:
    """Duck-typed stand-in for ``GitAttachmentStore`` (no subprocess)."""

    def __init__(
        self,
        objects: dict[str, bytes] | None = None,
        *,
        fetch_error: Exception | None = None,
        label: str = "sase-org/sase--attachments",
    ) -> None:
        self.objects = dict(objects or {})
        self.fetch_error = fetch_error
        self._label = label
        self.name = "git"

    def has(self, sha256: str) -> bool:
        return sha256 in self.objects

    def has_tombstone(self, sha256: str) -> bool:
        return False

    def describe(self) -> str:
        return self._label

    def get(self, sha256: str, dest: object, progress: object = None) -> None:
        if self.fetch_error is not None:
            raise self.fetch_error
        if sha256 not in self.objects:
            raise BlobStoreError(
                f"attachment {sha256[:16]}… is not in fake store", missing=True
            )
        raise AssertionError("unreachable in these tests")


def _cas_with(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, objects: dict[str, bytes]
) -> None:
    from sase.bead.attachments.store import LocalAttachmentStore

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    cas = LocalAttachmentStore()
    cas.ensure_dirs()
    for sha, data in objects.items():
        target = cas.object_path(sha)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        os.chmod(target, 0o444)


def test_state_blocked_from_outbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.attachments.fetch import _FetchContext, attachment_state
    from sase.bead.attachments.outbox import OutboxEntry

    local_data = b"blocked bytes stay local"
    local_sha = hashlib.sha256(local_data).hexdigest()
    remote_sha = hashlib.sha256(b"blocked and missing").hexdigest()
    _cas_with(tmp_path, monkeypatch, {local_sha: local_data})
    context = _FetchContext(
        mode="never",
        store=_FakeStore(),
        outbox={
            local_sha: OutboxEntry(
                digest=local_sha, size_bytes=len(local_data), state="blocked"
            ),
            remote_sha: OutboxEntry(digest=remote_sha, size_bytes=8, state="blocked"),
        },
    )
    assert attachment_state(local_sha, size_bytes=1, context=context) == "blocked"
    assert attachment_state(remote_sha, size_bytes=8, context=context) == "blocked"


def test_state_origin_only_above_git_max(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.attachments.fetch import _FetchContext, attachment_state

    monkeypatch.setattr("sase.bead.config.get_attachment_git_max_bytes", lambda: 10)
    data = b"too big for the git tier"
    sha = hashlib.sha256(data).hexdigest()
    _cas_with(tmp_path, monkeypatch, {sha: data})
    context = _FetchContext(mode="never", store=_FakeStore())
    assert attachment_state(sha, size_bytes=11, context=context) == "origin_only"
    assert attachment_state(sha, size_bytes=9, context=context) == "local_only"


def test_state_no_access_after_denied_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.attachments.fetch import (
        _FetchContext,
        _is_access_denied,
        attachment_state,
        resolve_badge_repo,
    )

    assert _is_access_denied(
        BlobStoreError("ERROR: Repository not found.", transient=True)
    )
    assert _is_access_denied(
        BlobStoreError("could not read Username: terminal prompts disabled")
    )
    assert not _is_access_denied(BlobStoreError("connection timed out"))

    missing = hashlib.sha256(b"grantless object").hexdigest()
    _cas_with(tmp_path, monkeypatch, {})
    store = _FakeStore(
        objects={missing: b"unreachable"},
        fetch_error=BlobStoreError(
            "cannot reach sase-org/sase--attachments: git fetch failed: "
            "ERROR: Repository not found.",
            transient=True,
        ),
    )
    context = _FetchContext(mode="force", store=store)
    assert attachment_state(missing, size_bytes=8, context=context) == "no_access"
    assert resolve_badge_repo(missing, context) == "sase-org/sase--attachments"


def test_badges_for_new_states() -> None:
    from sase.bead.attachments.fetch import attachment_badge

    assert (
        attachment_badge("no_access", repo="o/sase--attachments")
        == "🔒 no access (o/sase--attachments)"
    )
    assert attachment_badge("no_access") == "🔒 no access"
    assert attachment_badge("blocked") == "⛔ blocked by secret scanning"
    assert attachment_badge("origin_only", origin="athena") == "⧉ on athena"


def test_status_lines_origin_only_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.attachment_presentation import attachment_status_lines

    monkeypatch.setattr("sase.bead.config.get_attachment_git_max_bytes", lambda: 10)
    data = b"origin-only bytes"
    sha = hashlib.sha256(data).hexdigest()
    _cas_with(tmp_path, monkeypatch, {sha: data})
    from sase.bead.attachments.fetch import _current, fetch_context

    store = _FakeStore()
    with fetch_context(mode="never"):
        ambient = _current.get()
        assert ambient is not None
        ambient.discover = False
        ambient.store = store
        ambient.stores = [store]
        lines = attachment_status_lines(
            bead_id="sase-zz.1",
            name="huge.bin",
            sha256=sha,
            size_bytes=11,
            origin="athena",
        )
    assert any(line.startswith("⧉ on athena") for line in lines)
    assert "fetch via %dispatch:athena from athena" in lines


# -- JSON visibility and reasons ------------------------------------------


def test_list_json_carries_visibility_and_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.attachments.audience import (
        read_audience_reason,
        write_audience_metadata,
    )
    from sase.bead.cli_attachment import _wire_with_availability

    data = b"decided bytes"
    sha = hashlib.sha256(data).hexdigest()
    _cas_with(tmp_path, monkeypatch, {sha: data})
    assert read_audience_reason(sha) is None
    write_audience_metadata(
        sha256=sha,
        rule="public_evidence",
        reason="clean workspace log",
        explicit=False,
    )
    assert read_audience_reason(sha) == "clean workspace log"
    wire = _wire_with_availability(_attachment("log.txt", sha, visibility="public"))
    assert wire["visibility"] == "public"
    assert wire["audience_reason"] == "clean workspace log"
    legacy = _wire_with_availability(_attachment("old.txt", "dd" * 32))
    assert legacy["visibility"] == "private"
    assert "audience_reason" not in legacy


# -- raw URL builder -------------------------------------------------------


def test_github_raw_url_forms() -> None:
    from sase._git_remote import github_raw_url

    assert (
        github_raw_url(
            "git@github.com:sase-org/sase--attachments.git",
            provider=None,
            branch="main",
            path="files/objects/sha256/ab/abcdef.png",
        )
        == "https://raw.githubusercontent.com/sase-org/sase--attachments"
        "/main/files/objects/sha256/ab/abcdef.png"
    )
    assert (
        github_raw_url(
            "https://git.example.com/o/r.git",
            provider="github",
            branch="main",
            path="files/objects/sha256/ab/abcdef.png",
        )
        == "https://git.example.com/o/r/raw/main/files/objects/sha256/ab/abcdef.png"
    )
    assert (
        github_raw_url(
            "https://git.example.com/o/r.git",
            provider=None,
            branch="main",
            path="files/objects/sha256/ab/abcdef.png",
        )
        is None
    )
    assert (
        github_raw_url(
            "git@github.com:sase-org/sase--attachments.git",
            provider=None,
            branch="",
            path="files/objects/sha256/ab/abcdef.png",
        )
        is None
    )

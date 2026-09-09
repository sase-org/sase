"""Deterministic fixture corpus for pager rendered-link contract tests.

Mirrors the screenshot plan table and capture sources without depending on
live bob-cli / bob-mac-capture checkouts. Inventory/store roots are replaced
by an explicit ``ArtifactRefContext``; the resolver itself is not stubbed.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pytest

from sase.artifact_ref_models import (
    ArtifactRefContext,
    ArtifactRefDocumentOwner,
    ArtifactRefDocumentRoot,
    ArtifactRefProject,
    ArtifactRefRepository,
)
from sase.pager.document import (
    PagerDocument,
    PagerTargetSpan,
    section_target_spans,
    target_resolution_ref,
)
from sase.pager.link_scan import LinkSpanKind

Outcome = Literal[
    "document",
    "url_copy",
    "media",
    "unavailable",
    "ambiguous",
    "filtered",
    "attached",
]

PLAN_CYCLING = "plan:202609/capture_line_edge_cycling.md"
PLAN_PREVIOUS = "plan:202609/capture_ctrl_u_previous_line.md"
PLAN_SPACED = "plan:spaced plan.md#L3"
ROUTER = "Sources/BobMacCapture/CaptureKeyCommandRouter.swift"
CONTROLLER = "Sources/BobMacCapture/CaptureKeyCommandController.swift"
ROUTER_TESTS = "Tests/BobMacCaptureTests/CaptureKeyCommandRouterTests.swift"
CYCLING_URL = (
    "https://github.com/bobs-org/bob-cli/blob/main/.sase/plans/"
    "202609/capture_line_edge_cycling.md"
)
PREVIOUS_URL = (
    "https://github.com/bobs-org/bob-cli/blob/main/.sase/plans/"
    "202609/capture_ctrl_u_previous_line.md"
)
EXACT_URL = "https://example.test/exact?q=1#frag"

_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf"
    b"\xc0\x00\x00\x00\x03\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)

SCREENSHOT_BODY = f"""# capture_line_edge_cycling

See {ROUTER}
and {CONTROLLER}
and {ROUTER_TESTS}.

<!-- sase:links:start -->

## Links

| Relation | Artifact | Why |
| --- | --- | --- |
| implements | [plan:202609/capture_line_edge_cycling.md][2] | screenshot |
| related | [plan:202609/capture_ctrl_u_previous_line.md][3] | screenshot |

[2]: {CYCLING_URL}
[3]: {PREVIOUS_URL}

<!-- sase:links:end -->
"""

KITCHEN_BODY = f"""# kitchen sink

Sigiled quoted @plan:"spaced plan.md"#L3
Unsigiled bead:sase-zz.n0 and sigiled @bead:sase-zz.n0
Patch patch:fixture-patch and @patch:fixture-patch
Agent agent:alice.athena.fixture
Stitch stitch:deadbee1deadbee1
Indexed file:explicit:0123456789abcdef01234567
Markdown dest [not the path](src/lined.swift:4:2)
Sigiled file @src/naïve.md
Unicode line docs/café.md:12
Directory ./docs/assets
Media docs/assets/dot.png
Missing Sources/DoesNotExist.swift
URL {EXACT_URL}
"""


@dataclass(frozen=True, slots=True)
class ExpectedOccurrence:
    """One independently declared rendered target the scanner must not omit."""

    display: str
    kind: str
    resolution_ref: str | None
    outcome: Outcome
    body_contains: tuple[str, ...] = ()
    copy_text: str | None = None
    edit_path: str | None = None
    identity_contains: str | None = None
    unavailable_contains: str | None = None
    owner_checkout: str | None = None
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True, slots=True)
class RenderedLinkCorpus:
    """On-disk fixture tree plus the inventory context that owns it."""

    root: Path
    cwd: Path
    primary: Path
    plans: Path
    capture: Path
    other: Path
    screenshot_plan: Path
    previous_plan: Path
    kitchen_sink: Path
    spaced_plan: Path
    router: Path
    controller: Path
    router_tests: Path
    lined: Path
    naive: Path
    cafe: Path
    assets: Path
    media: Path
    shared_primary: Path
    shared_other: Path
    context: ArtifactRefContext
    other_context: ArtifactRefContext
    filtered_context: ArtifactRefContext

    def context_for(self, directory: Path) -> ArtifactRefContext:
        """Return the inventory that should own *directory*."""
        resolved = directory.expanduser().resolve(strict=False)
        if _is_under(resolved, self.other):
            return self.other_context
        return self.context


def build_corpus(tmp_path: Path) -> RenderedLinkCorpus:
    """Create the screenshot and kitchen-sink fixture tree under *tmp_path*."""
    root = tmp_path / "corpus"
    cwd = root / "cwd"
    primary = root / "bob-cli"
    plans = root / "plans"
    capture = root / "bob-mac-capture"
    other = root / "other-project"
    for path in (cwd, primary, plans, capture, other):
        path.mkdir(parents=True)
        if path is not cwd and path is not plans:
            (path / ".git").mkdir()

    router = _write(
        capture / ROUTER,
        "struct Router {}\n// See Sources/BobMacCapture/"
        "CaptureKeyCommandController.swift\n",
    )
    controller = _write(
        capture / CONTROLLER,
        "struct Controller {}\n",
    )
    router_tests = _write(
        capture / ROUTER_TESTS,
        "struct RouterTests {}\n",
    )
    _write(
        cwd / ROUTER,
        "DECOY cwd router\n",
    )

    screenshot_plan = _write(
        plans / "202609" / "capture_line_edge_cycling.md",
        SCREENSHOT_BODY,
    )
    previous_plan = _write(
        plans / "202609" / "capture_ctrl_u_previous_line.md",
        "# previous line\n",
    )
    spaced_plan = _write(
        plans / "spaced plan.md",
        "line1\nline2\nline3 target\nline4\n",
    )
    _write(plans / "202609" / "secret.md", "filtered\n")

    lined = _write(
        primary / "src" / "lined.swift",
        "one\ntwo\nthree\nfour\nfive\n",
    )
    naive = _write(primary / "src" / "naïve.md", "naive notes\n")
    cafe = _write(
        primary / "docs" / "café.md",
        "\n".join(f"cafe {index}" for index in range(1, 16)) + "\n",
    )
    assets = primary / "docs" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "readme.txt").write_text("asset dir\n", encoding="utf-8")
    media = assets / "dot.png"
    media.write_bytes(_TINY_PNG)
    kitchen_sink = _write(primary / "kitchen.md", KITCHEN_BODY)
    shared_primary = _write(primary / "src" / "shared.py", "from-primary\n")
    shared_other = _write(other / "src" / "shared.py", "from-other\n")

    context = _context(
        plans,
        root,
        repositories=(
            ArtifactRefRepository("bob-cli", checkout_paths=(primary,), kind="primary"),
            ArtifactRefRepository(
                "bob-mac-capture", checkout_paths=(capture,), kind="linked"
            ),
        ),
        project=("bob-cli", "gh_bobs-org__bob-cli"),
    )
    other_context = _context(
        other / "plans",
        root / "other-store",
        repositories=(
            ArtifactRefRepository(
                "other-project", checkout_paths=(other,), kind="primary"
            ),
        ),
        project=("other", "gh_example__other"),
    )
    filtered_context = _context(
        plans,
        root,
        repositories=context.repositories,
        project=("bob-cli", "gh_bobs-org__bob-cli"),
        plan_globs=("202608/**",),
    )
    return RenderedLinkCorpus(
        root=root,
        cwd=cwd,
        primary=primary,
        plans=plans,
        capture=capture,
        other=other,
        screenshot_plan=screenshot_plan,
        previous_plan=previous_plan,
        kitchen_sink=kitchen_sink,
        spaced_plan=spaced_plan,
        router=router,
        controller=controller,
        router_tests=router_tests,
        lined=lined,
        naive=naive,
        cafe=cafe,
        assets=assets,
        media=media,
        shared_primary=shared_primary,
        shared_other=shared_other,
        context=context,
        other_context=other_context,
        filtered_context=filtered_context,
    )


def screenshot_expected(corpus: RenderedLinkCorpus) -> tuple[ExpectedOccurrence, ...]:
    """Independently declared targets for the screenshot plan body."""
    return (
        ExpectedOccurrence(
            display=ROUTER,
            kind=LinkSpanKind.FILE_PATH.value,
            resolution_ref=ROUTER,
            outcome="document",
            body_contains=("struct Router {}",),
            copy_text=str(corpus.router),
            identity_contains=str(corpus.router),
            owner_checkout=str(corpus.capture),
        ),
        ExpectedOccurrence(
            display=CONTROLLER,
            kind=LinkSpanKind.FILE_PATH.value,
            resolution_ref=CONTROLLER,
            outcome="document",
            body_contains=("struct Controller {}",),
            copy_text=str(corpus.controller),
            identity_contains=str(corpus.controller),
        ),
        ExpectedOccurrence(
            display=ROUTER_TESTS,
            kind=LinkSpanKind.FILE_PATH.value,
            resolution_ref=ROUTER_TESTS,
            outcome="document",
            body_contains=("struct RouterTests {}",),
            copy_text=str(corpus.router_tests),
            identity_contains=str(corpus.router_tests),
        ),
        ExpectedOccurrence(
            display="[plan:202609/capture_line_edge_cycling.md][2]",
            kind=LinkSpanKind.ARTIFACT_REF.value,
            resolution_ref=PLAN_CYCLING,
            outcome="document",
            body_contains=("See Sources/BobMacCapture/CaptureKeyCommandRouter.swift",),
            copy_text=PLAN_CYCLING,
            identity_contains=PLAN_CYCLING,
        ),
        ExpectedOccurrence(
            display="[plan:202609/capture_ctrl_u_previous_line.md][3]",
            kind=LinkSpanKind.ARTIFACT_REF.value,
            resolution_ref=PLAN_PREVIOUS,
            outcome="document",
            body_contains=("# previous line",),
            copy_text=PLAN_PREVIOUS,
            identity_contains=PLAN_PREVIOUS,
        ),
        ExpectedOccurrence(
            display=CYCLING_URL,
            kind=LinkSpanKind.URL.value,
            resolution_ref=None,
            outcome="url_copy",
            copy_text=CYCLING_URL,
        ),
        ExpectedOccurrence(
            display=PREVIOUS_URL,
            kind=LinkSpanKind.URL.value,
            resolution_ref=None,
            outcome="url_copy",
            copy_text=PREVIOUS_URL,
        ),
    )


def kitchen_expected(corpus: RenderedLinkCorpus) -> tuple[ExpectedOccurrence, ...]:
    """Independently declared targets for the kitchen-sink document."""
    return (
        ExpectedOccurrence(
            display='@plan:"spaced plan.md"#L3',
            kind=LinkSpanKind.ARTIFACT_REF.value,
            resolution_ref=PLAN_SPACED,
            outcome="document",
            body_contains=("line3 target",),
            copy_text="plan:spaced plan.md#L3",
            edit_path=str(corpus.spaced_plan),
            identity_contains="plan:spaced plan.md",
            line=3,
        ),
        ExpectedOccurrence(
            display="bead:sase-zz.n0",
            kind=LinkSpanKind.ARTIFACT_REF.value,
            resolution_ref="bead:sase-zz.n0",
            outcome="unavailable",
            unavailable_contains="no local bead store",
        ),
        ExpectedOccurrence(
            display="@bead:sase-zz.n0",
            kind=LinkSpanKind.ARTIFACT_REF.value,
            resolution_ref="bead:sase-zz.n0",
            outcome="unavailable",
            unavailable_contains="no local bead store",
        ),
        ExpectedOccurrence(
            display="patch:fixture-patch",
            kind=LinkSpanKind.ARTIFACT_REF.value,
            resolution_ref="patch:fixture-patch",
            outcome="unavailable",
            unavailable_contains="could not be resolved",
        ),
        ExpectedOccurrence(
            display="@patch:fixture-patch",
            kind=LinkSpanKind.ARTIFACT_REF.value,
            resolution_ref="patch:fixture-patch",
            outcome="unavailable",
            unavailable_contains="could not be resolved",
        ),
        ExpectedOccurrence(
            display="agent:alice.athena.fixture",
            kind=LinkSpanKind.ARTIFACT_REF.value,
            resolution_ref="agent:alice.athena.fixture",
            outcome="unavailable",
            unavailable_contains="could not be resolved",
        ),
        ExpectedOccurrence(
            display="stitch:deadbee1deadbee1",
            kind=LinkSpanKind.ARTIFACT_REF.value,
            resolution_ref="stitch:deadbee1deadbee1",
            outcome="unavailable",
            unavailable_contains="no commit matching",
        ),
        ExpectedOccurrence(
            display="file:explicit:0123456789abcdef01234567",
            kind=LinkSpanKind.ARTIFACT_REF.value,
            resolution_ref="file:explicit:0123456789abcdef01234567",
            outcome="unavailable",
            unavailable_contains="could not be resolved",
        ),
        ExpectedOccurrence(
            display="[not the path](src/lined.swift:4:2)",
            kind=LinkSpanKind.FILE_PATH.value,
            resolution_ref="src/lined.swift:4:2",
            outcome="document",
            body_contains=("four",),
            copy_text=str(corpus.lined),
            edit_path=str(corpus.lined),
            identity_contains=str(corpus.lined),
            line=4,
            column=2,
        ),
        ExpectedOccurrence(
            display="@src/naïve.md",
            kind=LinkSpanKind.FILE_PATH.value,
            resolution_ref="src/naïve.md",
            outcome="document",
            body_contains=("naive notes",),
            copy_text=str(corpus.naive),
            edit_path=str(corpus.naive),
            identity_contains=str(corpus.naive),
        ),
        ExpectedOccurrence(
            display="docs/café.md:12",
            kind=LinkSpanKind.FILE_PATH.value,
            resolution_ref="docs/café.md:12",
            outcome="document",
            body_contains=("cafe 12",),
            copy_text=str(corpus.cafe),
            edit_path=str(corpus.cafe),
            identity_contains=str(corpus.cafe),
            line=12,
        ),
        ExpectedOccurrence(
            display="./docs/assets",
            kind=LinkSpanKind.FILE_PATH.value,
            resolution_ref="./docs/assets",
            outcome="document",
            body_contains=("dot.png", "readme.txt"),
            copy_text=str(corpus.assets),
            edit_path=str(corpus.assets),
            identity_contains=str(corpus.assets),
        ),
        ExpectedOccurrence(
            display="docs/assets/dot.png",
            kind=LinkSpanKind.FILE_PATH.value,
            resolution_ref="docs/assets/dot.png",
            outcome="media",
            copy_text=str(corpus.media),
        ),
        ExpectedOccurrence(
            display="Sources/DoesNotExist.swift",
            kind=LinkSpanKind.FILE_PATH.value,
            resolution_ref="Sources/DoesNotExist.swift",
            outcome="unavailable",
            unavailable_contains="not found",
        ),
        ExpectedOccurrence(
            display=EXACT_URL,
            kind=LinkSpanKind.URL.value,
            resolution_ref=None,
            outcome="url_copy",
            copy_text=EXACT_URL,
        ),
    )


def rendered_spans(document: PagerDocument) -> tuple[PagerTargetSpan, ...]:
    """Return merged scanned/attached spans in document order."""
    spans: list[PagerTargetSpan] = []
    for section in document.sections:
        spans.extend(section_target_spans(section, document.origin))
    return tuple(spans)


def assert_expected_rendered(
    document: PagerDocument,
    expected: tuple[ExpectedOccurrence, ...],
) -> None:
    """Fail if the scanner omitted any independently declared occurrence."""
    actual = [
        (span.kind, span.text, target_resolution_ref(span, document.origin))
        for span in rendered_spans(document)
    ]
    actual_keys = {(kind, text) for kind, text, _ref in actual}
    missing = [
        occurrence
        for occurrence in expected
        if (occurrence.kind, occurrence.display) not in actual_keys
    ]
    assert missing == [], f"scanner omitted {missing!r}; actual={actual!r}"
    by_display = {(kind, text): ref for kind, text, ref in actual}
    for occurrence in expected:
        assert by_display[(occurrence.kind, occurrence.display)] == (
            occurrence.resolution_ref
        )


def owner_for_checkout(
    checkout: Path, *, source_reference: str
) -> ArtifactRefDocumentOwner:
    """Build an owner that prefers *checkout* as an attached candidate."""
    return ArtifactRefDocumentOwner(
        source_reference=source_reference,
        source_directory=str(checkout),
        checkout_candidates=(checkout,),
        repository=checkout.name,
    )


def install_inventory(
    monkeypatch: pytest.MonkeyPatch, corpus: RenderedLinkCorpus
) -> None:
    """Replace inventory/store assembly with the corpus context."""

    def fake_context(
        workspace_dir: str | Path,
        workspace_num: int = 1,
        project: str | None = None,
    ) -> ArtifactRefContext:
        del workspace_num, project
        return corpus.context_for(Path(workspace_dir))

    monkeypatch.setattr("sase.artifact_ref_context.artifact_ref_context", fake_context)
    monkeypatch.setattr(
        "sase.pager._resolve_artifact_refs.artifact_ref_context", fake_context
    )
    monkeypatch.chdir(corpus.cwd)


@contextmanager
def forbid_checkout_allocation(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Fail if a label press clones, resets, or allocates a workspace."""

    def boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("label press must not allocate or clean a checkout")

    monkeypatch.setattr(
        "sase.running_field._workspace.get_workspace_directory_for_num",
        boom,
    )
    yield


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def _context(
    plans: Path,
    store: Path,
    *,
    repositories: tuple[ArtifactRefRepository, ...],
    project: tuple[str, str],
    plan_globs: tuple[str, ...] | None = None,
) -> ArtifactRefContext:
    plans.mkdir(parents=True, exist_ok=True)
    name, key = project
    return ArtifactRefContext(
        document_roots=(
            ArtifactRefDocumentRoot("plan", plans, path_globs=plan_globs),
            ArtifactRefDocumentRoot("plans", plans, path_globs=plan_globs),
        ),
        chats_root=store / "chats",
        artifact_index_path=store / "artifacts" / "index.jsonl",
        repositories=repositories,
        projects=(ArtifactRefProject(name=name, key=key),),
    )


__all__ = [
    "CONTROLLER",
    "CYCLING_URL",
    "ExpectedOccurrence",
    "EXACT_URL",
    "KITCHEN_BODY",
    "PLAN_CYCLING",
    "PLAN_PREVIOUS",
    "PLAN_SPACED",
    "PREVIOUS_URL",
    "ROUTER",
    "ROUTER_TESTS",
    "RenderedLinkCorpus",
    "SCREENSHOT_BODY",
    "assert_expected_rendered",
    "build_corpus",
    "forbid_checkout_allocation",
    "install_inventory",
    "kitchen_expected",
    "owner_for_checkout",
    "rendered_spans",
    "screenshot_expected",
]

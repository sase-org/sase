"""On-disk fixture tree assembly for the rendered-link corpus tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sase.artifact_ref_models import (
    ArtifactRefContext,
    ArtifactRefDocumentRoot,
    ArtifactRefProject,
    ArtifactRefRepository,
)

from tests.pager._rendered_link_fixtures import (
    CONTROLLER,
    KITCHEN_BODY,
    LINE_TARGET,
    ROUTER,
    ROUTER_TESTS,
    SCREENSHOT_BODY,
    _TINY_PNG,
)


@dataclass(frozen=True, slots=True)
class RenderedLinkCorpus:
    """On-disk fixture tree plus the inventory context that owns it."""

    root: Path
    cwd: Path
    primary: Path
    plans: Path
    designs: Path
    capture: Path
    other: Path
    screenshot_plan: Path
    previous_plan: Path
    kitchen_sink: Path
    spaced_plan: Path
    router: Path
    controller: Path
    router_tests: Path
    line_targets: Path
    lined: Path
    line_plan: Path
    design_doc: Path
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
    designs = root / "designs"
    capture = root / "bob-mac-capture"
    other = root / "other-project"
    for path in (cwd, primary, plans, designs, capture, other):
        path.mkdir(parents=True)
        if path not in {cwd, plans, designs}:
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
    line_plan = _write(
        plans / "202609" / "line_target_plan.md",
        "\n".join(f"plan line {index}" for index in range(1, 31)) + "\n",
    )
    design_doc = _write(
        designs / "line_target_design.md",
        "\n".join(f"design line {index}" for index in range(1, 51)) + "\n",
    )
    _write(plans / "202609" / "secret.md", "filtered\n")

    lined = _write(
        primary / "src" / "lined.swift",
        "one\ntwo\nthree\nfour\nfive\n",
    )
    line_targets = _write(
        primary / LINE_TARGET,
        "\n".join(f"source line {index}" for index in range(1, 61)) + "\n",
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
        designs=designs,
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
        designs=designs,
        capture=capture,
        other=other,
        screenshot_plan=screenshot_plan,
        previous_plan=previous_plan,
        kitchen_sink=kitchen_sink,
        spaced_plan=spaced_plan,
        router=router,
        controller=controller,
        router_tests=router_tests,
        line_targets=line_targets,
        lined=lined,
        line_plan=line_plan,
        design_doc=design_doc,
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
    designs: Path | None = None,
    plan_globs: tuple[str, ...] | None = None,
) -> ArtifactRefContext:
    plans.mkdir(parents=True, exist_ok=True)
    name, key = project
    document_roots = [
        ArtifactRefDocumentRoot("plan", plans, path_globs=plan_globs),
        ArtifactRefDocumentRoot("plans", plans, path_globs=plan_globs),
    ]
    if designs is not None:
        designs.mkdir(parents=True, exist_ok=True)
        document_roots.append(ArtifactRefDocumentRoot("designs", designs))
    return ArtifactRefContext(
        document_roots=tuple(document_roots),
        chats_root=store / "chats",
        artifact_index_path=store / "artifacts" / "index.jsonl",
        repositories=repositories,
        projects=(ArtifactRefProject(name=name, key=key),),
    )

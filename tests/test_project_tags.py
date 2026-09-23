"""Tests for the Python project-tag backend (D2–D4).

Covers the cached tag catalog, tag expansion equivalence, casefold
resolution, disabled and unknown-anchored vs. unanchored launch policy, alt
fan-out units, the one-target rule, canonical MRU recording input, catalog
caching with a never-building peek, and the launch-query ordering hook in
``canonicalize_project_aliases_in_prompt``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import sase.project_tags.catalog as tag_catalog_module
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.project_accents import PROJECT_ACCENTS, project_accent_index
from sase.project_aliases import canonicalize_project_aliases_in_prompt
from sase.project_tags import (
    ProjectTagCatalog,
    ProjectTagError,
    apply_project_tag_selection,
    build_targets,
    effective_find_vcs_workflow_tag,
    effective_vcs_workflow_tag,
    expand_project_tags,
    find_project_tag_trigger,
    find_project_tags,
    is_project_tag_name,
    known_project_tag_for,
    load_project_tag_catalog,
    peek_project_tag_catalog,
    project_tag_for,
    validate_project_tags_for_launch,
    validate_project_tags_with_catalog,
)
from sase.project_tags.catalog import _clear_project_tag_catalog_cache


def _record(
    project_name: str,
    *,
    aliases: list[str] | None = None,
    display_name: str | None = None,
    state: str = "enabled",
    system_managed: bool = False,
    launchable: bool = True,
) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=project_name,
        project_dir=f"/tmp/projects/{project_name}",
        project_file=f"/tmp/projects/{project_name}/{project_name}.sase",
        archive_file=None,
        workspace_dir=f"/tmp/workspaces/{project_name}",
        state=state,
        state_explicit=False,
        system_managed=system_managed,
        active_claim_count=0,
        launchable=launchable,
        aliases=list(aliases or []),
        warnings=[],
        parse_warnings=[],
        display_name=display_name,
        is_project=state != "sibling",
    )


def _workflow_types() -> dict[str, str]:
    return {
        "sase": "gh",
        "bob": "git",
        "beta": "git",
        "home": "git",
        "gh_acme__widgets": "gh",
    }


def _display_names() -> dict[str, str]:
    return {"gh": "GitHub", "git": "Git (bare)"}


@pytest.fixture()
def tag_catalog() -> ProjectTagCatalog:
    """A fake five-target catalog: sase, bob, widgets, disabled beta, home."""
    records = [
        _record("sase"),
        _record("bob", aliases=["bobby"]),
        _record("gh_acme__widgets", display_name="widgets"),
        _record("beta", state="disabled"),
        _record("home", system_managed=True),
    ]
    workflow_types = _workflow_types()
    display_names = _display_names()

    def _detect(project_file: str) -> str:
        for record in records:
            if record.project_file == project_file:
                return workflow_types[record.project_name]
        raise ValueError(f"unknown project file {project_file}")

    return ProjectTagCatalog(
        targets=tuple(
            build_targets(
                records,
                detect_workflow_type=_detect,
                get_display_name=display_names.get,
            )
        ),
        accent_palette=tuple(PROJECT_ACCENTS),
    )


@pytest.fixture(autouse=True)
def _patched_catalog(tag_catalog: ProjectTagCatalog):
    """Route every catalog load at the fake catalog (real core bindings)."""
    _clear_project_tag_catalog_cache()
    with patch.object(
        tag_catalog_module,
        "load_project_tag_catalog",
        return_value=tag_catalog,
    ):
        yield
    _clear_project_tag_catalog_cache()


# --- Catalog ---------------------------------------------------------------


def test_catalog_targets_carry_d2_fields(tag_catalog: ProjectTagCatalog) -> None:
    by_key = {target.key: target for target in tag_catalog.targets}
    sase = by_key["sase"]
    assert (sase.name, sase.tag, sase.workflow_type) == ("sase", "+sase", "gh")
    assert sase.vcs_ref == "#gh:sase"
    assert sase.provider_display == "GitHub"
    assert sase.state == "enabled"
    assert sase.accent is not None and sase.accent_index is not None
    widgets = by_key["gh_acme__widgets"]
    assert (widgets.name, widgets.tag) == ("widgets", "+widgets")
    beta = by_key["beta"]
    assert beta.state == "disabled"
    assert beta.accent is None and beta.accent_index is None
    home = by_key["home"]
    assert home.state == "system"
    assert home.accent is None and home.accent_index is None


def test_catalog_wire_targets_match_core_shape(
    tag_catalog: ProjectTagCatalog,
) -> None:
    assert tag_catalog.wire_targets()[0] == {
        "key": "beta",
        "name": "beta",
        "aliases": [],
        "workflow_type": "git",
        "state": "disabled",
        "workspace_dir": "/tmp/workspaces/beta",
    }


def test_catalog_known_tags_are_sorted(tag_catalog: ProjectTagCatalog) -> None:
    assert tag_catalog.known_tags() == [
        "+beta",
        "+bob",
        "+home",
        "+sase",
        "+widgets",
    ]


def test_tag_name_grammar() -> None:
    assert is_project_tag_name("sase")
    assert is_project_tag_name("bob-cli")
    assert is_project_tag_name("a")
    assert not is_project_tag_name("1abc")
    assert not is_project_tag_name("sase,")
    assert not is_project_tag_name("trailing.")
    assert not is_project_tag_name("trailing-")


# --- Expansion -------------------------------------------------------------


def test_expand_rewrites_tag_to_canonical_key() -> None:
    assert expand_project_tags("+sase do x") == "#gh:sase do x"
    assert expand_project_tags("+widgets do x") == "#gh:gh_acme__widgets do x"


def test_expand_is_case_insensitive() -> None:
    assert expand_project_tags("+Sase do x") == "#gh:sase do x"


def test_expand_leaves_unknown_tags_verbatim() -> None:
    assert expand_project_tags("+ssae do x") == "+ssae do x"


def test_expand_ignores_non_tags() -> None:
    assert expand_project_tags("C++ and a+b") == "C++ and a+b"
    assert expand_project_tags("no plus here") == "no plus here"


def test_find_project_tags_reports_anchored_spans() -> None:
    assert find_project_tags("no plus here") == []
    (span,) = find_project_tags("+sase do x")
    assert span["name"] == "sase"
    assert span["anchored"] is True
    assert (span["start"], span["end"]) == (0, 5)


# --- Launch validation (D3) -------------------------------------------------


def test_validate_disabled_tag_errors() -> None:
    with pytest.raises(ProjectTagError, match="disabled"):
        validate_project_tags_for_launch("+beta do x")


def test_validate_unknown_anchored_suggests() -> None:
    with pytest.raises(ProjectTagError) as exc:
        validate_project_tags_for_launch("+ssae do x")
    message = str(exc.value)
    assert "Unknown project tag +ssae (line 1)." in message
    assert "Did you mean +sase" in message
    assert "Known:" in message
    assert "+sase" in message.split("Known:")[1]


def test_validate_unknown_unanchored_is_plain_text() -> None:
    validate_project_tags_for_launch("run chmod +x file")
    validate_project_tags_for_launch("fix the C++ build")


def test_validate_alt_branches_are_separate_units() -> None:
    validate_project_tags_for_launch("%{+sase | +bob} audit the README")


def test_validate_two_targets_in_one_unit_errors() -> None:
    with pytest.raises(
        ProjectTagError, match="Only one workspace target.*`\\+sase` and `\\+bob`"
    ):
        validate_project_tags_for_launch("+sase +bob do x")


def test_validate_segments_are_separate_units() -> None:
    validate_project_tags_for_launch("+sase do x\n---\n+bob do y")


def test_validate_tag_plus_ref_errors() -> None:
    from sase.xprompt import find_vcs_workflow_tag_span

    if find_vcs_workflow_tag_span("#git:bob ") is None:
        pytest.skip("git workflow provider is not installed")
    with pytest.raises(ProjectTagError, match="Only one workspace target"):
        validate_project_tags_for_launch("+sase #git:bob do x")


# --- Tag-aware helpers -------------------------------------------------------


def test_effective_tags_resolve_before_extraction() -> None:
    assert (effective_vcs_workflow_tag("+sase do x") or "").strip() == "#gh:sase"
    assert (effective_find_vcs_workflow_tag("do +sase x") or "").strip() == "#gh:sase"
    assert (effective_vcs_workflow_tag("#gh:sase do x") or "").strip() == "#gh:sase"


def test_project_tag_for_spellings() -> None:
    assert project_tag_for("sase") == "+sase"
    assert project_tag_for("+sase") == "+sase"
    assert project_tag_for("bob") == "+bob"
    assert project_tag_for("zzz") == "zzz"
    assert project_tag_for("+zzz") == "+zzz"
    assert project_tag_for("sase-core") == "sase-core"
    assert project_tag_for("1abc") == "1abc"


# --- Caching -----------------------------------------------------------------


def test_catalog_peek_never_builds(tmp_path: Path) -> None:
    _clear_project_tag_catalog_cache()
    try:
        assert peek_project_tag_catalog() is None
        first = load_project_tag_catalog(tmp_path)
        assert peek_project_tag_catalog() is first
        second = load_project_tag_catalog(tmp_path, use_cache=False)
        assert second is not first
        # An uncached load leaves the shared cache alone ...
        assert peek_project_tag_catalog() is first
        # ... and still carries the synthetic system home target.
        assert [t.key for t in second.targets] == ["home"]
        home = second.targets[0]
        assert (home.tag, home.state, home.workflow_type) == (
            "+home",
            "system",
            "git",
        )
        assert home.vcs_ref == "#git:home"
        assert home.accent is None and home.accent_index is None
    finally:
        _clear_project_tag_catalog_cache()


def test_build_catalog_keeps_a_real_home_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A present ``home`` spec is never doubled by the synthetic target."""
    from sase.project_tags.catalog import _build_catalog

    home_record = _record("home", system_managed=True)
    monkeypatch.setattr(
        "sase.core.project_lifecycle_facade.list_project_records",
        lambda *args, **kwargs: [home_record],
    )
    catalog = _build_catalog(tmp_path)
    assert [t.key for t in catalog.targets] == ["home"]


def test_home_target_is_synthetic_before_its_spec_exists(tmp_path: Path) -> None:
    """An empty projects dir still yields the system ``home`` target."""
    from sase.project_tags.catalog import _build_catalog

    catalog = _build_catalog(tmp_path)
    assert catalog.known_tags() == ["+home"]
    (home,) = catalog.targets
    assert (home.key, home.name, home.tag) == ("home", "home", "+home")
    assert (home.workflow_type, home.state) == ("git", "system")
    assert home.vcs_ref == "#git:home"
    assert home.accent is None and home.accent_index is None
    assert home.to_wire() == {
        "key": "home",
        "name": "home",
        "aliases": [],
        "workflow_type": "git",
        "state": "system",
        "workspace_dir": None,
    }


# --- Launch-query ordering ----------------------------------------------------


def test_canonicalize_expands_tags_before_the_hash_guard() -> None:
    """The ``#``-less fast path must still expand ``+`` tags (D4)."""
    with patch(
        "sase.project_tags.expand_project_tags",
        return_value="#gh:sase fix",
    ) as expand_mock:
        result = canonicalize_project_aliases_in_prompt("+sase fix")
    expand_mock.assert_called_once_with("+sase fix")
    assert "#" in result


def test_accent_index_matches_accent() -> None:
    among = ("bob", "sase")
    for key in among:
        from sase.project_accents import project_accent

        assert PROJECT_ACCENTS[project_accent_index(key, among=among)] == (
            project_accent(key, among=among)
        )


# --- Humanizer tagify (D5) ------------------------------------------------------


_DISPLAY_BY_KEY = {
    "sase": "sase",
    "bob": "bob",
    "gh_acme__widgets": "widgets",
    "beta": "beta",
    "home": "home",
}


def _humanize_with_catalog(
    prompt: str,
    tag_catalog: ProjectTagCatalog,
    monkeypatch: pytest.MonkeyPatch,
    *,
    project_tags: bool = True,
) -> str:
    """Humanize *prompt* with the fake catalog as the warm peek snapshot."""
    from sase.project_aliases import humanize_project_refs_in_prompt

    monkeypatch.setattr(
        "sase.project_alias_prompts._project_tag_targets_for_tagify",
        lambda _seam: tag_catalog.targets,
    )
    return humanize_project_refs_in_prompt(
        prompt,
        _DISPLAY_BY_KEY,
        project_tags=project_tags,
    )


def test_tagify_rewrites_matching_workflow_refs(
    tag_catalog: ProjectTagCatalog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _humanize_with_catalog("#gh:sase run", tag_catalog, monkeypatch) == (
        "+sase run"
    )
    assert _humanize_with_catalog("#git:bob run", tag_catalog, monkeypatch) == (
        "+bob run"
    )
    assert _humanize_with_catalog("#gh:widgets run", tag_catalog, monkeypatch) == (
        "+widgets run"
    )
    assert _humanize_with_catalog("#git:home run", tag_catalog, monkeypatch) == (
        "+home run"
    )


def test_tagify_matches_keys_names_and_aliases_case_insensitively(
    tag_catalog: ProjectTagCatalog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _humanize_with_catalog("#gh:Sase run", tag_catalog, monkeypatch) == (
        "+sase run"
    )
    assert (
        _humanize_with_catalog("#gh:gh_acme__widgets run", tag_catalog, monkeypatch)
        == "+widgets run"
    )
    assert _humanize_with_catalog("#git:bobby run", tag_catalog, monkeypatch) == (
        "+bob run"
    )


def test_tagify_never_rewrites_non_project_refs(
    tag_catalog: ProjectTagCatalog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _humanize_with_catalog(
        "#gh:sase_fix_1 review", tag_catalog, monkeypatch
    ) == ("#gh:sase_fix_1 review")
    assert _humanize_with_catalog(
        "#gh:acme/widgets review", tag_catalog, monkeypatch
    ) == ("#gh:acme/widgets review")
    assert _humanize_with_catalog("#gh(sase) review", tag_catalog, monkeypatch) == (
        "#gh(sase) review"
    )
    assert _humanize_with_catalog("#gh:sase!! review", tag_catalog, monkeypatch) == (
        "#gh:sase!! review"
    )
    assert _humanize_with_catalog("#git:sase review", tag_catalog, monkeypatch) == (
        "#git:sase review"
    )


def test_tagify_keeps_refs_outside_tag_positions(
    tag_catalog: ProjectTagCatalog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refs whose tag form would not re-parse keep ``#`` (D1 round-trip)."""
    assert _humanize_with_catalog("(#gh:sase)", tag_catalog, monkeypatch) == (
        "(#gh:sase)"
    )
    assert _humanize_with_catalog(
        "for #gh:sase, #git:bob", tag_catalog, monkeypatch
    ) == ("for #gh:sase, +bob")
    assert _humanize_with_catalog('"#gh:sase"', tag_catalog, monkeypatch) == (
        '"#gh:sase"'
    )
    # Tag positions still rewrite on the same line shapes.
    assert _humanize_with_catalog("(#gh:sase) #gh:sase", tag_catalog, monkeypatch) == (
        "(#gh:sase) +sase"
    )
    assert _humanize_with_catalog(
        "line one #gh:sase\nline two #git:bob", tag_catalog, monkeypatch
    ) == ("line one +sase\nline two +bob")


def test_tagify_leaves_fenced_refs_verbatim(
    tag_catalog: ProjectTagCatalog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt = "```text\n#gh:sase fenced\n```\n#gh:sase live"
    assert _humanize_with_catalog(prompt, tag_catalog, monkeypatch) == (
        "```text\n#gh:sase fenced\n```\n+sase live"
    )


def test_tagify_flag_off_and_cold_catalog_keep_hash_form(
    tag_catalog: ProjectTagCatalog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.project_aliases import humanize_project_refs_in_prompt

    assert (
        humanize_project_refs_in_prompt(
            "#gh:sase run",
            _DISPLAY_BY_KEY,
            project_tags=False,
        )
        == "#gh:sase run"
    )
    monkeypatch.setattr(
        "sase.project_alias_prompts._project_tag_targets_for_tagify",
        lambda _seam: (),
    )
    assert humanize_project_refs_in_prompt("#gh:sase run", _DISPLAY_BY_KEY) == (
        "#gh:sase run"
    )


# --- Known-target spelling ---------------------------------------------------


def test_known_project_tag_for_matches_key_name_and_alias(
    tag_catalog: ProjectTagCatalog,
) -> None:
    assert known_project_tag_for(tag_catalog, "sase") == "+sase"
    assert known_project_tag_for(tag_catalog, "SASE") == "+sase"
    assert known_project_tag_for(tag_catalog, "+sase") == "+sase"
    assert known_project_tag_for(tag_catalog, "bobby") == "+bob"
    assert known_project_tag_for(tag_catalog, "gh_acme__widgets") == "+widgets"


def test_known_project_tag_for_rejects_unknown_names(
    tag_catalog: ProjectTagCatalog,
) -> None:
    # Patch names and typos never gain a ``+`` spelling here (unlike
    # project_tag_for's generator fallback); callers fall back to ``#``.
    assert known_project_tag_for(tag_catalog, "some-patch") is None
    assert known_project_tag_for(tag_catalog, "ssae") is None
    assert known_project_tag_for(tag_catalog, "") is None


# --- Core trigger ------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "cursor", "expected"),
    [
        ("+", 1, (0, 1, "")),
        ("+sa", 3, (0, 3, "sa")),
        ("Fix +bug", 8, (4, 8, "bug")),
        ("line\n +x", 8, (6, 8, "x")),
        ("\t+", 2, (1, 2, "")),
        ("%{+sa", 5, (2, 5, "sa")),
        ("%{a | +sa", 9, (6, 9, "sa")),
    ],
)
def test_find_project_tag_trigger_at_d1_boundaries(
    text: str, cursor: int, expected: tuple[int, int, str]
) -> None:
    trigger = find_project_tag_trigger(text, cursor)
    assert trigger is not None
    assert (trigger.start, trigger.end, trigger.query) == expected
    assert trigger.span == expected[:2]


@pytest.mark.parametrize(
    ("text", "cursor"),
    [
        ("a+b", 3),
        ("c++", 3),
        ("#+sa", 4),
        ("Fix #+sa", 8),
        ("hello world", 11),
        ("", 0),
        ("+", 0),
        ("+", 5),
        ("+", -1),
    ],
)
def test_find_project_tag_trigger_rejects_non_triggers(text: str, cursor: int) -> None:
    assert find_project_tag_trigger(text, cursor) is None


# --- Core in-place accept ----------------------------------------------------


def _patched_workflows() -> object:
    return patch(
        "sase.workspace_provider.get_workflow_names", return_value={"gh", "git"}
    )


def test_apply_selection_inserts_tag_in_place() -> None:
    with _patched_workflows():
        text, cursor = apply_project_tag_selection("+", (0, 1), "+sase ")
    assert (text, cursor) == ("+sase ", len("+sase "))


def test_apply_selection_keeps_surrounding_body() -> None:
    with _patched_workflows():
        text, cursor = apply_project_tag_selection(
            "Describe this repo. +", (20, 21), "+sase "
        )
    assert text == "Describe this repo. +sase "
    assert cursor == len(text)


def test_apply_selection_removes_other_target_in_segment() -> None:
    with _patched_workflows():
        text, _ = apply_project_tag_selection("#git:foo Fix bug +", (17, 18), "+sase ")
    assert text == "Fix bug +sase "


def test_apply_selection_switches_projects() -> None:
    with _patched_workflows():
        text, cursor = apply_project_tag_selection("+sase do it +bo", (12, 15), "+bob ")
    assert text == "do it +bob "
    assert cursor == len(text)


def test_apply_selection_keeps_other_segments() -> None:
    prompt = "#git:foo first\n---\n#git:baz second +"
    with _patched_workflows():
        text, _ = apply_project_tag_selection(
            prompt, (len(prompt) - 1, len(prompt)), "+sase "
        )
    assert text == "#git:foo first\n---\nsecond +sase "


def test_apply_selection_accepts_pr_ref_spelling() -> None:
    with _patched_workflows():
        text, cursor = apply_project_tag_selection("Review +sh", (7, 10), "#gh:ship ")
    assert text == "Review #gh:ship "
    assert cursor == len(text)


# --- Warm-catalog validation -------------------------------------------------


def test_validate_with_catalog_rejects_unknown_anchored(
    tag_catalog: ProjectTagCatalog,
) -> None:
    with pytest.raises(ProjectTagError, match=r"Unknown project tag \+ssae"):
        validate_project_tags_with_catalog("+ssae do it", tag_catalog)


def test_validate_with_catalog_rejects_disabled(
    tag_catalog: ProjectTagCatalog,
) -> None:
    with pytest.raises(ProjectTagError, match="disabled"):
        validate_project_tags_with_catalog("+beta do it", tag_catalog)


def test_validate_with_catalog_allows_unanchored_unknown(
    tag_catalog: ProjectTagCatalog,
) -> None:
    validate_project_tags_with_catalog("run chmod +x-dependent fix", tag_catalog)


def test_validate_with_catalog_rejects_two_targets(
    tag_catalog: ProjectTagCatalog,
) -> None:
    with pytest.raises(ProjectTagError, match="Only one workspace target"):
        validate_project_tags_with_catalog("+sase +bob", tag_catalog)

"""Jump hints cover collapsed group banners and panel titles on the Agents tab.

Pressing ``'`` should paint a ``[x]`` chip next to every collapsed banner
row alongside the visible-agent chips and every split-panel title, so a single
keystroke can land on an agent, focus a folded group banner, or focus a panel
in either its collapsed or expanded state. Expanded banners stay hint-less.
"""

from tests.ace.tui._jump_hints_for_folded_banners_helpers import _agent, _StubApp


def test_jump_targets_includes_collapsed_banners() -> None:
    """Targets list should contain a banner entry before its agent rows."""
    agents = [
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="beta", cl="b1", name="b1"),
        _agent(project="beta", cl="b1", name="b2"),
    ]
    # Collapse the alpha L0 banner so its single agent disappears and the
    # banner itself becomes a target.  beta agents stay visible.
    app = _StubApp(agents, collapsed=[("alpha",)])

    targets = app._jump_candidate_targets()

    assert ("banner", 0, ("alpha",)) in targets
    # The two beta agents are still visible.
    agent_targets = [t for t in targets if t[0] == "agent"]
    assert ("agent", 1) in agent_targets
    assert ("agent", 2) in agent_targets


def test_jump_targets_include_expanded_panel_but_skip_expanded_banners() -> None:
    """Expanded panel titles precede rows; expanded banners stay untargeted."""
    agents = [
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="beta", cl="b1", name="b1"),
    ]
    app = _StubApp(agents)

    targets = app._jump_candidate_targets()

    banner_targets = [t for t in targets if t[0] == "banner"]
    assert banner_targets == []
    assert targets == [("panel", None), ("agent", 0), ("agent", 1)]


def test_jump_targets_include_collapsed_panels_in_render_order() -> None:
    agents = [
        _agent(project="alpha", cl="a1", name="hidden-group"),
        _agent(project="beta", cl="b1", name="visible"),
        _agent(project="chop", cl="c1", name="hidden-one", tag="chop"),
        _agent(project="chop", cl="c2", name="hidden-two", tag="chop"),
        _agent(project="zoom", cl="z1", name="hidden-zoom", tag="zoom"),
    ]
    app = _StubApp(
        agents,
        collapsed=[("alpha",)],
        collapsed_panels={"chop", "zoom"},
    )

    assert app._panel_group.panel_keys == [None, "chop", "zoom"]
    assert app._jump_candidate_targets() == [
        ("panel", None),
        ("banner", 0, ("alpha",)),
        ("agent", 1),
        ("panel", "chop"),
        ("panel", "zoom"),
    ]


def test_all_panel_maps_use_stable_keys_including_untagged() -> None:
    agents = [
        _agent(project="home", cl="u1", name="untagged"),
        _agent(project="apple", cl="a1", name="visible", tag="apple"),
        _agent(project="chop", cl="c1", name="hidden", tag="chop"),
    ]
    app = _StubApp(agents, collapsed_panels={None, "chop"})

    app._begin_agents_jump_mode()

    assert app._entry_jump_hint_to_panel == {
        "1": ("panel", "apple"),
        "3": ("panel", None),
        "4": ("panel", "chop"),
    }
    assert app._entry_jump_panel_to_hint == {
        ("panel", "apple"): "1",
        ("panel", None): "3",
        ("panel", "chop"): "4",
    }

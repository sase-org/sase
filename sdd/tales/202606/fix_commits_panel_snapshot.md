---
create_time: 2026-06-24 06:49:58
status: done
prompt: sdd/prompts/202606/fix_commits_panel_snapshot.md
---
# Fix the failing `test_agents_commit_messages_panel_png_snapshot` visual test

## Summary

The GitHub Actions failure

```
FAILED tests/ace/tui/visual/test_ace_png_snapshots_agents_linked_repos.py::test_agents_commit_messages_panel_png_snapshot - AssertionError
```

is **not** a flaky pixel/font-drift problem. It is a deterministic failure caused by a **stale golden plus brittle text
assertions** that were committed in a state that never matched the test's own deterministic render at the pinned
`120x40` terminal size.

The fix is to make the test's fixture data compact and its assertions wrap-tolerant so the COMMITS detail panel renders
the asserted content reliably (with margin), then regenerate the committed PNG golden. No production/`src` code needs to
change.

## Root cause (verified)

`test_agents_commit_messages_panel_png_snapshot` builds a single DONE agent with two linked repositories, opens the ACE
Agents tab, and then:

1. asserts four substrings are present in the exported SVG via `assert_page_svg_contains` (`COMMITS:`,
   `feat(tui): show agent`, `sase-core`, `sase-github`), and
2. compares the rendered PNG against the committed golden
   `tests/ace/tui/visual/snapshots/png/agents_commit_messages_panel_120x40.png` with a generous `max_diff_ratio = 0.03`
   (3%).

The failure happens at step 1 (helper line `_ace_agents_png_snapshot_helpers.py:13`), before the PNG comparison is ever
reached. Two of the four substrings are missing from the render:

- **`feat(tui): show agent` — missing because it wraps.** The agents-tab detail panel is narrow, so the primary commit
  row `a1b2c3d4e5f6 feat(tui): show agent commits` wraps to `... feat(tui): show` / `agent commits`. The asserted phrase
  is never contiguous.
- **`sase-github` — missing because it is truncated.** The whole COMMITS section (primary group
  - `sase-core` group + `sase-github` group) does not fit in the 40-row detail panel, so the `sase-github` group is
    pushed below the visible viewport (the panel's bottom border renders right after the `sase-core` group).

Why the panel is so narrow: the Agents-tab layout is two side-by-side boxes. The left agent-list column auto-sizes to
the longest agent row (`list_width = clamp(max_left + 2 + max_suffix + 8, 60, 130)` in
`src/sase/ace/tui/widgets/_agent_list_build.py`), and the detail panel gets whatever horizontal space is left. The
fixture's long identity fields (`cl_name="visual-linked-commits"`, `agent_name="linked.repo.commits"`) plus the
timestamp/duration suffix make the agent row ~88 columns wide, leaving the detail panel only **~19 columns of inner
width** at `120x40` — narrow enough to wrap the asserted subject and overflow the panel vertically.

Why the committed golden also does not match (independent of the assertions): rendering the test at HEAD produces a PNG
that differs from the committed golden by **6.47%** (> the 3% tolerance), and the golden shows a _wider_ detail panel
with all groups visible. Verified findings:

- The render is byte-stable. Checking `src/` out at the golden's own commit
  (`1f8c86dce feat(tui): show agent commit messages`) and re-rendering produces the **identical** 6.47% diff against the
  golden. So no `src` change since the golden is responsible.
- The terminal size is pinned to exactly `(120, 40)` by `AcePage` (`run_test(size=(120, 40))`), and Textual lays text
  out in integer character cells, so wrapping is font/host independent. There was no Textual/`uv.lock` bump since the
  golden.
- Therefore the committed golden was generated from a different (wider-panel) layout than the committed test+fixture
  deterministically produce. It is a stale/incorrect golden that does not pass its own test at `120x40`; CI fails every
  run.

This is therefore a determinism/brittleness defect in the **test fixture and golden**, not a product regression and not
random screenshot flakiness. The detail panel is scrollable in the real app, so truncating extra content is not a
product bug — the snapshot simply captures the resting top-of-panel view, which means the fixture must be sized to fit.

## Goal

Make this snapshot test deterministically pass and resilient to small future layout shifts, while preserving its intent:
verify that the COMMITS detail panel renders the primary commit subject and the commit groups for both linked
repositories.

## Approach (validated by prototype)

Keep the existing whole-page PNG snapshot design (consistent with the sibling
`test_agents_linked_repo_diff_file_panel_png_snapshot`, which passes). Shrink the fixture so the COMMITS section fits
the detail panel with margin and the asserted strings never wrap, then regenerate the golden.

Two complementary levers, both confirmed to work by rendering the modified fixture and checking the exported SVG:

1. **Widen the detail panel** by shortening the agent identity used for this fixture, which narrows the auto-sized
   agent-list column. Shortening `cl_name` to `"visual-commits"` and `agent_name` to `"commits"` widens the detail panel
   from ~19 to ~42 inner columns, which alone makes `sase-github` and all groups visible.

2. **Shorten the commit content** so each commit row fits on a single line and the asserted primary subject is
   contiguous:
   - Primary subject: use a short subject (e.g. `"feat: show commits"`) so the `"<sha> <subject>"` row does not wrap;
     assert the full short subject string.
   - Linked subjects: keep them short single-line strings (e.g. `"feat: commit hook"`, `"test: commit parse"`,
     `"fix: subjects"`).
   - Optionally shorten `meta_new_commit` so the primary SHA renders with fewer of its 12 displayed characters, adding
     horizontal margin.

With those changes, a prototype render confirmed all four assertions pass and the full COMMITS section (primary +
`sase-core` + `sase-github`) renders within the `120x40` panel with several rows and ~5–10 columns of spare margin.

### Files to change

- `tests/ace/tui/visual/test_ace_png_snapshots_agents_linked_repos.py`
  - `_linked_repo_commits_agent()`: shorten `cl_name`, `agent_name`, the `meta_commit_message` subject, and (optionally)
    `meta_new_commit`. Keep the agent DONE with the two linked repos (`sase-core`, `sase-github`) so the test still
    exercises multi-repo rendering.
  - `_seed_linked_repo_visual_commits()`: shorten the seeded commit subjects to single-line strings.
  - `test_agents_commit_messages_panel_png_snapshot()`: update the `assert_page_svg_contains` strings to short,
    single-line, wrap-safe substrings that match the new fixture — e.g. `COMMITS:`, the new primary subject,
    `sase-core`, `sase-github`.

- `tests/ace/tui/visual/snapshots/png/agents_commit_messages_panel_120x40.png`
  - Regenerate the golden so it matches the new deterministic render.

No changes to any `src/` production code, the `png_diff` helper, the conftest, or the sibling diff-panel test.

### Robustness notes

- Keep the asserted substrings short and single-token-ish so they cannot wrap at the panel edge.
- Size the COMMITS fixture so its total height leaves a few blank rows below `sase-github` inside the panel, providing
  vertical margin against minor future layout changes.
- Do not assert on multi-word phrases that approach the panel inner width.

## Verification

1. Run the single test (it must pass at the explicit 3% tolerance, the same tolerance CI uses):
   `just test-visual tests/ace/tui/visual/test_ace_png_snapshots_agents_linked_repos.py::test_agents_commit_messages_panel_png_snapshot`
2. Regenerate the golden via the normal visual run with the update flag (the conftest applies the hermetic
   bundled-Fira-Code fontconfig automatically, so the golden is host-deterministic):
   `just test-visual --sase-update-visual-snapshots tests/ace/tui/visual/test_ace_png_snapshots_agents_linked_repos.py::test_agents_commit_messages_panel_png_snapshot`
   then re-run step 1 without the flag to confirm a clean pass.
3. Run the full visual suite to confirm no other golden regressed: `just test-visual`
4. Run `just check` (per repo policy for file changes); the repo is an ephemeral workspace clone, so run `just install`
   first if dependencies may be stale.
5. Inspect the regenerated golden visually (it should show `COMMITS:` with the primary commit and both `sase-core` and
   `sase-github` groups fully visible, no truncation).

## Out of scope / explicitly not doing

- No production layout change to the agents-tab panel split or the COMMITS renderer. The panel is scrollable; truncation
  of overflowing content is expected behavior, not a bug.
- No change to the PNG tolerance, the diff harness, or the hermetic font setup.
- No change to the sibling `test_agents_linked_repo_diff_file_panel_png_snapshot`, which renders a different (diff)
  panel with short, wrap-safe assertions and currently passes.

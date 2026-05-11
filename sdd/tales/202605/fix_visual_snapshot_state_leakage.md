---
create_time: 2026-05-11 18:09:27
status: done
prompt: sdd/prompts/202605/fix_visual_snapshot_state_leakage.md
---
# Plan: Fix ACE PNG visual snapshot state leakage in CI

## Problem

GitHub Actions has failed every CI run for ~36 hours (200/200 most-recent runs). The `visual-test` job consistently
reports 7 ACE PNG snapshot mismatches with 6%–15% pixel differences, while the same suite passes locally on `master`.
The artifacts uploaded by the failing CI job (downloaded for inspection) make the cause obvious: the differences are
**semantic**, not rendering-environment noise.

Concrete differences observed between the committed `expected.png` (golden, rendered on the developer's laptop) and the
CI `actual.png`:

| Surface           | Golden (laptop)                      | CI actual                        |
| ----------------- | ------------------------------------ | -------------------------------- |
| Top-bar LLM pill  | `CODEX(gpt-5.5) ■ IDLE`              | `GEMINI(gemini-3-flash-preview)` |
| CLs group label   | `[group: by date (o)]`               | `[group: by project (o)]`        |
| CLs sidebar       | `Earlier` / `(no timestamp)` buckets | `tmp` (project-name bucket)      |
| Agents group mode | `by status` (laptop default)         | `STANDARD` (CI default)          |

Three independent, real environmental inputs flow into the rendered UI and were never mocked out:

1. **CLs grouping mode** — `~/.sase/changespec_grouping_mode.txt`. Loaded at startup by
   `load_changespec_grouping_mode()` in `src/sase/ace/grouping_strategy.py`. Local file contains `by_date`; CI has no
   file so it falls back to `BY_PROJECT`.
2. **Agents grouping mode** — `~/.sase/grouping_mode.txt`. Loaded by `load_agent_grouping_mode()` in the same module.
   Local file contains `by_status`; CI default is `STANDARD`.
3. **Default LLM provider/model** — `resolve_effective_default_provider_model()` in
   `sase.llm_provider.temporary_override` reads `~/.config/sase/sase.yml`. Local config selects Codex/gpt-5.5; CI has
   none so it falls back to Gemini.

`tests/ace/tui/visual/test_ace_png_snapshots.py::_patch_startup_loaders` patches agent loaders, axe startup, and the
notification snapshot — but **not** the grouping-mode loaders and **not** the LLM provider resolver. The `AcePage` test
harness (`src/sase/ace/testing.py`) also performs no `$HOME` / sase-dir isolation. Goldens regenerated on a developer's
machine therefore bake in that developer's persisted UI state and effective LLM config.

The previous patch attempt assumed the failures were a stale Rust binding (`dismiss_agent_completions`); rebuilding
`sase_core_rs` masked the `WorkerFailed` exception locally, the snapshots compared clean to the locally-rendered output,
and "regenerate all snapshots" produced byte-identical PNGs — because both the goldens and the new captures were
rendered in the same leaky local environment. CI continued to fail because nothing about the underlying leakage was
addressed.

This plan fixes the leakage at the test-fixture layer (so CI and any clean developer machine produce the same bytes) and
regenerates the goldens against the now-hermetic environment.

## Out of scope

- The unrelated `test (3.12/3.13/3.14)` and `bead-backend` CI failures visible in the same job listing. The user's
  request is focused on the visual snapshot failures; those other lanes will be tracked separately.
- Changing the visual-renderer dependencies (cairosvg, Pillow), the font pin (`fonts-dejavu-core`), or the SVG-export
  path. The downloaded CI artifacts show clean glyph rendering with no font-fallback `?` boxes — fonts are not the
  problem.
- Reworking the persistence layer for grouping mode or LLM defaults. We only need to make the visual tests hermetic, not
  redesign the production persistence.

## Approach

Centralize hermetic fixture setup in `tests/ace/tui/visual/test_ace_png_snapshots.py::_patch_startup_loaders` so every
visual test starts from the same deterministic environment, then regenerate the seven affected goldens once against that
environment. Two production helpers are patched:

1. **Grouping modes.** Patch `sase.ace.grouping_strategy.load_agent_grouping_mode` and
   `sase.ace.grouping_strategy.load_changespec_grouping_mode` to return their default enum values
   (`GroupingMode.STANDARD`, `ChangeSpecGroupingMode.BY_PROJECT`). These are the values CI already produces, so the
   freshly regenerated goldens will match CI on every developer machine regardless of `~/.sase/*_grouping_mode.txt`.

   Patching the loaders (not `$HOME`) is the right boundary: the test only needs the loaded mode to be deterministic,
   and patching the loader avoids collateral effects on any other code paths that touch `~/.sase`.

2. **Default LLM provider/model.** Patch `sase.llm_provider.temporary_override.resolve_effective_default_provider_model`
   (and any callsite import alias in `sase.ace.tui.widgets.llm_override_indicator`) to return a fixed
   `(provider, model)` pair — a deterministic placeholder such as `("codex", "visual-snapshot-model")` — and patch
   `get_active_temporary_override` to return `None`. This freezes the top-bar indicator content. We pick a fixture-only
   label rather than the real CI fallback so the goldens make clear they're testing fixture content, not whichever
   provider happens to win in CI today.

After the patches land, regenerate exactly the seven failing goldens with
`just test-visual --sase-update-visual-snapshots tests/ace/tui/visual/test_ace_png_snapshots.py`. The remaining eight
visual tests are unaffected by these inputs and should stay byte-identical.

A small alternative considered: setting `monkeypatch.setenv("HOME", str(tmp_path))` in the fixture. Rejected because (a)
`Path.home()` is read in several places at import time that the patch would not catch, (b) it doesn't help with the LLM
resolver which reads `~/.config/sase`, and (c) the loader-level patches are smaller, more local, and easier to keep in
sync if the persistence path moves.

## Implementation outline

1. Extend `_patch_startup_loaders` in `tests/ace/tui/visual/test_ace_png_snapshots.py`:
   - Patch `sase.ace.grouping_strategy.load_agent_grouping_mode` → `GroupingMode.STANDARD`.
   - Patch `sase.ace.grouping_strategy.load_changespec_grouping_mode` → `ChangeSpecGroupingMode.BY_PROJECT`.
   - Patch `sase.llm_provider.temporary_override.resolve_effective_default_provider_model` and any re-import in
     `llm_override_indicator` → fixed pair.
   - Patch `get_active_temporary_override` → `None`.

   The patches must hit both the source module and any `from X import Y` re-export the production code actually reads
   (verify with grep before editing).

2. Run `just test-visual` locally with the new patches but **without** `--sase-update-visual-snapshots` to confirm the
   seven targeted tests now fail (proving the fixture is biting) and the other eight still pass.

3. Regenerate goldens: `just test-visual --sase-update-visual-snapshots tests/ace/tui/visual/test_ace_png_snapshots.py`.

4. Run `just test-visual` (no update flag) — all 15 must pass.

5. Run `just check` per workspace policy.

6. Optional safety net: if it's cheap, add a one-line assertion in `_patch_startup_loaders` that the patched
   `resolve_effective_default_provider_model` was actually monkey-patched (e.g., assert the function identity changed)
   so a future refactor that moves the resolver doesn't silently re-leak local state.

## Verification

- Locally, after regeneration: `just test-visual` reports 15 passed.
- Locally, simulate CI by temporarily moving `~/.sase/grouping_mode.txt` and `~/.sase/changespec_grouping_mode.txt`
  aside and unsetting any `SASE_*PROVIDER*` env vars — `just test-visual` should still pass. (This is a quick sanity
  check that the patches cover the real leakage surface.)
- In CI: the next push should turn the `visual-test` job green. The seven previously-failing tests are the success
  signal; the other eight should remain unchanged.

## Risks

- **Missed leakage source.** If another piece of TUI state still depends on user config (e.g., theme, custom keymap,
  fold-state file), the regenerated goldens will continue to embed local state and CI will fail again on a _different_
  surface. Mitigation: the simulate-CI step above will surface this before we commit.
- **Patch site drift.** If a future commit moves `resolve_effective_default_provider_model` to a new module, the test
  monkeypatch will silently no-op. Mitigation: the optional identity-changed assertion in step 6.
- **Goldens drift on Pillow/cairosvg bumps.** Not introduced by this change, but worth flagging — the suite remains
  pixel-exact (`max_diff_pixels=0`). Any future rasterizer upgrade will require golden regeneration in CI.

---
title: "Footprint"
description: "How Footprint feature IDs and the generated catalog work."
---

# Footprint: feature IDs and the catalog

Footprint is a local usage census: a generated **catalog** of every sase surface joined
with per-day aggregate counts, so a review can find surfaces with no recorded use. The
catalog is the denominator; without it, "never used" is indistinguishable from "never
measured."

## How IDs are formed

A feature ID has the form `<ns>:<path>` and matches `^[a-z]+:[a-z0-9_.~#-]+$`. The
namespaces are `cli`, `tui`, `view`, `macro`, `skill`, `config`, `auto`, and `plugin`.
Real registry names that predate the scheme are sanitized through
`sase.footprint.ids.sanitize` (lowercased, disallowed characters become `_`), so
`sase bead +1` is `cli:bead._1` and the `ref:plan` artifact reference is
`tui:artifacts.ref_plan`. Both the recorder and the generator sanitize through that one
helper, so IDs cannot drift between them.

| ns       | Example                      | Source of truth                                 |
| -------- | ---------------------------- | ----------------------------------------------- |
| `cli`    | `cli:bead.list`, `cli:_root` | Full argparse tree; options use `dest` names    |
| `tui`    | `tui:app.zoom_panel`         | Palette catalog, keymap scopes, built-in modes  |
| `view`   | `view:tab.agents`            | Tabs, subtabs, center tabs, stats views, modals |
| `macro`  | `macro:research`             | Bundled macros in `src/sase/macros/`            |
| `skill`  | `skill:sase_repo`            | Generated skill sources                         |
| `config` | `config:ace.page_size`       | `default_config.yml` leaf paths                 |
| `auto`   | `auto:axe.housekeeping.jobs` | AXE routine and job names                       |
| `plugin` | `plugin:listen`              | First-party plugin command words                |

Rules:

- **Allowlist, never denylist.** An unrecognized value collapses to `<ns>:~other`.
  User-defined names (custom macros, custom modes, saved-query contents) become
  `~custom`. `tui:saved_query.<n>` slot numbers are fine.
- **Aliases share one ID.** Legacy CLI words (`changespec`, `task`, `vcs`,
  `artifact-file`) resolve to their canonical command through `ids.CLI_ALIASES`. The key
  binding and the palette entry for one action are one feature reached two ways (`via`).
- **Navigation chrome is neither counted nor catalogued.** Cursor movement, scroll, and
  focus/tab cycling live in `ids.NAVIGATION_ACTIONS`. A catalogued action that is never
  recorded would look like a false deletion candidate.
- The generator uses **bundled defaults only**: it never reads the user's config, keymap
  overrides, saved queries, or custom modes, and it keeps only built-in TUI IDs
  (provider-discovered artifact tabs are resolved at record time against their
  `view:tab.*` entries instead).

## How to regenerate

The catalog lives at `src/sase/footprint/catalog.jsonl` (plus a header line with the
schema, entry count, and `rev`). Regenerate it with `just fix` (runs
`just sync-footprint-catalog`); `just lint` fails when the checked-in file drifts from
the registries. A PR that adds a parser leaf, option, binding, macro, skill, view,
modal, or config leaf fails lint until the catalog is regenerated, so surface changes
stay visible in diffs.

`src/sase/footprint/catalog.py` loads the catalog and the overlay off the hot path; hot
paths import only `ids` and `paths`.

## Recording seams

The TUI records at five seams, all funnelled through one mixin
(`src/sase/footprint/_tui_seams.py:FootprintTuiMixin`, first in the `AceApp` bases) so
every hit goes through the same counter (`src/sase/footprint/_tui.py:bump`):

- **`AceApp.run_action` override.** Counts only when `super()` returns `True`. The count
  is keyed by the `default_namespace` class scope plus the action name with parameters
  stripped, via a lazily built and cached class→scope map. `ids.NAVIGATION_ACTIONS` are
  skipped. `via` is `mouse` when `on_mouse_down` set a one-shot flag, otherwise `key`.
- **Palette.** `commands/execute.py:execute_command` records one hit for `tui:<spec.id>`
  with `via=palette` (`custom.*` collapses to `tui:~custom`).
- **Prefix modes.** `actions/_event_keyboard.py:on_key` records `tui:<mode>.<field>`
  with `via=mode` when a `_handle_<mode>_key` returns `True`, through a reverse
  key→field map per mode that is rebuilt when the keymap registry object changes.
  Covered modes are `fold`, `copy`, `leader`, `bang`, `bead_issue`, and `saved_query`
  (slot digits); custom modes record `tui:custom.~custom`. `escape` cancels are never
  counted. Checkout, ancestry, and entry-jump keys are navigation chrome and are not
  recorded.
- **View entry.** `watch_current_tab` records `view:tab.<name>`, the artifacts/files
  subtab watchers record `view:tab.<subtab>`, the admin center callback records
  `view:admin.<tab>`, and the Statistics `_set_view` records `view:stats.<view>`. Tab
  switches count only after startup completes and never for the restored initial tab.
  All view entries use `via=key`.
- **Modals.** The `AceApp.push_screen` override records `view:modal.<snake>` for every
  `ModalScreen`.

The counter is a `dict[(feature_id, via), int]` with one actor classified once at the
first flush. A daemon thread (`sase-footprint-flusher`) wakes every 60 s; when dirty it
swaps the dict, writes aggregated spool lines plus one `probe: tui` line via `_spool`,
and re-reads the mode and generation files. When the mode is `off`, or the generation
changed since the counts began, the batch is discarded. `flush_now(timeout=0.2)` runs
the same write synchronously and is called from `actions/lifecycle.py` `on_unmount` and
the `_hard_exit_ace` flush tuple.

## Performance budgets

| Path            | Budget                                                                                                                                           |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| CLI hit         | ≤ 100 µs p99 added. No new imports beyond stdlib plus `sase.footprint._cli`/`_spool`/`_actor`/`_mode`/`paths`/`ids`                              |
| TUI action bump | ≤ 2 µs. Zero event-loop I/O (asserted by monkeypatching `os.write` and by thread attribution of every spool write)                               |
| TUI flush       | Daemon thread only. No Textual timer, no pump involvement                                                                                        |
| TUI startup     | Zero Footprint work before first paint. Index maps are built lazily on the first hit                                                             |
| `j`/`k`         | p95 under 16 ms unchanged (`SASE_TUI_PERF=1`, `bench_tui_jk_panes.py::test_bench_patches_jk`); a regression over 0.5 ms blocks work on the seams |

## What the overlay is for

`src/sase/footprint/overlay.yml` holds curated human knowledge, reviewed in PRs:
`protected` classes (`recovery`, `safety`, `bootstrap`, `infra`) for rare-by-design
surfaces with a `why`, `keep` reasons (`rare_by_design`, `safety`, `agent_facing`,
`api_contract`, `other`), and `retire_with` siblings a cut should remove together. Every
key is an exact ID or a trailing-`*` glob, and every key must match at least one catalog
ID. The generator test fails otherwise.

---
create_time: 2026-06-19 21:29:11
status: done
prompt: sdd/prompts/202606/xprompt_completion_project_scope.md
---
# Fix: built-in `#plan` (and peers) only complete under `#gh:sase`, not other projects

## Problem / product context

In the `sase ace` prompt input widget, the built-in `#plan` xprompt appears in the completion menu when the prompt
carries `#gh:sase`, but disappears under other projects (e.g. `#gh:bob-cli`). `#plan` is a **core, built-in workflow
xprompt** (defined in `src/sase/default_config.yml`) and should be available in _every_ project context, exactly like
`#pick_plan` (a user `~/.xprompts/` helper) which correctly shows everywhere.

`#plan` is not alone — the same bug hides a whole family of built-in workflow xprompts shipped in `default_config.yml`:
`plan`, `epic`, `legend`, `review`, `research`, `research/{image,more,prompt}`, `prompt/{approve,review}`,
`bd/{land_epic, land_legend, new_epic, new_legend, next, review/plan, review/prompt, work_phase_bead}`, and `x`. It also
mis-scopes config-overlay xprompts (e.g. `sase_gmail` from `~/.config/sase/sase_athena.yml`). All of these are wrongly
pinned to whichever project owns the directory `sase ace` was launched from.

## Root cause (confirmed)

Xprompt completion entries carry a `project` field. The completion filter (`filter_structured_catalog_entries`,
`src/sase/xprompt/_catalog_structured.py:114`) keeps an entry only when `entry.project in (None, requested_project)`. So
an entry whose `project` is hard-pinned to `"sase"` is filtered out for every other project.

The `project` field is assigned by `classify()` in `src/sase/xprompt/_catalog_sources.py:133`. Each config xprompt's
`source_path` is a **virtual label string**, not a filesystem path. `src/sase/config/core.py:load_xprompts_by_source`
emits these labels: `default_config`, `plugin_config:{mod}`, `config`, `config_overlay:{file}`, `local_config`.
`classify()` only special-cases `plugin:`, `config`, and `config:`. Every other label falls through to a path-based
heuristic that does:

```python
source_path.resolve().relative_to(ws.resolve())  # ws = a known project workspace
```

`Path("default_config").resolve()` resolves the bare label **relative to the current working directory**. Because
`sase ace` runs with its CWD inside the registered `sase` project workspace
(`/home/bryan/projects/github/sase-org/sase/`), the label "resolves" under that workspace and `classify()` returns
`bucket="project", project="sase"`. The result is **CWD-dependent**, which is the smoking gun.

Reproduction (verified against the live install):

| `source_path`                    | classify from CWD `/tmp` | classify from CWD = sase workspace    |
| -------------------------------- | ------------------------ | ------------------------------------- |
| `default_config`                 | `project=None` ✓         | `project="sase"` ✗                    |
| `config_overlay:sase_athena.yml` | `project=None` ✓         | `project="sase"` ✗                    |
| `local_config`                   | `project=None`           | `project="sase"`                      |
| `config`                         | `project=None` ✓         | `project=None` ✓ (explicitly handled) |

`config` is correct only because it has an explicit early branch; the other virtual labels do not, so they leak into the
path heuristic.

### Why the fix is well-defined: the Rust core is already correct

This classification logic is mirrored in the shared Rust backend at
`../sase-core/crates/sase_core/src/xprompt_catalog.rs::classify_source` (the canonical implementation used by the nvim
LSP / `prefer_rust_catalog` path). That version is **already fixed**: it handles `plugin_config:`, and critically it
**gates every path-based heuristic behind `path.is_absolute()`**, so virtual labels never get resolved against CWD and
fall through to the correct `("config", None)` default.

The Python `classify()` has simply drifted from the canonical Rust logic. Per `memory/rust_core_backend_boundary.md`,
the Rust version is the source of truth; the fix is to **re-align the Python implementation to match it**. No Rust
change is required.

## Scope of impact

- `classify()` feeds both the structured/mobile catalog (`gather_structured_entries`) and the PDF/full catalog
  (`gather_entries`), so the fix corrects every Python catalog consumer: the `sase ace` TUI completion + argument hints,
  the mobile/structured catalog, and `sase xprompt` CLI listings.
- The reported `sase ace` bug flows entirely through the **Python** path (`build_xprompt_assist_entries` →
  `build_structured_xprompts_catalog` → `filter_structured_catalog_entries`); it does **not** go through `sase_core_rs`.
  So the Python fix directly resolves the user-visible issue.

## Fix approach

Re-align `classify()` in `src/sase/xprompt/_catalog_sources.py` to mirror the canonical Rust `classify_source`:

1. Treat `plugin_config:` like `plugin:` (plugin bucket, `project=None`).
2. Return early for an explicit `project` argument **before** the path heuristics (matches Rust ordering; harmless for
   existing absolute-path cases).
3. **Gate the package-dir, project-workspace, and `~/.config/sase` membership checks behind
   `source_path.is_absolute()`.** Genuine xprompt files always have absolute `source_path` (they come from
   `Path.cwd()`/`Path.home()` globs), so this loses nothing real — it only stops virtual labels from being misread as
   relative paths.
4. Keep the final fallback `("config", None)`.

Net effect: `default_config`, `config_overlay:*`, `plugin_config:*`, and `local_config` all classify as global
(`project=None`), exactly as they do from a neutral CWD and exactly as the Rust backend already does. Genuinely
project-scoped xprompts remain scoped, because they are loaded through the explicit project loop in `gather_*` (which
passes an explicit `project=` and hits step 2), and project-local `sase.yml` xprompts stay namespaced (`sase/docs`).

### Intentional, parity-driven consequence to flag

`local_config` (the CWD's own `./sase.yml`) currently classifies as `project="sase"` by accident of the CWD heuristic.
After the fix it becomes `project=None` — matching the Rust backend. Its entries are still namespaced (e.g.
`#sase/docs`) and are _also_ surfaced as properly project-scoped entries via the project-workspace loop, so they
continue to appear for their project; the only change is they additionally become visible (under their namespaced name)
elsewhere. This is the canonical behavior and is acceptable; it is called out here so it is not mistaken for a
regression.

## Tests

Extend `tests/test_xprompt_catalog_classification.py` (the existing `classify` unit suite, which already covers
`built-in`, `default_xprompts`, `plugin:`, `config`, explicit-project, and workspace-inferred cases — all using absolute
paths, so they remain green):

- `default_config` → `project=None` (regression test for this bug), asserted **with a `get_known_project_workspaces`
  mock that includes a workspace whose path is the CWD**, to prove the result no longer depends on CWD.
- `config_overlay:sase_athena.yml` → `project=None`.
- `plugin_config:some_module` → plugin bucket, `project=None`.
- A higher-level guard (in `tests/test_xprompt_catalog_structured.py` or a new test) asserting that a built-in
  `default_config` xprompt like `plan` survives `filter_structured_catalog_entries(..., project="some_other_project")` —
  i.e. it completes under any project, mirroring the user-reported scenario.

Also run the full suite and update any existing structured/mobile catalog assertions or snapshots that encoded the buggy
`project="sase"` grouping for `default_config` xprompts.

## Verification

- Reproduce the user scenario after the fix: build the structured catalog with `project="bob-cli"` and confirm `plan`
  (and the rest of the `default_config` family) is present; confirm it is also still present for `project="sase"`.
- Confirm `classify()` returns identical results regardless of CWD for all virtual labels.
- `just check` (run `just install` first — ephemeral workspace).

## Non-goals

- Changing the Rust `classify_source` (already correct) or re-plumbing the Python catalog to call through `sase_core_rs`
  instead of reimplementing classification. The longer-term direction of having Python defer to the Rust binding is
  noted but out of scope for this targeted bugfix.
- Deduplicating the pre-existing double `sase/docs` entry (`local_config` vs `project_local_config:sase`) observed
  during diagnosis — unrelated and not user-visible.
- Adding a `memory` bucket to the Python classifier (the Rust side has a `memory/long` special case Python lacks); not
  relevant to this bug.

## Key references

- `src/sase/xprompt/_catalog_sources.py:133` — `classify()` (the file to fix).
- `src/sase/xprompt/_catalog_structured.py:114` — the `entry.project in (None, project)` filter.
- `src/sase/config/core.py` (`load_xprompts_by_source`, ~line 237) — the virtual source-label taxonomy.
- `../sase-core/crates/sase_core/src/xprompt_catalog.rs:1127` — canonical, already-correct `classify_source`.
- `tests/test_xprompt_catalog_classification.py` — existing `classify` unit tests.

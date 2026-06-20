---
create_time: 2026-06-20 18:17:09
status: done
prompt: sdd/prompts/202606/correlated_alt_keys_fanout.md
---
# Plan: Correlate repeated alternation keys across `%{...}` directives

## Problem / product context

Fan-out prompts can contain multiple alternation directives (`%{...}` brace form, or the legacy `%alt(...)` / `%(...)`
paren forms). Branches may be _named_ with a `key=value` prefix, e.g. `%{a=Describe | b=Explain}`. Today, when a prompt
contains **more than one** alternation directive, the planner computes a full **Cartesian product** of every directive's
branch list. Named branches do not influence how the directives combine — the names only become agent-name suffixes.

This produces the wrong number of agents when the **same key is repeated across directives**. The reported bad prompt
was:

```
#gh:sase %{a=Describe | b=Explain} how this repo works %{a=in detail}.
```

- Directive 1 branches: `a=Describe`, `b=Explain`
- Directive 2 branches: `a=in detail` (single-branch, so an implicit empty branch is also added today)

Current (wrong) result — Cartesian product → **4 agents**:

| alt_id | rendered prompt                             |
| ------ | ------------------------------------------- |
| `a.a`  | `… Describe how this repo works in detail.` |
| `a.1`  | `… Describe how this repo works .`          |
| `b.a`  | `… Explain how this repo works in detail.`  |
| `b.1`  | `… Explain how this repo works .`           |

### Desired behavior

A keyword key that is **repeated across multiple alternation directives** should be _correlated_ (zipped) rather than
multiplied: every value sharing that key renders into the **same** agent prompt. This restricts the fan-out. For the
example above, exactly **2 agents** should launch:

| alt_id (suffix) | rendered prompt                             |
| --------------- | ------------------------------------------- |
| `a`             | `… Describe how this repo works in detail.` |
| `b`             | `… Explain how this repo works .`           |

The `b` agent's second directive contributes nothing (it has no `b=` branch), so that directive's span renders empty.

Key principle: **shared _named_ keys correlate; everything else stays a Cartesian product.** Disjoint named keys,
unnamed branches, and the existing multi-model fan-out path must keep their current Cartesian behavior.

## Where the logic lives (single source of truth)

The alternation parsing, Cartesian product, and `alt_id` allocation are implemented **only in the Rust core**
(`sase-core` linked repo), in `crates/sase_core/src/agent_launch/mod.rs`. The Python repo (`sase`) calls through the
`sase_core_rs` PyO3 binding via `sase.core.agent_launch_facade.plan_agent_launch_fanout` and only _consumes_ the
returned slots; it then applies agent naming. Per the repo's "Rust Core Backend Boundary" convention, this fix is
core/domain behavior and **belongs in the Rust core**, with Python limited to docstrings/tests.

Relevant code (current):

- `split_prompt_for_alternatives_with_ids` — parses directives, adds the implicit-empty branch for single-branch
  directives, calls `cartesian_product`, renders each combination, composes `alt_id` by joining branch ids with `.`.
- `allocate_alternative_branch_ids` — assigns each branch an id: the explicit name, else the next numeric id (skipping
  any numeric value already used as an explicit name), allocated **per directive**.
- `parse_directive_args_with_names` / `split_named_directive_arg` — split branches and extract the optional `key=`
  prefix into `DirectiveArg.name: Option<String>`.
- `cartesian_product` — generic recursive product helper.
- `plan_model_fanout` → `split_prompt_for_models_with_ids` — rewrites repeated `%model` directives into
  `%alt(%model:a,%model:b,…)` then calls the same alternatives splitter. Model branches are **unnamed** (`%model:opus`
  has no `=`), so they must remain Cartesian.

Python consumers/naming (no semantic change needed, only docs):

- `src/sase/xprompt/_directive_alt.py` — `split_prompt_for_alternatives`, `plan_prompt_fanout_variants`, and
  `_apply_fanout_naming` / `_fanout_suffixes`. Because a correlated group's `alt_id` is the named key (`a`, `b`),
  `_alt_id_has_named_component` already returns `True` and the suffix becomes `.a` / `.b` exactly as desired.

## Design: correlation groups

Replace the "one Cartesian axis per directive" model with "one Cartesian axis per **correlation group**", where a group
is a set of directives connected (transitively) by shared _explicit_ names.

Algorithm for `split_prompt_for_alternatives_with_ids`:

1. **Parse** every alternation directive into `(start, end, args: Vec<DirectiveArg>)`, keeping each branch's explicit
   `name: Option<String>`. Do **not** add the implicit-empty branch yet, and do not allocate ids yet (both decisions now
   depend on grouping).

2. **Group** directives into connected components by shared explicit name (union-find / connected components over
   directive indices: for each explicit name, union all directives that use it). Only explicit `key=` names link
   directives — auto-assigned numeric ids never cause correlation. A directive that shares no name with any other
   directive forms a singleton group.

3. **Build one axis per group.** An _axis_ is an ordered list of _variants_; a _variant_ is
   `(id: String, replacements: Vec<(directive_index, value: String)>)`.
   - **Singleton group** (one directive, or a directive whose names aren't shared): preserve today's behavior exactly.
     - If the directive has a single branch, append the implicit empty branch (`DirectiveArg{ name: None, value: "" }`)
       — this keeps the standalone with/without split.
     - Allocate ids with the existing per-directive `allocate_alternative_branch_ids`.
     - Each branch becomes one variant: `id = branch.id`, `replacements = [(dir_idx, branch.value)]`.

   - **Correlated group** (≥2 directives sharing ≥1 name): zip by key. **No implicit-empty branch is added** (a missing
     key already renders empty).
     - Allocate ids **group-wide** so unnamed branches from different directives never collide: reserve all explicit
       names in the group, then number unnamed branches sequentially across the group's directives in document order,
       skipping reserved numeric strings.
     - Compute the ordered, de-duplicated list of variant keys = the ids encountered across the group's directives in
       document order (named ids dedupe by equality; group-wide numeric ids are already unique).
     - For each key, build `replacements`: for every directive in the group, use its branch value for that key if
       present, otherwise `""` (empty render). `id = key`.

4. **Order axes** by the minimum directive `start` position, so `alt_id` reads left-to-right and matches existing
   document-order output for all-singleton prompts.

5. **Cartesian product across axes** (reuse `cartesian_product` over the axes' variant lists). For each combination (one
   variant per axis):
   - `alt_id` = join the selected variants' ids with `.`.
   - Collect all `(directive_index, value)` replacements from the selected variants. Every directive belongs to exactly
     one axis and every variant of that axis carries a replacement for every directive in its group, so in any
     combination **every** directive gets exactly one replacement.
   - Apply replacements to the prompt sorted by **descending** `start` (so earlier spans don't shift), mirroring the
     current rendering loop.

This keeps the common path (all-singleton / unnamed / disjoint-named / model fan-out) bit-identical to today, and only
changes behavior when explicit keys are shared across directives.

### Worked examples

- `%{a=Describe | b=Explain} how this repo works %{a=in detail}.` → one group `{D1, D2}` (share `a`), keys `[a, b]` → 2
  slots: `a` → `Describe how this repo works in detail.`, `b` → `Explain how this repo works .` ✔ (matches goal)

- `%alt(left=a,right=b) %alt(red=x,blue=y)` — disjoint names → two singleton groups → Cartesian:
  `left.red, left.blue, right.red, right.blue` (unchanged).

- `%{a | b} %alt(x,y)` — all unnamed → two singletons → Cartesian `1.1,1.2,2.1,2.2` (unchanged).

- `%{a=1|b=2} x %{a=3} y %{a=4|b=5}` — one group, keys `[a, b]` → 2 slots: `a`→`1 x 3 y 4`, `b`→`2 x  y 5`.

- `%{a=X|b=Y} %{c=P|d=Q}` (two independent correlated _pairs_ via a 3rd/4th directive would form two groups) and the
  simpler `%{a=X} %{a=Y}` → single shared key → **1 slot** `a`→`X Y`.

- Mixed named+unnamed in a correlated group `%{a=X | Y} %{a=Z}` → group-wide ids: keys `[a, 1]`; `a`→`X Z`, `1`→`Y `
  (second directive has no id `1` → empty).

## Implementation steps

### A. Rust core (`sase-core` linked repo) — primary change

> Open the linked repo with `sase workspace open -p sase-core -r "<reason>" <workspace_num>` and use the printed path.
> Do not hard-code workspace paths.

1. In `crates/sase_core/src/agent_launch/mod.rs`:
   - Refactor `split_prompt_for_alternatives_with_ids` to the correlation-group algorithm above. Parse into
     per-directive `DirectiveArg` lists first; defer implicit-empty and id allocation until after grouping.
   - Add a small connected-components (union-find) helper over directive indices keyed by explicit branch names.
   - Add a group-wide id-allocation helper for correlated groups (reserve explicit names, number unnamed branches across
     the group in document order). Keep `allocate_alternative_branch_ids` for singleton groups.
   - Introduce a lightweight internal `Axis`/`Variant` representation (or equivalent tuples) so a single variant can
     carry replacements for multiple directives; generalize the render loop to apply a set of `(start, end, value)`
     replacements sorted descending by `start`.
   - Update/add doc comments describing correlated-key semantics.
2. The model fan-out path (`split_prompt_for_models_with_ids` → `split_prompt_for_alternatives_with_ids`) needs no
   change: collapsed `%model` branches are unnamed and stay Cartesian. Verify by test.
3. No wire-shape change: `LaunchFanoutSlotWire` / `LaunchFanoutPlanWire` fields (`prompt`, `alt_id`, `model`,
   `name_generated`, `launch_kind`) are unchanged, so the PyO3 binding and schema version are untouched.

### B. Rust tests (`crates/sase_core/src/agent_launch/mod.rs` `#[cfg(test)]`)

Add tests (keep all existing ones — they should pass unchanged):

- Shared key zip = the bad-prompt case → 2 slots with alt_ids `a`/`b` and the exact rendered prompts (including the
  trailing-space-before-period on the `b` slot).
- Transitive 3-directive correlation (`%{a=1|b=2} %{a=3} %{a=4|b=5}`) → 2 slots.
- Single shared key collapses to 1 slot (`%{a=X} %{a=Y}`).
- Two independent correlated groups remain Cartesian between groups.
- Mixed named+unnamed in a correlated group → group-wide numeric ids, no collision.
- Regression assertions that disjoint-named and all-unnamed multi-directive prompts stay Cartesian (already covered by
  `fanout_planner_composes_cartesian_alt_ids`, `fanout_planner_brace_composes_cartesian_with_paren_alt`, and the model
  tests).

### C. Python repo (`sase`) — tests + docs only

1. Rebuild the binding so Python picks up the Rust change: `just install` detects a local `../sase-core` checkout (via
   `SASE_CORE_DIR` / `SASE_LINKED_REPO_SASE_CORE_DIR`) and runs `maturin develop` for `sase_core_rs`. Run
   `just rust-test` for the Rust suite.
2. `tests/test_directives_split_alternatives.py`: add an end-to-end case through `split_prompt_for_alternatives` for the
   bad prompt → exactly 2 prompts with the expected text.
3. `tests/test_core_agent_launch_wire.py`: add a case asserting `alt_id`s `["a", "b"]` for the shared-key prompt
   (mirrors the existing `*_exposes_alt_ids` style).
4. Add/extend a naming test (e.g. via `plan_prompt_fanout_variants` / `_apply_fanout_naming`) asserting the two slots
   receive `%name:<base>.a` and `%name:<base>.b`, confirming the suffixes the user expects.
5. Docstrings: update `src/sase/xprompt/_directive_alt.py` module + `split_prompt_for_alternatives` /
   `split_prompt_for_models` docstrings, which currently say a Cartesian product is always taken, to describe shared-key
   correlation.

### D. Docs

- `docs/xprompt.md`: update the **Cartesian Product** section (and the Named Branches section if needed) to document
  that a key repeated across directives correlates into one agent, with the worked example. Clarify the rule: disjoint
  keys and unnamed branches still Cartesian.

### E. Verify

- `just rust-test` (Rust suite) and `just check` (Python lint + mypy + pytest) both green. Per repo rules,
  `just install` must precede `just check` in an ephemeral workspace.
- Manual sanity: feeding the bad prompt through the planner yields 2 slots / `.a` + `.b`.

## Risks & decisions

- **Backward compatibility:** No existing test in either repo uses _shared named keys across directives_, so all current
  tests pass unchanged; only the new (previously unintended) case changes. This is a behavior change for that case —
  intended and documented as the fix.
- **Single-slot collapse:** `%{a=X} %{a=Y}` now yields 1 agent named `<base>.a`. This follows directly from the
  correlation rule and is acceptable; documented as expected.
- **Mixed named+unnamed in a correlated group:** handled deterministically via group-wide id allocation to avoid
  numeric-id collisions; covered by a test. (Rare in practice.)
- **Boundary discipline:** all semantic logic stays in `sase-core`; Python changes are docstrings/tests only. Wire
  schema and PyO3 binding are unchanged.

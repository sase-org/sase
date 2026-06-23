---
create_time: 2026-06-23 10:21:01
status: done
prompt: sdd/prompts/202606/fanout_duplicate_name_alt_model_axes.md
---
# Plan: Fix duplicate agent names when a model alt-axis is combined with another alt-axis

## Symptom

Launching the prompt in `~/tmp/bad_prompt.txt`:

```
#gh:sase %{Describe | Explain} what this repo does. #m_opus_codex
```

fails with:

```
ValueError: template group rendered duplicate concrete names; split duplicate templates into separate groups
```

`#m_opus_codex` now expands to `%{%m:opus | %m:#codex}`. The prompt therefore contains **two independent alternative
axes**:

- a **text axis** — `%{Describe | Explain}` (2 branches)
- a **model axis** — `%{%m:opus | %m:#codex}` (2 model branches)

These form a 2 × 2 Cartesian product (4 agents). `#gh:sase` is incidental to the failure.

## Root cause

The fan-out **naming** logic lives in Python in `src/sase/xprompt/_directive_alt.py` (`_apply_fanout_naming` →
`_fanout_suffixes`). For each fan-out slot the Rust core (`sase_core`) supplies an `alt_id` — one dot-separated
component per alt directive, in document order (e.g. `1.1`, `1.2`, `2.1`, `2.2`) — plus the slot's resolved `model`. The
Python side turns each slot into a `%name:<base>.<suffix>` directive.

`_fanout_suffixes` has a special case: when there are **≥2 distinct models** and the `alt_id` has **no named branch
component**, it discards the entire `alt_id` and uses **only** the model-derived suffix (`cld`, `cdx`, `cld_opus`, …).
This is correct for a _pure_ model fan-out (`%{%m:opus | %m:#codex}` alone → `@.cld` / `@.cdx`), but it is wrong when
another alt axis coexists: the text-axis component of the `alt_id` is thrown away, so slots that share a model but
differ in the text branch collapse to the **same** name.

For the bad prompt the four slots become:

| slot              | alt_id | model  | injected name             |
| ----------------- | ------ | ------ | ------------------------- |
| Describe + opus   | `1.1`  | opus   | `%name:@.cld`             |
| Describe + #codex | `1.2`  | #codex | `%name:@.cdx`             |
| Explain + opus    | `2.1`  | opus   | `%name:@.cld` ← duplicate |
| Explain + #codex  | `2.2`  | #codex | `%name:@.cdx` ← duplicate |

At launch, `multi_prompt_launcher.launch_multi_prompt_agents` collects these `%name` templates into a template group and
calls `PlannedNameAllocator.planned_names_for_template_group`, which runs `_ensure_unique_group_render_shapes`
(`src/sase/agent/multi_prompt_reference_allocator.py`). Rendering `@.cld` twice yields the same concrete name → the
`ValueError` above.

### This is a pre-existing latent bug, not a regression from the recent multi-model migration

- The naming logic (`_fanout_suffixes`) was **not** changed by the "reject legacy multi-model directives" work; only the
  _spelling_ that produces a model axis changed (`%model:opus`/`%model(opus,sonnet)` → `%{%m:opus | %m:sonnet}`).
- Git history shows the duplicate-name behavior predates the migration: the test
  `test_split_prompt_for_models_multi_model_with_user_alt_cartesian` asserted `foo.cld-opus` for **both** the `x` and
  `y` branches (commit `a6af84ef5`, before the migration). The migration only updated the prompt spelling and the suffix
  separator (`-` → `_`), keeping the same duplicate assertions.
- The unit test passes today only because `split_prompt_for_models` returns the per-slot prompts **without** running the
  allocator's uniqueness check. The duplicates surface only on the real launch path.

The user hit it now because they combined a text alt-axis with a multi-model xprompt — a combination that simply wasn't
exercised before. (The bug is also reachable via the _model-first_ ordering already encoded in the existing test.)

### Boundary note (no Rust / sase-core change needed)

The model→runtime-label suffix mapping (`cld`, `cdx`, `cld_opus`, …) is produced entirely in Python via
`sase.llm_provider.registry`/`config`. The Rust core only emits `alt_id` + `model` per slot and renders templates
(`render_agent_name_template`); it has no knowledge of provider short names. Per the `rust_core_backend_boundary` litmus
test, this naming/suffix layer is presentation-side Python glue. **The fix is Python-only**; `sase-core` is unaffected.

## Fix

Single focused change in `src/sase/xprompt/_directive_alt.py`, in `_fanout_suffixes` (with one small helper).

Goal: when the model-suffix path applies, **replace only the model-axis component of the `alt_id` with the model
suffix**, keeping every other (non-model) axis component. This preserves the nice pure-model naming while keeping the
extra axes distinct.

1. Add a helper `_detect_model_axis(component_lists, label_models_per_sub) -> int | None`:
   - Split each slot's `alt_id` into dot components.
   - Find the single component position whose value maps **consistently** to the slot's resolved model across all slots
     (same component value ⇒ same model) and is **non-constant** (≥2 distinct models). Return that index, else `None`.
   - This robustly handles text×model, model×text, multi-text×model, and the pure model case (single component ⇒ index
     0). It also tolerates a stray second model-bearing alt directive (the Rust core binds `slot.model` to one axis; the
     other axis is then treated as a plain text axis and still disambiguates correctly).

2. In `_fanout_suffixes`, change the model-suffix branch. Today:

   ```python
   suffixes.append(
       alt_suffix if _alt_id_has_named_component(slot.alt_id)
       else model_suffix_for[label_model]
   )
   ```

   New behaviour (named-branch case is unchanged — full `alt_id` is already unique):
   - If `alt_id` has a named component → keep `alt_suffix` (current behaviour).
   - Else if a model axis index was found → build the suffix from the `alt_id` components with the model-axis component
     replaced by `model_suffix_for[label_model]`, then run it through `_safe_fanout_suffix`.
   - Else (no identifiable model axis — pathological) → fall back to `alt_suffix` (full `alt_id`), which is always
     unique.

3. Defensive final pass: after assembling all suffixes, if any duplicates remain among the non-`None` suffixes, fall
   back the whole group to full-`alt_id` suffixes (always unique). This mirrors the existing alias-collision fallback in
   `_model_suffixes` and guarantees the allocator's uniqueness check can never be tripped by fan-out naming again.

### Resulting names (validated against a standalone prototype using the real helpers)

| prompt shape                                            | suffixes (before)                                                | suffixes (after)                                           |
| ------------------------------------------------------- | ---------------------------------------------------------------- | ---------------------------------------------------------- |
| pure model `%{%m:opus \| %m:#codex}`                    | `cld`, `cdx`                                                     | `cld`, `cdx` (unchanged)                                   |
| pure model same runtime `%{%m:opus \| %m:sonnet}`       | `cld_opus`, `cld_sonnet`                                         | unchanged                                                  |
| text × model (bad prompt)                               | `cld`, `cdx`, **`cld`**, **`cdx`** (dup)                         | `1.cld`, `1.cdx`, `2.cld`, `2.cdx`                         |
| model × text (existing test)                            | `cld_opus`, **`cld_opus`**, `cld_sonnet`, **`cld_sonnet`** (dup) | `cld_opus.1`, `cld_opus.2`, `cld_sonnet.1`, `cld_sonnet.2` |
| text × text × model                                     | dup                                                              | `1.1.cld`, `1.1.cdx`, … (all unique)                       |
| named model branches `%{o=%m:opus \| c=%m:#codex} %{…}` | `o.1`, `o.2`, `c.1`, `c.2`                                       | unchanged                                                  |
| 3-model swarm × text                                    | dup                                                              | `1.cld`, `1.cdx`, `1.agy`, `2.cld`, …                      |
| text-only (no model)                                    | `1`, `2`, `3`                                                    | unchanged                                                  |

Pure model fan-out naming is byte-for-byte unchanged, so the recently-confirmed multi-model naming parity is preserved.
Component order follows document order of the alt directives, so the model suffix lands where the model directive was
written.

## Tests

1. **Update** `tests/test_directives_split_models.py`:
   - `test_split_prompt_for_models_multi_model_with_user_alt_cartesian` currently asserts the **buggy duplicate** names
     (`foo.cld_opus` for both `x` and `y`). Change it to assert the new unique names
     (`foo.cld_opus.1`/`foo.cld_opus.2`/`foo.cld_sonnet.1`/`foo.cld_sonnet.2`) and add an explicit "all names are
     distinct" assertion.

2. **Add** a regression test for the user's exact shape (text-first × model-last):
   `%n:foo %{Describe | Explain} repo. %{%m:opus | %m:#codex}` → 4 slots with unique names `foo.1.cld` / `foo.1.cdx` /
   `foo.2.cld` / `foo.2.cdx`.

3. **Add** an end-to-end launch regression in `tests/test_multi_prompt_launcher_xprompt_groups.py` (or
   `tests/test_multi_prompt_launcher_planned_name_allocator.py`): launching a text-alt × multi-model prompt resolves
   template references and **does not raise** `template group rendered duplicate concrete names`. This is the assertion
   that actually reproduces the reported failure (the `split_prompt_for_models` unit tests bypass the allocator).

4. **Audit** other naming-assertion tests for the same combined-axis pattern and update if needed:
   `tests/ace/tui/test_agent_launch_dispatch.py`, `tests/test_multi_prompt_launcher_*`,
   `tests/test_cd_launch_from_cwd_multi_agent.py`. (Single-axis model fan-out and fork/wait-prefixed cases such as
   `foo.f1.cld_opus` already produce distinct names and need no change.)

## Verification

- `just install` (rebuild the binding) then `just check` (ruff + mypy + pytest).
- Manual smoke: launching the `~/tmp/bad_prompt.txt` prompt (and the bare
  `%{Describe | Explain} repo. %{%m:opus | %m:#codex}`) fans out to four agents with distinct names and no `ValueError`;
  a pure `%{%m:opus | %m:#codex}` still yields `@.cld` / `@.cdx`; a single `%m:opus` still launches one agent.

## Out of scope

- No `sase-core` (Rust) change — naming/suffix generation is Python-only.
- Minor cosmetic gap where a **named** non-model axis combined with an **unnamed** model axis uses the full `alt_id`
  (e.g. `1.quick`) instead of the model label (`cld_opus.quick`). That path already produces unique names, so it is not
  a correctness issue and is left as-is.

---
create_time: 2026-06-23 09:18:13
status: done
prompt: sdd/prompts/202606/remove_model_directive_multi_arg.md
---
# Plan: Remove Multi-Argument Support from the `%m` / `%model` Directive

## Goal

Completely remove every form of passing **multiple model arguments** to the `%m` / `%model` directive. After this change
`%m` / `%model` resolves to **exactly one** model. Any multi-model fan-out must be expressed with the existing `%alt` /
`%{...}` machinery, e.g.:

```
OLD: %m(claude/opus, codex/gpt-5.5)
NEW: %{%m:claude/opus | %m:codex/gpt-5.5}
```

Two legacy forms are being removed (per the user's Q&A decisions):

1. **Paren multi-arg** — `%m(opus, sonnet)` / `%model(opus, sonnet)`.
2. **Repeated directives** — `%model:opus` … `%model:sonnet` collapsing into a per-model fan-out. Repeated `%model` is
   now treated like any other duplicate single-value directive.

Misuse must **fail fast with a clear migration hint** (mirroring the existing `%wait:5m → "use %time:5m instead"`
precedent) — no legacy/best-effort fallback. Example message:

```
%m(opus, sonnet) is no longer supported; use %{%m:opus | %m:sonnet} instead
```

### What stays exactly the same

- A single top-level model plus alt text variations: `%model:opus %{Focus on security | Focus on perf}`.
- The new canonical multi-model form `%{%m:opus | %m:sonnet}` — models live **inside** alt branches, are split by the
  alternatives machinery, and already produce the same per-runtime / per-model agent name suffixes (`foo.cld-opus`,
  `foo.cld-sonnet`) that `%m(opus,sonnet)` produced. This path is unchanged; the implementer must confirm naming parity
  so the multi-model UX survives the migration.
- Models used as named alt branches: `%alt(opus=%model:opus, sonnet=%model:sonnet)` /
  `%{opus=%m:opus | sonnet=%m:sonnet}`.

## Architecture / where the behavior lives

The fan-out planner is the **authoritative gate**: every launch surface (TUI, CLI, Telegram) calls
`plan_prompt_fanout_variants` / `plan_agent_launch_fanout` before launching. The canonical implementation is the Rust
core (`sase_core`); Python re-implements only the slice that needs Python-side xprompt (`#ref`) resolution. So the
removal lands in the Rust core first, then in the thin Python mirror, then in the secondary directive extractor.

This change spans **four repos**:

- **sase-core** (Rust) — authoritative fan-out planner + directive metadata + Rust tests.
- **sase** (Python) — Python `#`-ref fan-out mirror, the `extract_prompt_directives` backstop, docs, Python/TUI tests.
- **sase-telegram** — user docs, comments, and tests that use the old syntax as a sample multi-model prompt.
- **chezmoi dotfiles** — the user's `m_*` xprompt definitions.

Linked-repo edits must go through `sase workspace open -p <repo> -r "<reason>" <N>` and be committed in their own repo.

---

## Phase 1: sase-core (Rust) — make multi-model an error, not a rewrite

File: `crates/sase_core/src/agent_launch/mod.rs`

1. **Add an error variant.** Extend `AgentLaunchFanoutPlanError` (around line 202) with a new
   `MultiModelUnsupported(String)` variant whose `Display` emits the migration hint. The pyo3 binding already maps every
   `AgentLaunchFanoutPlanError` to `PyValueError` (`crates/sase_core_py/src/lib.rs` `py_plan_agent_launch_fanout`), and
   the Python `_plan_model_fanout` already converts that `ValueError` into a `DirectiveError`, so the hint flows through
   to users unchanged — **no binding change needed**.

2. **Replace collection-and-rewrite with detection-and-raise** in `split_prompt_for_models_with_ids` (lines 477-553). It
   currently collects every top-level `%model` directive (already excluding fenced/disabled/alt-inner regions), dedupes,
   and — when ≥2 unique — rewrites them into a single `%alt(%model:a,%model:b,…)`. Change it so that, over the top-level
   `directive_spans`:
   - any single span with **more than one parsed arg** (the paren multi-arg form), **or**
   - **more than one** top-level `%model` occurrence carrying a value (the repeated form)

   returns `Err(MultiModelUnsupported(...))` with the migration hint. Exactly one top-level model (incl. single-arg
   `%model(opus)`) and zero top-level models still fall through to `split_prompt_for_alternatives_with_ids` unchanged.
   Delete the now-dead unique-model dedup + `%alt` rewrite block. The error propagates automatically through
   `plan_model_fanout` and the `"auto"` branch of `plan_agent_launch_fanout` via `?`.

3. **Edge cases to settle with tests:** bare `%model` (no value) used as a placeholder should not by itself trip the
   "repeated" check; `%model+` (plus sentinel) is already skipped; `%model()` (empty parens) carries no arg. Two
   same-value occurrences (`%model:opus` twice) is still misuse and must raise (duplicate single-value semantics).

File: `crates/sase_core/src/editor/directive.rs`

4. Flip the `model` directive metadata `allows_multiple: true → false` (line 9), matching its new single-value nature.
   This field is surfaced to editor frontends (LSP/nvim) via `DirectiveMetadata`; keep `alt`/`wait`/`time` as-is.

5. **Update Rust tests** in `mod.rs`. Tests whose subject is the removed behavior become error assertions; tests that
   merely _used_ multi-model syntax to exercise alt/Cartesian/whitespace logic switch to the `%{...}` form:
   - `fanout_planner_splits_models_and_alternatives` (repeated `%model` × `%alt`) → assert error, plus add/retain a
     Cartesian test using `%{%m:opus | %m:sonnet} %alt(x,y)`.
   - `fanout_planner_empty_branch_preserves_following_directive_separator` (uses `%model(opus,gpt-5.5)`) → rewrite to
     `%{%m:opus | %m:gpt-5.5}`.
   - `fanout_planner_brace_does_not_double_collect_nested_models` (`%model:opus\n%model:sonnet %{x | y}`) → assert error
     or repurpose to the new single-model-plus-alt shape.
   - Keep `fanout_planner_model_alt_ids_preserve_named_model_branches` and
     `fanout_planner_brace_model_branches_match_paren_parity` (models inside alt — already the supported form).
   - Add new tests: `%m(opus,sonnet)` errors with the hint; `%model:opus\n%model:sonnet` errors with the hint; single
     `%m:opus` / `%model(opus)` still plan a single agent; `%{%m:opus | %m:sonnet}` still yields two model slots with
     the expected suffixes; any metadata test asserting `allows_multiple` for `model` flips to `false`.

---

## Phase 2: sase (Python) — mirror the rejection and harden the extractor

File: `src/sase/xprompt/_directive_alt.py`

1. In `_plan_prompt_fanout` (the `#`-xprompt path, lines ~181-320), replace the collect/dedupe/rewrite-to-`%alt` block
   with the same detection as the Rust core: a paren span with >1 arg, or >1 top-level `%model` occurrence → raise
   `DirectiveError` with the migration hint. Keep the single-model passthrough (`directive_spans` with one model still
   falls through to `_plan_model_fanout`). Remove the now-dead `unique_models` dedup and the splice/rewrite code. The
   xprompt-shorthand resolution (`_model_value_for_naming`) is still needed by `_apply_fanout_naming`, so leave the
   naming/suffix helpers intact — they apply to the resulting model slots regardless of how the fan-out was spelled.
2. Update the module + `split_prompt_for_models` docstrings to drop the "rewrites `%model(a,b)` → `%alt(...)`" and
   "repeated scalar … collapsed" descriptions and state the new single-model contract.

File: `src/sase/xprompt/directives.py` — `extract_prompt_directives` (the secondary backstop)

3. Remove the `%model` soft exception. Today line 228 (`if name in _MULTI_VALUE_DIRECTIVES or name == "model"`) lets
   duplicate `%model` through with last-wins. Drop `or name == "model"` so `%model` is a normal single-value directive:
   a duplicate raises (with a model-specific migration hint rather than the generic "Duplicate directive" text), and a
   paren span with >1 positional arg raises (instead of silently taking the first arg at lines 250-251).
4. **Critical compatibility guard:** the new canonical syntax `%{%m:opus | %m:sonnet}` contains two `%model` directives
   _inside_ an alt block, and several metadata-only callers run the extractor on the **raw, un-split** prompt
   (`_prompt_bar_mount.py` `%edit` check, `query_handler/_query.py` display metadata, `agent/names/_resume.py` wait
   parsing, `history/prompt_metadata.py`). To avoid the extractor falsely flagging those branch-local models as
   top-level duplicates, **protect `%alt(...)` / `%{...}` / `%(...)` inner regions** in `extract_prompt_directives` the
   same way it already protects fenced and disabled regions (reuse `_ALT_DIRECTIVE_RE` + the matching-brace/paren
   helpers, as `_plan_prompt_fanout` does). After this, only _top-level_ `%model` directives are considered for
   duplicate/multi-arg detection; alt-inner models are left untouched (post-split prompts have no alt regions, so this
   is a no-op on the normal launch path). Update the function docstring accordingly.

Files: TUI launch comments

5. `src/sase/ace/tui/actions/agent_workflow/_launch_multi_model.py` (module docstring) and
   `src/sase/ace/tui/actions/agent_workflow/_launch_body.py` (comments at lines ~517-535) reference `%m(opus,sonnet)` /
   `#m_opus_codex -> %model(opus, #codex)`. Update those comments to the `%{...}` form. The `_launch_multi_model_agents`
   logic is generic over fan-out plans and needs no behavioral change.

Files: user docs

6. `docs/xprompt.md`: rewrite the **"Multi-Model Directive"** section (lines ~1314-1339) and the Cartesian example
   (lines ~1301-1309) to teach `%{%m:opus | %m:sonnet}` as the only multi-model form, state that comma/paren multi-arg
   and repeated `%model` are no longer supported, and keep the agent-naming/suffix explanation (it still applies). Fix
   the `%model(claude-sonnet)` "parenthesis syntax" mention (line ~988) so it no longer implies multi-arg.
7. `docs/llms.md`: update the worker-lane examples `%m(other,gpt-5.5)` / `%m(other, …)` (lines ~583-604) to the `%{...}`
   form (e.g. `%{%m:other | %m:gpt-5.5}`).
8. **Out of scope:** the historical `sdd/{tales,epics,research}/**` design docs that mention the old syntax — these are
   dated records of prior work and are intentionally left unchanged.

Files: Python tests to update (audit each; convert "splits into N" expectations to error assertions or the `%{...}`
form, and replace duplicate-`%model` last-wins assertions):

- `tests/test_directives_split_models.py` (paren, repeated, mixed multi-model splitting)
- `tests/test_directives_extract.py` (`test_alias_m_and_model_duplicate_last_wins`,
  `test_identical_duplicate_model_directives_accepted` → now assert raises; add a test that a raw
  `%{%m:opus | %m:sonnet}` extracts without error and reports no top-level model)
- `tests/test_multi_prompt_launcher_xprompts_models.py` (segment `%model(opus,sonnet)` per-model spawn)
- `tests/test_directives_has_helpers.py`, `tests/test_directives_strip.py`,
  `tests/test_cd_launch_from_cwd_multi_agent.py`, `tests/test_core_agent_launch_wire.py`,
  `tests/ace/tui/test_agent_launch_dispatch.py` — audit for paren/repeated multi-model usage and update.

---

## Phase 3: sase-telegram — docs, comments, and tests

Open with `sase workspace open -p sase-telegram`. The old syntax is used as a sample "multi-model prompt" that routes
through the canonical pipeline; the new syntax keeps those samples valid (the plugin passes the raw prompt through and
the canonical pipeline still does the fan-out, so the routing assertions remain meaningful).

- `README.md` (line ~61) and `docs/inbound.md` (line ~96): update the `%m(opus,sonnet)` user-facing example to
  `%{%m:opus | %m:sonnet}`.
- `src/sase_telegram/scripts/sase_tg_inbound.py` (comments at lines ~1118, 1137-1140): update the `%m(opus,sonnet)`
  references in docstrings/comments.
- `tests/test_inbound.py` (`test_multi_model_launches_via_canonical_pipeline`,
  `test_multi_model_photo_records_project_context_once`, lines ~1769-1893): replace the `%m(opus,sonnet)` prompts with
  `%{%m:opus | %m:sonnet}`; the assertions that the prompt is forwarded unchanged still hold.
- `CHANGELOG.md` references are historical — leave them.

---

## Phase 4: chezmoi — migrate the `m_*` xprompts

The user's `m_*` xprompts are all defined in `~/.local/share/chezmoi/home/dot_config/sase/sase.yml` (the chezmoi
source). Edit the source, then `chezmoi apply` so `~/.config/sase/sase.yml` is updated. Migrations:

| xprompt           | old value                      | new value                                    |
| ----------------- | ------------------------------ | -------------------------------------------- |
| `m_agy_pro_flash` | `%model(#agy_pro, #agy_flash)` | `%{%m:#agy_pro \| %m:#agy_flash}`            |
| `m_opus_codex`    | `%model(opus, #codex)`         | `%{%m:opus \| %m:#codex}`                    |
| `m_opus_sonnet`   | `%model(opus, sonnet)`         | `%{%m:opus \| %m:sonnet}`                    |
| `m_swarm`         | `%model(opus, #codex, #agy)`   | `%{%m:opus \| %m:#codex \| %m:#agy}`         |
| `m_jet_agy`       | `#m_jet #m_agy_pro_flash`      | `%{%m:#jet \| %m:#agy_pro \| %m:#agy_flash}` |

Notes:

- `m_jet_agy` currently composes a single model (`#m_jet`) with a 2-model xprompt (`#m_agy_pro_flash`), which today fans
  out to **3** agents via the repeated-directive collapse. That composition breaks under the new rules (it would put two
  top-level models in each split branch), so it is **flattened** to an explicit 3-branch alt. (Confirm 3-way is the
  intended shape.)
- `m_flash`, `m_pro`, `m_pro_flash`, `m_jet_pro_flash` are pure single-reference indirections to the xprompts above and
  need **no edit** — they keep working once their targets are migrated (a lone `#m_agy_pro_flash` now expands to a
  `%{...}` block, which is fine).
- The `#codex` / `#agy` / `#jet` / `#agy_pro` / `#agy_flash` tokens are carried over verbatim from the old paren args,
  so model resolution is unchanged.

---

## Verification

- **sase-core:** run the crate's Rust test suite (`cargo test` / the repo's `just check`); confirm the new error tests
  and the flipped `allows_multiple` metadata pass.
- **sase:** `just install` (rebuilds the `sase_core_rs` binding so the Rust change is picked up) then `just check`
  (ruff + mypy + pytest). No directive-regex change is required — `%model(a,b)` must still _parse_ so it can be
  _rejected_; rejection is at the semantic layer.
- **sase-telegram:** run its test suite in the opened workspace.
- **Manual smoke test:** launching `%m(opus, sonnet) review` surfaces the migration error;
  `%{%m:opus | %m:sonnet} review` fans out to two agents named with model suffixes; `#m_swarm` fans out to three; a
  single `%m:opus` launches one agent.

## Suggested landing order

1. sase-core (Rust authoritative change). 2. sase (Python mirror + rebuild binding + docs/tests). 3. sase-telegram.
2. chezmoi (`chezmoi apply`). The Rust and Python changes are coupled through the rebuilt binding and should land
   together.

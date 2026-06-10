---
create_time: 2026-06-09 20:36:35
status: done
prompt: sdd/prompts/202606/worker_model.md
bead_id: sase-4k
tier: epic
---
# Worker Model: A Secondary Default LLM Model for Delegated Work

## Problem

SASE has exactly one default-model lane today: `%model` directive → temporary override (`~/.sase/llm_override.json`, set
via the `,o` TUI modal) → configured `llm_provider.provider` → autodetect. Every agent launch that doesn't carry an
explicit `%model` directive resolves through this single chain.

That is wrong for delegated "secondary" work. When `sase bead work` fans out phase agents for an epic
(`src/sase/bead/work.py:render_multi_prompt()`), each phase segment gets `%model:<bead model>` only if the bead
explicitly specifies a model; otherwise the phase agent silently uses the primary default. Users who want planning on a
strong model and phase execution on a cheaper/faster model must hand-annotate every bead.

We want a **secondary default model** that:

- is configurable in `sase.yml`, but optional — when unset, behavior is exactly today's (fall through to the
  override/default chain);
- can itself be temporarily overridden from the TUI model override panel, symmetrically with the primary override;
- is automatically used by epic phase agents (and is trivially adoptable by other secondary launch sites later);
- ends up configured to `codex/gpt-5.5` in Bryan's chezmoi-managed `sase.yml`.

## Naming

The feature is called the **worker model** (`llm_provider.worker_model`). Rationale:

- Phase agents are launched by `sase bead work` via the `work_phase_bead` xprompt — "worker" is already this domain's
  vocabulary, not a new coinage.
- It pairs intuitively with the existing planner-grade primary lane ("planner thinks, workers execute"), echoing the
  existing "Same as planner" wording in `ModelPickerModal`.
- It names the _role_ (who uses it), not the mechanism ("secondary"/"fallback"), which makes config self-documenting:
  `worker_model: codex/gpt-5.5`.

Throughout the design, the existing default chain is the **primary lane** and the new chain is the **worker lane**.

## Design Overview

Two parallel lanes, where the worker lane drains into the primary lane when nothing worker-specific is set:

```
PRIMARY lane (existing, unchanged)          WORKER lane (new)
1. %model directive on the prompt           1. %model directive / per-bead model (existing, still wins)
2. temporary primary override               2. temporary worker override        (TUI, llm_worker_override.json)
3. llm_provider.provider + tier             3. llm_provider.worker_model        (sase.yml, optional)
4. autodetect                               4. ── falls through to PRIMARY lane steps 2-4 ──
```

Key property: the two lanes are independent and predictable. A worker override or configured `worker_model` never
affects primary launches; a primary override only reaches worker tasks when the worker lane is completely unset. This
matches the requested semantics ("if not provided, the current default model or override model is used in its place")
while keeping each lane's mental model simple.

### Mechanism 1: role-aware temporary override store

`src/sase/llm_provider/temporary_override.py` becomes role-aware:

- New `ModelRole = Literal["primary", "worker"]` (in `src/sase/llm_provider/types.py`).
- `get_active_temporary_override()`, `set_temporary_override()`, and `clear_temporary_override()` gain a keyword-only
  `role: ModelRole = "primary"` parameter. Default keeps every existing caller and the on-disk format 100% backward
  compatible.
- State files: `~/.sase/llm_override.json` (primary, unchanged name) and `~/.sase/llm_worker_override.json` (worker).
  Same `TemporaryLLMOverride` dataclass, same atomic write / self-cleaning expiry / duration parsing semantics.
- The `pre_override_*` snapshot is captured per-lane (snapshot of that lane's prior effective model). The reserved
  `other` alias remains tied to the primary lane only — no behavior change.

### Mechanism 2: worker-lane resolution

New `resolve_effective_worker_provider_model(model_tier="large") -> tuple[str, str]` in `temporary_override.py`, sibling
to `resolve_effective_default_provider_model()`:

1. Active worker override → its `(provider, model)`.
2. Configured `llm_provider.worker_model` (new accessor `get_configured_worker_model()` in
   `src/sase/llm_provider/config.py`; tolerant of missing/blank/non-string → unset) → resolved via the existing
   `resolve_model_alias()` + `resolve_model_provider()` rules, so provider syntax (`codex/gpt-5.5`), bare models, and
   user aliases all work. Guard against the self-referential value `worker` (treat as unset).
3. Otherwise → return `resolve_effective_default_provider_model(model_tier)` (primary override → provider → autodetect).

### Mechanism 3: the reserved `worker` model alias

Mirroring the reserved `other` alias in `resolve_model_alias()` (`src/sase/llm_provider/config.py`), the literal model
name `worker` becomes reserved: it short-circuits to the worker lane's effective `(provider, model)` formatted as
`provider/model`. Because the worker lane always drains into the primary lane, `worker` always resolves to a concrete
model — it can never leak the literal string "worker" into a launch.

This gives the feature a beautiful, composable surface for free:

- `render_multi_prompt()` injects a one-line `%model:worker` directive instead of hardcoding a resolved model — the
  rendered prompt stays readable and self-documenting, and resolution is late-bound to each agent's start.
- Users can hand-write `%model:worker` / `%m(worker)` in any prompt or xprompt to opt any agent into the worker lane.
- Future secondary launch sites (hooks, summarizers) adopt the worker lane by adding one directive.

A user-defined `model_aliases.worker` is shadowed by the reserved meaning; documented as reserved (same precedent as
`other`).

### Consumers: which launches use the worker lane

- **Epic phase agents** (`render_multi_prompt()` in `src/sase/bead/work.py`): phase segments without an explicit
  per-bead `assignment.model` get `%model:worker`. Beads with explicit models keep them (step 1 of the lane).
- **Land agents** (`land_epic` / `land_legend` segments): stay on the primary lane. Landing integrates and merges the
  whole epic — it deserves planner-grade strength unless the user explicitly sets `land_model`.
- **Legend epic-planning agents** (`render_legend_multi_prompt()` assignments): stay on the primary lane — they do
  planning work, not phase execution.
- Backward compatibility: with no worker override and no `worker_model` configured, `%model:worker` resolves to exactly
  what the no-directive path resolves to today, so existing users see zero behavior change.

### TUI: dual-lane Model Overrides modal

`TemporaryLLMOverrideModal` (`src/sase/ace/tui/modals/temporary_llm_override_modal.py`) becomes a two-lane panel,
retitled **"Model Overrides"**:

```
┌─ Model Overrides ────────────────────────────────────┐
│                                                      │
│  PRIMARY   claude(opus)                    default   │
│  WORKER    codex(gpt-5.5)                  config    │
│                                                      │
│   s    Set primary override                          │
│   w    Set worker override                           │
│   esc  cancel                                        │
└──────────────────────────────────────────────────────┘
```

- Each lane row shows its current effective model with provider-palette coloring (reuse `provider_styles.py`) plus a
  right-aligned, muted source tag: `override · 47m left`, `config`, `follows primary`, or `default`.
- Keys preserve existing muscle memory and tests: primary keeps `s` (set) / `c` (change) / `x` (clear). Worker adds `w`
  (set/change) and `W` (clear, shown only when a worker override is active).
- Both lanes reuse the existing `ModelPickerModal` (with `include_default_option=False`; worker flow titled "Pick Worker
  Model"), `CustomModelInputModal`, and `_DurationPickerModal` flows unchanged; the worker flow ends in
  `set_temporary_override(raw, seconds, source="ace", role="worker")` and a toast like
  `Worker model override: codex(gpt-5.5) for 1h`.
- `LLMOverrideIndicator` (top bar) additionally shows a compact worker chip **only while a worker override is active**
  (e.g. `Override codex(o3) 1h · W gpt-5.5 30m`). The steady-state configured `worker_model` is visible in the modal,
  not the top bar — temporary state gets ambient visibility, permanent config stays out of the way.
- The leader-mode action id `temporary_llm_override` and the `,o` key stay unchanged (renaming the id would break user
  keymap configs); only display labels in the footer/help modal update to "model overrides".

### Boundary + scope notes

- Model-lane resolution and override state are already a pure-Python launch-policy concern (`llm_provider/`,
  `~/.sase/*.json`); no Rust core (`sase-core`) changes are needed. If override state ever migrates into `sase_core`,
  both lanes move together.
- No new CLI subcommands/options in this work (overrides remain TUI-set, matching today). A `sase llm override` CLI is
  noted as future work; whichever phase adds it later must read `memory/long/cli_rules.md` first.
- Other secondary launch sites (summarize hook, fix-hook, mentors) are deliberately out of scope but trivially adoptable
  later via `%model:worker` or `resolve_effective_worker_provider_model()`.

## Phases

Each phase is self-contained, lands green (`just install` + `just check`), and is implemented by a distinct agent.
Phases 2 and 3 are independent of each other; both depend on Phase 1. Phase 4 depends on all prior phases.

### Phase 1 — Worker-lane core (config, override store, resolution, reserved alias)

Goal: the full worker-lane engine, fully inert (no consumer or UI changes yet).

- `src/sase/llm_provider/types.py`: add `ModelRole`.
- `src/sase/llm_provider/temporary_override.py`: role-aware state paths + `role` keyword on get/set/clear (default
  `"primary"`); per-lane `pre_override_*` snapshots; new `resolve_effective_worker_provider_model()`.
- `src/sase/llm_provider/config.py`: `get_configured_worker_model()`; reserved `worker` alias short-circuit in
  `resolve_model_alias()` (with self-reference guard and no recursion into itself).
- `src/sase/default_config.yml`: add commented `worker_model: ""` under `llm_provider`.
- Export any new public names via `src/sase/llm_provider/__init__.py` consistently with siblings.
- Tests (extend existing override/config test modules): role isolation (setting/clearing one lane never touches the
  other's state file), expiry per lane, full worker-lane precedence matrix (override > config > primary override >
  primary default), reserved-alias resolution incl. "nothing configured ⇒ identical to primary default", alias-target
  and provider-syntax `worker_model` values, malformed/blank config tolerance.

### Phase 2 — Epic phase agents launch on the worker lane

Goal: `sase bead work` phase agents use the worker lane; land/legend-planning segments unchanged.

- `src/sase/bead/work.py`: in `render_multi_prompt()`, inject `%model:worker` for phase segments lacking an explicit
  `assignment.model`. Leave the land segment and `render_legend_multi_prompt()` assignments untouched.
- Verify the directive path end-to-end: `%model:worker` flows through `extract_prompt_directives()` →
  `resolve_model_provider()` → `resolve_model_alias()` and lands the resolved provider/model in agent metadata
  (`src/sase/axe/run_agent_directives.py`).
- Tests: rendered multi-prompt snapshots/assertions (worker directive present for unannotated phases, absent for
  annotated phases and land segments); an integration-style test that a phase-agent directive resolution honors worker
  override > `worker_model` > primary; regression test that the rendered prompt is byte-identical to today when the
  worker lane is unset except for the `%model:worker` line (and that this line resolves to the primary default).
- `docs/beads.md`: short note on phase-agent model selection order.

### Phase 3 — TUI: dual-lane Model Overrides modal + indicator

Goal: the `,o` panel manages both lanes; the top bar surfaces active worker overrides. Make it beautiful.

- `src/sase/ace/tui/modals/temporary_llm_override_modal.py`: two-lane layout per the design above (lane rows with
  provider-colored model text + muted source tags; `s`/`c`/`x` primary, `w`/`W` worker; both flows reuse the existing
  picker → optional custom input → duration modal chain with `role` threaded through).
- `src/sase/ace/tui/modals/model_picker_modal.py`: accept an optional title (e.g. "Pick Worker Model"); no behavior
  changes otherwise.
- `src/sase/ace/tui/widgets/llm_override_indicator.py`: worker chip while a worker override is active.
- `src/sase/ace/tui/actions/agent_workflow/_leader_mode.py` + footer/help labels: "model overrides" wording; keep action
  id and `,o` key.
- `src/sase/ace/tui/styles.tcss`: lane-row styles; keep the modal's existing double-border visual language.
- Tests: extend `tests/test_temporary_llm_override_phase5.py` patterns — full worker set/change/clear flows write and
  remove `llm_worker_override.json`; primary flows untouched by worker state; source-tag rendering for all four states
  (override/config/follows-primary/default); indicator chip on/off; help/footer label sync. Add PNG visual snapshots for
  the dual-lane modal (both lanes idle + worker override active) under the existing `tests/ace/tui/visual/` suite if
  modal mounting is supported there (follow existing visual-test patterns; otherwise fall back to Textual pilot
  assertions).

### Phase 4 — Docs, user config, end-to-end polish

Goal: documentation, Bryan's config, and a final whole-feature verification pass.

- `docs/llms.md` + `docs/configuration.md`: document the worker model concept — config key, lane precedence diagram,
  reserved `worker` alias (and that it's reserved in `model_aliases`), the TUI panel, and state files.
- Chezmoi config: add `worker_model: codex/gpt-5.5` to the `llm_provider:` section of
  `/home/bryan/.local/share/chezmoi/home/dot_config/sase/sase.yml`, then `chezmoi apply` and verify
  `~/.config/sase/sase.yml` matches. Leave committing the dotfiles repo to Bryan (note it in the final report).
- End-to-end sanity: with the applied config, assert `resolve_effective_worker_provider_model()` returns
  `("codex", "gpt-5.5")` while the primary lane is unaffected; render an epic work plan dry-run
  (`sase bead work --dry-run` path or unit-level call) showing phase segments carrying `%model:worker`.
- Final `just check` across the repo; fix any drift from earlier phases.

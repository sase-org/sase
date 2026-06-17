---
create_time: 2026-06-17
updated_time: 2026-06-17
status: research
---

# Unifying the Default Model and `worker_models` into a Per-Role Model Config

## Research Request

SASE has a `worker_models` config field that selects the model used for "worker" agents (today: plan/phase
implementation), plus a separate field for the user's default model. The request:

1. **Merge** these two fields into a single config surface.
2. **Expand** that surface so the user can independently configure the model used to:
   - land epics,
   - create epics,
   - implement approved plans (currently part of `worker_models`),
   - implement phases of an epic (currently part of `worker_models`).
3. **Split** the existing single `worker_models` knob, since the bottom two bullets are both folded into it today.

This note maps the current implementation, surfaces the design tensions, proposes several alternatives, and ends with a
recommended approach.

## Bottom Line

Replace `llm_provider.worker_models` (and absorb the default-model lane) with a single **role → model** map,
`llm_provider.models`, resolved through the existing `%model:<spec>` alias machinery. Add one **reserved alias per
role** (`implement_phase`, `implement_plan`, `create_epic`, `land_epic`, `default`). Each role falls through to
`default`, which falls through to today's provider/autodetect chain. Keep each role value polymorphic — a scalar model
spec for the common case, or a primary-lane-keyed sub-map to preserve `worker_models`' current cross-provider power.
Keep temporary overrides coarse (primary + one secondary lane) rather than minting one override per role. No
`sase-core` change is required. See [Recommended Approach](#recommended-approach).

---

## Current State (grounded)

### The two fields being merged

| Field | Type | Role today | Where |
| --- | --- | --- | --- |
| `llm_provider.provider` | `string` (default `""`) | The **default/primary lane**: selects the provider; the *model* is derived from the provider's tier mapping (`large`/`small`). When empty, autodetect walks plugins by `llm_autodetect_priority`. | `src/sase/default_config.yml:270`; `registry.get_configured_default_provider_name()` |
| `llm_provider.worker_models` | `dict[str,str]` (default `{}`) | The **worker/secondary lane**: maps an *effective primary* lane to a worker target. Keys matched most-specific-first: `provider/model` → bare `model` → `provider`. Values accept bare models, aliases, or `provider/model`. | `config/sase.schema.json:577`; `src/sase/llm_provider/config.py:54-81` |

A subtle but important finding: **there is no standalone "default model" scalar today.** The default lane is
*provider + tier*, so a user can only pin their default *provider*, not a specific default *model* (short of a
`%model` directive or a temporary override). Merging is therefore also an opportunity to upgrade the default from
"provider only" to a full model spec.

### How model resolution works today

Everything routes through the `%model:<spec>` directive + alias resolution. Two lanes exist:

```
PRIMARY lane                                  WORKER lane
1. %model directive on the prompt             1. %model directive / per-bead model (wins)
2. temporary primary override                 2. temporary worker override (llm_worker_override.json)
   (~/.sase/llm_override.json)                3. llm_provider.worker_models[primary]
3. llm_provider.provider + tier               4. ── falls through to PRIMARY lane ──
4. autodetect
```

- Primary: `resolve_effective_default_provider_model()` (`temporary_override.py:333`).
- Worker: `resolve_effective_worker_provider_model()` / `resolve_worker_provider_model_for_primary()`
  (`temporary_override.py:380-462`).
- The elegant glue: the **reserved `worker` alias**. `resolve_model_alias("worker")`
  (`config.py:102-108`) short-circuits to the worker lane's `(provider, model)`. Consumers inject a single
  `%model:worker` line and resolution is late-bound at launch. This is the mechanism to generalize.

Design history is captured in `sdd/epics/202606/worker_model.md` (bead `sase-4k`, done): the lane started life as a
scalar `worker_model` and later became the `worker_models` mapping. The singular `worker_model` is now **schema-rejected**
(`tests/test_config_schema.py::test_config_schema_rejects_legacy_worker_model_field`) — establishing the project's
convention: **rename via hard rejection + clear error, never silent migration.**

### How the four target workflows resolve a model *today*

| # | Workflow | Code site | Resolves via | Lane today |
| --- | --- | --- | --- | --- |
| 1 | **Land epic** | `bead/work.py` land segment of `render_multi_prompt()` | default chain (no `%model:worker` injected) | **Primary** |
| 2 | **Create epic** | `run_agent_exec_plan_accept.py:284-369` (epic branch, `#bd/new_epic`) via `_resolve_followup_model()` | `resolve_worker_provider_model_for_primary()` | **Worker** |
| 3 | **Implement approved plan** (coder) | `run_agent_exec_plan_accept.py:371-468` (approve branch) via `_resolve_followup_model()` | `resolve_worker_provider_model_for_primary()` | **Worker** |
| 4 | **Implement phase** | `bead/work.py render_multi_prompt()` injects `%model:worker` per phase segment | `worker` alias → worker lane | **Worker** |

**Correction to the framing in the request:** epic *creation* (#2) already resolves through the worker lane today —
it shares `_resolve_followup_model()` with the coder (#3). Among the four, only **epic landing (#1) sits on the
default/primary lane**. So the work is less "add two brand-new knobs" and more "give the three already-worker-driven
flows (create/plan/phase) their own keys, and promote landing off the shared default." `_resolve_followup_model()`
already branches on `plan_result.action` (`epic`/`legend` vs approve), so it can pick a per-role lane with no
structural change.

### Config system facts that constrain the design

- Schema is **JSON Schema Draft-07** (`config/sase.schema.json`), validated in `tests/test_config_schema.py`. New
  fields need a schema property + a validation test. `llm_provider` uses `additionalProperties: false`, so a renamed
  field is rejected automatically once removed.
- Config is **layered + deep-merged** (defaults → plugins → user → overlays → local). A `dict`-shaped `models:` field
  merges cleanly across layers; a user can override one role without restating the rest.
- **Boundary:** model-lane resolution and override state are pure-Python launch policy (`llm_provider/`, `~/.sase/*.json`).
  The `worker_model` epic explicitly concluded **no `sase-core` change is needed**, and per
  `memory/short/rust_core_backend_boundary.md` this is presentation/launch glue, not shared domain state. (See
  [Boundary note](#boundary-note) for the one caveat.)
- Consumers to touch: `bead/work.py` (`render_multi_prompt` — phase + land segments),
  `run_agent_exec_plan_accept.py` (`_resolve_followup_model` — coder vs epic branch), plus the TUI override modal
  (`ace/tui/modals/temporary_llm_override_modal.py`) which is currently hard-wired to exactly two lanes.

---

## Design Tensions

These recur across every alternative; the alternatives differ mainly in how they resolve them.

1. **Primary-lane keying.** `worker_models` is keyed by the *primary* lane (`claude → codex/gpt-5.5`,
   `codex → claude/opus`). Bryan's chezmoi config uses this for cross-provider symmetry. A flat "role → scalar model"
   design loses it. Do we keep keying per role, drop it, or make it optional?
2. **Merge depth of the default field.** `provider` is load-bearing beyond model choice — it seeds autodetect and is the
   "default provider name" used in many places. Fully deleting it is invasive; folding a `default` *model* on top of it
   is cheap and strictly additive.
3. **Temporary overrides don't want to multiply.** The `,o` modal manages exactly two lanes today (primary + worker).
   Four+ steady-state roles must **not** imply four+ temporary-override lanes, or the modal and the
   `~/.sase/*_override.json` story explode. Steady-state granularity ≠ ephemeral granularity.
4. **Back-compat / migration.** The project rejects renamed fields loudly. Renaming `worker_models` breaks Bryan's
   config and any hand-written `%model:worker`. We need an explicit, low-friction migration story.

---

## Alternative Solutions

### Alternative A — Flat per-role scalar map

```yaml
llm_provider:
  models:
    default: claude/opus        # NEW: pins default model (was provider-only)
    land_epic: claude/opus
    create_epic: codex/gpt-5.5
    implement_plan: codex/gpt-5.5
    implement_phase: codex/gpt-5.5
```

Each role → one scalar spec (provider/model, bare model, or alias). Unset role → `default` → provider/autodetect.

- **Pros:** Dead simple, self-documenting, trivially merges across config layers, one obvious reserved alias per role.
- **Cons:** Drops primary-lane keying (Tension 1) — Bryan's `{claude: codex, codex: claude}` symmetry can't be
  expressed. Forces a hard break of `worker_models`.

### Alternative B — Per-role mapping keyed by primary lane (generalize `worker_models`)

```yaml
llm_provider:
  provider: claude            # default lane stays separate (NOT merged)
  role_models:
    implement_plan:  { claude: codex/gpt-5.5, codex: claude/opus }
    implement_phase: { claude: codex/gpt-5.5 }
    create_epic:     { claude: claude/opus }
    land_epic:       { claude: claude/opus }
```

`worker_models` becomes two of these sub-maps (`implement_plan` + `implement_phase`), plus two new roles. Each preserves
the `provider/model → model → provider` matching and primary fallthrough.

- **Pros:** Maximally faithful generalization; zero loss of current power; smallest conceptual leap from today's code
  (`get_configured_worker_model_entry_for_primary` just gains a `role` arg).
- **Cons:** **Does not satisfy the merge** — `provider` (default) stays separate. Always-nested shape is verbose for the
  common single-provider case. Adding `role_models.default` to fold in the default works but is awkward (a default
  keyed by primary is a near-tautology).

### Alternative C — Unified `models` map, polymorphic values (scalar **or** primary-keyed)

```yaml
llm_provider:
  models:
    default: claude                       # scalar; provider+tier still applies if bare provider
    implement_plan: codex/gpt-5.5         # scalar (common case)
    implement_phase: { claude: codex/gpt-5.5, codex: claude/opus }   # conditional (power case)
    create_epic: opus                     # alias / bare model
    # land_epic omitted -> falls through to default
```

Each value is `oneOf[string, map<string,string>]`. Scalar = today's simple case; map = today's `worker_models` keying.
Merges A's simplicity with B's power.

- **Pros:** Satisfies merge **and** split **and** expand in one field. Simple things stay simple; the niche
  cross-provider case stays expressible. Deep-merges across layers per role.
- **Cons:** Polymorphic value type adds modest schema/parsing complexity (a `oneOf` + a branch in the resolver). Two
  shapes to document.

### Alternative D — Named lanes + role→lane indirection

```yaml
llm_provider:
  provider: claude
  lanes:
    worker: { claude: codex/gpt-5.5 }     # = today's worker_models
    epic:   { claude: claude/opus }
  roles:
    implement_plan:  worker
    implement_phase: worker
    create_epic:     epic
    land_epic:       default
```

Decouple *what models exist* (lanes) from *which workflow uses which* (roles). `%model:lane:<name>` generalizes the
reserved alias.

- **Pros:** DRY when several roles share a lane; very flexible; clean future growth (hooks, summarizers map to lanes).
- **Cons:** Two-level indirection is the heaviest mental model; over-engineered for four roles that mostly want distinct
  values. Adds a new directive syntax.

### Alternative E — Do-minimal: keep `worker_models`, add three sibling scalars

```yaml
llm_provider:
  provider: claude
  worker_models: { claude: codex/gpt-5.5 }   # unchanged; still drives implement_plan + implement_phase
  land_epic_model: claude/opus               # NEW
  create_epic_model: claude/opus             # NEW
```

- **Pros:** Smallest diff; no migration of existing config; ships fastest.
- **Cons:** **Doesn't merge or split** — leaves `worker_models` as the conjoined plan+phase knob and scatters
  model config across mismatched field shapes (`worker_models` dict vs `*_model` scalars). Accrues exactly the
  inconsistency this request exists to remove. Good as a stopgap, poor as the destination.

---

## Recommended Approach

**Adopt Alternative C: a single `llm_provider.models` role map with polymorphic (scalar-or-keyed) values, resolved
through one reserved alias per role.** It is the only option that satisfies merge + split + expand together while
preserving `worker_models`' power and staying on the codebase's existing alias-resolution grain.

### Config shape

```yaml
llm_provider:
  provider: claude            # KEPT: seeds autodetect + default provider name
  models:
    default: claude/opus      # optional; upgrades the default lane from provider-only to a full model spec
    implement_plan: codex/gpt-5.5
    implement_phase: codex/gpt-5.5
    create_epic: claude/opus
    land_epic: claude/opus
    # any value may instead be a primary-keyed map to retain worker_models' cross-provider behavior:
    # implement_phase: { claude: codex/gpt-5.5, codex: claude/opus }
```

Roles (initial set): `default`, `implement_plan`, `implement_phase`, `create_epic`, `land_epic`. (Reserve room for
`create_legend` / `land_legend` later — the legend follow-ups mirror epics in `_resolve_followup_model`.)

### Resolution per role

For role `R`, `resolve_effective_role_provider_model(R)`:

1. Temporary override for R's lane (see override policy below).
2. `models[R]` — if scalar, resolve via existing `resolve_model_alias()` + `resolve_model_provider()`; if a map, match
   the current primary lane `provider/model → model → provider` (reuse `get_configured_worker_model_entry_for_primary`
   logic, generalized to take the sub-map).
3. Fall through to `models.default` (same scalar-or-keyed resolution).
4. Fall through to today's primary chain: `provider` + tier → autodetect.

This makes the **default lane just another role**, which is the "merge," while keeping `provider` as the autodetect
seed (avoids Tension 2's invasive deletion). Steps 2–3 generalize `worker_models` to N roles (the "split" + "expand").

### Reserved aliases (the elegant surface)

Generalize the reserved-`worker` mechanism in `resolve_model_alias()` to one short-circuit per role:
`%model:implement_phase`, `%model:implement_plan`, `%model:create_epic`, `%model:land_epic`, `%model:default`.
Consumers then inject a single role directive and resolution stays late-bound:

- `render_multi_prompt()`: phase segments inject `%model:implement_phase` (was `%model:worker`); land segment injects
  `%model:land_epic` (was nothing → default).
- `_resolve_followup_model()`: pick `implement_plan` for the approve branch, `create_epic` for the epic branch (the
  branch already exists at `run_agent_exec_plan_accept.py:284`/`371`).

### Temporary-override policy (resolves Tension 3)

**Do not** mint one temporary-override file/lane per role. Keep the `,o` modal's two lanes:

- **primary** → backs `default`.
- **secondary/"worker"** → backs *all* non-default roles' step 1 (blankets implement/create/land).

Steady-state per-role granularity lives only in `models:`. Ephemeral overrides stay coarse — "knock everything
secondary onto model X for the next hour" is the real ephemeral need, and it keeps the modal and on-disk override
format unchanged. Rename the modal's "worker" label to "secondary" for accuracy; keep the `,o` action id and key
(renaming the id breaks user keymaps — see `worker_model.md`).

### Migration (resolves Tension 4)

Follow the established `worker_model`→reject precedent:

- Remove `worker_models` from the schema; `additionalProperties: false` makes a leftover `worker_models` fail
  validation. Add a targeted check that emits a clear error: *"`llm_provider.worker_models` was replaced by
  `llm_provider.models`; map `worker_models` → `models.implement_plan` and `models.implement_phase`."* Mirror the
  existing `test_config_schema_rejects_legacy_worker_model_field` with a `worker_models` rejection test.
- Keep `%model:worker` working as a **deprecated alias for `implement_phase`** (its historical injection site), so
  hand-written prompts/xprompts don't break on day one; document it as deprecated. (Alternatively hard-reject it for
  consistency — recommend the soft alias since the blast radius includes user-authored xprompts, which schema rejection
  can't catch.)
- Update Bryan's chezmoi `sase.yml`: `worker_models: {claude: codex/gpt-5.5}` becomes
  `models: {implement_plan: {claude: codex/gpt-5.5}, implement_phase: {claude: codex/gpt-5.5}}` (or scalars if the
  cross-provider keying isn't needed).

### Why not the others

- **A** is the right *shape* but loses primary-lane keying Bryan uses — C is A plus an optional map value, strictly
  more capable at low cost.
- **B** preserves power but fails the merge and is verbose for the common case.
- **D** is the most flexible but over-engineered for four roles and adds new directive syntax.
- **E** ships fastest but entrenches the exact inconsistency this request removes; reasonable only as an interim step.

### Implementation surface (for a later plan)

- `config/sase.schema.json`: add `models` (`oneOf[string, object<string,string>]` values, fixed role keys + future
  room); remove `worker_models`.
- `src/sase/default_config.yml`: commented `models:` example under `llm_provider`.
- `src/sase/llm_provider/config.py`: `get_configured_role_model_entry(role, primary_provider, primary_model)`
  generalizing `get_configured_worker_model_entry_for_primary`; role-aware reserved aliases in `resolve_model_alias()`.
- `src/sase/llm_provider/temporary_override.py`: `resolve_effective_role_provider_model(role, ...)` generalizing the
  worker resolver; keep two override lanes.
- Consumers: `src/sase/bead/work.py` (`render_multi_prompt` — phase + land directives);
  `src/sase/axe/run_agent_exec_plan_accept.py` (`_resolve_followup_model` — role per branch).
- TUI: relabel `temporary_llm_override_modal.py` "worker" → "secondary"; behavior unchanged.
- Tests: schema accept/reject (`tests/test_config_schema.py`), role-resolution precedence matrix
  (extend the override/config test modules), `_resolve_followup_model` per-role selection
  (`test_axe_run_agent_exec_plan_followup_model_selection.py`), `render_multi_prompt` directive assertions.
- Docs: `docs/llms.md`, `docs/configuration.md`, `docs/beads.md`. No new CLI subcommand ⇒ no `cli_rules.md` /
  generated-skill work (confirm before assuming).

### Boundary note

Per the `worker_model` epic and `memory/short/rust_core_backend_boundary.md`, this is pure-Python launch policy — **no
`sase-core` change today.** The one forward-looking caveat the litmus test raises: if a non-TUI frontend (web, CLI
daemon, editor) later launches these same workflows and must pick the *same* per-role model to match the TUI, the
*role→model resolution rules* (not the Textual UI) become shared domain behavior and would belong in `sase_core`. That
is out of scope here; flag it as a revisit-if condition rather than a now-task.

## Open Questions / Decisions for the User

1. **Role value shape:** accept the polymorphic scalar-or-map values (recommended), or keep it strictly scalar
   (Alternative A) and drop `worker_models`' cross-provider keying?
2. **`%model:worker` fate:** keep as a deprecated alias for `implement_phase` (recommended, protects user xprompts), or
   hard-reject for consistency with `worker_model`?
3. **Default lane:** introduce `models.default` as a full model spec while keeping `provider` as the autodetect seed
   (recommended), or also retire `provider`?
4. **Role naming:** `implement_plan` / `implement_phase` / `create_epic` / `land_epic` — confirm these names (they drive
   both the config keys and the reserved aliases). Should `create_legend` / `land_legend` be reserved now or deferred?
5. **Scope of the secondary temporary override:** blanket *all* non-default roles (recommended) or only the implement
   roles?

---
title: Instruction bundle internals
description:
  Manifest, storage, cache, and delivery contracts for generated instruction bundles.
---

# Instruction bundle internals

This page documents the storage and delivery contracts behind instruction bundles.

## Bundle and manifest

A **bundle** is one Markdown document composed from memory: package, home, and project
layers under compiler-generated frame headings. A **manifest** is the JSON sidecar
describing that bundle: schema version, compiler identity, host-set facts, bundle
digests and size, per-layer budgets, the ordered section table (included sections with
byte offsets, excluded sections with reasons), delivery identity, and observation
status.

The manifest wire contract — closed vocabulary, validation invariants, and the
`common_digest` definition — is owned by `sase-core` (`instruction_manifest` module,
schema version 2). Markdown composition stays in Python (`sase.instructions`), which
reuses the legacy memory renderer through its structured units API. Only Python needs
composition today (launch and CLI preview); if a non-Python front end ever needs to
preview a render, composition moves into Rust rather than growing a second copy.

## Layers and section ids

The fixed layer order is package → plugin → home → project → launch, with `frame`
sections as document scaffolding. Every byte of a bundle belongs to exactly one section:

| Layer     | Section ids                                                                                  | Source                                                |
| --------- | -------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| `frame`   | `frame.title`, `frame.core`, `frame.reference`, `frame.webs`                                 | Compiler headings and the intro paragraphs            |
| `package` | `pkg.sase.*`, `pkg.root.final_declaration`, `pkg.helper.contract`, `pkg.provider.<provider>` | Contract template, helper template, adapter directive |
| `plugin`  | `plugin.<dist>.<slug>`                                                                       | Reserved; currently empty                             |
| `home`    | `home.core.<stem>`, `home.ref.<stem>`, `home.web.<stem>`                                     | Home memory at `Path.home()`                          |
| `project` | `proj.core.<stem>`, `proj.ref.<stem>`, `proj.web.<stem>`                                     | The project root's memory                             |
| `launch`  | `launch.<slug>`                                                                              | Reserved; currently empty                             |

The compiler renders the contract template once — with the project name and the merged
linked entries (project entries first, home-only entries tagged as home configuration) —
and splits it on H2 headings into the fixed ids. Unknown H2 headings in an override
template get `pkg.sase.<slug of heading>` and are lifecycle-neutral. Generated
`sase/memory/sase.md` notes (project and home) are superseded input: excluded with
reason `superseded_input`. A project note shadows a same-path home note, recorded as
`shadowed` plus `shadowed_by`.

Bundle layout: `#` title (plus a `Home:` line when the home layer contributes),
`## Core Memory` with the package sections then home and project core notes,
`## Reference Memory` with one entry per note, and `## Memory Webs` with one block per
web. Empty groups omit their frame section. Section bytes are
`text.rstrip("\n") + "\n\n"`, concatenated, so offsets are contiguous. Bundle bytes
never embed absolute paths, workspace names, timestamps, or hostnames: identical inputs
from any workspace give identical bytes.

## Overlays and facts

Each included section carries `lifecycle`: `neutral`, `root`, or `helper`. Facts are set
by the host — project content cannot set them:

| Fact       | Values                                                    |
| ---------- | --------------------------------------------------------- |
| `actor`    | `sase_root` \| `native_helper` \| `interactive`           |
| `mode`     | `runtime` \| `interactive` \| `export`                    |
| `purpose`  | `ordinary` \| `declaration_recovery` \| `conflict_repair` |
| `provider` | execution provider name                                   |
| `project`  | project memory name or null                               |
| `host`     | short hostname                                            |
| `vcs`      | VCS provider name or null                                 |

The root render (`runtime` + `sase_root`) carries `pkg.root.final_declaration` and
`pkg.provider.<provider>`; the helper render carries `pkg.helper.contract` instead.
Interactive and export renders carry neither; export additionally carries no `home.*`
content. Only the root render contains the `SASE Final Declaration` heading. Rendering
for `native_helper` is compiled at the boundary when the subagent slot is `explicit`.

`common_digest` is the sha256 of the canonical JSON array `[[id, sha256], …]` over
included sections with `provider_specific == false`, in bundle order. Equal
`common_digest` across providers means "same instructions except the provider section".
Section budgets record bytes and `tokens_est` (`ceil(len/4)`) per section and per layer;
the compiler does not truncate or reject a bundle for size. An adapter can separately
limit the delivered text and fall back when that limit is exceeded.

## Cache and store

The bundle bytes live once in a content-addressed store:
`<sase home>/instructions/bundles/<sha[:2]>/<sha>.md` (mode 0444, written atomically,
currently not pruned). The render cache (`<sase home>/instructions/cache/<key>.json`)
holds the compiled section table keyed by the sha256 over the compiler version, the sase
version, a per-process code fingerprint, the content-changing facts, the provider
directive file, and the sorted content hashes of every input-file class (project and
home memory, project configs, global config and overlays, resolved templates, the helper
template, the project `AGENTS.md`, and the task-type plugin distributions). A missing or
corrupt entry or blob is a miss. The hit path imports none of the heavy composition
modules, which keeps warm renders within the 250 ms p95 budget; every manifest records
`render_ms` and `cache` (`hit`, `miss`, or `bypass`).

## Delivery

Every root provider invocation routes through one boundary,
`sase.llm_provider._instruction_boundary.invoke_with_instructions`. With an artifacts
dir it resolves a delivery plan, renders the root bundle, optionally renders a helper
bundle, writes v2 manifests, and exposes the active delivery to adapters. With no
artifacts dir (for example the TUI fix-hook path) it invokes directly: no plan and no
active delivery.

### Plan hook and slots

Providers implement `llm_instruction_delivery` (`firstresult`) and return
`{"root": SLOT, "subagent": SLOT}`. Each SLOT is
`{"status", "channel"?, "max_bytes"?, "reason"?}`. `status` is one of `explicit`,
`inherits_native`, `inherits_root`, or `none`. The root slot may only be `explicit` or
`inherits_native`. A missing hook, a hook error, or an invalid return resolves to
legacy: both slots `inherits_native` with reason `provider_legacy`. Claude, Codex, Grok,
and Muse return explicit root slots when their sunset flags are on, and `flag_disabled`
legacy when off. Antigravity (agy), Qwen, and OpenCode stay `provider_legacy` on native
`AGENTS.md` discovery; see
[The Committed AGENTS.md Stays A Readable Projection](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/readable-agents-md.md).

`sase.llm_provider.instruction_delivery.resolve_delivery_plan(provider)` validates the
hook result and never raises. Objects without `instruction_delivery` also resolve to
legacy, so test fakes keep working.

### Marker

The delivered text is the compiler bundle bytes plus one trailing marker line:

```
<!-- sase-instructions bundle=<sha256[:12]> invocation=<invocation_id> -->
```

The bundle `.md` and its sha256 stay exactly the compiler's bytes. The marker is
trailing so every byte before it stays cacheable. Helper delivered text carries the
helper bundle's sha and the **root** invocation id.

### Helper manifests

When the subagent slot is `explicit`, the boundary also writes `NN-<provider>.helper.md`
and `NN-<provider>.helper.json` with the same `NN` as the root. The helper manifest has
`facts.actor = native_helper`, `delivery.status = explicit`, and `parent_invocation_id`
set to the root invocation id. A failed helper render or validation sends helpers back
to the packaged static helper template. A root bundle is never substituted for an
explicit helper bundle; Codex's declared `inherits_root` slot is a separate capability.

### Fallback and notifications

These switch the root slot to legacy delivery for that invocation:

- render failure (`.error.json` gains `"delivery_fallback": "legacy"`)
- invalid root bundle (`invalid_bundle`)
- delivered text over the slot's `max_bytes` (`oversize`)
- adapter materialization failure (`delivery_failed`)

`render_failed`, `invalid_bundle`, `oversize`, and `delivery_failed` raise one
notification, deduplicated per host, provider, reason, and day (`+1` on repeats).
`provider_legacy` and `flag_disabled` are declared states and never notify. A plan-hook
error selects legacy delivery; a bundle-preparation error also attempts to write an
`.error.json` record. If the final manifest rewrite fails after the provider call, SASE
logs a warning without retrying the call, so session IDs or fallback details may be
missing from the recorded manifest. These protections do not catch failures of the
provider invocation itself, and its legacy path can also fail. `KeyboardInterrupt` and
`SystemExit` propagate.

Codex currently has a fallback limitation: its shadow-home filtering follows the
`codex_explicit_instructions` flag, even when an invocation falls back or has no active
delivery plan. SASE-owned global instruction copies and the `~/AGENTS.md` fallback can
therefore remain absent from that shadow home. See
[Codex instruction delivery](../reference/providers/codex.md#codex-instruction-delivery)
before treating a legacy manifest as proof that all native instructions were restored.

### Manifest v2 fields

Root manifests record `delivery.status` (`explicit`, or `inherits_native` plus
`fallback`), `channel`, `provider_cli_version` (cached probe, `null` on failure),
`session_ids` (registered by the adapter, written back after the call; Codex stores the
thread id, which matches the rollout filename stem suffix), and the `subagent` slot.
`shadow` is no longer written; readers still accept it for E2-era runs. The manifest is
written before the call and atomically rewritten afterwards with session ids and any
adapter-reported fallback. A killed process keeps the pre-call manifest. Bundle and
manifest files are mode `0644`. The `agent_meta.json` `instructions` summary adds
`delivery_status` and `helper_manifest`.

`%dispatch` launch requests do not forward `SASE_INSTRUCTIONS_FILE`. The target renders
with its own code; no instruction bytes cross the wire. See
[Remote Dispatch](../reference/integrations/remote-dispatch.md).

### Adapter contract

Without an active explicit delivery, adapters use their legacy directive and delivery
path. The Codex shadow-home limitation above still applies.

An adapter whose slot is `explicit` must do three things together:

- deliver the slot's delivered text once through its channel
- suppress SASE-owned native instruction files
- drop its legacy directive, because the bundle carries `pkg.provider.<p>`

Adapters read the live delivery through
`sase.llm_provider.instruction_delivery.current_instruction_delivery()`. They call
`record_session` for every session id they start, `report_fallback` when materialization
fails, and `materialize(slot)` for a private 0600 file that is removed after the call.
Plugin authors: see [LLM Plugins](plugin-api.md#llm-plugins-pluggy).

Each invocation writes `<artifacts>/instructions/NN-<provider>.md` (the bundle) and
`NN-<provider>.json` (the normalized v2 manifest, `indent=2`, sorted keys), where `NN`
is a two-digit per-run sequence allocated with `O_EXCL`. `SASE_INSTRUCTIONS_FILE` holds
the bundle path during the call and is restored afterwards. The manifest's `attempt` is
`1 + count(attempts/*)`. With no artifacts dir, `SASE_INSTRUCTIONS_FILE` is never
exported and no delivery files are written.

## Related

- [Instruction bundles](../reference/memory/instruction-bundles.md) — preview and
  user-facing behavior.
- [External provider plugins](../reference/providers/plugins.md) — adapter hooks.

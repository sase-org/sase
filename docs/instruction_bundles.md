# Instruction Bundles

An instruction bundle collects the project, home, and SASE instructions for one agent
invocation. Its manifest records which sections were included and their digests, so you
can inspect the intended context and compare it with what a provider actually loaded.

The current implementation records bundles for diagnostics and prepares explicit
delivery for adapters. Root provider invocations render a bundle into the run's
artifacts and export `SASE_INSTRUCTIONS_FILE` for that provider call, then restore the
previous value. Adapter delivery depends on the provider's active delivery plan. Grok
and Muse use explicit delivery by default; Claude and Codex remain on legacy delivery
pending their adapter phases. A successful render therefore does not prove delivery: use
`sase instructions verify` to check observed loads. Render and transport failures never
fail an invocation; they fall back atomically to legacy delivery. The plan hook,
manifests, and fallback are described under [Delivery](#delivery).

See also
[Verifying instruction delivery](agent_providers.md#verifying-instruction-delivery).

## Inspecting your instructions

Start with these read-only commands from your project checkout:

```bash
sase instructions list                 # Current instruction files and provider shims
sase instructions render -s            # Intended bundle sections from current sources
sase instructions show AGENT           # Archived bundle bytes and digest check
sase instructions readout --since 7d   # Handoff-aware declaration misses and memory reads
sase instructions verify -c            # Observed loads and manifest coverage
sase instructions verify -a AGENT      # Compare a recorded run's intent with its loads
```

Replace `AGENT` with a name from `sase agent list -a` (dismissed agents resolve the same
way as `sase agent show`). `sase instructions show AGENT` prints that run's recorded
bundle and checks the stored bytes against the manifest `sha256` (`bytes match`, or
`MISMATCH` with exit 1). Use `-l` to list every recorded invocation including helper
bundles, `-n NN` to pick a sequence, `-H` for the helper bundle, `-j` for the manifest
JSON, and `-s` for the section table. A missing `instructions/` directory or an unknown
name exits 2.

`render -a AGENT` instead uses that agent's facts to compile a fresh preview from
today's memory; its digest may differ from the historical bundle. `verify` looks at the
newest 20 runs per provider from the last 7 days unless you pass `-n` (maximum 200) or
`--since`, and includes dismissed runs. Delivery problems still exit 0. A bad `--since`
or `--until` value, or an unknown `-a` name, exits 2. Inspect the rows rather than
treating exit code 0 as proof that delivery is correct.

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
| `plugin`  | `plugin.<dist>.<slug>`                                                                       | Reserved; no content in E2                            |
| `home`    | `home.core.<stem>`, `home.ref.<stem>`, `home.web.<stem>`                                     | Home memory at `Path.home()`                          |
| `project` | `proj.core.<stem>`, `proj.ref.<stem>`, `proj.web.<stem>`                                     | The project root's memory                             |
| `launch`  | `launch.<slug>`                                                                              | Reserved; no content in E2                            |

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
there is no truncation and no budget gate in E2.

## Cache and store

The bundle bytes live once in a content-addressed store:
`<sase home>/instructions/bundles/<sha[:2]>/<sha>.md` (mode 0444, written atomically,
never pruned in E2). The render cache (`<sase home>/instructions/cache/<key>.json`)
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
legacy: both slots `inherits_native` with reason `provider_legacy`. Built-in providers
currently declare that legacy plan; adapter phases flip them behind per-provider sunset
flags. `flag_disabled` is the same legacy shape when a flag is off.

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
to the E1 static helper template. The root bundle is never substituted across actors.

### Fallback and notifications

These keep the root slot on legacy delivery, with native discovery left intact, for that
one invocation:

- render failure (`.error.json` gains `"delivery_fallback": "legacy"`)
- invalid root bundle (`invalid_bundle`)
- delivered text over the slot's `max_bytes` (`oversize`)
- adapter materialization failure (`delivery_failed`)

`render_failed`, `invalid_bundle`, `oversize`, and `delivery_failed` raise one
notification, deduplicated per host, provider, reason, and day (`+1` on repeats).
`provider_legacy` and `flag_disabled` are declared states and never notify. Every
exception from plan resolution through manifest rewrite is caught and the call proceeds
through legacy delivery. `KeyboardInterrupt` and `SystemExit` propagate.

### Manifest v2 fields

Root manifests record `delivery.status` (`explicit`, or `inherits_native` plus
`fallback`), `channel`, `provider_cli_version` (cached probe, `null` on failure),
`session_ids` (registered by the adapter, written back after the call), and the
`subagent` slot. `shadow` is no longer written; readers still accept it for E2-era runs.
The manifest is written before the call and atomically rewritten afterwards with session
ids and any adapter-reported fallback. A killed process keeps the pre-call manifest.
Bundle and manifest files are mode `0644`. The `agent_meta.json` `instructions` summary
adds `delivery_status` and `helper_manifest`.

`%dispatch` launch requests do not forward `SASE_INSTRUCTIONS_FILE`. The target renders
with its own code; no instruction bytes cross the wire. See
[Remote Dispatch](remote_dispatch.md).

### Adapter contract

Without an active explicit delivery, an adapter behaves exactly as it does today (E1's
after-state). That is the only legacy path.

An adapter whose slot is `explicit` must do three things together:

- deliver the slot's delivered text once through its channel
- suppress SASE-owned native instruction files
- drop its legacy directive, because the bundle carries `pkg.provider.<p>`

Adapters read the live delivery through
`sase.llm_provider.instruction_delivery.current_instruction_delivery()`. They call
`record_session` for every session id they start, `report_fallback` when materialization
fails, and `materialize(slot)` for a private 0600 file that is removed after the call.
Plugin authors: see [LLM Plugins](plugins.md#llm-plugins-pluggy).

Each invocation writes `<artifacts>/instructions/NN-<provider>.md` (the bundle) and
`NN-<provider>.json` (the normalized v2 manifest, `indent=2`, sorted keys), where `NN`
is a two-digit per-run sequence allocated with `O_EXCL`. `SASE_INSTRUCTIONS_FILE` holds
the bundle path during the call and is restored afterwards. The manifest's `attempt` is
`1 + count(attempts/*)`. With no artifacts dir, `SASE_INSTRUCTIONS_FILE` is never
exported and no delivery files are written.

## Previewing bundles

`sase instructions render` previews the bundle for the current project and home sources
without delivering anything:

```bash
sase instructions render | head -40                      # what a root agent here would get
sase instructions render -f provider=codex -s            # sections instead of Markdown
sase instructions render -j                               # preview manifest as JSON
sase instructions render -p                               # parity against AGENTS.md files
```

Options (alphabetical): `-a/--agent NAME` starts from one agent's facts — the provider
from its run record, or its latest recorded manifest when one exists — while sources
stay the current project and home; stderr then reports whether the fresh bundle sha256
matches the agent's recorded bundle and lists changed section ids. `-f/--fact KEY=VALUE`
is repeatable and accepts comma-separated pairs; `mode=interactive|export` implies
`actor=interactive`, and a conflicting explicit actor is an error. `-j/--json` prints
the normalized manifest with `delivery.status: preview`. `-N/--no-cache` bypasses the
cache (`cache: bypass`). `-s/--sections` prints a Rich table of id, layer, status or
reason, lifecycle, bytes, `tokens_est`, and source. `-p/--parity` additionally checks
the bundle against the legacy root and home `AGENTS.md` files: every legacy core,
reference, and web path must map to an included or shadowed bundle section (the legacy
`sase.md` maps to the `pkg.sase.*` sections), every legacy repository name must appear
in `pkg.sase.repos`, and exactly one included section must contain the
`SASE Final Declaration` marker. The parity table goes to stderr and the exit code is 1
on any gap; extra bundle sections (for example `pkg.provider.*`) are reported as
additions, not failures. The default output is raw bundle Markdown on stdout plus one
summary line on stderr (sha256 and `common_digest` prefixes, section count, bytes,
`tokens_est`, cache, and milliseconds).

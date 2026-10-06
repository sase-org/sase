# Instruction Bundles

Every root provider invocation renders the memory-built instruction bundle the agent
_would_ receive, and records it with a `sase-core`-validated instruction manifest —
without delivering it. This page covers the concepts (bundle, manifest, layers, section
ids, overlays, facts, `common_digest`), the cache and store, and the Rust/Python split.
E2 is shadow only: nothing reads manifests to make a decision, and the shadow render
never fails an invocation.

See also
[Verifying instruction delivery](agent_providers.md#verifying-instruction-delivery).

## Bundle and manifest

A **bundle** is one Markdown document composed from memory: package, home, and project
layers under compiler-generated frame headings. A **manifest** is the JSON sidecar
describing that bundle: schema version, compiler identity, host-set facts, bundle
digests and size, per-layer budgets, the ordered section table (included sections with
byte offsets, excluded sections with reasons), delivery identity, and observation
status.

The manifest wire contract — closed vocabulary, validation invariants, and the
`common_digest` definition — is owned by `sase-core` (`instruction_manifest` module,
schema version 1). Markdown composition stays in Python (`sase.instructions`), which
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
for `native_helper` is preview-only in E2; the hook renders roots only.

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

## Shadow manifests

Every root provider invocation routes through one boundary,
`sase.llm_provider._instruction_boundary.invoke_with_instructions`, which shadow-renders
the bundle the agent _would_ get and records it without delivering anything. With the
`instruction_shadow_render` sunset flag on and an artifacts dir, each invocation writes
`<artifacts>/instructions/NN-<provider>.md` (the bundle) and `NN-<provider>.json` (the
normalized manifest, `indent=2`, sorted keys), where `NN` is a two-digit per-run
sequence allocated with `O_EXCL`. The `agent_meta.json` `instructions` summary counts
the manifests and points at the latest (`seq`, `provider`, `purpose`, `sha256`,
`common_digest`, `manifest`), and `SASE_INSTRUCTIONS_FILE` holds the bundle path during
the call and is restored afterwards. The manifest's `attempt` is
`1 + count(attempts/*)`.

Failure posture: the shadow render never fails an invocation. Any shadow exception is
caught, logged once as a warning, recorded best-effort as `NN-<provider>.error.json`
(exception type, message, `rendered_at`), and the call proceeds. Kill switch:
`SASE_INSTRUCTIONS_FILE` is never exported and no shadow file is written with
`sase flag disable instruction_shadow_render` (or no artifacts dir); remove the flag
when E3 delivers the rendered bundle or the readout shows zero shadow failures and warm
p95 within budget for 7 days.

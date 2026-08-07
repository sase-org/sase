# Agent Attachments and Image Previews

## Overview

SASE treats files produced by agents as first-class completion artifacts. When a successful agent
adds or modifies a supported image or video file, the completion path records the media in
`done.json` and appends it to the notification file list after the standard chat and diff artifacts,
and after any generated Markdown PDFs. When a successful agent adds or modifies up to 10 Markdown
files, core SASE renders PDF artifacts and attaches those PDFs to the same completion notification.
Explicit artifacts saved with `sase artifact create` are appended after generated media when the
agent completion notification is sent. Notification plugins can then deliver those files from
`Notification.files` without re-scanning the workspace.

ACE is SASE's terminal UI. It has two image surfaces: lightweight in-panel previews for notification
and file-panel attachments, and the separate `a` artifact viewer for opening completed agent
artifacts.

ACE can also surface media files referenced in saved prompt artifacts (`raw_xprompt.md` and
`*_prompt.md`) even when the media itself was not part of the agent's git diff. For current
successful runs, those prompt-referenced media files are persisted alongside the other default
generated-media artifacts — as byte copies or as byte-free version-control references, per
[VCS-Backed Artifact Files](#vcs-backed-artifact-files) — so the Agents-tab artifact picker can
still open them after a workspace is cleaned up. Legacy runs without persisted default artifacts
fall back to prompt-file discovery at view time. Prompt-referenced media are not notification
delivery attachments unless they also appear in `done.json.image_paths`, appear in
`done.json.video_paths`, or were saved explicitly with `sase artifact create`.

Supported image extensions are:

- `.png`
- `.jpg`
- `.jpeg`
- `.webp`
- `.gif`

Supported video extensions are:

- `.mp4`
- `.m4v`
- `.mov`
- `.webm`

## Generated Media Attachment Contract

Generated-image discovery runs when an agent finalizes successfully. This contract covers images
added to `done.json.image_paths` and completion notifications. Generated-video discovery uses the
same algorithm and writes videos to `done.json.video_paths`. The collector checks candidate paths in
stable order:

1. tracked files changed relative to `HEAD`
2. untracked files in the agent workspace
3. files named by the saved proposal or commit diff
4. files touched by the latest commit when the agent committed or opened a PR

Only existing files with supported media extensions are kept. Paths are resolved to absolute paths
so outbound notification processes can attach them even when they run outside the agent workspace.
Duplicates are removed while preserving order. Generated images are appended after any
already-attached chat, diff, or generated PDF files; generated videos are appended after generated
images.

The same lists are persisted as `image_paths` and `video_paths` in the agent's `done.json`. Agent
metadata consumers should read those fields instead of trying to infer generated media from
arbitrary notification files. GIFs remain in `image_paths` for compatibility with image-preview
consumers; downstream notification plugins can still choose an animation-specific transport based on
the `.gif` suffix.

Source: `src/sase/axe/image_attachments.py`

### Prompt-Referenced Media Default Artifacts

Default artifact persistence also scans the saved prompt files in the agent artifacts directory:

- `raw_xprompt.md`
- every sibling `*_prompt.md` file

Any path-like token ending in a common image suffix or supported video suffix is resolved as an
absolute, home-relative, or workspace-relative path. Existing files are added after
`done.json.image_paths` and `done.json.video_paths`, duplicates are removed, and the file does not
need to appear in the agent's git diff. These candidates carry origin `mentioned` into the capture
policy, so a mentioned repo file the run neither authored nor can reproduce from version control
gets no row at all. Images and GIFs are added as `image` artifacts. Prompt-referenced videos are
added as ordinary `file` artifacts; ACE detects the video suffix at view time and opens them with
the video preview path.

This is useful when a prompt asks an agent to inspect or transform an existing screenshot, mockup,
reference image, or reference video and the resulting run should keep that source media one keypress
away in ACE.

Prompt-referenced media are ACE artifact-list entries, not notification delivery attachments.
Current runs persist them to the global artifact index during finalization; legacy runs can still
synthesize them from prompt artifacts when ACE loads the row. Downstream notification plugins should
continue to use `done.json.image_paths` and `done.json.video_paths` for the generated-media
notification contract.

Source: `src/sase/core/artifact_file_defaults.py`

## Prompt Artifact Staging and Archive

Launch-time prompt preprocessing also stages every resolvable prompt reference so a later commit can
publish a durable prompt document. This staging is workspace-local and lives under:

```text
<workspace>/.sase/artifacts/
```

The directory has three responsibilities:

- `home/` holds readable working copies for home-directory `@path` references. This replaces the old
  `.sase/home/` location.
- `pool/<sha12>-<basename>` holds immutable content-addressed copies of external file bytes. The
  `sha12` prefix is the first twelve hexadecimal characters of the file's SHA-256 digest, and the
  basename is sanitized for a single path component.
- `prompt-artifacts.jsonl` records one manifest row per staged reference; `prompt-artifacts.lock`
  serializes concurrent writers.

Clean tracked files inside a known repository are recorded as VCS-backed rows instead of copied into
`pool/`. External files are hashed and pooled unless they exceed
`artifacts.capture.max_file_size_bytes`; oversized files are still hashed and recorded with a skip
reason, but their bytes are not copied. Locator-only references such as `@agent:`, `@bug:`, and
`@commit:` get manifest rows without file bytes.

When `sase commit` publishes the canonical prompt archive, it reads the manifest rows for that run,
copies pooled files to the agents sidecar under `artifacts/<YYYYMM>/`, and writes the prompt to
`prompts/<YYYYMM>/<name>.md`. The body is the prompt text selected for publication. The prompt's
`ARTIFACTS` header section lists exactly the `@...` references made clickable in the body.
VCS-backed rows link to hosted source blobs at the recorded revision, while copied external files
link to `../../artifacts/<YYYYMM>/<sha12>-<basename>`.

The local pool is a cache for publication, not the permanent archive.
`artifacts.capture.pool_max_bytes` controls when SASE opportunistically garbage-collects pool files
whose manifest rows all belong to terminal runs that have already published their prompt archive.
Manifest rows are retained so validation can still explain what happened.

If an older workspace still has `.sase/home/`, leave it in place until no live agent can be using
it. `sase doctor` reports it as `workspace.legacy_artifact_home` and tells you the exact directory
to remove after that check.

Sources:

- `src/sase/core/prompt_artifact_staging.py`
- `src/sase/agents_sync/prompt_archive/publish.py`
- `src/sase/agents_sync/prompt_archive/validation.py`
- `src/sase/doctor/checks_workspace.py`

## VCS-Backed Artifact Files

Automatic capture at agent finalization means _authorship_, and it never copies what version control
already stores. Every candidate discovered by generated-media and prompt-referenced-media discovery
is classified by `src/sase/core/artifact_capture_policy.py` before anything is written.

### The decision matrix

`origin` distinguishes candidates the run **changed** (`done.json.image_paths` / `video_paths`,
which come from `git diff HEAD`, untracked files, and the run's own commit) from candidates merely
**mentioned** in a saved prompt file. The first matching rule wins:

| #   | Condition                                                                                                             | Outcome                                                             | Reason slug                              |
| :-- | :-------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------ | :--------------------------------------- |
| 1   | The exact content is reproducible from a durable commit                                                               | `reference` — byte-free row with `vcs_repo`/`vcs_sha`/`vcs_relpath` | `vcs_reproducible`                       |
| 2   | Authored by this run: inside the agent's artifacts directory, `origin == changed`, or mtime at or after the run start | `store` — copy bytes                                                | `artifacts_dir`, `changed`, `run_window` |
| 3   | Mentioned only, and outside every known repo working tree                                                             | `store` — the user-supplied input case                              | `mentioned_external`                     |
| 4   | Otherwise (mentioned only, inside a known repo, not reproducible)                                                     | `skip` — no row is written                                          | `mentioned_repo`                         |

Three invariants make this safe:

- **No silent substitution.** A `reference` row is written only after the candidate's bytes have
  been reproduced from `<vcs_sha>:<vcs_relpath>` and the reproduction's SHA-256 verified equal to
  the candidate's. A tracked file with uncommitted edits therefore fails rule 1 and is stored
  instead.
- **Durability.** `vcs_sha` is reachable from a remote-tracking ref at capture time. An unpushed
  local commit does not qualify, because the numbered workspace holding it is reset on next open.
- **Fail-safe.** Any git failure, timeout, unknown repo, or ambiguity downgrades a would-be
  `reference` to `store` (reason `vcs_probe_failed`). Capture can never lose bytes.

Explicit artifacts created with `sase artifact create` never enter this matrix and always store
their own bytes.

Finalization prints one summary line beside the other `[artifacts]` output:

```text
[artifacts] default capture: stored=3 referenced=12 skipped=1 declared=2 cap_fired=false
```

`cap_fired` reports whether `artifacts.capture.max_stored_per_agent` was reached; once it is,
remaining `store` candidates become `skip` with reason `capture_cap`. Reference rows cost no bytes,
are not counted, and are never capped. `declared` counts auto-discovered candidates omitted because
the agent already registered their source with `sase artifact create`. See
[`configuration.md`](configuration.md#artifacts) for the `artifacts.capture` block.

### The record fields

A VCS-backed row carries `path: null` plus three provenance fields:

| Field         | Meaning                                                       |
| ------------- | ------------------------------------------------------------- |
| `vcs_repo`    | Repo inventory name (`record.name`) the content belongs to.   |
| `vcs_sha`     | A durable commit that held the exact content at capture time. |
| `vcs_relpath` | Path of the file relative to that repo's toplevel.            |

`sha256`, `size_bytes`, and `mime_type` are recorded exactly as they are for byte-backed rows, so a
byte-free row loses no integrity metadata. Index rows are written at schema version 2; the reader
accepts versions 1 and 2.

### Materialization and the `vcs-cache` directory

Reference resolution stays pure — it never shells out to git — so read-only callers (`sase lsp`,
`@`-completion, TUI hover) stay cheap. A VCS-backed row resolves with status `vcs_backed` and
locator `<vcs_repo>@<vcs_sha>:<vcs_relpath>` and no `resolved_path`. Callers that need bytes
materialize explicitly through `src/sase/core/artifact_file_vcs.py`'s `materialize_artifact_file()`,
which is the single Python entry point:

- `sase artifact path` prints the materialized cache path, and `sase artifact open` continues into
  the usual viewer.
- `@file:` references in a prompt expand to a materialized path; a failure fails the launch loudly
  rather than handing an agent a dangling path.
- The ACE Files pane renders a `PROVENANCE` section instead of a stored path and materializes off
  the UI thread.
- `sase artifact show` and `sase artifact list` need no materialization; `show` reports
  `stored_path_status: vcs-backed (<locator>)`.

Materialized content lands in a content-keyed cache:

```text
~/.sase/artifacts/vcs-cache/<sha256[:2]>/<sha256><suffix>
```

Lookup order is cache hit (re-hashed before it is trusted), then
`git cat-file blob <vcs_sha>:<vcs_relpath>` in each known checkout of the repo in turn, then a
bounded walk of at most `artifacts.capture.max_history_scan` durable commits touching the path —
which recovers content whose recorded sha was squash-rewritten or pruned. The cache is transient:
deleting it costs only re-materialization.

### Diagnosing an unresolvable reference

If `sase artifact path` on a VCS-backed row exits 1, the content could not be reproduced from any
known checkout. Work through it in this order:

1. `sase artifact show <ref>` — read the locator to get the repo, commit, and relpath.
2. `sase repo list` — confirm the `vcs_repo` name still exists in the inventory and has at least one
   existing clone. An unknown repo name leaves the resolver with no checkout to try.
3. In a checkout of that repo, `git fetch` and retry. Resolution measures reachability from
   remote-tracking refs, so a stale clone is the common cause.
4. `git cat-file blob <vcs_sha>:<vcs_relpath>` — if the object is gone (a rewritten or pruned
   commit), the bounded history walk is the fallback; raise `artifacts.capture.max_history_scan` if
   the content is deeper in history than the current bound.
5. `sase artifact doctor -v` — audits every VCS-backed row and lists the unresolvable ones under
   `Unresolvable VCS references`, so a systemic problem shows up as a bucket rather than one failing
   command.

A failure always names the repo, commit, path, and digest. SASE never substitutes different bytes
and never returns an empty file.

Sources:

- `src/sase/core/artifact_capture_policy.py`
- `src/sase/core/artifact_file_vcs.py`
- `src/sase/core/artifact_file_defaults.py`

## Consumption Ledger

When a launch prompt expands `@` artifact references in rewrite mode, SASE records the references
that the agent was actually handed. The ledger is append-only JSONL at:

```text
~/.sase/artifacts/consumption.jsonl
```

Writes use a sibling lock file:

```text
~/.sase/artifacts/consumption.lock
```

Each line is a schema-versioned envelope:

```json
{
  "schema_version": 1,
  "consumption": {
    "id": "3f0a91c2d4e5",
    "timestamp": "2026-07-30T14:02:11.481293+00:00",
    "ref": "file:default:52895d68931185056fd0e49f",
    "ref_kind": "file",
    "fragment": null,
    "role": "image",
    "artifact_id": "default:52895d68931185056fd0e49f",
    "resolved_path": "/home/user/.sase/artifacts/agents/sase/20260730134501/image.png",
    "resolution_status": "exact",
    "agent_name": "sase-b8.2",
    "agent_source": "SASE_AGENT_NAME",
    "artifacts_dir": "/home/user/.sase/projects/gh_sase-org__sase/artifacts/ace-run/202607/30/20260730134501",
    "project": "gh_sase-org__sase"
  }
}
```

`ref` is the fragment-free canonical reference and is the join key used by `sase artifact show` and
`sase artifact list --unused`. A prompt reference such as `@file:default:<digest>#L1-L5` records
`ref: file:default:<digest>` and stores the discarded anchor as `fragment: L1-L5`, so all fragments
of the same artifact aggregate together. `artifact_id` is populated only for `file:` references;
non-file references such as `chat:`, `bead:`, `bug:`, `plans:`, and `research:` leave it null but
are still recorded and summarized by `show`.

The v1 role vocabulary is deliberately small:

| Role          | Derivation                                                                                                                         |
| ------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `report`      | `chat:` and document-role references; `file:` references whose resolved path is Markdown, plain text, or PDF                       |
| `image`       | Visual media by suffix, including images and videos such as PNG, JPEG, GIF, SVG, WebP, MP4, MOV, and WebM                          |
| `source`      | Code, data, `bead:`, `agent:`, `commit:`, `bug:`, unknown suffixes, and other references that are neither reports nor visual media |
| `test-result` | Reserved for future writers; no v1 code emits it                                                                                   |

Grouping videos under `image` is intentional: in this ledger the role means visual media, and
keeping the v1 vocabulary to four values leaves later lineage work additive.

SASE logs every reference that successfully expands in rewrite mode. It does not log validation-only
checks, failed expansion passes, `sase artifact open`, `sase artifact path`, ACE browsing, or LSP
completion. Within one expansion pass duplicate references collapse to one event by canonical `ref`;
later launches, retries, and workflow steps append new events because they are separate
consumptions.

`sase artifact show <reference>` reads the ledger for any resolvable reference and adds
`consumption_count`, `consumed_by_agents`, `consuming_agents`, and `last_consumed_at` to the pretty
report. JSON output adds an additive `consumption` object with the full summary, or `null` when the
reference has never been consumed. `sase artifact list --unused` filters artifact files to rows with
no recorded `file:<id>` consumption; the filter is applied before `--limit`, so `-u -l 50` asks for
50 unused artifacts, not for unused rows among the newest 50.

Every canonical, fragment-free `file:` key in the ledger is a hard lifecycle protection. The shared
protection collector unions those consumed IDs with IDs found in persistent ProjectSpec, plan, bead,
and research references before `sase artifact stats` projects the default policy,
`sase artifact prune` removes rows, `sase artifact reclaim` converts stored rows to VCS-backed
identities, or opt-in automatic retention runs after agent finalization. Overlap is deduplicated,
while stats reports referenced, consumed, overlap, and total counts separately. A missing ledger is
an empty optional source; if a present ledger cannot be queried, reporting surfaces show it as
unavailable and every destructive apply or automatic enforcement pass refuses to change artifacts.

Sources:

- `src/sase/core/artifact_consumption.py`
- `src/sase/core/artifact_consumption_query.py`
- `src/sase/artifact_ref_prompt.py`
- `src/sase/artifact_cli/show.py`
- `src/sase/artifact_cli/listing.py`
- `src/sase/core/artifact_file_protection.py`
- `src/sase/artifact_cli/stats.py`
- `src/sase/artifact_cli/prune.py`
- `src/sase/artifact_cli/reclaim.py`
- `src/sase/axe/run_agent_exec_finalize.py`

## Store Lifecycle

The artifact-file store is measured, drained, and bounded through one deliberately staged
progression: **report → dry run → opt-in retention**. Nothing in it removes anything by surprise,
and nothing it removes is gone immediately.

| Stage              | Command                                    | Writes                                                       |
| ------------------ | ------------------------------------------ | ------------------------------------------------------------ |
| Report             | `sase artifact stats`                      | Never                                                        |
| Reclaim (lossless) | `sase artifact reclaim`                    | Only with `-a/--apply`                                       |
| Prune (lossy)      | `sase artifact prune`                      | Only with `-a/--apply`                                       |
| Undo / finalize    | `sase artifact trash {list,restore,purge}` | `restore` and `purge` write; `purge` is the only hard delete |
| Ongoing            | `artifacts.retention`                      | Only when explicitly enabled                                 |

### The protection contract

These rules hold on every surface above — manual and automatic, dry run and apply:

- **Declaration is permanent.** A row created by `sase artifact create` (`explicit=true`) is never
  removed, converted, or rewritten by any lifecycle command.
- **Referenced artifacts are protected.** An artifact ID appearing in a ProjectSpec, plan, bead,
  bead page, or research document is excluded, in both its bare `default:`/`explicit:` and
  `file:`-prefixed forms.
- **Consumed artifacts are protected.** Any canonical, fragment-free `file:` ID in
  [the consumption ledger](#consumption-ledger) is excluded.
- **The newest generation always survives.** Whatever the predicates say, the newest capture of
  every `(project, label)` pair is never selected. A label's history can shrink to one; it cannot
  vanish.
- **Unreadable protection sources block removal, never permit it.** If a required source cannot be
  read, `--apply` refuses with the source named and the automatic pass skips entirely. The dry run
  still renders and reports the gap.
- **Nothing hard-deletes except `trash purge`.** Every other removal is restorable.

### Report first: `sase artifact stats`

`stats` is read-only. It panels totals split explicit / automatic / VCS-backed, the observed window
and growth rate, per-kind and per-project and top-agent groups (with the truncated remainder shown
rather than hidden), duplicate-digest redundancy, per-label generation projections, an upper bound
on reclaimable rows, protection counts (referenced, consumed, overlap, total, plus any unavailable
source as a warning), trash occupancy, and — last — exactly what the configured default policy would
select. `-j/--json` emits the same content as one envelope.

Read the reclaimable figure as an _upper bound_, not a result: it counts automatic byte-backed rows
whose `source_path` lives inside their `workspace_dir`. Reproducibility is only ever established by
the digest verification `reclaim` does.

### Reclaim before pruning

`sase artifact reclaim` is lossless, so run it first: it keeps every row, label, and provenance
field and deletes only a copy of content version control already stores. For each eligible automatic
row it resolves the owning repo and relative path from `workspace_dir` + `source_path` (mapping a
`sase/repos/...` prefix to the matching sidecar, linked, or external repo), walks that path's
durable remote-tracking history within `-d/--max-history-scan` commits (default 100), and converts
the row only when a blob's SHA-256 equals the row's recorded digest. Because the dry run compares
digests rather than materializing content, it touches nothing at all — not even `vcs-cache/`.

**Reclaim changes a row's ID.** A reference row's ID derives from its VCS identity rather than its
stored path, so the converted row gets a new ID; the old row is removed and the new one written.
Both IDs appear in the plan's OLD REF / NEW REF columns and in each
`Reclaimed file:<old> -> file:<new>` apply line, so anyone holding the old ID can follow it.
Preserving the old ID is not an option — it would collide with the ID a re-capture of the same
content computes, and idempotent capture depends on that. This is also why reclaim honors the
reference and consumption protections: changing an ID that something already names would break the
reference.

Rows reclaim cannot verify are never touched. They are reported in the **Rows Left Untouched**
panel, grouped by a stable reason:

| Reason                                                     | What to do                                                                                                                                           |
| ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `explicit`, `referenced`                                   | Working as intended; the row is protected.                                                                                                           |
| `already_vcs_backed`                                       | Nothing to do; the row is already byte-free.                                                                                                         |
| `missing_sha256`, `missing_size`                           | Run `sase artifact doctor -f` to backfill enrichment fields, then retry.                                                                             |
| `missing_workspace_dir`, `missing_source_path`             | The row predates provenance capture; only pruning can address it.                                                                                    |
| `source_outside_workspace`                                 | The file was never inside a repo checkout, so no relpath is derivable.                                                                               |
| `unknown_project`, `unknown_repo`, `inventory_unavailable` | Check `sase repo list`; the repo the row names is not in the inventory.                                                                              |
| `missing_checkout`                                         | No live clone of that repo exists right now. Open one and retry.                                                                                     |
| `vcs_probe_failed`                                         | A git call failed or timed out; the row is left alone by design.                                                                                     |
| `digest_not_found`                                         | The exact content is not in durable history within the scan bound. Raise `-d`, or accept that the bytes are genuinely unique and let pruning decide. |

### Prune what remains

`sase artifact prune` is the lossy step, and the only one that removes information. It plans from
the same protection set with `-g/--keep-generations` (defaulting to
`artifacts.retention.keep_per_label`), `-b/--before`, `-k/--kind`, `-m/--min-size`, `-p/--project`,
and `-l/--limit`, renders the identical table in both modes, and changes nothing without
`-a/--apply`. Selecting a byte-free row is legitimate and reclaims no bytes — it removes index noise
— so the plan counts byte-backed and byte-free selections separately and only ever sums byte-backed
rows into reclaimable bytes.

### The trash

Every removal — from `prune`, from `reclaim`, and from automatic retention — moves the stored bytes
_and_ the complete index row into `~/.sase/artifacts/trash/`. One entry is one directory containing
`entry.json` (schema version, entry ID, artifact ID, `trashed_at`, `reason`, `size_bytes`, stored
filename, and the verbatim original index row) plus the moved payload file when the row had bytes.
Bytes are moved before the index row is dropped, so an interrupted batch leaves a restorable entry
rather than an orphaned row.

```bash
sase artifact trash                       # newest-first listing, grace-period flag per entry
sase artifact trash restore <entry-or-ref>  # payload back in place, index row re-inserted
sase artifact trash purge                 # permanent, and only past the grace period
sase artifact trash purge -a              # permanent, ignoring the grace period
```

`artifacts.retention.trash_grace_days` (default 14) is the cutoff `purge` honors and the one
`trash list` marks entries against. Until a purge runs, trashed bytes still occupy disk: a full
reclaim pass moves its recovered bytes into the trash, so `du` does not drop at apply time.
`reclaim --apply` says this outright in its summary.

### Ongoing enforcement

`artifacts.retention` is disabled by default and removes nothing until enabled. Once enabled, one
bounded pass runs after automatic capture at each agent finalization: it plans with the configured
policy plus the protection scan, trashes what it selects, and purges trash entries past the grace
period, printing one `[artifacts] retention:` line with rows trashed, bytes reclaimed, and entries
purged. The pass is wrapped defensively and never fails a run; when a protection source is
unavailable it prints `[artifacts] retention skipped:` and touches nothing. See
[configuration](configuration.md#artifacts) for the fields.

Sources:

- `src/sase/artifact_cli/stats.py`
- `src/sase/artifact_cli/prune.py`
- `src/sase/artifact_cli/reclaim.py`
- `src/sase/artifact_cli/trash.py`
- `src/sase/core/artifact_file_retention.py`
- `src/sase/core/artifact_file_reclaim.py`
- `src/sase/core/artifact_file_trash.py`
- `src/sase/core/artifact_file_protection.py`
- `src/sase/axe/run_agent_exec_finalize.py`

## Markdown PDF Attachment Contract

Markdown discovery runs on successful agent finalization with the same candidate ordering as image
discovery. Supported source extensions are `.md` and `.markdown`. Sources are resolved to existing
workspace files, generated run artifacts are excluded, and duplicates are removed before rendering.
If more than 10 Markdown sources remain after filtering, SASE skips PDF rendering for that run and
adds a completion-notification note instead of rendering a large attachment set.

Core SASE renders discovered Markdown sources into the current agent artifacts directory:

```text
<artifacts_dir>/markdown_pdfs/<sanitized-relative-source-path>.pdf
<artifacts_dir>/markdown_pdfs/index.json
```

Rendering is best-effort. Missing Pandoc/PDF-engine tools or conversion errors do not fail the agent
run; failed sources are omitted. Successful PDF paths are persisted as `markdown_pdf_paths` in
`done.json`, and `index.json` records `source_path` to `pdf_path` mappings for diagnostics. When the
10-source limit is exceeded, `done.json.markdown_pdf_paths` is empty and the source count is carried
through completion handling for the user-facing skip note.

While PDFs are being prepared, the runner writes `workflow_state.json.pdf_status` plus a compact
`activity` label. ACE loads the activity during refresh and shows messages such as
`Preparing PDFs from Markdown...`, `PDF 2/4 <path>`, or `PDFs done 3/4 (1 skipped)` only in the
prompt/detail header's labeled `Activity:` field. This status is transient finalization state; the
durable output remains `done.json.markdown_pdf_paths` and `markdown_pdfs/index.json`.

Markdown PDFs use a built-in small-screen layout by default: a narrow portrait page, small margins,
larger readable body text, and wrapping-friendly CSS for code blocks, tables, links, and other long
content. The preferred `wkhtmltopdf` path receives both the default stylesheet and explicit
page/margin options; LaTeX fallbacks receive the same page size, margin, font size, and line-height
defaults through Pandoc variables.

When a discovered Markdown source starts with usable, non-empty YAML frontmatter, the rendered PDF
replaces the raw metadata block with a styled **Properties** card; the original Markdown file is not
changed. Labels and property ordering use the same helpers as ACE's plan-detail presentation, while
the PDF renders nested mappings and sequences as indented lines. HTML-sensitive property text is
escaped. On the preferred `wkhtmltopdf` path, Pandoc's document-title metadata uses the frontmatter
`title` value converted to text, or the source filename stem when `title` is absent. Empty,
malformed, or absent frontmatter leaves the render input unchanged, and a preprocessing failure
falls back to rendering the original Markdown. Dedicated launch-preview PDFs opt out of this
transformation in both the highlighted and generic-fallback passes, preserving prompt frontmatter.

Completion notifications attach generated Markdown PDFs after the saved chat and diff files, before
image attachments. The Agents tab file panel also loads `markdown_pdf_paths` alongside plan and
image files for completed agents.

Sources:

- `src/sase/attachments/markdown_pdf.py`
- `src/sase/axe/run_agent_exec.py`

## Explicit Artifact Contract

Agents can save a generated file explicitly with:

```bash
sase artifact create [-k <kind>] [-l <label>] [-m] -p <path>
```

`sase artifact-file create` remains a compatibility alias for the same command.

`-k/--kind` is one of `chat`, `plan`, `image`, `markdown`, `pdf`, or `file`, and defaults to a kind
inferred from the file extension. `-l/--label` sets the display label and defaults to the source
file name. `-m/--move` removes the source after storing it instead of retaining the default
workspace copy; it is intended for scratch files, and using it on a tracked file leaves a deletion
in the working tree. `-p/--path` is required.

On success the command prints four lines:

```text
id: explicit:<hash>
source: /absolute/path/to/report.md
path: /home/<user>/.sase/artifacts/agents/<project>/<timestamp>/report-<digest>.md
ref: file:explicit:<hash>
```

The `source:` line records where the artifact came from, `path:` names the stored snapshot, and
`ref:` is the copyable name to hand to a user or another agent. By default the source remains in
place. Later source edits do not propagate to the stored snapshot; run `create` again to register a
fresh one.

Every new index row also records `sha256` (the full digest of the stored file), `size_bytes`, and
`mime_type`. All three are optional at index schema version 1, so rows written before they existed
simply carry `null`; `sase artifact doctor` reports those gaps, `sase artifact doctor -f` backfills
them for every row whose stored file is still present, and `sase artifact doctor -v` re-hashes live
stored files to verify the recorded digests. The reader accepts index schema versions 1 and 2 and
the writer preserves rows with any other schema version verbatim, so a mixed-age fleet cannot lose
rows on rewrite.

The CLI command is intended for agent processes: it requires `SASE_AGENT=1` and `SASE_ARTIFACTS_DIR`
so SASE knows which run owns the artifact, and it exits non-zero with an explanatory message when
either is missing or the source path is not a file. It copies the source file into persistent SASE
artifact storage, records an association with the current agent, and lets ACE show the artifact even
after the agent is dismissed and later revived. During completion notification delivery, SASE
appends existing explicit artifact files after chat, diff, generated Markdown PDFs, generated image
attachments, and generated video attachments. Duplicate stored paths and artifacts whose source is
already attached are ignored, missing files are skipped, and explicit-artifact index failures do not
fail the completion path.

Sources:

- `src/sase/artifact_cli/create.py`
- `src/sase/core/artifact_file_explicit.py`

## Notification Delivery

Core SASE stores generated PDFs, generated images, generated videos, and explicit artifact
attachments in the existing `Notification.files` list. There is no separate notification schema
field for typed attachments yet. This keeps the contract compatible with existing notification
storage and lets downstream plugins decide how to render each file:

- Telegram integrations can send static images as photos, GIFs as animations, videos as videos, and
  keep markdown/diff files as documents.
- Google Chat integrations can upload image files directly into the completion thread.
- The ACE notification modal can still open attached files in `$EDITOR` with `e` and cycle them with
  `Ctrl+N` / `Ctrl+P`.

See [`notifications.md`](notifications.md) for the notification model and modal keybindings.

## ACE Artifact Viewer

The Agents tab exposes completed agent artifacts through the `a` key. When artifacts exist, ACE
opens the artifact panel for selection. Chat transcripts, plan files, generated Markdown PDFs,
generated images, generated videos, prompt-referenced media, and explicit artifacts created with
`sase artifact create [-k <kind>] [-l <label>] [-m] -p <path>` all use the same list. Generated
videos are stored as ordinary `file` artifacts, but the picker labels supported video suffixes as
`[video]` and the viewer opens them with terminal video playback. The panel is shown even for a
single artifact so users can confirm the artifact label, kind, and path before opening it.

The selected agent's prompt/detail header also includes non-chat artifacts in the plan-adjacent
`SASE CONTEXT` `ARTIFACTS` lane. The complete lane order is `PLAN`, `ARTIFACTS`, `MEMORY`, `SKILLS`,
then `WORKSPACES`; within `ARTIFACTS`, `Commits`, `Deltas`, and `Artifacts` remain in that order
when present. Paths are shown relative to the agent workspace when possible, home-relative when
appropriate, and with hint numbers when hint mode is active.

The panel supports one-key selectors, `j`/`k` navigation, `m` to mark rows, `Enter` to open the
marked set or highlighted row, `y` to copy highlighted Markdown contents, `Y` to copy the
highlighted artifact path, and `A` to open every artifact in list order. Copied paths are
workspace-relative when possible and fall back to home-relative paths. When multiple artifacts are
opened together, the terminal viewer adds `n`/`p` navigation between artifacts in addition to page
navigation.

When ACE is running inside tmux, the artifact viewer launches in a right-side tmux pane and the
Agents list collapses while the pane is live. Press `l` from the Agents tab to focus the tracked
artifact pane, or press `a` again to close it. Row-changing navigation is guarded while the pane is
open so the TUI does not drift to a different agent than the viewer. Outside tmux, ACE suspends and
opens the viewer in the current terminal pane. The viewer chooses its mode from the artifact kind
and file extension: supported images are displayed directly, supported videos play with mpv, PDFs
are converted to PNG pages, and Markdown is rendered to PDF before paging. The page loop uses
`j`/`k` to move between pages, wrapping at the first and last page, `n`/`p` to move between
artifacts in a sequence, `r` to refresh or replay the current artifact, and `q` to close the viewer.

Only one plan artifact is listed for each agent. If run metadata contains both an archived plan path
and an SDD tale path, committed plans prefer the SDD path; uncommitted plans prefer the archived
path unless only the SDD path is available.

Viewer dependencies are intentionally outside the agent completion path. `kitten` is required for
image/PDF/Markdown terminal display, `mpv` is required for terminal video playback, `pdftoppm` is
required for PDF/Markdown paging, and Markdown rendering also needs `pandoc` plus one supported PDF
engine. If a dependency is missing, ACE shows a warning instead of failing the TUI or changing the
stored artifact list.

Source: `src/sase/ace/tui/graphics/viewer.py`

### Video Preview

ACE plays `.mp4`, `.m4v`, `.mov`, and `.webm` artifacts in the same artifact viewer used for images
and PDFs. Inside tmux, selecting a video opens the tracked right-side artifact pane; outside tmux,
ACE suspends and plays in the current terminal. Playback uses `mpv --vo=kitty` by default, bounded
to the same cell area used for image artifacts.

While mpv is running, mpv owns playback keys: `space` pauses or resumes, arrow keys seek, `m`
toggles mute, and `q` stops playback. After playback exits, the artifact viewer footer returns with
the usual navigation keys: `r` replays, `n`/`p` move through a multi-artifact sequence, `z` toggles
tmux zoom when available, `<tab>` focuses the SASE TUI from a tmux artifact pane, and `q` closes the
viewer.

Videos are muted by default because SASE often runs on a remote host or inside tmux where the server
audio device is not useful. Configure playback under `ace.artifact_viewer.video`:

```yaml
ace:
  artifact_viewer:
    video:
      audio: false
      loop: false
      vo: "kitty"
      extra_mpv_args: []
```

Set `audio: true` to start unmuted, `loop: true` to pass `--loop-file=inf`, `vo` to use another mpv
video output such as `tct`, and `extra_mpv_args` to append additional mpv flags after SASE defaults.
SASE launches mpv with `--no-config` so user mpv profiles cannot break the curated terminal preview;
put viewer-specific customization in the SASE config instead.

## ACE Image Preview Foundation

The notification modal and Agents tab file panel route supported image extensions through the
preview layer before attempting text decoding.

The internal preview layer renders PNG, JPEG, WebP, and GIF attachments as a portable Rich cell
preview. It uses Pillow to decode the first image frame, apply EXIF orientation, fit it inside the
visible panel bounds, composite transparency onto a dark background, and apply a mild preview-only
sharpen pass after resizing. Each terminal cell samples a 2 x 2 pixel block and chooses the closest
Unicode block mask with foreground and background colors, which preserves more edges, diagonals, UI
details, and text-like shapes than a fixed half-block sampler.

No Kitty, iTerm2, Sixel, or other terminal image protocol support is required. The renderer only
emits colored Unicode text through Rich/Textual, so it works the same way in ordinary terminals,
multiplexed sessions, SSH sessions, and environments with no image protocol support. Preview quality
depends on the visible pane size and terminal color depth: larger panes provide more sampled cells,
and truecolor terminals preserve colors better than 256-color terminals.

ACE checks only terminal color depth from the environment. When `COLORTERM=truecolor`,
`COLORTERM=24bit`, or a truecolor marker in `TERM` is present, previews use 24-bit color; otherwise
they use 256-color approximations. Missing files, unsupported extensions, decode errors, missing
Pillow, and images above the renderer guardrails show a concise text fallback with the file path,
byte size when available, and the relevant editor or artifact action. Use `e` in notifications, `E`
on the Agents tab, or the `a` artifact viewer whenever full-fidelity viewing is needed.

Source: `src/sase/ace/tui/graphics/`

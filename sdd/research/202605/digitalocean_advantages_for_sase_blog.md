# DigitalOcean Advantages for the `sase.sh` Blog

Date: 2026-05-07 (revised 2026-05-07 to add cost worksheet, region/data-residency control, edge-compute side-by-side,
stateful pricing baseline, Spaces concrete pricing, and strategic vendor-risk asymmetry)

## Question

If Cloudflare Pages is the current preferred host for the static `sase.sh` blog, what practical advantages would
DigitalOcean still provide?

## Short Answer

Cloudflare Pages remains the better default for a pure static MkDocs blog: it has global static delivery, Git previews,
simple custom domains, and much better economics for ordinary static traffic.

DigitalOcean becomes attractive if the blog is expected to grow into more than a static publication. Its advantages are
control, stateful infrastructure, conventional server runtime, first-party observability, and a smoother path from
static site to product surface. The strongest DigitalOcean option is not "static site only"; it is either:

1. Keep `sase.sh` on a Droplet or App Platform so the blog can sit beside dynamic services, or
2. Use Cloudflare Pages for the static blog and DigitalOcean for stateful backends, media, databases, or internal tools.

## DigitalOcean Shapes to Consider

| Shape | What it means | Best when |
| --- | --- | --- |
| App Platform static site | Git-connected static site hosted through DigitalOcean's CDN. | You want a Pages-like managed deploy but prefer DO's control plane. |
| App Platform app | Static site plus web services, workers, jobs, functions, databases, domains, logs, and metrics. | The blog may add server-side features soon. |
| Droplet origin | Caddy/Nginx on the existing Droplet, likely still proxied by Cloudflare DNS/CDN. | You want full Linux control, existing server reuse, and simple predictable VM pricing. |
| Hybrid | Cloudflare Pages for `sase.sh`; DigitalOcean for backends/media/state. | Best default if the blog stays static but SASE later needs services. |

## Where DigitalOcean Is Better Than Cloudflare Pages

### 1. Full Server Control

A Droplet gives normal Linux hosting. That matters if `sase.sh` needs anything outside Pages' static/edge model:

- Caddy or Nginx configuration beyond `_headers` and `_redirects`.
- SSH access for one-off inspection, logs, and emergency edits.
- Arbitrary binaries, image tooling, fonts, Cairo/Pango, `uv`, Rust, search indexers, or custom build pipelines.
- Conventional long-running processes, local cron, queue workers, private admin services, or preview environments.
- Easier mental model for debugging: DNS -> proxy -> origin -> process -> files/logs.

For the SASE blog specifically, this is useful if the site grows into "docs plus operational tooling" rather than just
published Markdown.

### 2. Better Path to Stateful Product Features

App Platform supports static sites, web services, workers, jobs, functions, and managed databases in the same app model.
That makes DigitalOcean a cleaner path if the blog later needs:

- A newsletter/signup endpoint that writes to a database.
- Comment moderation, private feedback, or invite capture.
- Webhook handlers for GitHub, Buttondown, or release automation.
- Scheduled jobs to rebuild RSS/social metadata/search indexes.
- A small authenticated admin surface for drafting or launch checklists.
- Server-rendered pages where Cloudflare Workers' runtime constraints become annoying.

Cloudflare can do these with Workers, D1, KV, Durable Objects, Queues, and R2, but that pulls the project into an
edge-runtime architecture. DigitalOcean lets the backend be an ordinary container, Python service, Go binary, or systemd
process.

#### Edge/Function Compute Side-by-Side

| Aspect | Cloudflare Workers (Free) | Cloudflare Workers (Paid, $5/mo) | DigitalOcean Functions |
| --- | --- | --- | --- |
| Free allowance | 100k req/day, 10 ms CPU/invocation | 10M req/mo + 30M CPU-ms/mo included | 90,000 GiB-seconds/mo per team |
| Overage | n/a (hard cap) | $0.30 per extra million requests, $0.02 per million CPU-ms | $0.0000185/GiB-second |
| Max CPU per invocation | 10 ms | 5 minutes (default 30 s) | minimum 100 ms billed; longer durations supported |
| Runtime | V8 isolates: JS/TS, WASM, partial Python | Same | Native Go, Node.js, PHP, Python |
| Egress charges | None | None | None within DO; standard outbound on cross-product calls |
| Stateful storage | KV, D1, R2, Durable Objects, Hyperdrive | Same | Managed PG/MySQL/Redis/Kafka/OpenSearch/MongoDB; Spaces |

Two implications:

- For very bursty, very short edge work, Cloudflare Workers is cheaper and lower-latency.
- For longer-running, language-native, library-heavy workloads (e.g. anything that wants `requests`, `pandas`,
  `playwright`, native binaries, Rust crates, or just a normal Python venv), DigitalOcean Functions or an App Platform
  worker/service is significantly less friction than fitting into V8 isolates or Workers' Python preview.

### 3. Predictable VM Economics for an Existing Droplet

If the Droplet is already paid for and lightly used, the marginal cost of hosting a static blog there is close to zero.
DigitalOcean Droplets start at $4/month and include outbound transfer starting at 500 GiB/month; extra Droplet outbound
transfer is $0.01/GiB. That is a lot of headroom for a personal/project blog if Cloudflare caches static assets in front
of it.

App Platform static hosting is less compelling on raw traffic economics: the free tier includes three static-only apps,
but only 1 GiB outbound transfer per app before $0.02/GiB overage. That is fine for a small site, but it is not a reason
to choose DigitalOcean over Cloudflare Pages for a static blog.

### 4. Heavier Build Tolerance

Cloudflare Pages Free builds currently allow one concurrent build, 500 builds/month, and a 20-minute timeout. That is
comfortable for MkDocs, but it can become tight if the site starts generating social cards, API docs, Rust docs,
screenshot galleries, or searchable offline artifacts.

DigitalOcean App Platform build limits are currently 4 CPU cores, 10 GiB memory, 24 GiB disk, and a 1-hour timeout.
If the build gets heavier, DigitalOcean is more forgiving, and a Droplet or external GitHub Actions deploy can remove
most platform build-image constraints entirely.

There is also a build-environment shape difference worth calling out: App Platform can build directly from a
`Dockerfile` (or a buildpack), so any native dependency the project needs — `cairo`, `pango`, `libvips`, custom Rust
toolchain, an `apt` install, a private PyPI mirror — is just a `RUN` line. Cloudflare Pages is constrained to its build
image v3 and a small set of "build environment variables" knobs; anything outside that pushes the project to either
"build the artifact in CI and deploy the prebuilt site" or to migrate to Workers Static Assets where Wrangler controls
more of the pipeline. For an MkDocs site this is a non-issue today; it becomes relevant the first time a plugin needs
a system library.

### 5. First-Party Operational Visibility

App Platform has built-in activity/build/deployment/runtime logs, metrics/insights, and log forwarding to DigitalOcean
Managed OpenSearch, OpenSearch, Datadog, and Better Stack. Droplets add normal server logs, `journalctl`, access logs,
Prometheus exporters, and whatever SASE already uses for host monitoring.

For a simple blog, this is overkill. For a site that becomes a launch surface, docs hub, API demo, or user funnel,
operational visibility becomes more valuable.

### 6. Media and Artifact Hosting Fit

DigitalOcean Spaces is S3-compatible object storage with an optional built-in CDN, custom CDN endpoints, TTL control,
and cache purging. This is useful if `sase.sh` starts serving:

- Large screenshots and infographics.
- Demo videos.
- Downloadable release artifacts.
- Generated HTML reports.
- Public datasets or examples.

Concrete pricing as of this note: Spaces Standard is a flat **$5/month** subscription that includes **250 GiB stored**,
**1,024 GiB of outbound transfer**, and the Spaces CDN at no additional cost. Overage is **$0.02/GiB stored** and
**$0.01/GiB outbound**. Cold storage is available at $0.007/GiB stored with $0.01/GiB retrieval. For a blog hosting
infographics and occasional demo videos, the included tier is effectively the entire bill.

Cloudflare's comparable answer is R2 plus public buckets/custom domains. R2 has no egress fees, which is the headline
advantage; Spaces beats R2 on simplicity (a single subscription line item, S3 tooling parity, CDN included by default,
fewer feature flags).

### 6a. Region Selection and Data Residency

Cloudflare Pages and Workers are global by design — assets are served from the nearest of Cloudflare's ~600 city PoPs
and there is no user-facing "where does this run" knob beyond paid regional services like Workers Smart Placement and
D1 region hints. That is great for read-mostly static traffic and bad if a future feature has data-residency
requirements (EU-only storage, US-only storage, contractual single-region commitments).

DigitalOcean is the inverse: every Droplet, App Platform app, Managed Database, and Space is bound to a specific named
datacenter region (NYC1/2/3, SFO2/3, AMS3, FRA1, LON1, TOR1, BLR1, SGP1, SYD1). That makes DigitalOcean the easier
choice when:

- A future SASE service needs to live in a specific jurisdiction.
- A self-hosted enterprise install needs to know which region its data ends up in.
- An audit requires "list every place customer data is stored."

The trade-off is that DigitalOcean origin latency to a far-away reader is meaningfully worse than Cloudflare's edge
delivery. The Cloudflare-Pages-as-CDN-in-front-of-DigitalOcean-origin pattern resolves this: pin the origin to a single
DO region for compliance, and let Cloudflare cache the static surface.

### 7. Clearer Escape Hatch From Platform Constraints

DigitalOcean App Platform has limitations, but the escape hatch is conventional: move the component to a Droplet,
Kubernetes, a managed database, or a container image. A Droplet also avoids App Platform constraints such as no SSH/SFTP
into containers, limited local filesystem persistence (4 GiB cap, no volumes, no IPv6, no SMTP egress, AMD64-only
container images), and some gVisor/runtime restrictions.

This is the strongest strategic reason to pick DigitalOcean: the project can degrade into boring infrastructure when
needed.

### 8. Strategic Vendor-Risk Asymmetry

The sibling [`cloudflare_pages_sase_blog_launch.md`](./cloudflare_pages_sase_blog_launch.md) notes that Cloudflare has
publicly committed all new investment to Workers and is converging Pages and Workers into a single experience. This is
not a "Pages is being killed" risk — Cloudflare has explicitly committed to keeping Pages projects working — but it is
a *churn* risk: docs, dashboard UX, build images, and best-practice guidance will keep shifting underneath any project
that depends on the Pages-specific surface (Pages Functions, the Pages dashboard's preview/redeploy semantics,
`wrangler pages` ergonomics).

DigitalOcean's product surface for hosting is older, slower-moving, and less prone to mid-flight pivots. The cost is
that App Platform's static-site path is plainly less polished than Pages or Workers Static Assets; the benefit is that
a 2026 build runbook is likely to still be valid in 2028.

For a one-author blog this churn is a paper cut. For a project that wants infrastructure decisions to age, this
asymmetry is one of the few clean, non-cost reasons to prefer DigitalOcean.

### 9. Stateful Service Pricing Baseline

A common reason to keep DigitalOcean in the architecture is that the stateful product surface is priced predictably and
operates like every other Postgres/Redis/etc. you have used:

| Service | Cheapest plan | What it includes |
| --- | --- | --- |
| Managed PostgreSQL (dev/single node) | $15/mo | 1 GiB RAM, automatic failover (no HA replica), suitable for dev/low-traffic. |
| Managed PostgreSQL (HA) | $30/mo + $30/mo standby | 1 vCPU / 2 GiB RAM primary plus matching standby for failover. |
| Read-only replica node | $15/mo | Adds a regional read replica. |
| Storage overage | $0.21/GiB/mo | Beyond the included plan storage. |
| Spaces (object storage) | $5/mo | 250 GiB stored, 1,024 GiB transfer, CDN included. |
| Droplet (VM) | $4/mo | 1 vCPU / 512 MiB / 10 GiB SSD / 500 GiB transfer. |

Cloudflare's comparable D1 / Hyperdrive / Workers KV / R2 stack can be cheaper for very small, very edge-friendly
workloads, but the moment the project wants `psql`, `pg_dump`, extensions like `pgvector`, point-in-time recovery, and
"a Postgres my ORM has worked with for ten years," DigitalOcean wins on operational familiarity.

## Concrete Cost Worksheet

Numbers below assume the SASE blog is roughly 50 MB of built assets (MkDocs Material with infographics) and that
average page weight is ~250 KB after compression. These are illustrative monthly bills, not quotes.

| Scale | Pageviews/mo | Outbound GiB/mo | Cloudflare Pages | DO App Platform (static) | DO Droplet ($4) + Cloudflare DNS/CDN | DO Droplet ($4) origin only (no CF cache) |
| --- | --- | --- | --- | --- | --- | --- |
| Tiny | 10,000 | ~3 GiB | $0 | $0 (within 1 GiB/app + small overage ~$0.04) | $4 (Droplet flat) | $4 |
| Small | 100,000 | ~25 GiB | $0 | ~$0.48 overage on top of $0 | $4 (Cloudflare absorbs egress) | $4 (within 500 GiB Droplet allowance) |
| Medium | 1,000,000 | ~250 GiB | $0 (still within free) | ~$5 overage | $4 (Cloudflare absorbs egress) | $4 (still within Droplet allowance) |
| Large | 10,000,000 | ~2,500 GiB | $0 (free, unmetered egress) | ~$50 overage | $4 (Cloudflare absorbs egress) | ~$24 ($4 + 2,000 GiB × $0.01) |

Key observations from the worksheet:

- For a pure static blog, **Cloudflare Pages is free at every plausible blog scale** because its egress is not metered.
  No DigitalOcean shape beats $0.
- An existing Droplet fronted by Cloudflare DNS/CDN is the only DigitalOcean shape that is cost-competitive at scale,
  and only because Cloudflare is doing the egress work. This is the "DigitalOcean origin, Cloudflare edge" hybrid.
- Pure App Platform static hosting is the worst of both worlds at higher scale: you pay $0.02/GiB egress without any
  edge caching benefit beyond what Spaces CDN provides.
- The Droplet wins on cost only if it would already exist for other reasons. Spinning one up *for the blog* and paying
  $4/mo to do work Pages does for free is a non-cost decision (control, server reuse, future services).

Build/CI cost is not in this table because both platforms have effectively-free build allowances for an MkDocs site of
this shape.

## DigitalOcean Caveats

These are not deal-breakers, but they prevent DigitalOcean from being the default static-blog choice.

- App Platform static-site free traffic is only 1 GiB outbound per app, then $0.02/GiB.
- App Platform static sites are served through Spaces CDN and cannot be scaled like service components.
- App Platform does not directly support 301/302 redirects in the same simple way Pages supports `_redirects`.
- App Platform domains do not support DNSSEC-enabled domains.
- App Platform containers are AMD64-only, no IPv6, no SMTP egress, and have a 4 GiB local filesystem cap with no
  persistent volumes — anything stateful must live in a managed database, Spaces, or an external service.
- Droplets require OS patching, web server config, TLS/cert renewal strategy, firewalling, backups, monitoring, and
  incident response.
- DigitalOcean's network footprint is roughly 15 datacenter regions globally vs Cloudflare's ~600-city PoP network.
  An end user in São Paulo or Mumbai hitting a NYC3 origin pays ~150–250 ms of round trip per uncached asset; with
  Cloudflare in front of the same origin, that drops to single-digit-ms cache hits at the local PoP. Origin region
  choice matters a lot more on DigitalOcean than on Cloudflare.
- If Cloudflare is already authoritative for `sase.sh`, Cloudflare Pages is the shorter path to a static canonical blog.

## Recommendation for SASE

Use Cloudflare Pages for the first production version of `https://sase.sh/blog/`.

Keep DigitalOcean in the architecture as the likely home for:

- The existing Droplet if it is already used for other sites or private tools.
- Any future SASE service that needs a normal server/container runtime.
- Managed PostgreSQL/Valkey/OpenSearch if the site becomes stateful.
- Spaces if the blog starts hosting large media/artifacts and R2 is not preferred.

Switch the blog itself to DigitalOcean only if one of these becomes true:

1. The site needs long-running server-side code at the same origin.
2. The build needs native packages or build time that Pages makes painful.
3. Reusing the existing Droplet is more valuable than Cloudflare's static-hosting simplicity.
4. The blog becomes part of a larger `sase.sh` product surface with databases, workers, cron jobs, or admin tools.

## Source Notes

- DigitalOcean App Platform can deploy from Git repositories or container images, auto-detect runtimes, and add services,
  static sites, databases, workers, and jobs after app creation:
  <https://docs.digitalocean.com/products/app-platform/how-to/create-apps/>
- DigitalOcean App Platform feature list includes static assets, dynamic apps, Git deployment, Docker/container images,
  SSL, custom domains, CDN, metrics, rollback, scaling, DDoS mitigation, and Git LFS:
  <https://docs.digitalocean.com/products/app-platform/details/features/>
- DigitalOcean App Platform static-site configuration supports output directories, routes, app-level env vars, custom
  error/catchall pages, and `doctl`/API app-spec updates:
  <https://docs.digitalocean.com/products/app-platform/how-to/manage-static-sites/>
- DigitalOcean App Platform pricing: static-only free tier is three apps with 1 GiB outbound transfer each; additional
  static apps are $3/month; overage is $0.02/GiB; paid service containers start at $5/month:
  <https://docs.digitalocean.com/products/app-platform/details/pricing/>
- DigitalOcean App Platform limits: builds get 4 CPU cores, 10 GiB memory, 24 GiB disk, and 1-hour timeout; static sites
  use Spaces CDN; App Platform has DNSSEC, redirect, local filesystem, and SSH/SFTP limitations:
  <https://docs.digitalocean.com/products/app-platform/details/limits/>
- DigitalOcean Droplet pricing: Droplets are Linux VMs billed per second with a monthly cap; pricing starts at $4/month;
  outbound transfer starts at 500 GiB/month and extra outbound transfer is $0.01/GiB:
  <https://docs.digitalocean.com/products/droplets/details/pricing/> and
  <https://www.digitalocean.com/pricing/droplets>
- DigitalOcean Spaces provides S3-compatible object storage with optional CDN, custom CDN endpoints, TTL control, and
  cache purging:
  <https://docs.digitalocean.com/products/spaces/details/features/>
- Cloudflare Pages current limits: Free plan has one concurrent build, 500 builds/month, 20-minute build timeout,
  20,000 files, 25 MiB max asset size, unlimited active preview deployments, and `_redirects` / `_headers` limits:
  <https://developers.cloudflare.com/pages/platform/limits/>
- Cloudflare Pages build image v3 currently includes Node 22.16.0, Python 3.13.3, pip, pipx, Poetry, pnpm, Yarn, Hugo,
  and Zola, but not `uv` as a documented preinstalled tool:
  <https://developers.cloudflare.com/pages/configuration/build-image/>
- DigitalOcean Spaces pricing: $5/mo subscription includes 250 GiB storage, 1,024 GiB outbound transfer, and the
  Spaces CDN at no additional cost; overage $0.02/GiB stored, $0.01/GiB outbound; cold storage $0.007/GiB stored:
  <https://docs.digitalocean.com/products/spaces/details/pricing/>
- DigitalOcean Managed PostgreSQL pricing: dev single-node clusters from $15/mo (1 GiB RAM, automatic failover,
  no HA); HA cluster from $30/mo + matching $30/mo standby; read replicas $15/mo; storage overage $0.21/GiB/mo:
  <https://docs.digitalocean.com/products/databases/postgresql/details/pricing/>
- DigitalOcean Functions pricing: 90,000 GiB-seconds/team/month free; overage $0.0000185/GiB-second; minimum 100 ms
  per invocation; supported runtimes Go, Node.js, PHP, Python:
  <https://docs.digitalocean.com/products/functions/details/pricing/>
- Cloudflare Workers pricing: Free plan 100k req/day with 10 ms CPU/invocation; Workers Paid $5/mo includes 10M
  req/mo + 30M CPU-ms/mo, max 5 minutes CPU/invocation; egress is never metered:
  <https://developers.cloudflare.com/workers/platform/pricing/>
- Cloudflare global network: data centers in hundreds of cities across 100+ countries (~600 city locations
  enumerated on the network page):
  <https://www.cloudflare.com/network/>

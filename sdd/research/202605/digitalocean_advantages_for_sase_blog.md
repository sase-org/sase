# DigitalOcean Advantages for the `sase.sh` Blog

Date: 2026-05-07

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

Cloudflare's comparable answer is R2 plus public buckets/custom domains. Either is viable. Spaces is attractive if the
rest of the operational stack is already in DigitalOcean and if S3-compatible tooling matters.

### 7. Clearer Escape Hatch From Platform Constraints

DigitalOcean App Platform has limitations, but the escape hatch is conventional: move the component to a Droplet,
Kubernetes, a managed database, or a container image. A Droplet also avoids App Platform constraints such as no SSH/SFTP
into containers, limited local filesystem persistence, no App Platform volumes, and some gVisor/runtime restrictions.

This is the strongest strategic reason to pick DigitalOcean: the project can degrade into boring infrastructure when
needed.

## DigitalOcean Caveats

These are not deal-breakers, but they prevent DigitalOcean from being the default static-blog choice.

- App Platform static-site free traffic is only 1 GiB outbound per app, then $0.02/GiB.
- App Platform static sites are served through Spaces CDN and cannot be scaled like service components.
- App Platform does not directly support 301/302 redirects in the same simple way Pages supports `_redirects`.
- App Platform domains do not support DNSSEC-enabled domains.
- Droplets require OS patching, web server config, TLS/cert renewal strategy, firewalling, backups, monitoring, and
  incident response.
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

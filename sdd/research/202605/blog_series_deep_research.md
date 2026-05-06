Yes, and the answer is probably: **you do not need a large droplet if the site is static.**

For `sase.sh`, assuming:

```text
MkDocs/Docusaurus/static HTML
Caddy or Nginx
No database
No server-side rendering
No WordPress/Ghost
No app process
```

then I’d start with:

```text
1 vCPU / 1 GB RAM
```

and put **Cloudflare in front** of it.

That setup can handle a surprisingly large launch spike because the droplet is only serving static files, and Cloudflare can absorb most repeat traffic.

## Practical recommendation

Use your current droplet unless it is extremely tiny or overloaded with other services.

My sizing rule:

| Setup                                                |                           Droplet size I’d use |
| ---------------------------------------------------- | ---------------------------------------------: |
| Static site + Cloudflare cache                       |                          **1 vCPU / 1 GB RAM** |
| Static site, no CDN, moderate spike                  |                        **1 vCPU / 1–2 GB RAM** |
| Static site, no CDN, very image-heavy                | **2 vCPU / 2–4 GB RAM**, but better to add CDN |
| WordPress/Ghost/CMS                                  |                **2 vCPU / 2–4 GB RAM minimum** |
| Static site plus search, analytics, demos, API, etc. |        Depends on those services, not the blog |

For the SASE canonical blog, I’d do:

```text
1 vCPU / 1 GB RAM droplet
Caddy
Cloudflare DNS/proxy enabled
Aggressive static caching
Images optimized
Builds done in GitHub Actions, not on the droplet
```

## The real bottleneck is bandwidth, not CPU

A static blog post is cheap to serve. The main risk during a viral spike is transfer volume.

Rough math:

```text
100,000 pageviews × 500 KB/page ≈ 50 GB transfer
100,000 pageviews × 1 MB/page   ≈ 100 GB transfer
1,000,000 pageviews × 1 MB/page ≈ 1 TB transfer
```

That is manageable, but you do not want all of it coming directly from your droplet if the post really takes off.

With Cloudflare in front, most repeated assets and pages can be served from cache. Your droplet might only see a fraction of the traffic. Without a CDN, the droplet can still serve the traffic, but you may burn through included transfer much faster. I can’t live-check current DigitalOcean bandwidth allowances here, so verify the current transfer limits for your exact plan.

## “Blows up” traffic is usually less scary than it sounds

Suppose a post gets **250,000 pageviews in one day**. That sounds huge, but the average request rate is:

```text
250,000 / 86,400 ≈ 2.9 pageviews/sec
```

Even if the peak is 20× the daily average:

```text
~60 pageviews/sec
```

A small droplet serving static files with Caddy or Nginx can handle that, especially with compression and CDN caching.

The scary case is not average load. It is:

```text
huge unoptimized images
no CDN
many uncached assets per page
bots/scrapers
analytics scripts
server-side rendering
```

Avoid those and the droplet size barely matters.

## What I would configure before launch

### 1. Put Cloudflare in front

Use:

```text
sase.sh      proxied through Cloudflare
www.sase.sh  redirect to sase.sh
```

Keep the droplet as the origin.

### 2. Cache static assets hard

For assets with hashed filenames, cache for a long time:

```text
Cache-Control: public, max-age=31536000, immutable
```

For HTML pages, use a shorter cache:

```text
Cache-Control: public, max-age=300
```

or something similarly conservative.

### 3. Optimize images

This matters more than droplet size.

Use:

```text
WebP / AVIF where practical
reasonable dimensions
lazy loading
compressed social preview images
no 5 MB screenshots inline
```

A viral post with ten 2 MB images is a bandwidth problem. A viral post with compressed images and cached assets is easy.

### 4. Do not build on the droplet

Build in GitHub Actions:

```text
mkdocs build --strict
rsync site/ to droplet
```

The droplet should only serve files.

### 5. Add basic monitoring

Watch:

```text
CPU usage
RAM usage
network outbound
Caddy/Nginx access logs
5xx errors
disk space
Cloudflare cache hit ratio
```

Upgrade only if the metrics say you need to.

## When would I upgrade?

I would not upgrade preemptively unless the current droplet is already under load.

Upgrade from **1 GB → 2 GB** if:

```text
RAM is consistently above ~70–80%
CPU is consistently high during normal traffic
you are running other services on the droplet
Caddy/Nginx starts competing with background jobs
```

Upgrade from **2 GB → 4 GB** only if:

```text
you add dynamic services
you host demos/APIs on the same box
you run search indexing locally
you run analytics/database workloads
you refuse to use a CDN and traffic is huge
```

For a static blog alone, a 4 GB droplet is usually unnecessary.

## My preferred launch setup

```text
Droplet:       1 vCPU / 1 GB RAM
Web server:    Caddy
CDN/DNS:       Cloudflare
Build:         GitHub Actions
Deploy:        rsync over SSH
Content:       static HTML/CSS/JS/images
Images:        compressed and lazy-loaded
Monitoring:    DO graphs + uptime monitor + logs
```

That should survive a very successful launch.

## The best safety valve

The most important move is this:

```text
Enable Cloudflare proxy/cache before announcing the series.
```

That gives you room to handle a big spike without resizing the droplet. If the series truly explodes, you can later move static assets to object storage or a static host, but you probably will not need to.

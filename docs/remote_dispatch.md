# Remote Dispatch Runbook

Remote dispatch lets one SASE controller discover, enroll, and operate agents on another
machine. The supported setup path is explicit and credentialed:

1. Prepare the target machine and run its gateway on loopback.
2. Expose that loopback gateway through a private tailnet HTTPS endpoint.
3. Issue a target-local one-time bootstrap bundle.
4. Enroll the target from the controller with `sase machine init`.
5. Verify authenticated status, then launch and manage remote agents with
   `%dispatch:<alias>`.

Tailnet membership is not authorization. Enrollment uses a single-use bootstrap secret
issued by the target gateway's credential store, and ordinary fleet calls use the
credential written into the controller's protected SASE state.

## Install

Install SASE normally on each machine that will act as a target. The target needs the
Python `sase` command and the packaged Rust entry points in the same installed tool
environment:

```bash
uv tool install --reinstall sase
uv tool dir
"$(uv tool dir)/sase/bin/sase" version
"$(uv tool dir)/sase/bin/sase_gateway" --help
"$(uv tool dir)/sase/bin/sase_federation_worker" --help
```

On machines where noninteractive SSH does not load the uv-tool bin directory, use the
absolute paths under `$(uv tool dir)/sase/bin/`. The dispatch resolver checks that
installed-venv directory for `sase_gateway` and `sase_federation_worker`; the shell
`PATH` does not need to expose those commands.

Restart AXE after updating a target or controller install:

```bash
sase axe stop
sase axe start
```

`sase axe ensure` is also acceptable when you want to heal a stopped orchestrator
without forcing a stop/start cycle.

## Run The Gateway

Run the gateway as the same OS user and with the same SASE home that will issue the
bootstrap bundle. Keep it bound to loopback unless you are doing a short, deliberate LAN
smoke test:

```bash
sase_gateway --bind 127.0.0.1:7629 --sase-home ~/.sase
curl -fsS http://127.0.0.1:7629/api/v1/health
```

The public health response must include a `fleet.supported_protocol_versions` list for
automatic compatibility classification. Older gateways without that field can still be
manually enrolled when the authenticated protocol negotiation accepts the controller,
but discovery will report compatibility as unknown.

### Linux Supervision

For a user-systemd target, run the installed gateway from the uv-tool environment:

```bash
TOOL_DIR="$(uv tool dir)"
systemd-run --user --unit=sase-gateway \
  --property=Restart=on-failure \
  "$TOOL_DIR/sase/bin/sase_gateway" \
  --bind 127.0.0.1:7629 \
  --sase-home "$HOME/.sase"

systemctl --user status sase-gateway --no-pager
curl -fsS http://127.0.0.1:7629/api/v1/health
```

Use the host's normal unit naming if it already has a permanent service. The important
properties are loopback bind, the correct SASE home, and restart-on-failure behavior.

### macOS Supervision

For macOS, prefer a LaunchAgent owned by the same user. Replace `TOOL_DIR` with the
absolute `uv tool dir` result for that machine:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>sh.sase.gateway</string>
  <key>ProgramArguments</key>
  <array>
    <string>TOOL_DIR/sase/bin/sase_gateway</string>
    <string>--bind</string>
    <string>127.0.0.1:7629</string>
    <string>--sase-home</string>
    <string>/Users/YOU/.sase</string>
  </array>
  <key>KeepAlive</key>
  <true/>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
```

Load it with
`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/sh.sase.gateway.plist` and
inspect it with `launchctl print gui/$(id -u)/sh.sase.gateway`.

## Expose Through Tailscale Serve

The gateway should stay on `127.0.0.1`; Tailscale Serve terminates HTTPS inside the
tailnet and proxies to the loopback port:

```bash
tailscale serve --bg --yes 7629
tailscale serve status
curl -fsS https://TARGET.tailnet-name.ts.net/api/v1/health
```

If the CLI prints a `login.tailscale.com/f/serve?...` URL, Tailscale Serve or HTTPS
certificates are not enabled for the tailnet or node. Open the URL while signed in as a
tailnet owner/admin and enable Serve before retrying. A successful setup shows a Serve
config and the MagicDNS HTTPS health URL answers with the gateway health JSON.

Do not use Tailscale Funnel for remote dispatch. SASE's gateway is intended to remain
inside a private tailnet or equivalent private access layer.

## Issue A Bootstrap

Issue the bundle on the target, as the gateway user, against the gateway's SASE home:

```bash
umask 077
sase machine bootstrap --json > /tmp/sase-apollo-bootstrap.json
```

The file contains a live single-use secret. Do not pass it in argv, paste it into logs,
or record it in a bead note. Move it to the controller over a protected channel and
delete both temporary copies after enrollment. The default expiry is the gateway store's
short TTL, so issue the bundle immediately before running init.

## Enroll From The Controller

From the controller, run discovery and then initialize with the bundle file:

```bash
sase machine discover -j
sase machine init -B /path/to/bootstrap.json
sase machine list -j
sase machine status TARGET -j
sase doctor -D -C dispatch
```

`sase machine init --check` and `sase init --check --json` are offline checks; they do
not discover peers or talk to gateways. Explicit `sase machine init` performs discovery,
shows already enrolled machines beside new candidates, writes the machine record and
credential, deploys the chezmoi-managed overlay when configured, reloads config, and
runs an authenticated hello before declaring success.

If enrollment partially succeeds after the target consumes the bootstrap, follow the
command's recovery text. Retry a failed local apply when the credential is already
stored; issue a fresh target bundle and run `sase machine repair TARGET` when the target
credential needs to rotate.

## Launch And Operate

After status is healthy, launch remote agents by adding a dispatch selector to a normal
launch prompt:

```bash
sase run "%dispatch:apollo summarize the current project state; do not change files"
```

ACE consumes the same fleet records. `sase ace --tmux` prints the tmux target for the
session; from there, the Agents tab shows enrolled machines and remote row counts, Focus
can follow a remote row, and remote lifecycle actions are sent through
`sase machine agent` and `sase machine attention` durable requests.

To prove restart resilience, restart the target gateway service, then rerun:

```bash
sase machine status apollo
sase run "%dispatch:apollo report hostname and SASE version; do not change files"
```

The enrollment should survive a gateway process restart. Reissue a bootstrap only for a
new or repaired enrollment, not for ordinary gateway restarts.

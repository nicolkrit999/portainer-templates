---
name: public-proxy-batch-lessons
description: Non-obvious Docker/Traefik/CodeIgniter facts found while building traefik-public Batch 2 (ip_range+gateway quirk, path-block limits, local test harness)
metadata:
  type: reference
---

Facts verified 2026-11-03 on a local Docker 29.9.1 / Compose 5.6.0 / traefik:v3.7.17 (not on the NAS). Full write-up: `/home/krit/momentary/proxy-research/findings/cross-cutting.md` (entry "Batch 2 PROXY side"), scripts in its `tools/public-*`. The router/network list itself lives in `traefik-public/README.md`.

- **Fixed proxy IP vs dynamic backends:** Docker gives the lowest free address to the first container that attaches. A backend that attaches before the proxy's holder takes `.2`, the holder's `ipv4_address: .2` then fails with "Address already in use" and the whole public edge stays down. New `public-<app>` networks therefore get `ip_range` in the upper half of the /28 AND an explicit `gateway` (.1): without `gateway`, Docker uses the ip_range's first address as the gateway. A static IP outside the ip_range is accepted. The Batch 1 networks (jellyfin, navidrome, gokapi, gitea, privatebin) have no `ip_range` (latent risk); never change a live network's IPAM in the compose: Compose stops the project's holder, fails to remove the network ("has active endpoints") and leaves it stopped.
- **Traefik v3 rules:** matchers take one value each; `!` negation works (`Host(...) && !Path(...)`). A request that matches no router gets Traefik's own 404 with no middleware (no HSTS), and the access log shows no router name. Dot segments, `//` and `%61`-style encodings are normalized before matching. A rule sees only the path, never a query key prefix.
- **CodeIgniter (Easy!Appointments 1.6.1):** also routes from a query string that starts with `/` (`/?/api/v1/...`) when the path is empty, so a Traefik path block does not close the REST API; the fix is `if ($args ~ "^/") { return 404; }` in the app's nginx vhost. `index.php/api_settings` is a staff admin page: block `/api` by whole segments, not by string prefix.
- **Header profiles:** the global proxy `Referrer-Policy: same-origin` overrides an app's own value; TREK loads map tiles cross-origin, so OpenCloud/TREK use `strict-origin-when-cross-origin` (what the apps send) in `public-secure-headers-app-framing`.
- **Local test recipe:** bring up a COPY of the compose with an unreachable ACME `caServer` flag and `driver: json-file` on the logging blocks (laptop daemon is journald, rejects `max-file`), a stand-in bridge named like the macvlan network, a self-signed wildcard cert as a second file in the dynamic dir, stub backends named like the real containers, `curl --resolve host:443:<stand-in IP> -k`.

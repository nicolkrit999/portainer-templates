# Gotcha: Cloudflare-only hostnames are broken by the wildcard DNS override

`dnsmasq` (LAN) and `dnsmasq-tailnet` (tailnet) answer `*.${DNS_WILDCARD_DOMAIN}`
with this NAS's own IP, so every hostname under the domain is intercepted
locally - including ones deliberately kept Cloudflare-Tunnel-only and never
given a Traefik router (e.g. Cloudflare Access SSH applications, which aren't
HTTP and can't be Traefik-routed the normal way).

**Symptom (2026-08-23):** `git push` to Gitea over `gitea-ssh.<domain>`
(proxied via `cloudflared access ssh --hostname %h`) failed with
`x509: certificate is valid for <hash>.traefik.default, not gitea-ssh.<domain>`.
Local DNS sent the client to Traefik, which has no router/cert for that
hostname (by design) and served its self-signed default cert. Same bug
confirmed for `ssh.<domain>`.

**Fix:** a more-specific `--server=/<host>.${DNS_WILDCARD_DOMAIN}/1.1.1.1`
line per exception hostname, which forwards just that label to a public
resolver instead of answering locally. Currently `gitea-ssh` and `ssh`, in
BOTH `dnsmasq/docker-compose.yml` (lines 140-141) and
`dnsmasq-tailnet/docker-compose.yml` (lines 107-108). Both files carry an
inline comment explaining it; keep them in sync.

**Side effect (not a regression):** the global `--filter-AAAA` /
`--filter-rr=HTTPS` / `--filter-rr=SVCB` flags also apply to forwarded
answers, so these hostnames only ever get IPv4 answers.

**How to apply:** when adding a new Cloudflare-only, non-Traefik hostname
(check the Cloudflare Tunnel dashboard's public hostname list - it is not
visible from this repo), add the same `--server=` exclusion to BOTH dnsmasq
compose files. This is the opposite of the usual `adding-compose-services`
DNS step, which adds an override for a new Traefik-routed service.

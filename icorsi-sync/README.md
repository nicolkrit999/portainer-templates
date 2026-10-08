# icorsi-sync

Automatically download your **Moodle / iCorsi** course material into **OpenCloud**.

It logs into Moodle's API with a personal token, looks at each course you choose, and
copies the material into OpenCloud - keeping the **same structure and order** the course uses.
It runs on a schedule, only fetches what's new or changed, and retries until nothing is missing.

What it saves per course:
- all **files** (PDFs, slides, code, anything in folders/resources/pages/books, …),
- **links** (external URLs) as small `.txt` files,
- **section text** (intros, notes written directly on the page) as `_info.md`,
- **announcements / forum posts** as `.md` files.

It is **read-only** on Moodle: it can only *read* and *download*. It can never submit an
assignment, start a quiz, or mark attendance.

---

## How files end up organised

Everything for a course goes into a `_icorsi/` subfolder inside that course's folder, so it
never mixes with your own notes. Sections and items are **numbered (`001 - `)** so they sort
in the course's real order instead of alphabetically:

```
<your course folder>/_icorsi/
├── 001 - <section name>/000 - _info.md          text written on the page (pinned on top)
├── 001 - <section name>/001 - <file.pdf>        a single file
├── 002 - <section name>/001 - <folder>/<file…>  a folder (its own subfolders kept, unnumbered)
├── 002 - <section name>/002 - <link>.url.txt    an external link
└── 000 - Annunci/<date> <title>.md              announcements pinned at the top (and 000 - Forum/… for other forums)
```

`_icorsi/` is **tool-owned** - treat it as a faithful mirror. With `PRUNE_ORPHANS` on (below),
anything you put inside it that isn't part of the course will be removed; keep your own edits
*outside* `_icorsi/`.

---

## The one thing you'll edit: `courses.json`

This file decides **which courses to download and where to put them**. It is *not* in this
repo (it's personal) - it lives next to the running container, in the data folder you mount
(e.g. `${VOLUME_CONFIG}/icorsi-sync/data/courses.json`). See `courses.example.json` for the shape.

It maps a **course ID** to a **folder** (relative to `OPENCLOUD_BASE_PATH`):

```json
{
  "12345": "Example Subject",
  "23456": "Another Subject/2025-2026",
  "34567": null
}
```

- **Course ID** - the number in the course URL: `…/course/view.php?id=`**`12345`**.
- **Folder** - where its `_icorsi/` goes. Subfolders are fine (`Another Subject/2025-2026`).
- **`null`** - skip this course (kept here for reference, but never downloaded, no warnings).

To add a course: copy its ID from the URL, add a line, restart the container. That's it -
the folder is created automatically. Editing this file needs no rebuild.

> If you enrol in a new course you haven't listed, the tool just notifies you (optionally on
> Discord) so you can add it - it won't download anything until you do.

---

## Automatic token renewal

The Moodle mobile token expires after about **2 days**. You don't have to babysit it: as long
as the container keeps running, the tool re-mints the token **fully headlessly** on every run,
so it never actually expires. It does this the same way the mobile app does - it asks Moodle for
a one-time autologin key, redeems it to open a session, and reads back a fresh token. Your
`ICORSI_TOKEN`, `ICORSI_PRIVATETOKEN` and `ICORSI_USERID` are stored in `/data/token.json` and
rotated in place; the env vars only seed that file on first start.

**Keep all three env vars set** even after the first run. They aren't read again while
`token.json` is healthy, but they're your only recovery path if that file is ever lost or
corrupted, or if the token fully lapses (see below) - leave them in place so the tool can
re-bootstrap itself.

**You're warned if renewal ever has trouble.** Success is silent - if the sync keeps running,
renewal is working. But if the headless renewal starts failing (Moodle changes something,
autologin gets disabled, a network/IP problem), the tool sends a Discord **early warning while
the current token still works** - so you can fix it *before* sync ever stops. It doesn't spam
on a transient blip (needs two consecutive failures first), but once alerted **it repeats once a
day for as long as the problem persists** - so a warning nobody acts on immediately doesn't just
go silent. (Before 2026-07-28 it only alerted once per problem, ever - that's how a token death on
2026-07-11 went unnoticed until 2026-07-28. See the Troubleshooting section below if you're
dealing with an active alert.)

It hard-fails (skips runs until you intervene) in two distinct situations - **only one of which
is actually about downtime:**
- **The container was down long enough for the token to naturally expire** (~2 days) without
  `keep_alive()` running to slide it forward. Restarting with the env vars still set
  re-bootstraps it from them (only if those saved values are still valid - see below).
- **iCorsi/Moodle revokes your session and token out-of-band**, independent of any downtime -
  this is what actually happened on 2026-07-10/11: the container had been running continuously
  for days, `keep_alive()` was renewing every 6h without issue, and then both the token and the
  underlying Moodle session died within the same ~6h window. Nothing client-side causes or
  prevents this - it is now handled automatically by the `icorsi-auth` sidecar (see "Automatic
  re-login" below); a fresh manual credential capture is only the fallback if that fails. See
  Troubleshooting below.

> **Harmless log warning you can ignore:**
> `keep_alive refresh failed: ... autologinkeygenerationlockout - ... wait 6 minutes between requests`
> This is **normal and safe to ignore.** Moodle only lets you mint a new autologin key once every
> 6 minutes. It shows up when the container is **restarted/redeployed twice within 6 minutes** (e.g.
> while you're setting it up), because each start immediately tries to renew. In steady state the
> tool only renews once every `SYNC_INTERVAL_SECONDS` (6h by default) - 60× outside the limit - so
> it never happens on its own. Your token isn't affected: it was already refreshed on the previous
> run, and the next run renews cleanly. (This single blip also won't trigger the Discord early
> warning, which needs two consecutive failures.)

## Automatic re-login (icorsi-auth)

**Why.** iCorsi's Moodle revokes the mobile token *and* the session server-side roughly every
**3 days**, regardless of uptime (observed: a token renewed at 13:38 was `invalidtoken - token not
found` six hours later, with its session dead too). Nothing the tool holds survives that, so it used to
need a manual token capture each time. The `icorsi-auth` sidecar removes that: when renewal fails,
`icorsi-sync` asks it for a **fresh login** and it returns a new token.

**Your login path.** The account only logs in through iCorsi's **"SUPSI login"** button
(Moodle `auth_oidc`), not the plain e-mail/password form. The sidecar automates exactly that, in
headless Chromium (a fresh browser per attempt, nothing persisted):

1. `launch.php` while logged out (Moodle remembers it as the page to return to), then `/auth/oidc/`
   which redirects to **Microsoft Entra ID** (`login.microsoftonline.com`, SUPSI tenant).
2. Microsoft: e-mail, password, then the **TOTP code** computed from your secret (RFC 6238, SHA1, 6
   digits). If Microsoft's default is an Authenticator push it clicks "Sign in another way" and picks the
   verification-code option (you may see one stray push notification on your phone: just ignore it).
   "Stay signed in?" is answered **No**.
3. Microsoft posts back to iCorsi, Moodle lands on `launch.php`, which redirects to
   `moodlemobile://token=...`. Chromium can't open that scheme, so the redirect is read from the network
   layer and parsed into `wstoken` + `privatetoken` (expects `parts=3`).

**What the sidecar can and cannot reach.**
- Network allowlist, enforced three ways (Chromium's own DNS rules, a per-request route filter, and a
  redirect-hop check that aborts the attempt): only `www.icorsi.ch` (and there only `launch.php`,
  `/login/index.php`, and the OIDC entry point / redirect URI `/auth/oidc/` + `/auth/oidc/index.php`;
  other `auth_oidc` endpoints such as `ucp.php` or `logout.php` are refused) and the Microsoft login hosts `login.microsoftonline.com`,
  `aadcdn.msftauth.net`, `aadcdn.msauth.net`. Everything else is refused (e.g. `login.live.com`,
  Microsoft telemetry, branding images, `analytics.usi.ch`, all Office/Outlook/Teams/mysignins/account
  pages). `--probe` prints the aborted hosts so you can see the allowlist at work.
  **Exception:** redirect targets cannot be intercepted, so if Moodle redirects to another iCorsi page
  after login (e.g. `/my/`) that one document is loaded with the live session; its scripts and
  subresources are still blocked and the flow immediately re-requests `launch.php`
  (`relaunched_launch_php=True`).
- Any unexpected Microsoft page ("More information required", consent, password change, account setup)
  is never clicked through: the attempt fails with `interstitial:<page-id>` and the sidecar halts.
- It never calls Moodle web services, never logs out, never touches courses, files or OpenCloud.
- Credentials, TOTP codes, tokens and page content are never logged, screenshotted or traced; failures
  log only a short error code and the host/path where the browser stopped. The TOTP secret is never
  written to disk, and the three secrets are removed from the process environment right after start
  (`os.environ`) and the process is made non-dumpable (`PR_SET_DUMPABLE=0`) so the same-uid Chromium
  processes cannot read them back from `/proc/1/environ` or `/proc/1/mem`.
- Separate container: no `/data`, not on the `cloudflare-web` network (own default network), no ports,
  read-only filesystem (tmpfs `/tmp` for the browser profile), all capabilities dropped except those
  needed to chown `/auth` and drop privileges, `no-new-privileges`, runs as `PUID`/`PGID`,
  `mem_limit: 768m` (Chromium can balloon). The two containers share only
  `${VOLUME_CONFIG}/icorsi-sync/auth` (`/auth`, mode 0700): `request.json` / `result.json` (the token,
  deleted by `icorsi-sync` once read) and a `heartbeat` timestamp. Rate-limit state (`sidecar.json`, no
  secrets) lives in the sidecar-only `${VOLUME_CONFIG}/icorsi-sync/auth-state` (`/state`).
- **Chromium's own sandbox is off (`--no-sandbox`).** Docker's default seccomp profile blocks the
  user-namespace calls it needs; the alternative is `seccomp=unconfined` for the whole container, which
  weakens the container boundary more than dropping the in-browser sandbox does. The browser only loads
  the allowlisted login pages (plus the one-document redirect exception above), in a read-only,
  capability-less, non-root container.

**Security trade-off, in plain words.** The Microsoft password **and** the TOTP secret together are a
full SUPSI Microsoft sign-in, defeating the point of 2FA: if the NAS (or Portainer, or its env) is
compromised, whoever gets them *is* you for everything on that SUPSI account (mail, Teams, OneDrive...),
not just iCorsi. Mitigations: the sidecar is isolated as above, and you can cut it off at any time by
removing that authenticator method in <https://mysignins.microsoft.com> (Security info) and/or changing
your password.

**How to get the TOTP secret** (do this once; keep your normal phone login working):
1. <https://mysignins.microsoft.com> -> **Security info** -> **Add sign-in method** -> **Authenticator app**.
2. Click **"I want to use a different authenticator app"** (not the Microsoft Authenticator download
   prompt) -> Next -> **"Can't scan image?"** -> copy the **Secret key**.
3. Add that key to **your phone's authenticator app too** (so the phone and the NAS generate the same
   codes), enter the 6-digit code Microsoft asks for to finish adding the method.
4. Put the key in Portainer as `ICORSI_MS_TOTP_SECRET` (spaces / lowercase are fine).
5. Make it the **default** sign-in method, or at least make sure Microsoft offers **"Use a verification
   code"** when you pick "Sign in another way", otherwise you get `mfa_method_unavailable`.

**Set in Portainer** (read only by `icorsi-auth`; without all three it idles and answers requests with
an error, and the manual procedure below still applies):
`ICORSI_MS_USERNAME` (your SUPSI Microsoft e-mail), `ICORSI_MS_PASSWORD`, `ICORSI_MS_TOTP_SECRET`.

**Test it** (the first command types nothing and needs no credentials):
```
docker exec icorsi-auth python /app/icorsi_auth.py --probe   # reaches the Microsoft e-mail page through the allowlist? OK/FAIL
docker exec icorsi-auth python /app/icorsi_auth.py --once    # one real login now; prints a redacted summary only
```
`--once` (and the daemon) take an exclusive lock on `/state/login.lock`, so they never log in at the same
time; `--once` prints `REFUSED: login in progress` if the lock is held. `--once` expects `parts=3` (wstoken + privatetoken); `relaunched_launch_php=True` means Moodle lost the
return page through OIDC and `launch.php` had to be requested a second time. `parts=2` still works but
gives no privatetoken. It respects the rate limits below; `--once --force` skips the spacing (not the
daily cap). The image is ~890 MB (Chromium headless shell + Debian libraries).

**Rate limiting** (protects the Microsoft account from lockout):
- at least **30 min** between logins, doubling up to 6 h after consecutive failures;
- at most **6 logins per rolling 24 h** (persisted in `sidecar.json`, so restarts don't bypass it);
- a wrong TOTP code is retried **once** with the next 30 s window's code, then fails;
- on `bad_username`, `bad_password`, `bad_totp`, `account_locked`, `mfa_method_unavailable`,
  `oidc_rejected`, `interstitial:*` and `blocked_required_host:*` the sidecar **halts**, and it also
  halts after **2 consecutive failures of any kind once the credentials were submitted**
  (`repeated_failures:<code>`). The halt is **persisted** in `sidecar.json`, so a NAS reboot, OOM kill or
  redeploy does not resume submitting bad credentials. It is lifted automatically when any of the three
  `ICORSI_MS_*` values changes (a short, non-reversible fingerprint is stored to notice this), or manually
  with `docker exec icorsi-auth python /app/icorsi_auth.py --clear-halt` (use this when you fixed something
  on the Microsoft side). Then test with `... --once --force`;
- a password or code rejected by Microsoft is detected even if the error banner is not recognised: still
  being on the same step 5 s after Microsoft answered counts as a rejection;
- before typing the TOTP the code page is checked: if it is an SMS / voice code box the sidecar switches to
  "Sign in another way" and fails with `mfa_method_unavailable` rather than typing a TOTP into it;
- when it refuses, it answers `icorsi-sync` immediately and the Discord alert includes that reason.

**What the failure alerts mean** (Discord / `docker logs icorsi-auth`):

| Code | Meaning / fix |
|---|---|
| `bad_username` | Microsoft doesn't know `ICORSI_MS_USERNAME` (use the full SUPSI e-mail). Halts. |
| `bad_password` | Wrong `ICORSI_MS_PASSWORD` (or it was changed). Halts. |
| `bad_totp` | Code rejected twice: wrong `ICORSI_MS_TOTP_SECRET`, or the NAS clock is off. Halts. |
| `account_locked` | Microsoft smart-lockout. Wait / unlock, then `--clear-halt`. Halts. |
| `mfa_method_unavailable` | No "verification code" option offered; see step 5 above. Halts. |
| `interstitial:<page-id>` | Microsoft wants something (MFA registration, password change, consent). Sign in once in a browser, then `--clear-halt`. Halts. |
| `oidc_rejected` | Microsoft accepted, iCorsi bounced back to its login form. Halts. |
| `blocked_required_host:<host>` | The allowlist blocked a host the login needs; the sidecar's host list needs an update. Halts. |
| `repeated_failures:<code>` | Two consecutive failures after the credentials were sent (e.g. `timeout`); halted to protect the account. Check `docker logs icorsi-auth`, then `--clear-halt`. |
| `nav_off_allowlist` | A redirect left the allowlist; attempt aborted (no halt, backs off). |
| `timeout`, `no_login_redirect`, `no_token_redirect`, `unparseable_token_blob`, `network_error`, `browser_error`, `unexpected_session` (`launch.php` answered without a login), `unexpected_page` (stuck on an unexpected host/path), `playwright_missing` | Transient / site changed; retried with backoff (halts if it happens twice in a row after the credentials were sent). Persistent `no_token_redirect` means `launch.php` no longer returns the app redirect. |
| `internal error: <ExceptionName>` | Unexpected exception inside the sidecar; counted as a submitted attempt. The details are in `docker logs icorsi-auth`. |

**How to tell it worked:** `docker logs icorsi-sync` shows `requested fresh login from icorsi-auth sidecar`
followed by `fresh login obtained via icorsi-auth` and `authenticated (userid=...)`. With the sidecar in
place `ICORSI_TOKEN` / `ICORSI_PRIVATETOKEN` / `ICORSI_SESSION_COOKIE` are no longer needed: if there is
no token at all, `icorsi-sync` bootstraps straight from the sidecar.

The manual capture below is now only a **fallback** (e.g. Microsoft changed its login pages, an
`interstitial`, lost authenticator).

---

## Get your Moodle credentials (once)

You need three things, and you can grab all of them in one go from the `launch.php` redirect.

**The order of operations matters and is the #1 thing to get right:** you must visit the
`launch.php` URL **while logged out**, so that visiting it *is* what triggers your login/SSO -
the resulting page is the immediate post-login relaunch, which is what makes Moodle include the
privatetoken. If you log in first and *then* navigate to `launch.php` in a separate step (even in
the same private window), you will reliably get only 2 of the 3 parts (no privatetoken) - this is
documented, reproducible Moodle behaviour
(`public/admin/tool/mobile/launch.php`: the privatetoken is omitted unless
`$SESSION->justloggedin` is set on that exact request), **not** a sign that anything is broken or
that your account is restricted. Getting the steps in the wrong order is the most likely
explanation if you only ever see 2 parts - try the correct order below before assuming you need
the `ICORSI_SESSION_COOKIE` fallback further down.

1. Open a **private/incognito** browser window. **Do not log in yet.**
2. Open DevTools → **Network** tab → tick **Preserve log**.
3. Navigate DIRECTLY to:
   `https://<your-moodle>/admin/tool/mobile/launch.php?service=moodle_mobile_app&passport=1&urlscheme=moodlemobile`
   This bounces you through the normal login/SSO flow. Complete it.
4. Once logged in, you land back on `launch.php` and get an "open app" dialog - **Cancel** it.
5. In the Network tab, click the (last) `launch.php` row → **Response Headers → `location`** →
   copy what's after `token=`.
6. Decode it: `echo '<that>' | base64 -d`. You should get three `:::`-separated parts:
   `signature:::wstoken:::privatetoken`.
   - **`ICORSI_TOKEN`** = the 2nd part (the wstoken).
   - **`ICORSI_PRIVATETOKEN`** = the 3rd part (needed for headless renewal).
   - If you only get 2 parts, double check you truly started logged-out on this exact URL (not a
     leftover session from a previous visit) before falling back to `ICORSI_SESSION_COOKIE` below.
7. **`ICORSI_USERID`** = your numeric Moodle user id (from your profile URL `…/user/profile.php?id=`).
   It's optional - the tool auto-discovers it on the first successful run - but seeding it lets
   renewal work even if the very first token is already expired.

Set these three once in Portainer / `.env`; you won't need to touch them again unless the
container was offline long enough for the token to fully lapse.

> **If you genuinely can't get a privatetoken even with the correct logged-out-first order**
> (possible causes: a `moodle/site:config`-holding account - `launch.php` withholds the
> privatetoken unconditionally for those; or the site's reverse proxy/CDN not setting things up
> for Moodle's `is_https()` check to pass - both are server-side and not fixable from here) -
> there's a second, fully headless renewal path that doesn't need a privatetoken at all: it slides
> a saved Moodle **session** forward instead. Set **`ICORSI_SESSION_COOKIE`** instead of
> `ICORSI_PRIVATETOKEN`:
> 1. While logged into iCorsi in that same browser, open DevTools → **Application** (Chrome)
>    or **Storage** (Firefox) → **Cookies** → `https://www.icorsi.ch`.
> 2. Find the session cookie - usually named **`MoodleSession`**, but some installs suffix it
>    per-instance (e.g. SUPSI's icorsi.ch uses `MoodleSessionelabm2`) - copy its **Value**.
> 3. Set `ICORSI_SESSION_COOKIE=<cookie name>=<value>` (e.g. `MoodleSessionelabm2=abc123...`),
>    or just the bare value if the name really is `MoodleSession`.
>
> Trade-off vs. the privatetoken path: a Moodle session is generally capped at a shorter idle
> timeout (commonly hours, vs. the wstoken's ~2-day lifetime), so this path is more sensitive to
> the container being down for a while. `keep_alive()` touching it every `SYNC_INTERVAL_SECONDS`
> (6h default) is what's expected to keep it alive indefinitely under normal operation.
> With `ICORSI_TOKEN` + `ICORSI_SESSION_COOKIE` + `ICORSI_USERID` set, renewal works exactly
> the same way (headless, every run) - it just refreshes the session instead of using a
> privatetoken. The one difference: the session is what's alive, so the container being
> offline for longer than the site's session timeout (commonly 8h, not the ~2 day token
> lifetime) can lapse it - if that happens you're back to capturing a fresh
> `ICORSI_SESSION_COOKIE` the same way.

---

## Settings (environment variables)

Set these where you run the container (e.g. Portainer stack env). Secrets stay here, never in git.

| Variable | What it is |
|---|---|
| `ICORSI_TOKEN` | your Moodle token (secret, **bootstrap only** - seeds `/data/token.json` once) |
| `ICORSI_PRIVATETOKEN` | your Moodle private token (secret, **bootstrap only**) - enables headless auto-renewal |
| `ICORSI_USERID` | your numeric Moodle user id (optional; auto-discovered on first run) |
| `OPENCLOUD_WEBDAV_URL` | OpenCloud spaces WebDAV URL, e.g. `http://opencloud:9200/dav/spaces/<space-id>` (`<space-id>` is `<storage-uuid>$<node-uuid>`) |
| `OPENCLOUD_USER` / `OPENCLOUD_APP_PASSWORD` | OpenCloud login - use an **app password** (secret) |
| `OPENCLOUD_HOST_HEADER` | optional trusted domain to send as `Host` when hitting the container directly, e.g. `opencloud.nicolkrit.ch` - only needed if direct requests are rejected |
| `OPENCLOUD_BASE_PATH` | base folder (relative to the space root) the `courses.json` paths are relative to |
| `ICORSI_MS_USERNAME` / `ICORSI_MS_PASSWORD` / `ICORSI_MS_TOTP_SECRET` | SUPSI Microsoft e-mail, password and authenticator TOTP secret for automatic re-login - secrets, read **only** by the `icorsi-auth` container; optional but strongly recommended (see the security trade-off above) |
| `PUID` / `PGID` | host user/group the container drops to; must own the mounted `/data` dir (default `1000`/`1000`) |
| `DISCORD_WEBHOOK_URL` | optional - get notified of new files / new courses / renewal trouble / problems |
| `HEARTBEAT_URL` | optional - GET after each successful run (uptime-kuma / healthchecks.io push URL) |
| `VOLUME_CONFIG` | host storage base for the bind-mounts; data at `${VOLUME_CONFIG}/icorsi-sync/data`, sync/auth handoff at `${VOLUME_CONFIG}/icorsi-sync/auth` (e.g. `/volume2/docker`) |

Optional toggles (sensible defaults, see `.env.example`): `SUBFOLDER` (`_icorsi`),
`INCLUDE_URL_LINKS`, `SAVE_SECTION_INFO`, `SAVE_FORUMS`, `EXCLUDE_MODULES`,
`ICORSI_CONCURRENCY` (parallel transfers per course, default 4),
`SYNC_INTERVAL_SECONDS` (default 6h), `RECON_MAX_PASSES` (default 5), `DRY_RUN`, and:

- **`PRUNE_ORPHANS`** (default `false`) - when `true`, files inside a course's `_icorsi/` that
  are no longer part of the course (renamed / moved / removed on iCorsi) are **deleted**, so you
  always have exactly **one current copy**. Strictly limited to `_icorsi/`, and only runs for a
  course that fetched successfully with **0 missing files**. Deletions go to OpenCloud's **trash**
  (recoverable), so they still use quota until you empty it.

**Reliability:** each file download/upload is retried on transient errors, and after uploading
the tool re-checks what's actually in OpenCloud and re-fetches anything still missing - looping
until nothing is missing (bounded by `RECON_MAX_PASSES`). Anything it truly can't get is
reported (`⚠️ missing`) and retried on the next scheduled run. It never deletes your own files.

**Tip:** set `DRY_RUN=true` for the first run - it lists what it *would* download and writes
nothing. When the log looks right, set it back to `false`.

---

## Troubleshooting

**First, check whether it's actually broken right now** - don't assume from an old Discord
message alone, since alerts repeat daily while a problem persists (see above) and could be
describing something already fixed if you changed something since:
- `docker logs icorsi-sync --tail 50` - look for the most recent `=== run start ===` block and
  what happened after it.
- Docker health status (`docker inspect icorsi-sync` / the Portainer UI) - `unhealthy` means
  `state.json`'s `last_run` is older than `2 × SYNC_INTERVAL_SECONDS` (stale runs, i.e. it's
  actually failing, not just quiet). It self-clears within `start_period` (15m) of a real
  successful run - no manual action needed once the underlying problem is fixed.

**Discord alert: `no Moodle token available`** - `token.json` is missing/corrupt AND
`ICORSI_TOKEN` isn't set either. Set `ICORSI_TOKEN` (+ `ICORSI_PRIVATETOKEN` or
`ICORSI_SESSION_COOKIE`, + `ICORSI_USERID`) in Portainer and restart.

**Discord alert: `the Moodle token expired and automatic renewal failed`** - the no-sidecar case
(`/auth` not mounted): both the wstoken and the stored session are dead; recovery must be a fresh
manual credential capture (see below), no env var already in place will fix this on its own even if
they look correct - the *values* are dead, not just missing.

**Discord alert: `automatic renewal AND automatic re-login (icorsi-auth) failed: <why>`** - the sidecar
was asked for a fresh login and could not deliver one. `<why>` is a code from the failure table in
"Automatic re-login" (e.g. `halted after bad_password: ...`); fix that cause first, and use the manual
capture below only if the sidecar cannot be fixed.

**Discord alert: `Moodle rejected the site_info check (<errorcode>)`** - something other than a
dead token (e.g. `accessexception`) is rejecting the pre-flight API call. Usually transient/
Moodle-side (a maintenance window, a temporarily disabled web service) - if it clears on its own
within a day you don't need to do anything. If it's still alerting after a day, treat it the same
as a dead token below.

**Discord alert: `PROACTIVE token renewal is failing`** - the current token still works (sync is
still running fine) but the *renewal* mechanism itself is broken - fix it before the token
actually expires (~2 days out) to avoid a hard stop. Check the same recovery steps below at your
convenience, not urgently.

### Full manual recovery procedure (dead token / dead renewal) - fallback when automatic re-login fails

1. **Capture fresh credentials - get the order exactly right, this is the part most likely to go
   wrong:**
   1. Open a **private/incognito** browser window. **Do not log into iCorsi yet.**
   2. DevTools → **Network** tab → tick **Preserve log**.
   3. Navigate DIRECTLY to (this is the one and only URL you should visit first in this window):
      `https://www.icorsi.ch/admin/tool/mobile/launch.php?service=moodle_mobile_app&passport=1&urlscheme=moodlemobile`
   4. This bounces you into the login/SSO flow - complete it normally.
   5. You land back on `launch.php` - **Cancel** the "open app?" dialog.
   6. Network tab → click the (last) `launch.php` request → **Response Headers** → `location` →
      copy everything after `token=`.
   7. Decode: `echo '<that>' | base64 -d` → `signature:::wstoken:::privatetoken` (or just
      `signature:::wstoken` - see below).
   - **If you log in first and visit `launch.php` afterward (a second tab, a bookmark, typing the
     URL after already being logged in) you will reliably get only `signature:::wstoken` - 2
     parts, no privatetoken.** This is normal, reproducible Moodle behavior tied to
     `$SESSION->justloggedin`, not a broken account or a bug - redo it in the exact order above
     (logged out → visit the URL → THEN log in) before concluding you can't get a privatetoken.
     Confirmed twice in this project: the wrong order gave 2 parts both times; doing it in the
     right order gave 3 parts on the very next try, same account.
2. **If you got 3 parts:**
   `ICORSI_TOKEN` = 2nd part, `ICORSI_PRIVATETOKEN` = 3rd part. Set both in Portainer.
3. **If you only ever get 2 parts even with the order right** (rare - would mean either a
   `moodle/site:config`-holding account, which `launch.php` withholds the privatetoken from
   unconditionally, or the site's reverse proxy not satisfying Moodle's `is_https()` check -
   both server-side, not fixable from your end): use the `ICORSI_SESSION_COOKIE` fallback
   instead - see "Get your Moodle credentials" above for how to capture it from the same browser
   session (DevTools → Application/Storage → Cookies → the site's Moodle session cookie, which
   may be named exactly `MoodleSession` or suffixed per-install, e.g. SUPSI's icorsi.ch uses
   `MoodleSessionelabm2` - always check the actual cookie name, don't assume).
4. **`ICORSI_USERID`** - unchanged, no need to recapture (it's your numeric Moodle user id, not
   part of the token blob).
5. Set the values from step 2 and/or 3 (plus `ICORSI_USERID`) in the Portainer stack's
   environment.
6. **Delete `/data/token.json`** before/while restarting - the env vars are bootstrap-only and get
   silently ignored as long as `token.json` still has a (dead) `wstoken` in it. From a shell with
   access to the container: `docker exec icorsi-sync rm -f /data/token.json`. Then restart/
   redeploy the stack.
7. Watch `docker logs icorsi-sync -f` for `token bootstrapped from env` and a successful
   `authenticated (userid=...)` line. Docker health should flip back to healthy within ~15-20
   minutes of the first successful run.

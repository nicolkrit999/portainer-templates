# icorsi-sync

Automatically download your **Moodle / iCorsi** course material into **ownCloud**.

It logs into Moodle's API with a personal token, looks at each course you choose, and
copies the material into ownCloud - keeping the **same structure and order** the course uses.
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

It maps a **course ID** to a **folder** (relative to `OWNCLOUD_BASE_PATH`):

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
the current token still works** - so you can fix it *before* sync ever stops. It doesn't spam:
one alert per problem (after two consecutive failures, to skip transient blips), and it goes
quiet again once renewal recovers.

The **only** way it hard-fails: the container is down for longer than ~2 days *across* an
expiry. Then the stored token is dead and can't renew itself - you get a Discord alert; with
the env vars still set, restarting the container re-bootstraps from them.

## Get your Moodle credentials (once)

You need three things, and you can grab all of them in one go from the `launch.php` redirect:

1. Open a **private/incognito** browser window and log into your Moodle site.
2. Open DevTools → **Network** tab → tick **Preserve log**.
3. Go to (same tab): `https://<your-moodle>/admin/tool/mobile/launch.php?service=moodle_mobile_app&passport=1&urlscheme=moodlemobile`
   and **Cancel** the "open app" dialog.
4. Click the `launch.php` row → **Response Headers → `location`** → copy what's after `token=`.
5. Decode it: `echo '<that>' | base64 -d`. You'll get up to three `:::`-separated parts:
   `signature:::wstoken:::privatetoken`.
   - **`ICORSI_TOKEN`** = the 2nd part (the wstoken).
   - **`ICORSI_PRIVATETOKEN`** = the 3rd part (needed for headless renewal - do the login in
     **incognito** so the response includes it).
6. **`ICORSI_USERID`** = your numeric Moodle user id (from your profile URL `…/user/profile.php?id=`).
   It's optional - the tool auto-discovers it on the first successful run - but seeding it lets
   renewal work even if the very first token is already expired.

Set these three once in Portainer / `.env`; you won't need to touch them again unless the
container was offline long enough for the token to fully lapse.

---

## Settings (environment variables)

Set these where you run the container (e.g. Portainer stack env). Secrets stay here, never in git.

| Variable | What it is |
|---|---|
| `ICORSI_TOKEN` | your Moodle token (secret, **bootstrap only** - seeds `/data/token.json` once) |
| `ICORSI_PRIVATETOKEN` | your Moodle private token (secret, **bootstrap only**) - enables headless auto-renewal |
| `ICORSI_USERID` | your numeric Moodle user id (optional; auto-discovered on first run) |
| `OWNCLOUD_WEBDAV_URL` | ownCloud WebDAV URL, e.g. `http://owncloud:8080/remote.php/dav/files/<user>` |
| `OWNCLOUD_USER` / `OWNCLOUD_APP_PASSWORD` | ownCloud login - use an **app password** (secret) |
| `OWNCLOUD_HOST_HEADER` | trusted domain to send as `Host` when hitting the container directly (else ownCloud returns HTTP 400), e.g. `owncloud.nicolkrit.ch` |
| `OWNCLOUD_BASE_PATH` | base folder the `courses.json` paths are relative to |
| `PUID` / `PGID` | host user/group the container drops to; must own the mounted `/data` dir (default `1000`/`1000`) |
| `DISCORD_WEBHOOK_URL` | optional - get notified of new files / new courses / renewal trouble / problems |
| `HEARTBEAT_URL` | optional - GET after each successful run (uptime-kuma / healthchecks.io push URL) |
| `VOLUME_CONFIG` | host storage base for the data bind-mount; data lives at `${VOLUME_CONFIG}/icorsi-sync/data` (e.g. `/volume2/docker`) |

Optional toggles (sensible defaults, see `.env.example`): `SUBFOLDER` (`_icorsi`),
`INCLUDE_URL_LINKS`, `SAVE_SECTION_INFO`, `SAVE_FORUMS`, `EXCLUDE_MODULES`,
`ICORSI_CONCURRENCY` (parallel transfers per course, default 4),
`SYNC_INTERVAL_SECONDS` (default 6h), `RECON_MAX_PASSES` (default 5), `DRY_RUN`, and:

- **`PRUNE_ORPHANS`** (default `false`) - when `true`, files inside a course's `_icorsi/` that
  are no longer part of the course (renamed / moved / removed on iCorsi) are **deleted**, so you
  always have exactly **one current copy**. Strictly limited to `_icorsi/`, and only runs for a
  course that fetched successfully with **0 missing files**. Deletions go to ownCloud's **trash**
  (recoverable), so they still use quota until you empty it.

**Reliability:** each file download/upload is retried on transient errors, and after uploading
the tool re-checks what's actually in ownCloud and re-fetches anything still missing - looping
until nothing is missing (bounded by `RECON_MAX_PASSES`). Anything it truly can't get is
reported (`⚠️ missing`) and retried on the next scheduled run. It never deletes your own files.

**Tip:** set `DRY_RUN=true` for the first run - it lists what it *would* download and writes
nothing. When the log looks right, set it back to `false`.

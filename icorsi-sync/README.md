# icorsi-sync

Automatically download your **Moodle / iCorsi** course material into **ownCloud**.

It logs into Moodle's API with a personal token, looks at each course you choose, and
copies the material into ownCloud — keeping the same structure the course uses. It runs
on a schedule, only fetches what's new or changed, and never deletes anything.

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
never mixes with your own notes:

```
<your course folder>/_icorsi/
├── <section name>/<file.pdf>              a single file
├── <section name>/<folder>/<file...>      a folder (with its subfolders kept)
├── <section name>/<link>.url.txt          an external link
├── <section name>/_info.md                text written on the page
└── _annunci/<date> <title>.md             announcements
```

---

## The one thing you'll edit: `courses.json`

This file decides **which courses to download and where to put them**. It is *not* in this
repo (it's personal) — it lives next to the running container, in the data folder you mount
(e.g. `/volume2/docker/icorsi-sync/data/courses.json`). See `courses.example.json` for the shape.

It maps a **course ID** to a **folder** (relative to `OWNCLOUD_BASE_PATH`):

```json
{
  "22233": "English",
  "23109": "Databases/2025-2026",
  "18590": null
}
```

- **Course ID** — the number in the course URL: `…/course/view.php?id=`**`22233`**.
- **Folder** — where its `_icorsi/` goes. Subfolders are fine (`Databases/2025-2026`).
- **`null`** — skip this course (kept here for reference, but never downloaded, no warnings).

To add a course: copy its ID from the URL, add a line, restart the container. That's it —
the folder is created automatically. Editing this file needs no rebuild.

> If you enrol in a new course you haven't listed, the tool just notifies you (optionally on
> Discord) so you can add it — it won't download anything until you do.

---

## Get your Moodle token (once)

1. Log into your Moodle site in a browser.
2. Open DevTools → **Network** tab → tick **Preserve log**.
3. Go to (same tab): `https://<your-moodle>/admin/tool/mobile/launch.php?service=moodle_mobile_app&passport=1&urlscheme=moodlemobile`
   and **Cancel** the "open app" dialog.
4. Click the `launch.php` row → **Response Headers → `location`** → copy what's after `token=`.
5. Decode it: `echo '<that>' | base64 -d` → your token is the part after `:::`.

The token is independent of your browser and lasts until you revoke it (or the site expires
it). If it ever stops working, the tool tells you — just repeat these steps.

---

## Settings (environment variables)

Set these where you run the container (e.g. Portainer stack env). Secrets stay here, never in git.

| Variable | What it is |
|---|---|
| `ICORSI_TOKEN` | your Moodle token (secret) |
| `OWNCLOUD_WEBDAV_URL` | ownCloud WebDAV URL, e.g. `http://owncloud:8080/remote.php/dav/files/<user>` |
| `OWNCLOUD_USER` / `OWNCLOUD_APP_PASSWORD` | ownCloud login — use an **app password** (secret) |
| `OWNCLOUD_HOST_HEADER` | trusted domain to send as `Host` when hitting the container directly (else ownCloud returns HTTP 400), e.g. `owncloud.nicolkrit.ch` |
| `OWNCLOUD_BASE_PATH` | base folder the `courses.json` paths are relative to |
| `DISCORD_WEBHOOK_URL` | optional — get notified of new files / new courses / problems |

Optional toggles (sensible defaults, see `.env.example`): `SUBFOLDER` (`_icorsi`),
`INCLUDE_URL_LINKS`, `SAVE_SECTION_INFO`, `SAVE_FORUMS`, `EXCLUDE_MODULES`,
`SYNC_INTERVAL_SECONDS` (default 6h), `DRY_RUN`.

**Tip:** set `DRY_RUN=true` for the first run — it lists what it *would* download and writes
nothing. When the log looks right, set it back to `false`.

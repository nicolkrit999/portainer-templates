#!/usr/bin/env python3
"""
icorsi-sync — mirror SUPSI iCorsi (Moodle) course material into ownCloud via WebDAV.

Pure stdlib (no pip deps). Talks to Moodle Web Services with a long-lived mobile
token, walks each mapped course, and uploads `folder`/`resource` files (and,
optionally, `url` links as .txt) into ownCloud, mirroring the course structure
under a per-subject `_icorsi/` subfolder.

Design notes:
- ALLOWLIST: only course IDs present in courses.json (with a non-null path) are synced.
- AUTO-DISCOVERY only *informs*: new enrolled-but-unmapped courses -> notify once.
- UNENROLL handling: a mapped course missing from your enrolment list -> notify once,
  keep files, skip from then on.
- SELF-HEALING: every run reconciles against what is actually present in ownCloud
  (size check), re-downloading anything missing/partial/updated (Moodle timemodified).
- NEVER deletes or moves anything. `_icorsi/` is a faithful mirror.
"""

import os
import re
import sys
import json
import time
import html
import base64
import hashlib
import logging
import tempfile
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

# --------------------------------------------------------------------------- #
# Config (from env)
# --------------------------------------------------------------------------- #
def env(key, default=None, required=False):
    v = os.environ.get(key, default)
    if required and not v:
        sys.exit(f"FATAL: required env var {key} is not set")
    return v

def env_bool(key, default=False):
    return str(os.environ.get(key, str(default))).strip().lower() in ("1", "true", "yes", "on")

DRY_RUN           = env_bool("DRY_RUN", False)

ICORSI_BASE   = env("ICORSI_BASE_URL", "https://www.icorsi.ch").rstrip("/")
TOKEN         = env("ICORSI_TOKEN", required=True)
WS_ENDPOINT   = f"{ICORSI_BASE}/webservice/rest/server.php"
ICORSI_HOST   = urllib.parse.urlsplit(ICORSI_BASE).netloc.lower()

# ownCloud creds aren't needed for a dry run (nothing is written/listed)
DAV_URL       = (env("OWNCLOUD_WEBDAV_URL", "", required=not DRY_RUN) or "").rstrip("/")
DAV_USER      = env("OWNCLOUD_USER", "", required=not DRY_RUN)
DAV_PASS      = env("OWNCLOUD_APP_PASSWORD", "", required=not DRY_RUN)
# When reaching the ownCloud container directly (http://owncloud:8080), send this as the
# Host header so ownCloud's trusted-domain check passes (otherwise it replies HTTP 400).
DAV_HOST_HEADER = env("OWNCLOUD_HOST_HEADER", "")                       # e.g. owncloud.nicolkrit.ch
BASE_PATH     = env("OWNCLOUD_BASE_PATH", "").strip("/")               # e.g. University/Supsi
SUBFOLDER     = env("SUBFOLDER", "_icorsi").strip("/")

INCLUDE_URL_LINKS = env_bool("INCLUDE_URL_LINKS", True)
RUN_ON_START      = env_bool("RUN_ON_START", True)

# By default, download files from EVERY module type. A static file GET never starts a
# quiz attempt, submits, or marks an activity viewed — the tool only reads metadata and
# fetches files — so there's no safety reason to exclude anything (e.g. a PDF inside a
# quiz intro is fetched too). EXCLUDE_MODULES is an optional opt-in filter; empty = all.
EXCLUDE_MODULES = set(m.strip().lower() for m in env("EXCLUDE_MODULES", "").split(",") if m.strip())

# Also capture non-file text content:
SAVE_SECTION_INFO = env_bool("SAVE_SECTION_INFO", True)   # labels + section intros -> _info.md
SAVE_FORUMS       = env_bool("SAVE_FORUMS", True)          # forum/announcement posts -> .md (read-only)
INTERVAL          = int(env("SYNC_INTERVAL_SECONDS", "21600"))          # 6h
LOOP              = INTERVAL > 0
DISCORD_WEBHOOK   = env("DISCORD_WEBHOOK_URL", "")
HTTP_TIMEOUT      = int(env("HTTP_TIMEOUT", "60"))
HTTP_RETRIES      = int(env("HTTP_RETRIES", "3"))

STATE_DIR     = env("STATE_DIR", "/data")
STATE_FILE    = os.path.join(STATE_DIR, "state.json")

def _resolve_courses_file():
    """Real map is the private /data/courses.json. Fall back to a privately-baked
    /app/courses.json if someone chooses that. The committed courses.example.json
    is a template only and is never auto-loaded."""
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in ("/data/courses.json", os.path.join(here, "courses.json")):
        if os.path.exists(cand):
            return cand
    return None

UA = "icorsi-sync/1.0 (+https://github.com)"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("icorsi-sync")


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def http(url, method="GET", data=None, headers=None, timeout=HTTP_TIMEOUT):
    """Single HTTP request. Returns (status, body_bytes, resp_headers)."""
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", UA)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers or {})


def http_retry(url, **kw):
    """HTTP with retries on network errors / 5xx."""
    last = None
    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            status, body, hdrs = http(url, **kw)
            if status >= 500:
                last = f"HTTP {status}"
                raise urllib.error.URLError(last)
            return status, body, hdrs
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = str(e)
            if attempt < HTTP_RETRIES:
                time.sleep(2 * attempt)
    raise RuntimeError(f"request failed after {HTTP_RETRIES} attempts ({url}): {last}")


def basic_auth_header(user, pw):
    raw = f"{user}:{pw}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


def clean_name(name, fallback="untitled"):
    """Sanitize a single path segment (NOT a multi-segment path)."""
    if name is None:
        return fallback
    s = html.unescape(str(name))
    s = s.replace("/", "-").replace("\\", "-")
    s = "".join(ch for ch in s if ch >= " ")          # drop control chars
    s = s.strip().rstrip(". ")                          # trailing dot/space unsafe on some FS
    return s or fallback


def clean_path(p):
    """Sanitize a Moodle 'filepath' (may contain real '/' separators)."""
    parts = [clean_name(seg) for seg in p.split("/") if seg.strip()]
    return parts


# --------------------------------------------------------------------------- #
# Moodle Web Services
# --------------------------------------------------------------------------- #
class MoodleError(Exception):
    def __init__(self, fn, code, msg):
        self.fn, self.code, self.msg = fn, code, msg
        super().__init__(f"{fn}: {code} - {msg}")


# SAFETY GUARD #1 (function allowlist, default-deny): the ONLY Moodle WS functions
# this tool may ever call. All are read-only. Anything not listed — known, unknown, or
# added by a future Moodle version (e.g. mod_quiz_start_attempt, mod_assign_save_submission,
# mod_attendance_*, any *_save_* / *_view_*) — is refused here. So writes are impossible.
WS_READONLY_ALLOWED = {
    "core_webservice_get_site_info",
    "core_enrol_get_users_courses",
    "core_course_get_contents",
    "mod_forum_get_forums_by_courses",
    "mod_forum_get_forum_discussions",
}

# SAFETY GUARD #2 (transport): EVERY request to iCorsi passes through _assert_icorsi_get.
# It enforces GET-only, the iCorsi host only, and only the WS endpoint or the static file
# handler. This blocks any POST and any "action" URL (startattempt.php, assignment submit,
# attendance marking, /mod/*/view.php, ...) from ever being sent — even via a bug.
_ICORSI_ALLOWED_PATHS = (
    "/webservice/rest/server.php",
    "/pluginfile.php",
    "/webservice/pluginfile.php",
    "/tokenpluginfile.php",
)


def _assert_icorsi_get(url, method="GET"):
    u = urllib.parse.urlsplit(url)
    if u.netloc.lower() != ICORSI_HOST:
        raise RuntimeError(f"SAFETY: refusing request to unexpected host {u.netloc!r}")
    if method != "GET":
        raise RuntimeError(f"SAFETY: only GET is allowed to iCorsi (got {method})")
    if not any(u.path == p or u.path.startswith(p + "/") for p in _ICORSI_ALLOWED_PATHS):
        raise RuntimeError(f"SAFETY: iCorsi path not allowed: {u.path!r}")


def ws(fn, **params):
    if fn not in WS_READONLY_ALLOWED:
        raise RuntimeError(f"SAFETY: refusing to call non-allowlisted WS function {fn!r}")
    q = {"wstoken": TOKEN, "wsfunction": fn, "moodlewsrestformat": "json"}
    q.update(params)
    url = WS_ENDPOINT + "?" + urllib.parse.urlencode(q, doseq=True)
    _assert_icorsi_get(url, "GET")
    status, body, _ = http_retry(url)
    data = json.loads(body.decode("utf-8"))
    if isinstance(data, dict) and data.get("exception"):
        raise MoodleError(fn, data.get("errorcode"), data.get("message"))
    return data


def file_download_url(fileurl):
    """Append the WS token to a pluginfile URL."""
    parts = urllib.parse.urlsplit(fileurl)
    qs = dict(urllib.parse.parse_qsl(parts.query))
    qs["token"] = TOKEN
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(qs), parts.fragment)
    )


# --------------------------------------------------------------------------- #
# WebDAV (ownCloud)
# --------------------------------------------------------------------------- #
class WebDav:
    def __init__(self, base_url, user, pw, host_header=""):
        self.base = base_url.rstrip("/")
        self.hdr = basic_auth_header(user, pw)
        # ownCloud rejects requests whose Host isn't a trusted domain with HTTP 400.
        # When we reach the container directly (http://owncloud:8080), send the public
        # trusted hostname as Host so the request is accepted.
        if host_header:
            self.hdr["Host"] = host_header
        # path prefix of the dav root, e.g. /remote.php/dav/files/oc_admin
        self.root_path = urllib.parse.urlsplit(self.base).path.rstrip("/")
        self._ensured = set()

    def _abs(self, logical_path):
        enc = urllib.parse.quote(logical_path, safe="/")
        return f"{self.base}/{enc.lstrip('/')}"

    def ensure_dir(self, logical_path):
        """MKCOL each segment of logical_path (idempotent)."""
        logical_path = logical_path.strip("/")
        if not logical_path or logical_path in self._ensured:
            return
        segs = logical_path.split("/")
        cur = ""
        for seg in segs:
            cur = f"{cur}/{seg}" if cur else seg
            if cur in self._ensured:
                continue
            if DRY_RUN:
                self._ensured.add(cur)
                continue
            status, _, _ = http_retry(self._abs(cur), method="MKCOL", headers=self.hdr)
            # 201 created, 405 already exists -> both fine
            if status not in (201, 405, 301):
                log.warning("MKCOL %s -> HTTP %s", cur, status)
            self._ensured.add(cur)

    def list_files(self, logical_dir):
        """Recursively list files under logical_dir. Returns {logical_path: size}."""
        out = {}
        stack = [logical_dir.strip("/")]
        body = ('<?xml version="1.0"?>'
                '<d:propfind xmlns:d="DAV:"><d:prop>'
                '<d:resourcetype/><d:getcontentlength/></d:prop></d:propfind>')
        while stack:
            d = stack.pop()
            hdr = {**self.hdr, "Depth": "1", "Content-Type": "application/xml"}
            status, raw, _ = http_retry(self._abs(d), method="PROPFIND",
                                        data=body.encode(), headers=hdr)
            if status == 404:
                continue                      # dir doesn't exist yet
            if status != 207:
                log.warning("PROPFIND %s -> HTTP %s", d, status)
                continue
            for href, is_col, size in self._parse_multistatus(raw):
                rel = href
                if rel.strip("/") == d.strip("/"):
                    continue                  # the directory itself
                if is_col:
                    stack.append(rel)
                else:
                    out[rel] = size
        return out

    def _parse_multistatus(self, raw):
        ns = {"d": "DAV:"}
        root = ET.fromstring(raw)
        results = []
        for resp in root.findall("d:response", ns):
            href_el = resp.find("d:href", ns)
            if href_el is None or not href_el.text:
                continue
            path = urllib.parse.unquote(urllib.parse.urlsplit(href_el.text).path)
            if path.startswith(self.root_path):
                path = path[len(self.root_path):]
            path = path.strip("/")
            is_col = resp.find(".//d:resourcetype/d:collection", ns) is not None
            size_el = resp.find(".//d:getcontentlength", ns)
            size = int(size_el.text) if (size_el is not None and size_el.text and size_el.text.isdigit()) else 0
            results.append((path, is_col, size))
        return results

    def put_bytes(self, logical_path, data):
        parent = "/".join(logical_path.strip("/").split("/")[:-1])
        self.ensure_dir(parent)
        if DRY_RUN:
            return
        hdr = {**self.hdr, "Content-Type": "application/octet-stream"}
        status, _, _ = http_retry(self._abs(logical_path), method="PUT", data=data, headers=hdr)
        if status not in (200, 201, 204):
            raise RuntimeError(f"PUT {logical_path} -> HTTP {status}")

    def put_file(self, logical_path, fileobj, size):
        parent = "/".join(logical_path.strip("/").split("/")[:-1])
        self.ensure_dir(parent)
        if DRY_RUN:
            return
        hdr = {**self.hdr, "Content-Type": "application/octet-stream",
               "Content-Length": str(size)}
        req = urllib.request.Request(self._abs(logical_path), data=fileobj, method="PUT")
        for k, v in hdr.items():
            req.add_header(k, v)
        req.add_header("User-Agent", UA)
        with urllib.request.urlopen(req, timeout=max(HTTP_TIMEOUT, 300)) as r:
            if r.status not in (200, 201, 204):
                raise RuntimeError(f"PUT {logical_path} -> HTTP {r.status}")


# --------------------------------------------------------------------------- #
# Notifications (Discord webhook, optional)
# --------------------------------------------------------------------------- #
def notify(msg):
    log.info("NOTIFY: %s", msg)
    if not DISCORD_WEBHOOK:
        return
    try:
        data = json.dumps({"content": msg[:1900]}).encode()
        http(DISCORD_WEBHOOK, method="POST", data=data,
             headers={"Content-Type": "application/json"}, timeout=15)
    except Exception as e:
        log.warning("discord notify failed: %s", e)


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)


# --------------------------------------------------------------------------- #
# Core sync
# --------------------------------------------------------------------------- #
def build_expected(course_id, sections):
    """Return (files, links) for a course.
    files: list of dict {rel, fileurl, tm, size}
    links: list of dict {rel, content}
    'rel' is relative to the course's _icorsi base.
    """
    files, links = [], []
    for sec in sections:
        section = clean_name(sec.get("name") or f"section-{sec.get('section', 0)}", "General")
        for mod in sec.get("modules", []):
            modname = mod.get("modname")
            modtitle = clean_name(mod.get("name"), "module")
            if modname in EXCLUDE_MODULES:
                continue
            # url modules -> save the external link as a .txt
            if modname == "url":
                if not INCLUDE_URL_LINKS:
                    continue
                target = None
                for c in mod.get("contents", []):
                    if c.get("type") == "url" and c.get("fileurl"):
                        target = c.get("fileurl")
                        break
                if not target and mod.get("url"):
                    target = mod["url"]
                if target:
                    content = f"{html.unescape(mod.get('name','link'))}\n{target}\n"
                    links.append({"rel": f"{section}/{modtitle}.url.txt",
                                  "content": content.encode("utf-8")})
                continue
            # every other module type: download whatever real files it exposes.
            # (a static file GET has no side effects — see WS_READONLY_ALLOWED.)
            for c in mod.get("contents", []):
                if c.get("type") != "file":
                    continue
                fname = clean_name(c.get("filename"), "file")
                if modname == "resource":
                    rel_parts = [section, fname]
                else:
                    inner = clean_path(c.get("filepath", "/"))
                    rel_parts = [section, modtitle] + inner + [fname]
                files.append({
                    "rel": "/".join(rel_parts),
                    "fileurl": c.get("fileurl"),
                    "tm": int(c.get("timemodified", 0) or 0),
                    "size": int(c.get("filesize", 0) or 0),
                })
    return files, links


class _HTMLToText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out = []
        self._href = None

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.out.append("\n")
        elif tag == "li":
            self.out.append("\n- ")
        elif tag in ("p", "div", "tr", "h1", "h2", "h3", "h4", "ul", "ol"):
            self.out.append("\n")
        elif tag == "a":
            self._href = dict(attrs).get("href")

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            self.out.append(f" ({self._href})")
            self._href = None
        if tag in ("p", "div", "tr", "h1", "h2", "h3", "h4"):
            self.out.append("\n")

    def handle_data(self, data):
        self.out.append(data)


def html_to_text(h):
    """Best-effort HTML -> readable text/markdown (links kept inline as text (url))."""
    if not h:
        return ""
    p = _HTMLToText()
    try:
        p.feed(h)
        txt = "".join(p.out)
    except Exception:
        txt = re.sub(r"<[^>]+>", "", h)
    txt = html.unescape(txt).replace("\xa0", " ").replace("\r", "")
    txt = re.sub(r"[ \t]+\n", "\n", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()


def build_section_info(sections):
    """Aggregate each section's intro/summary + label text into one _info.md."""
    texts = []
    for sec in sections:
        section = clean_name(sec.get("name") or f"section-{sec.get('section', 0)}", "General")
        parts = []
        summ = html_to_text(sec.get("summary"))
        if summ:
            parts.append(summ)
        for mod in sec.get("modules", []):
            if mod.get("modname") == "label" and "label" not in EXCLUDE_MODULES:
                t = html_to_text(mod.get("description") or mod.get("name"))
                if t:
                    parts.append(t)
        if not parts:
            continue
        body = f"# {section}\n\n" + "\n\n---\n\n".join(parts) + "\n"
        texts.append({"rel": f"{section}/_info.md", "content": body.encode("utf-8"), "tm": 0})
    return texts


def fetch_forums(course_id):
    """Read-only: list forums + their discussions (announcements & posts) -> markdown.
    Uses only listing functions, so it does NOT mark anything as read."""
    texts, files = [], []
    forums = ws("mod_forum_get_forums_by_courses", **{"courseids[0]": course_id})
    for f in forums:
        fname = clean_name(f.get("name"), "forum")
        folder = "_annunci" if f.get("type") == "news" else f"_forum/{fname}"
        try:
            discs = ws("mod_forum_get_forum_discussions", forumid=f["id"]).get("discussions", [])
        except MoodleError as e:
            log.warning("forum %s discussions failed: %s", f.get("id"), e)
            continue
        for d in discs:
            ts = int(d.get("timemodified") or d.get("created") or 0)
            datestr = time.strftime("%Y-%m-%d", time.localtime(ts)) if ts else "0000-00-00"
            title = clean_name(d.get("name") or d.get("subject") or "post", "post")
            stem = f"{datestr} {title}"[:120].strip()
            body = html_to_text(d.get("message"))
            md = (f"# {html.unescape(d.get('name', ''))}\n\n"
                  f"- **Data:** {datestr}\n"
                  f"- **Autore:** {d.get('userfullname', '')}\n\n"
                  f"{body}\n")
            atts = d.get("attachments") or []
            if atts:
                md += "\n**Allegati:**\n" + "\n".join(f"- {a.get('filename')}" for a in atts) + "\n"
            texts.append({"rel": f"{folder}/{stem}.md", "content": md.encode("utf-8"), "tm": ts})
            for a in atts:
                if a.get("fileurl"):
                    files.append({"rel": f"{folder}/{stem}/{clean_name(a.get('filename'), 'file')}",
                                  "fileurl": a.get("fileurl"),
                                  "tm": int(a.get("timemodified", 0) or 0),
                                  "size": int(a.get("filesize", 0) or 0)})
    return texts, files


def download(fileurl):
    """Download a pluginfile to a temp file. Returns (path, size)."""
    url = file_download_url(fileurl)
    _assert_icorsi_get(url, "GET")
    tmp = tempfile.NamedTemporaryFile(delete=False)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=max(HTTP_TIMEOUT, 300)) as r:
            size = 0
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                tmp.write(chunk)
                size += len(chunk)
        tmp.close()
        return tmp.name, size
    except Exception:
        tmp.close()
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


def sync_course(dav, course_id, rel_folder, state):
    """Sync one course. Returns (downloaded, skipped, errors)."""
    base = "/".join(p for p in [BASE_PATH, rel_folder, SUBFOLDER] if p).strip("/")
    sections = ws("core_course_get_contents", courseid=course_id)
    files, links = build_expected(course_id, sections)

    texts = build_section_info(sections) if SAVE_SECTION_INFO else []
    if SAVE_FORUMS:
        try:
            ftexts, ffiles = fetch_forums(course_id)
            texts += ftexts
            files += ffiles
        except Exception as e:
            log.warning("forums for course %s skipped: %s", course_id, e)

    existing = {} if DRY_RUN else dav.list_files(base)
    fstate = state.setdefault("files", {})

    downloaded = skipped = errors = 0

    # regular files
    for f in files:
        logical = f"{base}/{f['rel']}"
        cur_size = existing.get(logical)
        prev = fstate.get(logical, {})
        up_to_date = (
            cur_size is not None
            and (f["size"] == 0 or cur_size == f["size"])
            and prev.get("tm", -1) >= f["tm"]
        )
        if up_to_date:
            skipped += 1
            continue
        if DRY_RUN:
            log.info("[dry] would download %s (%d B)", logical, f["size"])
            downloaded += 1
            continue
        try:
            path, size = download(f["fileurl"])
            try:
                with open(path, "rb") as fh:
                    dav.put_file(logical, fh, size)
            finally:
                os.unlink(path)
            fstate[logical] = {"tm": f["tm"], "size": size}
            downloaded += 1
            log.info("uploaded %s (%d B)", logical, size)
        except Exception as e:
            errors += 1
            log.error("failed %s: %s", logical, e)

    # url -> txt links
    for l in links:
        logical = f"{base}/{l['rel']}"
        if existing.get(logical) is not None and logical in fstate:
            skipped += 1
            continue
        if DRY_RUN:
            log.info("[dry] would write link %s", logical)
            downloaded += 1
            continue
        try:
            dav.put_bytes(logical, l["content"])
            fstate[logical] = {"tm": 0, "size": len(l["content"]), "link": True}
            downloaded += 1
        except Exception as e:
            errors += 1
            log.error("failed link %s: %s", logical, e)

    # generated text (section _info.md + forum/announcement .md) — dedup by content hash
    for t in texts:
        logical = f"{base}/{t['rel']}"
        digest = hashlib.md5(t["content"]).hexdigest()
        prev = fstate.get(logical, {})
        present = DRY_RUN or existing.get(logical) is not None
        if present and prev.get("md5") == digest:
            skipped += 1
            continue
        if DRY_RUN:
            log.info("[dry] would write %s", logical)
            downloaded += 1
            continue
        try:
            dav.put_bytes(logical, t["content"])
            fstate[logical] = {"tm": t.get("tm", 0), "size": len(t["content"]), "md5": digest}
            downloaded += 1
            log.info("wrote %s", logical)
        except Exception as e:
            errors += 1
            log.error("failed text %s: %s", logical, e)

    return downloaded, skipped, errors


def load_courses():
    path = _resolve_courses_file()
    if not path:
        sys.exit("FATAL: no course map found. Create /data/courses.json "
                 "(see courses.example.json for the format).")
    with open(path) as f:
        raw = json.load(f)
    # numeric course IDs only (ignores helper keys like "_comment").
    # value null/false/""/"skip" => explicitly skipped (silent, no "new course" ping).
    mapped, skipped = {}, set()
    for k, v in raw.items():
        if not str(k).isdigit():
            continue
        if v in (None, False, "", "skip"):
            skipped.add(str(k))
            continue
        mapped[str(k)] = str(v).strip("/")
    return mapped, skipped


def run_once(dav, state):
    log.info("=== run start (dry_run=%s) ===", DRY_RUN)
    try:
        info = ws("core_webservice_get_site_info")
    except MoodleError as e:
        if e.code == "invalidtoken":
            if not state.get("token_alerted"):
                notify("⚠️ icorsi-sync: token is invalid/expired. Re-mint it and update the "
                       "ICORSI_TOKEN env var in Portainer.")
                state["token_alerted"] = True
                save_state(state)
            log.error("invalid token, skipping run")
            return
        raise
    state["token_alerted"] = False
    userid = info["userid"]
    log.info("authenticated as %s (userid=%s)", info.get("fullname"), userid)

    enrolled = {str(c["id"]): c.get("fullname", "") for c in
                ws("core_enrol_get_users_courses", userid=userid)}
    mapped, skipped = load_courses()

    archived = set(state.get("archived_courses", []))
    known_unmapped = set(state.get("known_unmapped", []))

    # new enrolled course that is neither mapped nor explicitly skipped -> notify once
    for cid, name in enrolled.items():
        if cid in mapped or cid in skipped or cid in known_unmapped:
            continue
        notify(f"🆕 icorsi-sync: new enrolled course not mapped: {cid} — {name}\n"
               f"Add it to courses.json to start syncing (or set it to null to skip).")
        known_unmapped.add(cid)
    known_unmapped &= set(enrolled)               # forget ones now gone
    known_unmapped -= set(mapped)                 # forget ones now mapped
    known_unmapped -= skipped                     # forget ones now explicitly skipped

    total_dl = total_sk = total_err = 0
    changed_courses = []

    for cid, rel in mapped.items():
        if cid not in enrolled:
            if cid not in archived:
                notify(f"📦 icorsi-sync: course {cid} no longer in your enrolments "
                       f"(passed/unenrolled?). Keeping existing files, skipping from now on.")
                archived.add(cid)
            continue
        archived.discard(cid)                     # re-enrolled? resume
        try:
            dl, sk, err = sync_course(dav, cid, rel, state)
            total_dl += dl; total_sk += sk; total_err += err
            if dl or err:
                changed_courses.append(f"[{cid}] {enrolled[cid]}: +{dl}" + (f" ⚠️{err}" if err else ""))
            log.info("course %s (%s): %d new, %d ok, %d errors", cid, rel, dl, sk, err)
            save_state(state)                     # checkpoint per course
        except MoodleError as e:
            total_err += 1
            log.error("course %s api error: %s", cid, e)
        except Exception as e:
            total_err += 1
            log.error("course %s failed: %s", cid, e)

    state["archived_courses"] = sorted(archived)
    state["known_unmapped"] = sorted(known_unmapped)
    state["last_run"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_state(state)

    log.info("=== run done: %d downloaded, %d skipped, %d errors ===",
             total_dl, total_sk, total_err)
    if total_dl or total_err:
        summary = (f"✅ icorsi-sync: {total_dl} new file(s), {total_err} error(s).\n"
                   + "\n".join(changed_courses[:20]))
        notify(summary)


def main():
    log.info("icorsi-sync starting | base=%s | dav=%s | interval=%ss | dry_run=%s",
             BASE_PATH, DAV_URL, INTERVAL, DRY_RUN)
    dav = WebDav(DAV_URL, DAV_USER, DAV_PASS, DAV_HOST_HEADER)
    if not RUN_ON_START and LOOP:
        time.sleep(INTERVAL)
    while True:
        state = load_state()
        try:
            run_once(dav, state)
        except Exception as e:
            log.exception("run failed: %s", e)
            notify(f"❌ icorsi-sync run failed: {e}")
        if not LOOP:
            break
        log.info("sleeping %ss until next run", INTERVAL)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()

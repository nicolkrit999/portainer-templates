#!/usr/bin/env python3
"""
icorsi-sync — mirror SUPSI iCorsi (Moodle) course material into ownCloud via WebDAV.

Pure stdlib. Reads Moodle Web Services with a long-lived mobile token, walks each
mapped course, and uploads files (plus url links as .txt, section text and forum
posts as .md) into ownCloud under a per-subject `_icorsi/` subfolder, mirroring the
course's structure and order. Allowlist of courses (courses.json); auto-discovery
only notifies about new/unenrolled courses. Incremental, self-healing, read-only on
Moodle. Optional prune keeps exactly one current copy.
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
import unicodedata
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from html.parser import HTMLParser


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

DAV_URL       = (env("OWNCLOUD_WEBDAV_URL", "", required=not DRY_RUN) or "").rstrip("/")
DAV_USER      = env("OWNCLOUD_USER", "", required=not DRY_RUN)
DAV_PASS      = env("OWNCLOUD_APP_PASSWORD", "", required=not DRY_RUN)
# Sent as the Host header. Reaching the container directly (http://owncloud:8080) would
# otherwise fail ownCloud's trusted-domain check with HTTP 400.
DAV_HOST_HEADER = env("OWNCLOUD_HOST_HEADER", "")
BASE_PATH     = env("OWNCLOUD_BASE_PATH", "").strip("/")
SUBFOLDER     = env("SUBFOLDER", "_icorsi").strip("/")

INCLUDE_URL_LINKS = env_bool("INCLUDE_URL_LINKS", True)
RUN_ON_START      = env_bool("RUN_ON_START", True)
EXCLUDE_MODULES   = set(m.strip().lower() for m in env("EXCLUDE_MODULES", "").split(",") if m.strip())
SAVE_SECTION_INFO = env_bool("SAVE_SECTION_INFO", True)
SAVE_FORUMS       = env_bool("SAVE_FORUMS", True)
PRUNE_ORPHANS     = env_bool("PRUNE_ORPHANS", False)
RECON_MAX_PASSES  = int(env("RECON_MAX_PASSES", "5"))
INTERVAL          = int(env("SYNC_INTERVAL_SECONDS", "21600"))
LOOP              = INTERVAL > 0
DISCORD_WEBHOOK   = env("DISCORD_WEBHOOK_URL", "")
HTTP_TIMEOUT      = int(env("HTTP_TIMEOUT", "60"))
HTTP_RETRIES      = int(env("HTTP_RETRIES", "3"))

STATE_DIR     = env("STATE_DIR", "/data")
STATE_FILE    = os.path.join(STATE_DIR, "state.json")

def _resolve_courses_file():
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


def http(url, method="GET", data=None, headers=None, timeout=HTTP_TIMEOUT):
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


def retrying(label, fn):
    """Retry fn() on transient errors; HTTP 4xx are raised immediately (won't self-heal)."""
    last = None
    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            return fn()
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500:
                raise
            last = e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
        if attempt < HTTP_RETRIES:
            time.sleep(2 * attempt)
    raise RuntimeError(f"{label} failed after {HTTP_RETRIES} attempts: {last}")


def basic_auth_header(user, pw):
    raw = f"{user}:{pw}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


def nfc(s):
    """Canonical Unicode form. ownCloud stores/returns NFC; Moodle may send NFD. Normalizing
    both sides keeps the SAME file from looking like two different paths (which would cause
    endless re-upload and prune delete/recreate churn)."""
    return unicodedata.normalize("NFC", s)


def clean_name(name, fallback="untitled"):
    """Sanitize one path segment to a canonical (NFC) form; collapses any '/' in the name."""
    if name is None:
        return fallback
    s = html.unescape(str(name))
    s = s.replace("/", "-").replace("\\", "-")
    s = "".join(ch for ch in s if ch >= " ")
    s = nfc(s).strip().rstrip(". ")
    return s or fallback


def clean_path(p):
    """Split a Moodle 'filepath' into sanitized segments."""
    return [clean_name(seg) for seg in p.split("/") if seg.strip()]


def unique_path(path, taken):
    """Return a path not already in `taken`, inserting ' (2)', ' (3)', … before the extension
    on collision, then add it to `taken`. Guarantees two distinct items never overwrite each
    other (same filename in one folder, two same-named forums/discussions, …)."""
    if path not in taken:
        taken.add(path)
        return path
    stem, dot, ext = path.rpartition(".")
    if not dot or "/" in ext:        # no real extension (e.g. a directory-like name)
        stem, dot, ext = path, "", ""
    i = 2
    while f"{stem} ({i}){dot}{ext}" in taken:
        i += 1
    cand = f"{stem} ({i}){dot}{ext}"
    taken.add(cand)
    return cand


class MoodleError(Exception):
    def __init__(self, fn, code, msg):
        self.fn, self.code, self.msg = fn, code, msg
        super().__init__(f"{fn}: {code} - {msg}")


# Safety guard 1 — function allowlist (default-deny). The only WS functions this tool may
# call; all read-only. Anything else (mod_quiz_start_attempt, *_save_*, *_view_*, ...) raises,
# so it is structurally impossible to submit, start a quiz, mark viewed, or mark attendance.
WS_READONLY_ALLOWED = {
    "core_webservice_get_site_info",
    "core_enrol_get_users_courses",
    "core_course_get_contents",
    "mod_forum_get_forums_by_courses",
    "mod_forum_get_forum_discussions",
}

# Safety guard 2 — transport. Every iCorsi request passes _assert_icorsi_get: GET-only, the
# iCorsi host only, and only the WS endpoint or static file handler. Blocks any POST and any
# /mod/*/view.php action URL from being sent, even via a bug.
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
    parts = urllib.parse.urlsplit(fileurl)
    qs = dict(urllib.parse.parse_qsl(parts.query))
    qs["token"] = TOKEN
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(qs), parts.fragment)
    )


class WebDav:
    def __init__(self, base_url, user, pw, host_header=""):
        self.base = base_url.rstrip("/")
        self.hdr = basic_auth_header(user, pw)
        if host_header:
            self.hdr["Host"] = host_header
        self.root_path = urllib.parse.urlsplit(self.base).path.rstrip("/")
        self._ensured = set()

    def _abs(self, logical_path):
        enc = urllib.parse.quote(logical_path, safe="/")
        return f"{self.base}/{enc.lstrip('/')}"

    def ensure_dir(self, logical_path):
        logical_path = logical_path.strip("/")
        if not logical_path or logical_path in self._ensured:
            return
        cur = ""
        for seg in logical_path.split("/"):
            cur = f"{cur}/{seg}" if cur else seg
            if cur in self._ensured:
                continue
            if DRY_RUN:
                self._ensured.add(cur)
                continue
            status, _, _ = http_retry(self._abs(cur), method="MKCOL", headers=self.hdr)
            if status not in (201, 405, 301):     # 405 = already exists
                log.warning("MKCOL %s -> HTTP %s", cur, status)
            self._ensured.add(cur)

    def list_files(self, logical_dir):
        return self._list(logical_dir)[0]

    def _list(self, logical_dir):
        """Recursively walk logical_dir. Returns ({file_path: size}, {dir_path})."""
        out, dirs = {}, set()
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
                continue
            if status != 207:
                log.warning("PROPFIND %s -> HTTP %s", d, status)
                continue
            for href, is_col, size in self._parse_multistatus(raw):
                if href.strip("/") == d.strip("/"):
                    continue
                if is_col:
                    dirs.add(href.strip("/"))
                    stack.append(href)
                else:
                    out[href] = size
        return out, dirs

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
            path = nfc(path.strip("/"))
            is_col = resp.find(".//d:resourcetype/d:collection", ns) is not None
            size_el = resp.find(".//d:getcontentlength", ns)
            size = int(size_el.text) if (size_el is not None and size_el.text and size_el.text.isdigit()) else 0
            results.append((path, is_col, size))
        return results

    def put_bytes(self, logical_path, data):
        self.ensure_dir("/".join(logical_path.strip("/").split("/")[:-1]))
        if DRY_RUN:
            return
        hdr = {**self.hdr, "Content-Type": "application/octet-stream"}
        status, _, _ = http_retry(self._abs(logical_path), method="PUT", data=data, headers=hdr)
        if status not in (200, 201, 204):
            raise RuntimeError(f"PUT {logical_path} -> HTTP {status}")

    def put_file(self, logical_path, local_path, size):
        self.ensure_dir("/".join(logical_path.strip("/").split("/")[:-1]))
        if DRY_RUN:
            return
        hdr = {**self.hdr, "Content-Type": "application/octet-stream",
               "Content-Length": str(size)}

        def attempt():
            req = urllib.request.Request(self._abs(logical_path), method="PUT")
            for k, v in hdr.items():
                req.add_header(k, v)
            req.add_header("User-Agent", UA)
            with open(local_path, "rb") as fh:      # reopen per retry
                req.data = fh
                with urllib.request.urlopen(req, timeout=max(HTTP_TIMEOUT, 300)) as r:
                    if r.status not in (200, 201, 204):
                        raise RuntimeError(f"PUT {logical_path} -> HTTP {r.status}")
        retrying(f"PUT {logical_path}", attempt)

    def delete(self, logical_path):
        """DELETE a file/collection (goes to ownCloud trash). Used only by prune."""
        if DRY_RUN:
            return
        status, _, _ = http_retry(self._abs(logical_path), method="DELETE", headers=self.hdr)
        if status not in (200, 204, 404):
            log.warning("DELETE %s -> HTTP %s", logical_path, status)


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


def build_expected(course_id, sections):
    """Return (files, links). 'rel' is each item's path under the course's _icorsi base.
    Sections and modules arrive in course display order, so a zero-padded "001 - " prefix
    makes the filesystem sort the same way instead of alphabetically."""
    files, links = [], []
    for si, sec in enumerate(sections, 1):
        section = f"{si:03d} - " + clean_name(sec.get("name") or f"section-{sec.get('section', 0)}", "General")
        for mi, mod in enumerate(sec.get("modules", []), 1):
            modname = mod.get("modname")
            modtitle = clean_name(mod.get("name"), "module")
            if modname in EXCLUDE_MODULES:
                continue
            prefix = f"{mi:03d} - "
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
                    links.append({"rel": f"{section}/{prefix}{modtitle}.url.txt",
                                  "content": content.encode("utf-8")})
                continue
            for c in mod.get("contents", []):
                if c.get("type") != "file":
                    continue
                fname = clean_name(c.get("filename"), "file")
                if modname == "resource":
                    rel_parts = [section, f"{prefix}{fname}"]
                else:
                    rel_parts = [section, f"{prefix}{modtitle}"] + clean_path(c.get("filepath", "/")) + [fname]
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
    """One _info.md per section, aggregating its summary + label text."""
    texts = []
    for si, sec in enumerate(sections, 1):
        raw_section = clean_name(sec.get("name") or f"section-{sec.get('section', 0)}", "General")
        section = f"{si:03d} - {raw_section}"      # numbering must match build_expected
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
        body = f"# {raw_section}\n\n" + "\n\n---\n\n".join(parts) + "\n"
        texts.append({"rel": f"{section}/000 - _info.md", "content": body.encode("utf-8"), "tm": 0})
    return texts


def fetch_forums(course_id):
    """Forums/announcements -> .md. Uses only listing functions, so it does NOT mark posts read."""
    texts, files = [], []
    forums = ws("mod_forum_get_forums_by_courses", **{"courseids[0]": course_id})
    for f in forums:
        fname = clean_name(f.get("name"), "forum")
        # "000 - " pins forums to the top of the course folder (before "001 - ...").
        folder = "000 - Annunci" if f.get("type") == "news" else f"000 - Forum/{fname}"
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
    """Download a pluginfile to a temp file (with retries). Returns (path, size)."""
    url = file_download_url(fileurl)
    _assert_icorsi_get(url, "GET")

    def attempt():
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

    return retrying(f"GET {url}", attempt)


def sync_course(dav, course_id, rel_folder, state):
    """Sync one course. Returns (uploaded, skipped, errors, pruned);
    'errors' is the count of expected files still missing after the reconcile loop."""
    base = nfc("/".join(p for p in [BASE_PATH, rel_folder, SUBFOLDER] if p).strip("/"))
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

    fstate = state.setdefault("files", {})

    # Assign each item a unique destination path (deterministic from the stable API order);
    # unique_path keeps two distinct items from overwriting each other on a name collision.
    taken = set()
    file_by, link_by, text_by = {}, {}, {}
    for f in files:
        file_by[unique_path(f"{base}/{f['rel']}", taken)] = f
    for l in links:
        link_by[unique_path(f"{base}/{l['rel']}", taken)] = l
    for t in texts:
        text_by[unique_path(f"{base}/{t['rel']}", taken)] = t
    expected = set(taken)

    def do_file(logical, f):
        path, size = download(f["fileurl"])
        try:
            dav.put_file(logical, path, size)
        finally:
            os.unlink(path)
        fstate[logical] = {"tm": f["tm"], "size": size}
        log.info("uploaded %s (%d B)", logical, size)

    def do_link(logical, l):
        dav.put_bytes(logical, l["content"])
        fstate[logical] = {"size": len(l["content"]),
                           "md5": hashlib.md5(l["content"]).hexdigest(), "link": True}

    def do_text(logical, t):
        dav.put_bytes(logical, t["content"])
        fstate[logical] = {"tm": t.get("tm", 0), "size": len(t["content"]),
                           "md5": hashlib.md5(t["content"]).hexdigest()}
        log.info("wrote %s", logical)

    if DRY_RUN:
        for logical in list(file_by) + list(link_by) + list(text_by):
            log.info("[dry] would write %s", logical)
        return len(expected), 0, 0, 0

    existing = dav.list_files(base)
    uploaded = skipped = 0

    for logical, f in file_by.items():
        cur = existing.get(logical)
        prev = fstate.get(logical)
        # Up-to-date = present + unchanged on iCorsi (timemodified) + intact (ownCloud size ==
        # the bytes we stored). Moodle's reported filesize is deliberately NOT used: it is 0
        # for generated 'page' files, which made those re-upload every run.
        if cur is not None and prev and prev.get("tm", -1) >= f["tm"] and cur == prev.get("size"):
            skipped += 1
            continue
        try:
            do_file(logical, f); uploaded += 1
        except Exception as e:
            log.error("failed %s: %s", logical, e)

    for logical, l in link_by.items():
        digest = hashlib.md5(l["content"]).hexdigest()
        if existing.get(logical) == len(l["content"]) and fstate.get(logical, {}).get("md5") == digest:
            skipped += 1
            continue
        try:
            do_link(logical, l); uploaded += 1
        except Exception as e:
            log.error("failed link %s: %s", logical, e)

    for logical, t in text_by.items():
        digest = hashlib.md5(t["content"]).hexdigest()
        if existing.get(logical) == len(t["content"]) and fstate.get(logical, {}).get("md5") == digest:
            skipped += 1
            continue
        try:
            do_text(logical, t); uploaded += 1
        except Exception as e:
            log.error("failed text %s: %s", logical, e)

    # Reconcile: re-list ownCloud and retry anything still missing/wrong-size, looping until
    # none remain, bounded by RECON_MAX_PASSES and a no-progress guard.
    def find_missing():
        actual = dav.list_files(base)
        miss = []
        for lg in file_by:
            cur = actual.get(lg)
            prev = fstate.get(lg)
            if cur is None or not prev or cur != prev.get("size"):
                miss.append(lg)
        for lg, l in link_by.items():
            if actual.get(lg) != len(l["content"]):
                miss.append(lg)
        for lg, t in text_by.items():
            if actual.get(lg) != len(t["content"]):
                miss.append(lg)
        return actual, miss

    actual, missing = find_missing()
    passes = 0
    while missing and passes < RECON_MAX_PASSES:
        passes += 1
        before = len(missing)
        log.info("reconcile pass %d for %s: %d missing", passes, course_id, before)
        for lg in missing:
            try:
                if lg in file_by:
                    do_file(lg, file_by[lg])
                elif lg in link_by:
                    do_link(lg, link_by[lg])
                elif lg in text_by:
                    do_text(lg, text_by[lg])
                uploaded += 1
            except Exception as e:
                log.error("reconcile failed %s: %s", lg, e)
        actual, missing = find_missing()
        if len(missing) >= before:
            break
    for lg in missing:
        log.error("STILL MISSING after %d passes: %s", passes, lg)
    errors = len(missing)

    # Prune (opt-in): delete everything under base that isn't in the current expected set —
    # old/renamed/removed files and their folders — so exactly one current copy remains.
    # Only when the course fetched OK with 0 errors. Deletes go to ownCloud trash.
    pruned = 0
    if PRUNE_ORPHANS and expected and errors == 0:
        actual_files, actual_dirs = dav._list(base)
        expected_dirs = set()
        for lg in expected:
            segs = lg[len(base) + 1:].split("/")
            for i in range(1, len(segs)):
                expected_dirs.add(f"{base}/" + "/".join(segs[:i]))
        for lg in sorted(actual_files):
            if lg not in expected:
                try:
                    dav.delete(lg); fstate.pop(lg, None); pruned += 1
                    log.info("pruned file %s", lg)
                except Exception as e:
                    log.error("prune file failed %s: %s", lg, e)
        # shallowest first: deleting a collection removes its subtree, so nested orphans below
        # it just 404 (ignored by delete()).
        for d in sorted(actual_dirs - expected_dirs, key=lambda p: p.count("/")):
            try:
                dav.delete(d); pruned += 1
                log.info("pruned folder %s", d)
            except Exception as e:
                log.error("prune folder failed %s: %s", d, e)

    return uploaded, skipped, errors, pruned


def load_courses():
    """Returns (mapped {id: path}, skipped {id}). Non-numeric keys are ignored;
    a null/false/""/"skip" value means explicitly skip (no 'new course' notification)."""
    path = _resolve_courses_file()
    if not path:
        sys.exit("FATAL: no course map found. Create /data/courses.json "
                 "(see courses.example.json for the format).")
    with open(path) as f:
        raw = json.load(f)
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

    # Two courses pointing at the same folder would prune each other's files — refuse both.
    by_target = {}
    for cid, rel in mapped.items():
        by_target.setdefault(rel, []).append(cid)
    dup_targets = {rel for rel, cids in by_target.items() if len(cids) > 1}
    if dup_targets:
        notify("⚠️ icorsi-sync: multiple courses map to the same folder "
               f"({', '.join(sorted(dup_targets))}); skipping them — give each a unique folder.")

    archived = set(state.get("archived_courses", []))
    known_unmapped = set(state.get("known_unmapped", []))

    for cid, name in enrolled.items():
        if cid in mapped or cid in skipped or cid in known_unmapped:
            continue
        notify(f"🆕 icorsi-sync: new enrolled course not mapped: {cid} — {name}\n"
               f"Add it to courses.json to start syncing (or set it to null to skip).")
        known_unmapped.add(cid)
    known_unmapped &= set(enrolled)
    known_unmapped -= set(mapped)
    known_unmapped -= skipped

    total_dl = total_sk = total_err = total_pr = 0
    changed_courses = []

    for cid, rel in mapped.items():
        if rel in dup_targets:
            continue
        if cid not in enrolled:
            if cid not in archived:
                notify(f"📦 icorsi-sync: course {cid} no longer in your enrolments "
                       f"(passed/unenrolled?). Keeping existing files, skipping from now on.")
                archived.add(cid)
            continue
        archived.discard(cid)                     # re-enrolled -> resume
        try:
            dl, sk, err, pr = sync_course(dav, cid, rel, state)
            total_dl += dl; total_sk += sk; total_err += err; total_pr += pr
            if dl or err or pr:
                line = f"[{cid}] {enrolled[cid]}: +{dl}"
                if pr:
                    line += f" 🗑️{pr}"
                if err:
                    line += f" ⚠️{err} missing"
                changed_courses.append(line)
            log.info("course %s (%s): %d new, %d skipped, %d missing, %d pruned",
                     cid, rel, dl, sk, err, pr)
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

    verb = "would write" if DRY_RUN else "uploaded"
    log.info("=== run done%s: %d %s, %d skipped, %d missing, %d pruned ===",
             " (DRY RUN — nothing written)" if DRY_RUN else "",
             total_dl, verb, total_sk, total_err, total_pr)
    if not DRY_RUN and (total_dl or total_err or total_pr):
        summary = (f"✅ icorsi-sync: {total_dl} new, {total_pr} pruned, {total_err} missing.\n"
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

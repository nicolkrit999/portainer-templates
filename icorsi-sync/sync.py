#!/usr/bin/env python3
"""
icorsi-sync - mirror SUPSI iCorsi (Moodle) course material into ownCloud via WebDAV.

Pure stdlib. Reads Moodle Web Services with a mobile token, walks each mapped
course, and uploads files (plus url links as .txt, section text and forum posts
as .md) into ownCloud under a per-subject `_icorsi/` subfolder, mirroring the
course's structure and order. Allowlist of courses (courses.json); auto-discovery
only notifies about new/unenrolled courses. Incremental, self-healing, read-only on
Moodle. Optional prune keeps exactly one current copy.

The mobile wstoken expires (~2 days). A scoped TokenManager renews it fully
headlessly via the Moodle autologin chain (get_autologin_key -> redeem -> relaunch),
so no manual re-mint is needed while the container keeps running.
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
import threading
import traceback
import http.client
import http.cookiejar
import unicodedata
import urllib.parse
import urllib.request
import urllib.error
import concurrent.futures
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
HEARTBEAT_URL     = env("HEARTBEAT_URL", "")
CONCURRENCY       = max(1, int(env("ICORSI_CONCURRENCY", "4")))
HTTP_TIMEOUT      = int(env("HTTP_TIMEOUT", "60"))
HTTP_RETRIES      = int(env("HTTP_RETRIES", "3"))

STATE_DIR     = env("STATE_DIR", "/data")
STATE_FILE    = os.path.join(STATE_DIR, "state.json")
TOKEN_FILE    = os.path.join(STATE_DIR, "token.json")

def _resolve_courses_file():
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in ("/data/courses.json", os.path.join(here, "courses.json")):
        if os.path.exists(cand):
            return cand
    return None

UA = "icorsi-sync/1.0 (+https://github.com)"
# Substring "MoodleMobile" satisfies Moodle's is_moodle_app(); without it the
# autologin/relaunch endpoints reject the request with "apprequired". Used ONLY by
# the renewal path (TokenManager), never by the read path.
MOODLE_APP_UA = "MoodleMobile 4.4.0 (44000)"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("icorsi-sync")


# The running wstoken is owned by the TokenManager instance (mutated on renewal),
# NOT a frozen module constant. ws()/file_download_url() read it at call time.
_TM = None

def current_wstoken():
    if _TM is None:
        sys.exit("FATAL: TokenManager not initialised")
    return _TM.wstoken


_REDACT_RE = re.compile(r"(?i)\b(wstoken|token|privatetoken|key)=[^\s&'\"]+")

def _redact(text):
    """Blank wstoken/token/privatetoken/key query params so a secret can never reach
    a log line, an exception message, or a Discord notification."""
    if not text:
        return text
    return _REDACT_RE.sub(lambda m: f"{m.group(1)}=REDACTED", str(text))


def _clamp_bytes(name, limit=120):
    """Clamp one path segment to <=limit UTF-8 bytes, preserving the extension.
    ownCloud/most filesystems cap a name at 255 bytes; an over-long segment would
    fail every PUT forever, so clamp deterministically."""
    if name is None:
        return name
    if len(name.encode("utf-8")) <= limit:
        return name
    stem, dot, ext = name.rpartition(".")
    if dot and len(("." + ext).encode("utf-8")) < limit and "/" not in ext:
        room = limit - len(("." + ext).encode("utf-8"))
        stem = stem.encode("utf-8")[:room].decode("utf-8", "ignore").rstrip()
        return f"{stem}.{ext}"
    return name.encode("utf-8")[:limit].decode("utf-8", "ignore").rstrip()


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
            if status == 429:
                # Rate limited: honour Retry-After if present, else back off. Never
                # hand a 429 HTML/empty body to json.loads upstream.
                ra = hdrs.get("Retry-After", "")
                delay = int(ra) if str(ra).isdigit() else 2 * attempt
                last = "HTTP 429 (rate limited)"
                if attempt < HTTP_RETRIES:
                    time.sleep(min(delay, 60))
                    continue
                break
            if status >= 500:
                last = f"HTTP {status}"
                if attempt < HTTP_RETRIES:
                    time.sleep(2 * attempt)
                    continue
                break
            return status, body, hdrs
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = str(e)
            if attempt < HTTP_RETRIES:
                time.sleep(2 * attempt)
    raise RuntimeError(
        f"request failed after {HTTP_RETRIES} attempts ({_redact(url)}): {_redact(str(last))}")


def retrying(label, fn):
    """Retry fn() on transient errors; HTTP 4xx are raised immediately (won't self-heal).
    A MoodleError (e.g. invalidtoken) is re-raised at once so the caller can renew."""
    last = None
    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            return fn()
        except MoodleError:
            raise
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500:
                raise
            last = e
        except (urllib.error.URLError, TimeoutError, OSError, http.client.IncompleteRead) as e:
            last = e
        if attempt < HTTP_RETRIES:
            time.sleep(2 * attempt)
    raise RuntimeError(f"{label} failed after {HTTP_RETRIES} attempts: {_redact(str(last))}")


def basic_auth_header(user, pw):
    raw = f"{user}:{pw}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


def nfc(s):
    """Canonical Unicode form. ownCloud stores/returns NFC; Moodle may send NFD. Normalizing
    both sides keeps the SAME file from looking like two different paths (which would cause
    endless re-upload and prune delete/recreate churn)."""
    return unicodedata.normalize("NFC", s)


def clean_name(name, fallback="untitled"):
    """Sanitize one path segment to a canonical (NFC) form; collapses any '/' in the name
    and clamps it to a safe byte length so an over-long name never fails PUT forever."""
    if name is None:
        return fallback
    s = html.unescape(str(name))
    s = s.replace("/", "-").replace("\\", "-")
    s = "".join(ch for ch in s if ch >= " ")
    s = nfc(s).strip().rstrip(". ")
    s = _clamp_bytes(s)
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


# Safety guard 1 - function allowlist (default-deny). The only WS functions this tool may
# call; all read-only. Anything else (mod_quiz_start_attempt, *_save_*, *_view_*, ...) raises,
# so it is structurally impossible to submit, start a quiz, mark viewed, or mark attendance.
WS_READONLY_ALLOWED = {
    "core_webservice_get_site_info",
    "core_enrol_get_users_courses",
    "core_course_get_contents",
    "mod_forum_get_forums_by_courses",
    "mod_forum_get_forum_discussions",
}

# Safety guard 2 - transport. Every iCorsi READ request passes _assert_icorsi_get: GET-only,
# the iCorsi host only, and only the WS endpoint or static file handler. Blocks any POST and any
# /mod/*/view.php action URL from being sent, even via a bug. The renewal path uses its OWN,
# separate guard (_assert_icorsi_renewal) - it is never routed through here.
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
    q = {"wstoken": current_wstoken(), "wsfunction": fn, "moodlewsrestformat": "json"}
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
    qs["token"] = current_wstoken()
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(qs), parts.fragment)
    )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Returning None from redirect_request leaves the 3xx response untouched, so the caller
    can read the Location header instead of following it (needed to capture the
    moodlemobile://token= relaunch redirect and the redeem Set-Cookie)."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class TokenManager:
    """Owns the Moodle mobile wstoken and renews it headlessly via the autologin chain.

    Renewal is POST + a MoodleMobile User-Agent + cookies - the exact opposite of the
    read path's guarantees - so it lives here with its OWN narrow guard
    (_assert_icorsi_renewal) and is never routed through ws()/_assert_icorsi_get.

    Persists to /data/token.json (atomic write). Bootstraps once from env vars
    (ICORSI_TOKEN / ICORSI_PRIVATETOKEN / ICORSI_USERID); after that token.json is the
    source of truth.
    """

    _RENEWAL_PATHS = (
        "/webservice/rest/server.php",
        "/admin/tool/mobile/autologin.php",
        "/admin/tool/mobile/launch.php",
    )

    def __init__(self, base, token_file):
        self.base = base.rstrip("/")
        self.ws_endpoint = self.base + "/webservice/rest/server.php"
        self.token_file = token_file
        self.wstoken = None
        self.privatetoken = None
        self.userid = None
        self.session_cookie = None      # {"name": ..., "value": ...} last known MoodleSession
        self.last_renewed = 0
        self.last_checked = 0
        self.token_alerted = False
        self._fullname = ""
        self._lock = threading.Lock()
        self._load()

    # ---- persistence ----
    def _load(self):
        data = {}
        try:
            with open(self.token_file) as f:
                data = json.load(f)
        except FileNotFoundError:
            data = {}
        except Exception as e:
            log.warning("token.json failed to parse (%s); re-bootstrapping from env", e)
            data = {}
        if data.get("wstoken"):
            self.wstoken       = data.get("wstoken")
            self.privatetoken  = data.get("privatetoken")
            self.userid        = data.get("userid")
            self.session_cookie = data.get("session_cookie")
            self.last_renewed  = data.get("last_renewed", 0)
            self.last_checked  = data.get("last_checked", 0)
            self.token_alerted = data.get("token_alerted", False)
            log.info("token loaded from %s", self.token_file)
            return
        # Bootstrap (one-time) from env. Deliberately NOT sys.exit on a missing token:
        # if token.json later corrupts and the env vars were removed, exiting here would
        # crash-loop the container. Instead we leave wstoken empty and let ensure_valid()
        # degrade to a deduped alert + skip-run (the loop stays up and keeps alerting).
        self.wstoken = env("ICORSI_TOKEN", "") or None
        self.privatetoken = env("ICORSI_PRIVATETOKEN", "") or None
        uid = str(env("ICORSI_USERID", "") or "")
        self.userid = int(uid) if uid.isdigit() else None
        if not self.wstoken:
            log.error("no token available (token.json missing/corrupt and ICORSI_TOKEN unset); "
                      "runs will be skipped until it is re-seeded")
        else:
            log.info("token bootstrapped from env (privatetoken=%s, userid=%s)",
                     "set" if self.privatetoken else "MISSING", self.userid)
            if not self.privatetoken:
                log.warning("ICORSI_PRIVATETOKEN not set - automatic renewal will NOT work; "
                            "set it (and ICORSI_USERID) to enable headless renewal")
        self._save()

    def _save(self):
        os.makedirs(os.path.dirname(self.token_file), exist_ok=True)
        data = {
            "wstoken": self.wstoken,
            "privatetoken": self.privatetoken,
            "userid": self.userid,
            "session_cookie": self.session_cookie,
            "last_renewed": self.last_renewed,
            "last_checked": self.last_checked,
            "token_alerted": self.token_alerted,
        }
        tmp = self.token_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.token_file)

    def current_wstoken(self):
        return self.wstoken

    # ---- renewal guard + transport (separate from the read path) ----
    def _assert_icorsi_renewal(self, url, method):
        u = urllib.parse.urlsplit(url)
        if u.netloc.lower() != ICORSI_HOST:
            raise RuntimeError(f"SAFETY(renewal): refusing host {u.netloc!r}")
        if method not in ("GET", "POST"):
            raise RuntimeError(f"SAFETY(renewal): method not allowed: {method}")
        if u.path not in self._RENEWAL_PATHS:
            raise RuntimeError(f"SAFETY(renewal): path not allowed: {u.path!r}")

    def _request(self, url, method="GET", data=None, cookiejar=None, follow_redirects=True):
        self._assert_icorsi_renewal(url, method)
        handlers = []
        if cookiejar is not None:
            handlers.append(urllib.request.HTTPCookieProcessor(cookiejar))
        if not follow_redirects:
            handlers.append(_NoRedirect())
        opener = urllib.request.build_opener(*handlers)
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("User-Agent", MOODLE_APP_UA)
        if data is not None:
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with opener.open(req, timeout=HTTP_TIMEOUT) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers or {})

    # ---- renewal steps ----
    def _get_autologin_key(self):
        # privatetoken MUST be in the POST body (a ?privatetoken= query -> invalidprivatetoken).
        body = urllib.parse.urlencode({
            "wstoken": self.wstoken,
            "wsfunction": "tool_mobile_get_autologin_key",
            "moodlewsrestformat": "json",
            "privatetoken": self.privatetoken or "",
        }).encode()
        _, raw, _ = self._request(self.ws_endpoint, "POST", data=body)
        data = json.loads(raw.decode("utf-8"))
        if isinstance(data, dict) and data.get("exception"):
            raise MoodleError("tool_mobile_get_autologin_key", data.get("errorcode"),
                              data.get("message"))
        return data["key"], data["autologinurl"]

    def _autologin_session(self):
        """Steps 1-2: mint an autologin key, then redeem it with a FRESH (logged-out) jar.
        Returns the cookie jar carrying the new MoodleSession."""
        if not self.userid:
            raise RuntimeError("cannot redeem autologin key without a userid")
        key, autologinurl = self._get_autologin_key()
        cj = http.cookiejar.CookieJar()
        redeem = autologinurl + "?" + urllib.parse.urlencode({"userid": self.userid, "key": key})
        # Do not follow the redirect; complete_user_login() sets MoodleSession on the 3xx.
        self._request(redeem, "GET", cookiejar=cj, follow_redirects=False)
        return cj

    def _relaunch(self, cj):
        """Step 3: GET launch.php with the session jar; read the moodlemobile://token=<b64>
        Location header. Returns {"wstoken":..., "privatetoken": ... or None} or None."""
        url = self.base + "/admin/tool/mobile/launch.php?" + urllib.parse.urlencode(
            {"service": "moodle_mobile_app", "passport": 1, "urlscheme": "moodlemobile"})
        _, _, hdrs = self._request(url, "GET", cookiejar=cj, follow_redirects=False)
        loc = hdrs.get("Location") or hdrs.get("location")
        return self._parse_launch_blob(loc)

    @staticmethod
    def _parse_launch_blob(location):
        if not location or "token=" not in location:
            return None
        b64 = location.split("token=", 1)[1]
        try:
            decoded = base64.b64decode(b64).decode("utf-8", "ignore")
        except Exception:
            return None
        parts = decoded.split(":::")
        # 3 parts (signature:::wstoken:::privatetoken) when justloggedin is set (fresh login);
        # 2 parts (signature:::wstoken) for a plain relaunch on an existing session.
        if len(parts) >= 3:
            return {"wstoken": parts[1], "privatetoken": parts[2]}
        if len(parts) == 2:
            return {"wstoken": parts[1], "privatetoken": None}
        return None

    def _capture_session(self, cj):
        for c in cj:
            if c.name.startswith("MoodleSession"):
                self.session_cookie = {"name": c.name, "value": c.value}
                return

    def _jar_from_stored(self):
        jar = http.cookiejar.CookieJar()
        sc = self.session_cookie
        if not sc:
            return jar
        ck = http.cookiejar.Cookie(
            0, sc["name"], sc["value"], None, False,
            ICORSI_HOST, True, False, "/", True, True, None, False, None, None, {}, False)
        jar.set_cookie(ck)
        return jar

    def _adopt(self, blob, cj):
        self.wstoken = blob["wstoken"]
        if blob.get("privatetoken"):
            self.privatetoken = blob["privatetoken"]
        self._capture_session(cj)
        self.last_renewed = time.time()
        self.token_alerted = False
        self._save()
        log.info("token/session refreshed via renewal chain")

    # ---- public API ----
    def renew(self):
        """Recover a dead token. (a) relaunch on a stored session (cheapest), then
        (b) the full autologin chain. Returns True on success."""
        with self._lock:
            old = self.wstoken
            if self.session_cookie:
                try:
                    cj = self._jar_from_stored()
                    blob = self._relaunch(cj)
                    if blob and blob.get("wstoken") and blob["wstoken"] != old:
                        self._adopt(blob, cj)
                        return True
                except Exception as e:
                    log.warning("renew via stored session failed: %s", _redact(str(e)))
            try:
                if self.privatetoken:
                    cj = self._autologin_session()
                    blob = self._relaunch(cj)
                    if blob and blob.get("wstoken"):
                        self._adopt(blob, cj)
                        return True
            except Exception as e:
                log.warning("renew via autologin chain failed: %s", _redact(str(e)))
            return False

    def keep_alive(self):
        """Proactively re-mint the token and refresh the MoodleSession BEFORE expiry.

        Runs the autologin chain each loop while the token is still valid, which slides
        the ~2-day token clock and keeps a live session on hand for renew() path (a).
        This is the continuous path that stops the token ever actually expiring. Best
        effort - never raises.

        Returns (ok, detail):
          ok=True   -> chain succeeded (token/session refreshed)
          ok=False  -> chain attempted and failed (detail = redacted reason)
          ok=None   -> nothing to attempt (no privatetoken/userid and no stored session)
        The caller uses this to warn EARLY when proactive renewal is broken while the
        token still works, instead of only finding out at expiry."""
        with self._lock:
            if not ((self.privatetoken and self.userid) or self.session_cookie):
                return None, ""
            try:
                if self.privatetoken and self.userid:
                    cj = self._autologin_session()
                    blob = self._relaunch(cj)
                    if blob and blob.get("wstoken"):
                        self._adopt(blob, cj)
                        return True, ""
                if self.session_cookie:
                    cj = self._jar_from_stored()
                    blob = self._relaunch(cj)
                    if blob and blob.get("wstoken"):
                        self._adopt(blob, cj)
                        return True, ""
                return False, "renewal chain returned no usable token"
            except Exception as e:
                detail = _redact(str(e))
                log.warning("keep_alive refresh failed: %s", detail)
                return False, detail

    def _record_site_info(self, info):
        if not info:
            return
        uid = info.get("userid")
        if uid:
            self.userid = uid
        # Log the userid only - the full name is PII and adds nothing operationally.
        log.info("authenticated (userid=%s)", uid)

    def ensure_valid(self, notify_fn):
        """Called at the start of each run (and on a mid-run invalidtoken). Verifies the
        token with a site_info read; on invalidtoken it renews. Returns True if the token
        is usable, False (after a deduped alert) if it is dead and unrenewable."""
        self.last_checked = time.time()
        if not self.wstoken:
            # token.json missing/corrupt and no bootstrap env - skip the run rather than crash.
            if not self.token_alerted:
                notify_fn("⚠️ icorsi-sync: no Moodle token available (token.json missing/corrupt "
                          "and ICORSI_TOKEN not set). Re-seed ICORSI_TOKEN + ICORSI_PRIVATETOKEN "
                          "(+ ICORSI_USERID) in Portainer, then restart.")
                self.token_alerted = True
                self._save()
            return False
        try:
            info = ws("core_webservice_get_site_info")
        except MoodleError as e:
            if e.code == "invalidtoken":
                log.warning("wstoken rejected as invalid; attempting automatic renewal")
                if self.renew():
                    info = None
                    try:
                        info = ws("core_webservice_get_site_info")
                    except MoodleError as e2:
                        log.warning("post-renewal site_info still failing: %s", e2.code)
                    self._record_site_info(info)
                    self.token_alerted = False
                    self._save()
                    return True
                if not self.token_alerted:
                    notify_fn("⚠️ icorsi-sync: the Moodle token expired and automatic renewal "
                              "failed. Re-bootstrap by re-seeding ICORSI_TOKEN + "
                              "ICORSI_PRIVATETOKEN (+ ICORSI_USERID) in Portainer, then restart.")
                    self.token_alerted = True
                    self._save()
                log.error("token invalid and renewal failed")
                return False
            raise
        self.token_alerted = False
        self._record_site_info(info)
        self._save()
        return True


class WebDav:
    def __init__(self, base_url, user, pw, host_header=""):
        self.base = base_url.rstrip("/")
        self.hdr = basic_auth_header(user, pw)
        if host_header:
            self.hdr["Host"] = host_header
        self.root_path = urllib.parse.urlsplit(self.base).path.rstrip("/")
        self._ensured = set()
        self._lock = threading.Lock()      # guards _ensured under the parallel file pass

    def _abs(self, logical_path):
        enc = urllib.parse.quote(logical_path, safe="/")
        return f"{self.base}/{enc.lstrip('/')}"

    def ensure_dir(self, logical_path):
        logical_path = logical_path.strip("/")
        if not logical_path:
            return
        with self._lock:
            if logical_path in self._ensured:
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
    msg = _redact(msg)
    log.info("NOTIFY: %s", msg)
    if not DISCORD_WEBHOOK:
        return
    try:
        data = json.dumps({"content": msg[:1900]}).encode()
        http(DISCORD_WEBHOOK, method="POST", data=data,
             headers={"Content-Type": "application/json"}, timeout=15)
    except Exception as e:
        log.warning("discord notify failed: %s", _redact(str(e)))


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        log.warning("state.json failed to parse (%s); starting from empty state", e)
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
            stem = _clamp_bytes(f"{datestr} {title}".strip(), 120)
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


def download(fileurl, expected_size=0):
    """Download a pluginfile to a temp file (with retries). Returns (path, size).
    Rejects HTML/error-page bodies and (when the manifest gives a size) short reads,
    so a 200 error page is never stored and marked up-to-date forever."""
    url = file_download_url(fileurl)
    _assert_icorsi_get(url, "GET")

    def attempt():
        tmp = tempfile.NamedTemporaryFile(delete=False)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=max(HTTP_TIMEOUT, 300)) as r:
                ctype = (r.headers.get("Content-Type") or "").lower()
                first = r.read(1 << 16)
                if ctype.startswith("text/html"):
                    raise RuntimeError("download returned text/html (error/login page); refusing to store")
                if first[:1] in (b"{", b"[") and ("json" in ctype or b'"exception"' in first[:1024]):
                    j = None
                    try:
                        j = json.loads(first.decode("utf-8", "ignore"))
                    except ValueError:
                        j = None
                    if isinstance(j, dict) and j.get("exception"):
                        code = j.get("errorcode")
                        if code == "invalidtoken":
                            raise MoodleError("pluginfile", code, j.get("message", ""))
                        raise RuntimeError(f"download returned Moodle error {code}")
                size = len(first)
                tmp.write(first)
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    tmp.write(chunk)
                    size += len(chunk)
            tmp.close()
            if expected_size > 0 and size != expected_size:
                raise RuntimeError(f"download size mismatch: got {size}, expected {expected_size}")
            return tmp.name, size
        except Exception:
            tmp.close()
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            raise

    return retrying(f"GET {_redact(url)}", attempt)


def _parallel(logicals, worker, lock):
    """Run worker(logical) over logicals in a bounded thread pool. Counts successes under
    `lock`; a MoodleError(invalidtoken) is re-raised after the pool drains so the caller can
    renew mid-run. Other errors are logged (redacted) and counted as failures."""
    if not logicals:
        return 0
    ok = 0
    moodle_err = None
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futs = {ex.submit(worker, lg): lg for lg in logicals}
        for fut in concurrent.futures.as_completed(futs):
            lg = futs[fut]
            try:
                fut.result()
                with lock:
                    ok += 1
            except MoodleError as e:
                if e.code == "invalidtoken":
                    moodle_err = e
                else:
                    log.error("failed %s: %s", lg, e)
            except Exception as e:
                log.error("failed %s: %s", lg, _redact(str(e)))
    if moodle_err:
        raise moodle_err
    return ok


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
            log.warning("forums for course %s skipped: %s", course_id, _redact(str(e)))

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

    lock = threading.Lock()
    dl_cache = {}        # logical -> (temp_path, size); each file downloaded at most once/run
    hard_failed = set()  # logicals whose iCorsi download failed this run (don't re-fetch)
    existing = {}        # ownCloud view; kept updated as we upload so find_missing can reuse it

    def do_file(logical, f):
        if logical in dl_cache:
            path, size = dl_cache[logical]
        else:
            try:
                path, size = download(f["fileurl"], f.get("size", 0))
            except MoodleError:
                raise
            except Exception:
                with lock:
                    hard_failed.add(logical)
                raise
            with lock:
                dl_cache[logical] = (path, size)
        dav.put_file(logical, path, size)
        with lock:
            fstate[logical] = {"tm": f["tm"], "size": size}
            existing[logical] = size
        log.info("uploaded %s (%d B)", logical, size)

    def do_link(logical, l):
        dav.put_bytes(logical, l["content"])
        with lock:
            fstate[logical] = {"size": len(l["content"]),
                               "md5": hashlib.md5(l["content"]).hexdigest(), "link": True}
            existing[logical] = len(l["content"])

    def do_text(logical, t):
        dav.put_bytes(logical, t["content"])
        with lock:
            fstate[logical] = {"tm": t.get("tm", 0), "size": len(t["content"]),
                               "md5": hashlib.md5(t["content"]).hexdigest()}
            existing[logical] = len(t["content"])
        log.info("wrote %s", logical)

    def do_item(logical):
        if logical in file_by:
            do_file(logical, file_by[logical])
        elif logical in link_by:
            do_link(logical, link_by[logical])
        elif logical in text_by:
            do_text(logical, text_by[logical])

    if DRY_RUN:
        for logical in list(file_by) + list(link_by) + list(text_by):
            log.info("[dry] would write %s", logical)
        return len(expected), 0, 0, 0

    existing.update(dav.list_files(base))
    uploaded = skipped = 0

    try:
        # Decide what to (re)write vs skip as already-current.
        files_to_do, links_to_do, texts_to_do = [], [], []
        for logical, f in file_by.items():
            cur = existing.get(logical)
            prev = fstate.get(logical)
            # Up-to-date = present + unchanged on iCorsi (timemodified) + intact (ownCloud size ==
            # the bytes we stored). Moodle's reported filesize is deliberately NOT used here: it is
            # 0 for generated 'page' files, which made those re-upload every run.
            if cur is not None and prev and prev.get("tm", -1) >= f["tm"] and cur == prev.get("size"):
                skipped += 1
                continue
            files_to_do.append(logical)
        for logical, l in link_by.items():
            digest = hashlib.md5(l["content"]).hexdigest()
            if existing.get(logical) == len(l["content"]) and fstate.get(logical, {}).get("md5") == digest:
                skipped += 1
                continue
            links_to_do.append(logical)
        for logical, t in text_by.items():
            digest = hashlib.md5(t["content"]).hexdigest()
            if existing.get(logical) == len(t["content"]) and fstate.get(logical, {}).get("md5") == digest:
                skipped += 1
                continue
            texts_to_do.append(logical)

        # Pre-create every needed parent dir sequentially, so the parallel pass never has to
        # create one concurrently (ensure_dir is also individually locked as a belt-and-braces).
        for logical in files_to_do + links_to_do + texts_to_do:
            dav.ensure_dir("/".join(logical.strip("/").split("/")[:-1]))

        uploaded += _parallel(files_to_do, do_item, lock)
        uploaded += _parallel(links_to_do + texts_to_do, do_item, lock)

        # Reconcile: re-list ownCloud and retry anything still missing/wrong-size, looping until
        # none remain, bounded by RECON_MAX_PASSES and a no-progress guard. The FIRST check reuses
        # the in-memory `existing` view built during upload (no extra PROPFIND); later passes re-list
        # to truly verify. Files whose iCorsi download hard-failed are not re-fetched.
        def find_missing(actual=None):
            if actual is None:
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

        actual, missing = find_missing(existing)
        passes = 0
        while missing and passes < RECON_MAX_PASSES:
            passes += 1
            before = len(missing)
            todo = [lg for lg in missing if lg not in hard_failed]
            log.info("reconcile pass %d for %s: %d missing (%d retryable)",
                     passes, course_id, before, len(todo))
            uploaded += _parallel(todo, do_item, lock)
            actual, missing = find_missing()
            if len(missing) >= before:
                break
        for lg in missing:
            log.error("STILL MISSING after %d passes: %s", passes, lg)
        errors = len(missing)
    finally:
        # Release cached download temp files even if a course aborts mid-run (e.g. _parallel
        # re-raises MoodleError(invalidtoken)), so /data/tmp never accumulates orphans.
        for path, _ in dl_cache.values():
            try:
                os.unlink(path)
            except OSError:
                pass

    # Prune (opt-in): delete everything under base that isn't in the current expected set -
    # old/renamed/removed files and their folders - so exactly one current copy remains.
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
                    log.error("prune file failed %s: %s", lg, _redact(str(e)))
        # shallowest first: deleting a collection removes its subtree, so nested orphans below
        # it just 404 (ignored by delete()).
        for d in sorted(actual_dirs - expected_dirs, key=lambda p: p.count("/")):
            try:
                dav.delete(d); pruned += 1
                log.info("pruned folder %s", d)
            except Exception as e:
                log.error("prune folder failed %s: %s", d, _redact(str(e)))

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


def _process_keepalive(state, result, notify_fn):
    """Track proactive-renewal (keep_alive) health across runs and alert EARLY when it breaks.

    `result` is keep_alive()'s (ok, detail). Uses two state keys (missing == 0/False):
    `keepalive_fail_count` and `keepalive_alerted`. Emits at most ONE '⚠️ renewal failing'
    notify per breakage episode, and only after 2 consecutive failures (so a single transient
    blip is ignored). On the next success it resets the counter/flag and, if it had alerted,
    sends a brief recovery notify. Returns True when state changed (caller should save)."""
    ok, detail = result
    if ok is None:                       # nothing to attempt this run - leave state untouched
        return False
    if ok is False:
        state["keepalive_fail_count"] = state.get("keepalive_fail_count", 0) + 1
        if state["keepalive_fail_count"] >= 2 and not state.get("keepalive_alerted"):
            notify_fn("⚠️ icorsi-sync: PROACTIVE token renewal is failing "
                      f"({_redact(detail) or 'unknown error'}). The current token still works, "
                      "but sync will stop when it expires (~2 days). Check the renewal setup "
                      "(autologin/token/privatetoken).")
            state["keepalive_alerted"] = True
        return True
    # ok is True - recovered / healthy
    changed = bool(state.get("keepalive_fail_count") or state.get("keepalive_alerted"))
    if state.get("keepalive_alerted"):
        notify_fn("✅ icorsi-sync: token renewal recovered.")
    state["keepalive_fail_count"] = 0
    state["keepalive_alerted"] = False
    return changed


def run_once(dav, state, tm):
    log.info("=== run start (dry_run=%s) ===", DRY_RUN)
    # Token pre-flight: verify (and, on invalidtoken, renew) before doing any work.
    if not tm.ensure_valid(notify):
        state["token_alerted"] = True
        save_state(state)
        log.error("token invalid and renewal failed, skipping run")
        return
    state["token_alerted"] = False
    userid = tm.userid
    if not userid:
        log.error("no userid available after site_info; skipping run")
        return

    enrolled = {str(c["id"]): c.get("fullname", "") for c in
                ws("core_enrol_get_users_courses", userid=userid)}
    mapped, skipped = load_courses()

    # Two courses pointing at the same folder would prune each other's files - refuse both.
    by_target = {}
    for cid, rel in mapped.items():
        by_target.setdefault(rel, []).append(cid)
    dup_targets = {rel for rel, cids in by_target.items() if len(cids) > 1}
    if dup_targets:
        notify("⚠️ icorsi-sync: multiple courses map to the same folder "
               f"({', '.join(sorted(dup_targets))}); skipping them - give each a unique folder.")

    archived = set(state.get("archived_courses", []))
    known_unmapped = set(state.get("known_unmapped", []))

    for cid, name in enrolled.items():
        if cid in mapped or cid in skipped or cid in known_unmapped:
            continue
        notify(f"🆕 icorsi-sync: new enrolled course not mapped: {cid} - {name}\n"
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
            # A mid-run token expiry: renew, then continue with the remaining courses; if
            # renewal fails, alert (deduped inside ensure_valid) and abort the rest of the run.
            if e.code == "invalidtoken":
                if tm.ensure_valid(notify):
                    log.info("token renewed mid-run; continuing with remaining courses")
                    continue
                notify("⚠️ icorsi-sync: token expired mid-run and renewal failed; aborting run.")
                break
            total_err += 1
            log.error("course %s api error: %s", cid, e)
        except Exception as e:
            total_err += 1
            log.error("course %s failed: %s", cid, _redact(str(e)))

    state["archived_courses"] = sorted(archived)
    state["known_unmapped"] = sorted(known_unmapped)
    state["last_run"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_state(state)

    verb = "would write" if DRY_RUN else "uploaded"
    log.info("=== run done%s: %d %s, %d skipped, %d missing, %d pruned ===",
             " (DRY RUN - nothing written)" if DRY_RUN else "",
             total_dl, verb, total_sk, total_err, total_pr)
    if not DRY_RUN and (total_dl or total_err or total_pr):
        summary = (f"✅ icorsi-sync: {total_dl} new, {total_pr} pruned, {total_err} missing.\n"
                   + "\n".join(changed_courses[:20]))
        notify(summary)

    # Proactively slide the session / re-mint the token so it never actually expires. If that
    # chain is failing WHILE the token still works, warn early (deduped, after 2 consecutive
    # failures) instead of only discovering it at expiry. Then ping the positive heartbeat.
    ka_result = tm.keep_alive()
    if not DRY_RUN and _process_keepalive(state, ka_result, notify):
        save_state(state)
    if not DRY_RUN and HEARTBEAT_URL:
        try:
            http(HEARTBEAT_URL, method="GET", timeout=15)
            log.info("heartbeat pinged")
        except Exception as e:
            log.warning("heartbeat failed: %s", _redact(str(e)))


def main():
    global _TM
    _TM = TokenManager(ICORSI_BASE, TOKEN_FILE)
    log.info("icorsi-sync starting | base=%s | dav=%s | interval=%ss | dry_run=%s | concurrency=%s",
             BASE_PATH, DAV_URL, INTERVAL, DRY_RUN, CONCURRENCY)
    dav = WebDav(DAV_URL, DAV_USER, DAV_PASS, DAV_HOST_HEADER)
    if not RUN_ON_START and LOOP:
        time.sleep(INTERVAL)
    while True:
        state = load_state()
        try:
            run_once(dav, state, _TM)
        except Exception as e:
            log.error("run failed:\n%s", _redact(traceback.format_exc()))
            notify(f"❌ icorsi-sync run failed: {_redact(str(e))}")
        if not LOOP:
            break
        log.info("sleeping %ss until next run", INTERVAL)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()

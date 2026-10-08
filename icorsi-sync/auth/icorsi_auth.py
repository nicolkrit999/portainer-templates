#!/usr/bin/env python3
"""icorsi-auth: the only component that holds the iCorsi login credentials (stdlib only).

Job: when icorsi-sync drops a request into the shared handoff dir (/auth), perform ONE fresh
Moodle login on the native login form and hand back the resulting mobile wstoken (+ privatetoken
+ session cookie). That is all it can do:

  * Every HTTP request passes _guard(): host www.icorsi.ch only, https only, path exactly
    /login/index.php (GET, POST) or /admin/tool/mobile/launch.php (GET). Nothing else.
  * Redirects are never followed by urllib. Each hop is re-checked by _guard() before being
    requested; a moodlemobile:// Location is read and never followed.
  * It never calls Moodle web services, never logs out, never contacts edu-ID / SSO hosts.
  * Credentials live only in this process's environment. They are never logged, never put in
    exception text and never written to disk. Results (tokens) are written to /auth/result.json
    (mode 0600), the same secrets the sync container already stores in its own token.json.

Modes:  (default) daemon loop | --probe (GET-only sanity check, never POSTs) |
        --once [--force] (one login now, prints a redacted summary, writes nothing but state)
"""

import base64
import http.client
import http.cookiejar
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

BASE_HOST = "www.icorsi.ch"
BASE = "https://" + BASE_HOST
LOGIN_PATH = "/login/index.php"
LAUNCH_PATH = "/admin/tool/mobile/launch.php"
LAUNCH_URL = BASE + LAUNCH_PATH + "?service=moodle_mobile_app&passport=1&urlscheme=moodlemobile"
LOGIN_URL = BASE + LOGIN_PATH

# path -> (allowed methods, allowed query keys)
_ALLOWED = {
    LOGIN_PATH: (("GET", "POST"), {"testsession"}),
    LAUNCH_PATH: (("GET",), {"service", "passport", "urlscheme"}),
}
# Same UA the sync container's renewal path uses (Moodle's is_moodle_app() looks for the substring).
UA = "MoodleMobile 4.4.0 (44000)"

AUTH_DIR = os.environ.get("AUTH_HANDOFF_DIR", "/auth")
REQUEST_FILE = os.path.join(AUTH_DIR, "request.json")
RESULT_FILE = os.path.join(AUTH_DIR, "result.json")
HEARTBEAT_FILE = os.path.join(AUTH_DIR, "heartbeat")
STATE_DIR = os.environ.get("AUTH_STATE_DIR", "/state")
STATE_FILE = os.path.join(STATE_DIR, "sidecar.json")

POLL_SECONDS = 10
HTTP_TIMEOUT = 30
MAX_HOPS = 8
MAX_BODY = 1_000_000
MIN_SPACING = 30 * 60            # between credential submissions
MAX_BACKOFF = 6 * 3600           # cap for the doubling backoff after repeated failures
MAX_PER_DAY = 6                  # credential submissions per rolling 24h
PRE_POST_RETRY = 5 * 60          # a failure before any credential was sent (network, site down)
STALE_REQUEST = 3600             # ignore requests older than this

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("icorsi-auth")


class GuardError(Exception):
    pass


class LoginFailure(Exception):
    """Carries a short, fixed-vocabulary code - never response bodies or credentials."""

    def __init__(self, code, detail=""):
        self.code, self.detail = code, detail
        super().__init__(code if not detail else f"{code}: {detail}")


# ---------------------------------------------------------------------------------------------
# Guard + transport
# ---------------------------------------------------------------------------------------------
def _guard(method, url):
    try:
        u = urllib.parse.urlsplit(url)
        port = u.port
    except ValueError:
        raise GuardError("url")
    if u.scheme != "https":
        raise GuardError("scheme")
    if (u.hostname or "").lower() != BASE_HOST or port not in (None, 443) or u.username or u.password:
        raise GuardError("host:" + (u.hostname or "?"))
    rule = _ALLOWED.get(u.path)
    if not rule:
        raise GuardError("path:" + u.path)
    methods, keys = rule
    if method not in methods:
        raise GuardError("method:" + method)
    if u.query:
        for k, _v in urllib.parse.parse_qsl(u.query, keep_blank_values=True):
            if k not in keys:
                raise GuardError("query:" + u.path)


class _HoldRedirects(urllib.request.HTTPRedirectHandler):
    """Return 3xx responses to the caller untouched; urllib must never follow a redirect itself."""

    def http_error_301(self, req, fp, code, msg, headers):
        return fp

    http_error_302 = http_error_303 = http_error_307 = http_error_308 = http_error_301


def _new_opener():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj), _HoldRedirects()), cj


def _fetch(opener, method, url, data=None):
    _guard(method, url)
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", UA)
    if data is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        try:
            r = opener.open(req, timeout=HTTP_TIMEOUT)
        except urllib.error.HTTPError as e:
            r = e
        with r:
            status = r.status if hasattr(r, "status") else r.code
            body = r.read(MAX_BODY) if status < 300 or status >= 400 else b""
            return status, dict(r.headers), body
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as e:
        raise LoginFailure("network_error", type(e).__name__)


def _walk(opener, method, url, data=None):
    """Request `url`, then follow redirects manually (each hop re-guarded) until a non-redirect.

    Returns ("app", location) when a moodlemobile: Location is seen (never requested), or
    ("page", status, final_url, body)."""
    for _ in range(MAX_HOPS):
        status, hdrs, body = _fetch(opener, method, url, data)
        if status in (301, 302, 303, 307, 308):
            loc = hdrs.get("Location") or hdrs.get("location") or ""
            if not loc:
                raise LoginFailure("redirect_without_location")
            if loc.lower().startswith("moodlemobile:"):
                return ("app", loc)
            if status in (307, 308) and method == "POST":
                raise LoginFailure("unexpected_redirect", "POST-preserving redirect")
            nxt = urllib.parse.urljoin(url, loc)
            try:
                _guard("GET", nxt)
            except GuardError as e:
                p = urllib.parse.urlsplit(nxt)
                raise LoginFailure("unexpected_redirect", f"{p.hostname}{p.path} ({e})")
            method, data, url = "GET", None, nxt
            continue
        return ("page", status, url, body)
    raise LoginFailure("too_many_redirects")


# ---------------------------------------------------------------------------------------------
# Login flow
# ---------------------------------------------------------------------------------------------
class _FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_login = False
        self.has_form = False
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form" and a.get("id") == "login":
            self.in_login = self.has_form = True
        elif tag == "input" and self.in_login and a.get("name"):
            self.fields[a["name"]] = a.get("value") or ""

    def handle_endtag(self, tag):
        if tag == "form":
            self.in_login = False


def _parse_form(body):
    p = _FormParser()
    p.feed(body.decode("utf-8", "ignore"))
    return p


def _parse_blob(location):
    if not location or "token=" not in location:
        return None
    try:
        raw = urllib.parse.unquote(location.split("token=", 1)[1]).strip()
        raw = raw.replace("-", "+").replace("_", "/")
        raw += "=" * (-len(raw) % 4)
        decoded = base64.b64decode(raw).decode("utf-8", "ignore")
    except Exception:
        return None
    parts = decoded.split(":::")
    if len(parts) >= 3 and parts[1]:
        return {"wstoken": parts[1], "privatetoken": parts[2] or None, "parts": 3}
    if len(parts) == 2 and parts[1]:
        return {"wstoken": parts[1], "privatetoken": None, "parts": 2}
    return None


def _load_login_form(opener):
    res = _walk(opener, "GET", LAUNCH_URL)
    if res[0] == "app":
        raise LoginFailure("unexpected_session", "launch.php answered without login")
    _, status, final, body = res
    if urllib.parse.urlsplit(final).path != LOGIN_PATH or status != 200:
        raise LoginFailure("no_login_redirect", f"status {status} at {urllib.parse.urlsplit(final).path}")
    form = _parse_form(body)
    if not form.has_form or not form.fields.get("logintoken") or "username" not in form.fields \
            or "password" not in form.fields:
        raise LoginFailure("login_form_missing")
    return form


def do_login(username, password):
    """One full login. Returns dict(wstoken, privatetoken, parts, session_cookie). Raises
    LoginFailure with `.posted` set True once credentials have been submitted."""
    opener, cj = _new_opener()
    form = _load_login_form(opener)
    payload = urllib.parse.urlencode({
        "anchor": form.fields.get("anchor", ""),
        "logintoken": form.fields["logintoken"],
        "username": username,
        "password": password,
    }).encode()
    try:
        res = _walk(opener, "POST", LOGIN_URL, payload)
    except LoginFailure as e:
        e.posted = True
        raise
    except Exception as e:
        err = LoginFailure("transport_error", type(e).__name__)
        err.posted = True
        raise err from None
    finally:
        del payload
    posted = True
    try:
        if res[0] == "page":
            _, status, final, body = res
            path = urllib.parse.urlsplit(final).path
            q = urllib.parse.urlsplit(final).query
            if path == LOGIN_PATH and "testsession" not in q:
                raise LoginFailure("invalid_login")
            raise LoginFailure("unexpected_page", f"status {status} at {path}")
        # The chain (POST -> login?testsession= -> launch.php) ended at moodlemobile://token=...
        blob = _parse_blob(res[1])
        if not blob:
            raise LoginFailure("unparseable_token_blob")
        sess = next(({"name": c.name, "value": c.value} for c in cj
                     if c.name.startswith("MoodleSession")), None)
        blob["session_cookie"] = sess
        return blob
    except LoginFailure as e:
        e.posted = posted
        raise
    except Exception as e:
        err = LoginFailure("transport_error", type(e).__name__)
        err.posted = posted
        raise err from None


# ---------------------------------------------------------------------------------------------
# State / rate limiting (no secrets in state)
# ---------------------------------------------------------------------------------------------
def _atomic_write(path, text):
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def _load_state():
    """Missing file (first run) -> empty state. Present but unreadable/corrupt -> fail closed."""
    try:
        with open(STATE_FILE) as f:
            s = json.load(f)
        return {"attempts": [float(t) for t in s.get("attempts", [])],
                "fails": int(s.get("fails", 0)),
                "next_allowed_at": float(s.get("next_allowed_at", 0)),
                "last_result": str(s.get("last_result", ""))}
    except FileNotFoundError:
        return {"attempts": [], "fails": 0, "next_allowed_at": 0.0, "last_result": ""}
    except Exception as e:
        log.error("state file unreadable (%s) - failing closed for %ss", type(e).__name__, MIN_SPACING)
        return {"attempts": [], "fails": 0, "next_allowed_at": time.time() + MIN_SPACING,
                "last_result": "state_unreadable"}


def _save_state(s):
    try:
        _atomic_write(STATE_FILE, json.dumps(s))
    except OSError as e:
        log.warning("could not persist state: %s", type(e).__name__)


def _gate(state, now, force=False):
    """Return None if a login may proceed now, else (reason, retry_after_seconds)."""
    recent = [t for t in state["attempts"] if now - t < 86400]
    state["attempts"] = recent
    if len(recent) >= MAX_PER_DAY:
        return "daily cap reached", int(min(recent) + 86400 - now) + 1
    if not force and now < state["next_allowed_at"]:
        return "rate-limited", int(state["next_allowed_at"] - now) + 1
    return None


def _record(state, now, outcome, posted):
    if posted:
        state["attempts"].append(now)
    state["last_result"] = outcome
    if outcome == "ok":
        state["fails"] = 0
        state["next_allowed_at"] = now + MIN_SPACING
    elif posted:
        state["fails"] += 1
        back = min(MAX_BACKOFF, MIN_SPACING * (2 ** (state["fails"] - 1)))
        state["next_allowed_at"] = now + back
    else:
        state["next_allowed_at"] = now + PRE_POST_RETRY
    _save_state(state)


# ---------------------------------------------------------------------------------------------
# Daemon
# ---------------------------------------------------------------------------------------------
def _read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _answer(request_id, **fields):
    out = {"request_id": request_id, "created_at": time.time()}
    out.update(fields)
    _atomic_write(RESULT_FILE, json.dumps(out))


def _result_id():
    r = _read_json(RESULT_FILE)
    return r.get("request_id") if isinstance(r, dict) else None


def run_daemon(username, password):
    halted = [None]   # in-memory only: cleared by restarting the container
    answered = set()
    creds = bool(username and password)
    if not creds:
        log.error("ICORSI_LOGIN_USERNAME / ICORSI_LOGIN_PASSWORD not set - idling; every request "
                  "will be answered with an error. Set both in Portainer and restart.")
    log.info("icorsi-auth started (handoff dir %s)", AUTH_DIR)
    while True:
        now = time.time()
        try:
            _atomic_write(HEARTBEAT_FILE, str(int(now)))
        except OSError as e:
            log.warning("heartbeat write failed: %s", type(e).__name__)
        try:
            req = _read_json(REQUEST_FILE)
            rid = req.get("request_id") if isinstance(req, dict) else None
            if rid and isinstance(rid, str) and rid not in answered and rid != _result_id():
                answered.add(rid)
                if len(answered) > 100:
                    answered.clear()
                _handle(rid, req, username, password, creds, halted)
        except Exception as e:  # never die: a crash loop must not hammer anything
            log.error("loop error: %s", type(e).__name__)
        time.sleep(POLL_SECONDS)


def _handle(rid, req, username, password, creds, halted_ref):
    now = time.time()
    log.info("login request %s... received (reason=%s)", rid[:8], str(req.get("reason", ""))[:80])
    if not creds:
        return _answer(rid, ok=False, error="icorsi-auth has no ICORSI_LOGIN_USERNAME/PASSWORD configured",
                       retry_after=0)
    if halted_ref[0]:
        return _answer(rid, ok=False, error="halted: invalid login - fix ICORSI_LOGIN_PASSWORD and "
                                            "restart icorsi-auth", retry_after=0)
    try:
        if now - float(req.get("requested_at", now)) > STALE_REQUEST:
            return _answer(rid, ok=False, error="stale request ignored", retry_after=0)
    except (TypeError, ValueError):
        pass
    state = _load_state()
    gate = _gate(state, now)
    if gate:
        log.warning("not logging in: %s (retry in %ss)", gate[0], gate[1])
        prev = _read_json(RESULT_FILE)
        if isinstance(prev, dict) and prev.get("ok") is True and now - float(prev.get("created_at", 0)) < MIN_SPACING:
            keep = {k: v for k, v in prev.items() if k not in ("request_id", "created_at")}
            return _answer(rid, **keep)
        return _answer(rid, ok=False, error=f"{gate[0]}: next attempt allowed in {gate[1]}s",
                       retry_after=gate[1])
    try:
        r = do_login(username, password)
    except LoginFailure as e:
        posted = getattr(e, "posted", False)
        _record(state, now, e.code, posted)
        if e.code == "invalid_login":
            halted_ref[0] = True
            msg = "invalid login: iCorsi rejected the credentials - fix ICORSI_LOGIN_PASSWORD and restart icorsi-auth"
        elif posted and e.code not in ("network_error", "transport_error", "too_many_redirects"):
            halted_ref[0] = True
            msg = f"halted after {e.code}: credentials were submitted but login did not complete - check the " \
                  "account in a browser, then restart icorsi-auth"
        else:
            msg = str(e)
        log.error("login failed: %s", e.code)
        return _answer(rid, ok=False, error=msg[:300],
                       retry_after=max(0, int(state["next_allowed_at"] - time.time())))
    except Exception as e:
        _record(state, now, "exception", True)
        log.error("login failed: %s", type(e).__name__)
        return _answer(rid, ok=False, error="internal error: " + type(e).__name__, retry_after=PRE_POST_RETRY)
    _record(state, now, "ok", True)
    log.info("login ok (parts=%d, privatetoken=%s, session_cookie=%s, wstoken_len=%d)", r["parts"],
             bool(r["privatetoken"]), bool(r["session_cookie"]), len(r["wstoken"]))
    out = dict(ok=True, wstoken=r["wstoken"], privatetoken=r["privatetoken"], parts=r["parts"],
               session_cookie=r["session_cookie"])
    if r["parts"] == 2:
        out["warning"] = "justloggedin not set - no privatetoken"
    _answer(rid, **out)


# ---------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------
def cmd_probe():
    try:
        opener, _ = _new_opener()
        form = _load_login_form(opener)
    except (LoginFailure, GuardError) as e:
        print("FAIL:", e)
        return 1
    print("OK: logged-out launch.php redirects to login/index.php; native form found "
          f"(logintoken length {len(form.fields['logintoken'])}); nothing was submitted")
    return 0


def cmd_once(username, password, force):
    if not (username and password):
        print("FAIL: ICORSI_LOGIN_USERNAME / ICORSI_LOGIN_PASSWORD not set")
        return 1
    state = _load_state()
    now = time.time()
    gate = _gate(state, now, force)
    if gate:
        print(f"REFUSED: {gate[0]} (retry in {gate[1]}s; --force skips the spacing, not the daily cap)")
        return 2
    try:
        r = do_login(username, password)
    except (LoginFailure, GuardError) as e:
        _record(state, now, getattr(e, "code", "guard"), getattr(e, "posted", False))
        print("FAIL:", e)
        return 1
    except Exception as e:
        _record(state, now, "exception", True)
        print("FAIL:", type(e).__name__)
        return 1
    _record(state, now, "ok", True)
    print(f"OK: parts={r['parts']} wstoken_len={len(r['wstoken'])} privatetoken={bool(r['privatetoken'])} "
          f"session_cookie={r['session_cookie']['name'] if r['session_cookie'] else None}")
    return 0


def _drop_root():
    """A root `docker exec` must not create root-owned state: drop to PUID/PGID first."""
    if os.geteuid() == 0:
        try:
            uid, gid = int(os.environ.get("PUID", "1000")), int(os.environ.get("PGID", "1000"))
            os.setgroups([gid])
            os.setgid(gid)
            os.setuid(uid)
        except (ValueError, OSError):
            print("FAIL: cannot drop root privileges")
            sys.exit(1)


def main():
    if "--once" in sys.argv or "--probe" in sys.argv:
        _drop_root()
    username = os.environ.get("ICORSI_LOGIN_USERNAME", "").strip()
    password = os.environ.get("ICORSI_LOGIN_PASSWORD", "")
    if "--probe" in sys.argv:
        sys.exit(cmd_probe())
    if "--once" in sys.argv:
        sys.exit(cmd_once(username, password, "--force" in sys.argv))
    run_daemon(username, password)


if __name__ == "__main__":
    main()

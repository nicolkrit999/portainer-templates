#!/usr/bin/env python3
"""icorsi-auth: the only component that holds the SUPSI Microsoft credentials.

Job: when icorsi-sync drops a request into the shared handoff dir (/auth), perform ONE fresh
login through iCorsi's "SUPSI login" (Moodle auth_oidc -> Microsoft Entra ID -> password -> TOTP)
in headless Chromium and hand back the resulting Moodle mobile wstoken (+ privatetoken + session
cookie). That is all it can do:

  * A fresh browser and context per attempt; nothing is persisted (profile lives in tmpfs).
  * Network allowlist, enforced in three independent layers:
      1. Chromium's own resolver (--host-resolver-rules): only www.icorsi.ch and the Microsoft
         login hosts resolve at all - covers redirect hops, workers, prefetch, websockets.
      2. context.route(): only the allowlisted host+path (+method) pairs are continued, all
         others are aborted and counted by host.
      3. context.on('request'): redirect hops (which route() never sees) are checked; a hop to
         a foreign host fails the attempt (nav_off_allowlist).
  * It never navigates to Office/Outlook/Teams/mysignins/account pages, never clicks through
    consent or account-setup screens (any unknown page => interstitial:<page-id>, halt).
  * Credentials, the TOTP code, tokens and page content are never logged, never put in exception
    text, never screenshotted/traced. Failures log only a fixed-vocabulary code and the host/path
    where the browser stopped. The TOTP secret is never written to disk. The secrets are removed
    from os.environ right after start so no child process (Chromium, Playwright driver) inherits
    them, and the process is made non-dumpable (PR_SET_DUMPABLE=0) so the same-uid Chromium
    processes cannot read /proc/<pid>/environ or /proc/<pid>/mem. Results (tokens) go to /auth/result.json (mode 0600), the same secrets the sync
    container already stores in its own token.json.

Modes:  (default) daemon loop | --probe (navigate to the Microsoft e-mail page, type nothing) |
        --once [--force] (one login now, redacted summary) | --clear-halt |
        --selftest (RFC 6238 vector)
"""

import base64
import binascii
import collections
import contextlib
import ctypes
import fcntl
import hashlib
import hmac
import json
import logging
import os
import re
import struct
import sys
import threading
import time
import types
import urllib.parse

try:
    from playwright.sync_api import Error as PWError
    from playwright.sync_api import sync_playwright
except ImportError:  # keeps py_compile / --selftest usable without the browser stack
    sync_playwright = None
    PWError = Exception

BASE_HOST = "www.icorsi.ch"
BASE = "https://" + BASE_HOST
LOGIN_PATH = "/login/index.php"
LAUNCH_PATH = "/admin/tool/mobile/launch.php"
OIDC_PREFIX = "/auth/oidc/"
OIDC_PATHS = frozenset({"/auth/oidc/", "/auth/oidc/index.php"})   # login entry point + redirect URI only
LAUNCH_URL = BASE + LAUNCH_PATH + "?service=moodle_mobile_app&passport=1&urlscheme=moodlemobile"
OIDC_URL = BASE + OIDC_PREFIX + "?source=loginpage"
LAUNCH_QUERY_KEYS = {"service", "passport", "urlscheme"}

# Microsoft hosts the converged login actually needs (discovered live 2026-10-08). Everything else
# (login.live.com, autologon.microsoftazuread-sso.com, *.events.data.microsoft.com, branding
# images, footer links, analytics.usi.ch ...) is refused.
# login.microsoft.com is the same Entra sign-in service; the real SUPSI flow redirects through it.
MS_LOGIN_HOSTS = frozenset({"login.microsoftonline.com", "login.microsoft.com"})
MS_HOSTS = MS_LOGIN_HOSTS | {"aadcdn.msftauth.net", "aadcdn.msauth.net"}
HOST_RULES = "MAP * ~NOTFOUND, " + ", ".join("EXCLUDE " + h for h in sorted(MS_HOSTS | {BASE_HOST}))
# Hosts whose being aborted would break the login (vs. cosmetic ones such as branding images).
_SUSPECT_SUFFIXES = (".msauth.net", ".msftauth.net", "microsoftonline.com", "login.microsoft.com")

AUTH_DIR = os.environ.get("AUTH_HANDOFF_DIR", "/auth")
REQUEST_FILE = os.path.join(AUTH_DIR, "request.json")
RESULT_FILE = os.path.join(AUTH_DIR, "result.json")
HEARTBEAT_FILE = os.path.join(AUTH_DIR, "heartbeat")
STATE_DIR = os.environ.get("AUTH_STATE_DIR", "/state")
STATE_FILE = os.path.join(STATE_DIR, "sidecar.json")
LOCK_FILE = os.path.join(STATE_DIR, "login.lock")

POLL_SECONDS = 10
TOTAL_TIMEOUT = 150              # whole attempt; icorsi-sync waits AUTH_WAIT_SECONDS (180) for an answer
NAV_TIMEOUT_MS = 30_000
ACTION_TIMEOUT_MS = 15_000
IDLE_INTERSTITIAL = 15           # seconds on a Microsoft page matching no known step => interstitial
TOTP_MIN_REMAIN = 6              # don't submit a code that would expire within this many seconds
MIN_SPACING = 30 * 60            # between credential submissions
MAX_BACKOFF = 6 * 3600           # cap for the doubling backoff after repeated failures
MAX_PER_DAY = 6                  # credential submissions per rolling 24h
MAX_POSTED_FAILS = 2             # consecutive failures after credentials were sent => halt, whatever the code
STUCK_SECONDS = 5                # still on a submitted step this long after Microsoft answered => rejected
PRE_POST_RETRY = 5 * 60          # a failure before any credential was sent (network, site down)
STALE_REQUEST = 3600             # ignore requests older than this

# Failures that need a human: the daemon halts (persisted; lifted by changed credentials or --clear-halt).
HALT_CODES = {"bad_username", "bad_password", "bad_totp", "account_locked",
              "mfa_method_unavailable", "oidc_rejected"}
_ADVICE = {
    "bad_username": "Microsoft does not know ICORSI_MS_USERNAME - fix it in Portainer and run --clear-halt (or change the credential)",
    "bad_password": "Microsoft rejected ICORSI_MS_PASSWORD - fix it in Portainer and run --clear-halt (or change the credential)",
    "bad_totp": "Microsoft rejected the TOTP code twice - check ICORSI_MS_TOTP_SECRET (and the NAS clock), "
                "then run --clear-halt (or change the credential)",
    "account_locked": "the Microsoft account is locked - wait / unlock it in a browser, then run --clear-halt (or change the credential)",
    "mfa_method_unavailable": "Microsoft offers no authenticator-code option - add an Authenticator app method "
                              "with this TOTP secret in Security info, then run --clear-halt (or change the credential)",
    "oidc_rejected": "Microsoft accepted the login but iCorsi refused it - try SUPSI login in a browser, "
                     "then run --clear-halt (or change the credential)",
}

logging.basicConfig(level=logging.DEBUG if os.environ.get("ICORSI_AUTH_DEBUG") == "1" else logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("icorsi-auth")


class LoginFailure(Exception):
    """Carries a short, fixed-vocabulary code - never page content or credentials."""

    def __init__(self, code, detail=""):
        self.code, self.detail = code, detail
        self.posted = False      # True once the password was submitted
        self.where = ""          # host/path where the browser stopped
        super().__init__(code if not detail else f"{code}: {detail}")


# ---------------------------------------------------------------------------------------------
# TOTP (RFC 6238, SHA1, 6 digits, 30 s) - stdlib only
# ---------------------------------------------------------------------------------------------
def decode_totp_secret(secret):
    s = re.sub(r"[\s-]", "", secret or "").upper().rstrip("=")
    if not s:
        raise ValueError("empty")
    key = base64.b32decode(s + "=" * (-len(s) % 8))
    if not key:
        raise ValueError("empty")
    return key


def totp_at(key, counter, digits=6):
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 15
    return str((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** digits).zfill(digits)


def cmd_selftest():
    # RFC 6238 appendix B, SHA1, T=59 -> 94287082 (8 digits); the 6-digit code is its last 6.
    key = b"12345678901234567890"
    ok = totp_at(key, 59 // 30, 8) == "94287082" and totp_at(key, 59 // 30, 6) == "287082"
    ok = ok and decode_totp_secret("gezd gnbv-gy3t qojq") == b"1234567890"
    print("OK: TOTP self-test passed" if ok else "FAIL: TOTP self-test")
    return 0 if ok else 1


# ---------------------------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------------------------
def _split(url):
    try:
        u = urllib.parse.urlsplit(url)
        return u, (u.hostname or "").lower(), u.port
    except ValueError:
        return None, "", None


def url_allowed(url, method="GET"):
    u, host, port = _split(url)
    if u is None or u.scheme != "https" or port not in (None, 443) or u.username or u.password:
        return False
    if host == BASE_HOST:
        if u.path == LAUNCH_PATH:
            return method == "GET" and all(k in LAUNCH_QUERY_KEYS for k, _ in
                                           urllib.parse.parse_qsl(u.query, keep_blank_values=True))
        if u.path == LOGIN_PATH:
            return method == "GET"
        return u.path in OIDC_PATHS and method in ("GET", "POST")
    return host in MS_HOSTS


_GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def _where(page):
    """host + path (no query, no GUIDs) of the page the browser is on - safe to log."""
    try:
        u, host, _ = _split(page.url)
        if not host:
            return (u.scheme + ":" if u else "?")[:20]
        return (host + _GUID.sub("<id>", u.path))[:120]
    except Exception:
        return "?"


def _parse_blob(location):
    if not location or "token=" not in location:
        return None
    try:
        raw = urllib.parse.unquote(location.split("token=", 1)[1]).strip()
        raw = raw.replace("-", "+").replace("_", "/")
        raw += "=" * (-len(raw) % 4)
        decoded = base64.b64decode(raw).decode("utf-8", "ignore")
    except (binascii.Error, ValueError):
        return None
    parts = decoded.split(":::")
    if len(parts) >= 3 and parts[1]:
        return {"wstoken": parts[1], "privatetoken": parts[2] or None, "parts": 3}
    if len(parts) == 2 and parts[1]:
        return {"wstoken": parts[1], "privatetoken": None, "parts": 2}
    return None


# ---------------------------------------------------------------------------------------------
# Browser session
# ---------------------------------------------------------------------------------------------
def _new_state():
    return types.SimpleNamespace(
        aborted=collections.Counter(),   # host -> count of allowlist aborts
        violation="",                    # set when a redirect hop left the allowlist
        token_url=None,                  # moodlemobile://token=... (never logged)
        ms_seen=False, callback=False,   # reached Microsoft / Microsoft posted back to iCorsi
        offpath=False,                   # iCorsi redirected to a page outside the allowlist (e.g. /my/)
        ms_posts=0,                      # POST responses from Microsoft (marks "the server answered")
        posted=False,                    # password was submitted
        deadline=time.monotonic() + TOTAL_TIMEOUT)


def _attach(ctx, page, S):
    def on_route(route):
        try:
            req = route.request
            if url_allowed(req.url, req.method):
                route.continue_()
            else:
                _, host, _p = _split(req.url)
                S.aborted[host or "?"] += 1
                if log.isEnabledFor(logging.DEBUG):
                    u = urllib.parse.urlsplit(req.url)
                    log.debug("aborted %s %s%s", req.method, host, u.path[:80])
                route.abort("blockedbyclient")
        except PWError:
            pass

    def capture(token_url, source_url):
        u, host, _ = _split(source_url)
        if S.token_url is None and u is not None and host == BASE_HOST and u.path == LAUNCH_PATH:
            S.token_url = token_url

    def on_request(req):
        u, host, _ = _split(req.url)
        if req.url.lower().startswith("moodlemobile:"):
            return
        if host in MS_LOGIN_HOSTS:
            S.ms_seen = True
        if host == BASE_HOST and u is not None and u.path.startswith(OIDC_PREFIX) and req.method == "POST":
            S.callback = True
        if req.redirected_from is None:
            return                      # first hop of a chain was already vetted by on_route
        if url_allowed(req.url, req.method):
            return
        if host == BASE_HOST:
            S.offpath = True            # e.g. /my/ instead of launch.php: handled by the flow
        elif not S.violation:
            S.violation = host or "?"

    def on_response(resp):
        try:
            if resp.request.method == "POST" and _split(resp.url)[1] in MS_LOGIN_HOSTS:
                S.ms_posts += 1
        except PWError:
            pass

    def on_failed(req):
        if req.url.lower().startswith("moodlemobile:") and req.redirected_from is not None:
            capture(req.url, req.redirected_from.url)

    def on_cdp(e):
        try:
            url = e["request"]["url"]
            if url.lower().startswith("moodlemobile:"):
                capture(url, (e.get("redirectResponse") or {}).get("url", ""))
        except (KeyError, TypeError):
            pass

    def on_page(p):
        if p is not page:
            try:
                p.close()
            except PWError:
                pass

    ctx.route("**/*", on_route)
    ctx.on("request", on_request)
    ctx.on("response", on_response)
    ctx.on("requestfailed", on_failed)
    ctx.on("page", on_page)
    page.on("dialog", lambda d: d.dismiss())
    cdp = ctx.new_cdp_session(page)
    cdp.send("Network.enable")
    cdp.on("Network.requestWillBeSent", on_cdp)


def _tick(S, page):
    if S.violation:
        raise LoginFailure("nav_off_allowlist", S.violation)
    if time.monotonic() > S.deadline:
        raise LoginFailure("timeout")


def _wait(S, page, ms=400):
    page.wait_for_timeout(ms)           # pumps Playwright events (time.sleep would not)
    _tick(S, page)


def _vis(page, sel):
    try:
        return page.locator(sel).first.is_visible()
    except PWError:
        return False


def _text(page, sel):
    try:
        return page.locator(sel).first.inner_text(timeout=1500).lower()
    except PWError:
        return ""


def _goto(S, page, url, first=False):
    try:
        page.goto(url, wait_until="commit", timeout=NAV_TIMEOUT_MS)
    except PWError as e:
        msg = str(e)                    # in-memory only; the URL here is launch.php/oidc, no secrets
        if first and re.search(r"ERR_(NAME_NOT_RESOLVED|INTERNET_DISCONNECTED|CONNECTION|TIMED_OUT|NETWORK)", msg):
            raise LoginFailure("network_error")
        # ERR_ABORTED / blocked-by-client on a redirect target is normal here; the state loop decides.


def _click(page, sel):
    page.click(sel, timeout=ACTION_TIMEOUT_MS)


_NOT_AUTHENTICATOR = re.compile(r"\b(text|texted|sms|call|called|phone number)\b|\*{2,}|\+\d", re.I)


def _submit_otc(page):
    """The enter-code page's button is #idSubmit_SAOTCC_Continue; the other Entra pages use #idSIButton9."""
    page.locator("#idSubmit_SAOTCC_Continue:visible, #idSIButton9:visible").first.click(timeout=ACTION_TIMEOUT_MS)


def _pgid(page):
    try:
        v = page.evaluate("() => { try { return String((window.$Config && window.$Config.pgid) || '') }"
                          " catch (e) { return '' } }")
        v = re.sub(r"[^A-Za-z0-9_]", "", v or "")[:40]
        return v or "unknown"
    except PWError:
        return "unknown"


class _Seen:
    """How long a condition has been continuously true (debounces stale error banners)."""

    def __init__(self):
        self.t = {}

    def hold(self, key, cond, secs):
        if not cond:
            self.t.pop(key, None)
            return False
        return time.monotonic() - self.t.setdefault(key, time.monotonic()) >= secs


def _bootstrap(S, page):
    """Logged-out launch.php (sets wantsurl) -> login page; returns once /login/index.php is reached."""
    _goto(S, page, LAUNCH_URL, first=True)
    end = min(S.deadline, time.monotonic() + 25)
    while True:
        _tick(S, page)
        if S.token_url:
            raise LoginFailure("unexpected_session")        # launch.php answered without a login
        u, host, _ = _split(page.url)
        if host == BASE_HOST and u.path == LOGIN_PATH:
            break
        if time.monotonic() > end:
            raise LoginFailure("no_login_redirect")
        page.wait_for_timeout(300)
    _goto(S, page, OIDC_URL)


def _drive(S, page, ctx, creds, probe):
    _bootstrap(S, page)
    st = types.SimpleNamespace(email=False, pw=False, otc=0, otc_counter=-1, marker=0, another=False,
                               proof=False, kmsi=False, fb=False, since={}, seen=_Seen())
    probe_end = time.monotonic() + 45
    st_last = [None]

    def next_code():
        while True:
            now = time.time()
            counter = int(now // 30)
            if counter > st.otc_counter and 30 - (now % 30) >= TOTP_MIN_REMAIN:
                st.otc_counter = counter
                return totp_at(creds.totp_key, counter)
            _wait(S, page, 500)

    while True:
        _tick(S, page)
        if S.token_url:
            break
        if S.offpath:
            S.offpath = False
            if not S.ms_seen:
                raise LoginFailure("unexpected_page")
            if st.fb:
                raise LoginFailure("no_token_redirect")
            st.fb = True                # wantsurl lost through OIDC: request launch.php once more
            _goto(S, page, LAUNCH_URL)
            continue
        u, host, _ = _split(page.url)

        if host == BASE_HOST:
            on_launch = u.path == LAUNCH_PATH
            on_login = u.path == LOGIN_PATH and S.callback
            if st.seen.hold("launch", on_launch, 10):
                raise LoginFailure("no_token_redirect")
            if st.seen.hold("login", on_login, 4):
                raise LoginFailure("oidc_rejected", "")
            if st.seen.hold("oidcpage", S.callback and u.path.startswith(OIDC_PREFIX), 10):
                raise LoginFailure("oidc_rejected", "")
            _wait(S, page)
            continue

        if host not in MS_LOGIN_HOSTS:
            if st.seen.hold("foreign", True, 12):
                raise LoginFailure("unexpected_page")
            _wait(S, page)
            continue
        st.seen.hold("foreign", False, 0)

        fresh = S.ms_posts > st.marker

        # --- which step is on screen (most specific first)
        step = None
        if _vis(page, "input#idTxtBx_SAOTCC_OTC"):
            step = "otc"
        elif _vis(page, "input#i0118:not(.moveOffScreen)"):
            step = "password"
        elif _vis(page, "input#i0116"):
            step = "email"
        elif _vis(page, '[data-value="PhoneAppOTP"]'):
            step = "proof_otp"
        elif _vis(page, "#signInAnotherWay"):
            step = "another"
        elif _vis(page, "#idBtn_Back") and "stay signed in" in _text(page, "body"):
            step = "kmsi"
        if step and step != st_last[0]:
            st_last[0] = step
            log.info("login step: %s", step)

        # Probe mode stops here, before any branch that could type or click.
        if probe:
            if step == "email":
                return {"probe": True}
            if time.monotonic() > probe_end:
                raise LoginFailure("timeout")
            _wait(S, page)
            continue

        # --- credential / MFA errors (only meaningful after the server answered our submit).
        # Fail closed: Microsoft answered but we are still on the step we submitted => rejected,
        # even when the error banner's element id is not the one we know.
        if st.email and _vis(page, "#usernameError"):
            raise LoginFailure("bad_username")
        if st.pw and fresh:
            pw_stuck = step == "password" and st.seen.hold("pwstuck", True, STUCK_SECONDS)
            if st.seen.hold("pwerr", _vis(page, "#passwordError"), 1.2) or pw_stuck:
                raise LoginFailure("account_locked" if "locked" in _text(page, "#passwordError")
                                   else "bad_password")
        if st.otc and fresh:
            otc_stuck = step == "otc" and st.seen.hold("otcstuck", True, STUCK_SECONDS)
            if st.seen.hold("otcerr", _vis(page, "#idSpan_SAOTCC_Error_OTC"), 1.2) or otc_stuck:
                if "locked" in _text(page, "#idSpan_SAOTCC_Error_OTC"):
                    raise LoginFailure("account_locked")
                if st.otc >= 2:
                    raise LoginFailure("bad_totp")
                code = next_code()      # first code rejected: retry once with the NEXT window's code
                page.fill("input[name=otc]", code, timeout=ACTION_TIMEOUT_MS)
                st.otc, st.marker = 2, S.ms_posts
                st.seen.hold("otcerr", False, 0)
                st.seen.hold("otcstuck", False, 0)
                _submit_otc(page)
                del code
                continue
        if not (st.pw and fresh and step == "password"):
            st.seen.hold("pwstuck", False, 0)
        if not (st.otc and fresh and step == "otc"):
            st.seen.hold("otcstuck", False, 0)

        # --- the code box may belong to SMS / voice rather than the authenticator app: never type a TOTP there
        if step == "otc" and st.otc == 0:
            desc = _text(page, "#idDiv_SAOTCC_Description")
            if desc and _NOT_AUTHENTICATOR.search(desc):
                if not st.another:
                    st.another = True
                    _click(page, "#signInAnotherWay")
                elif st.seen.hold("smsotc", True, 12):
                    raise LoginFailure("mfa_method_unavailable")
                _wait(S, page)
                continue
            st.seen.hold("smsotc", False, 0)

        if step == "email" and not st.email and not probe:
            page.fill("input#i0116", creds.username, timeout=ACTION_TIMEOUT_MS)
            st.email, st.marker = True, S.ms_posts
            _click(page, "#idSIButton9")
        elif step == "password" and st.email and not st.pw:
            page.fill("input#i0118", creds.password, timeout=ACTION_TIMEOUT_MS)
            st.pw, S.posted, st.marker = True, True, S.ms_posts
            _click(page, "#idSIButton9")
        elif step == "otc" and st.otc == 0:
            code = next_code()
            page.fill("input[name=otc]", code, timeout=ACTION_TIMEOUT_MS)
            st.otc, st.marker = 1, S.ms_posts
            _submit_otc(page)
            del code
        elif step == "another" and not st.another:
            st.another = True
            _click(page, "#signInAnotherWay")
        elif step == "proof_otp" and not st.proof:
            st.proof = True
            _click(page, '[data-value="PhoneAppOTP"]')
        elif step == "kmsi" and not st.kmsi:
            st.kmsi = True
            _click(page, "#idBtn_Back")     # "Stay signed in?" -> No
        elif step is None:
            if st.pw and st.another and not st.proof and _vis(page, "[data-value]"):
                raise LoginFailure("mfa_method_unavailable")        # proof list without authenticator code
            if st.pw and "proofup" in _pgid(page).lower():
                raise LoginFailure("interstitial:" + _pgid(page))
            if st.seen.hold("idle", True, IDLE_INTERSTITIAL):
                raise LoginFailure("interstitial:" + _pgid(page))
        else:
            st.seen.hold("idle", False, 0)
        if step is not None:
            st.seen.hold("idle", False, 0)
            # an MFA choice that stays on screen long after we clicked it => option not usable
            if (step == "another" and st.another and st.seen.hold("another", True, 12)) or \
               (step == "proof_otp" and st.proof and st.seen.hold("proof", True, 12)):
                raise LoginFailure("mfa_method_unavailable")
        _wait(S, page)

    blob = _parse_blob(S.token_url)
    S.token_url = None
    if not blob:
        raise LoginFailure("unparseable_token_blob")
    sess = None
    for c in ctx.cookies(BASE):
        if c.get("name", "").startswith("MoodleSession"):
            sess = {"name": c["name"], "value": c["value"]}
            break
    blob["session_cookie"] = sess
    blob["fallback_launch"] = st.fb
    return blob


def do_login(creds, probe=False):
    """One full login (or, with probe=True, a no-typing reachability check). Returns a dict plus
    `aborted_hosts`; raises LoginFailure with `.posted` / `.where` set."""
    if sync_playwright is None:
        raise LoginFailure("playwright_missing")
    S = _new_state()
    page = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, chromium_sandbox=False, timeout=NAV_TIMEOUT_MS,
                                        args=[f"--host-resolver-rules={HOST_RULES}",
                                              "--disable-background-networking", "--disable-breakpad",
                                              "--disable-domain-reliability", "--mute-audio",
                                              "--disable-dev-shm-usage"])
            try:
                ver = browser.version or "0.0.0.0"
                ua = (f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                      f"Chrome/{ver} Safari/537.36")
                ctx = browser.new_context(service_workers="block", accept_downloads=False, locale="en-US",
                                          user_agent=ua, viewport={"width": 1024, "height": 768})
                try:
                    ctx.set_default_timeout(ACTION_TIMEOUT_MS)
                    ctx.set_default_navigation_timeout(NAV_TIMEOUT_MS)
                    page = ctx.new_page()
                    _attach(ctx, page, S)
                    try:
                        res = _drive(S, page, ctx, creds, probe)
                    except LoginFailure as e:
                        e.where, e.posted = _where(page), S.posted
                        if e.code in ("timeout", "no_token_redirect", "unexpected_page", "no_login_redirect"):
                            bad = sorted(h for h in S.aborted if h.endswith(_SUSPECT_SUFFIXES))
                            if bad:
                                new = LoginFailure("blocked_required_host:" + bad[0])
                                new.where, new.posted = e.where, e.posted
                                raise new from None
                        raise
                    except PWError as e:
                        err = LoginFailure("browser_error", type(e).__name__)   # message may echo page data
                        err.where, err.posted = _where(page), S.posted
                        raise err from None
                    res["aborted_hosts"] = dict(S.aborted)
                    return res
                finally:
                    ctx.close()
            finally:
                browser.close()
    except LoginFailure:
        raise
    except PWError as e:
        err = LoginFailure("browser_error", type(e).__name__)
        err.posted = S.posted
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
                "last_result": str(s.get("last_result", "")),
                "halted": str(s.get("halted", "")), "halt_fp": str(s.get("halt_fp", ""))}
    except FileNotFoundError:
        return {"attempts": [], "fails": 0, "next_allowed_at": 0.0, "last_result": "",
                "halted": "", "halt_fp": ""}
    except Exception as e:
        log.error("state file unreadable (%s) - failing closed for %ss", type(e).__name__, MIN_SPACING)
        return {"attempts": [], "fails": 0, "next_allowed_at": time.time() + MIN_SPACING,
                "last_result": "state_unreadable", "halted": "", "halt_fp": ""}


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


def _should_halt(code):
    return code in HALT_CODES or code.startswith(("interstitial:", "blocked_required_host:"))


def _apply_failure(state, creds, code, posted):
    """After _record(): persist a halt for human-needed codes, or after MAX_POSTED_FAILS consecutive
    failures that happened after credentials were sent. Returns the halt reason or ''."""
    if _should_halt(code):
        reason = code
    elif posted and state["fails"] >= MAX_POSTED_FAILS:
        reason = "repeated_failures:" + code.split(":", 1)[0]
    else:
        return ""
    state["halted"], state["halt_fp"] = reason, getattr(creds, "fp", "")
    _save_state(state)
    return reason


def _lift_stale_halt(state, creds):
    """A persisted halt survives restarts; it is lifted only when the credentials changed."""
    if state["halted"] and creds and state["halt_fp"] and creds.fp != state["halt_fp"]:
        log.info("credentials changed since the halt (%s) - resuming", state["halted"])
        state["halted"], state["halt_fp"] = "", ""
        state["fails"], state["next_allowed_at"] = 0, 0.0
        _save_state(state)


@contextlib.contextmanager
def _login_lock():
    """Exclusive, non-blocking lock so the daemon and a `docker exec --once` never log in concurrently."""
    fd = None
    try:
        fd = os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        if fd is not None:
            os.close(fd)
        yield False
        return
    except OSError:
        if fd is not None:
            os.close(fd)
        yield True      # no usable lock file (e.g. /state not writable): rate-limit state is unusable anyway
        return
    try:
        yield True
    finally:
        os.close(fd)    # closing releases the flock


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


def _heartbeat_loop():
    """Own thread: the heartbeat must keep ticking while a (slow) browser login blocks the main loop."""
    while True:
        try:
            _atomic_write(HEARTBEAT_FILE, str(int(time.time())))
        except OSError as e:
            log.warning("heartbeat write failed: %s", type(e).__name__)
        time.sleep(POLL_SECONDS)


def run_daemon(creds, problem):
    answered = set()
    if not creds:
        log.error("%s - idling; every request will be answered with an error. Fix it in Portainer "
                  "and restart.", problem)
    st0 = _load_state()
    _lift_stale_halt(st0, creds)
    if st0["halted"]:
        log.error("halted after %s (persisted): %s", st0["halted"], _advice(st0["halted"]))
    threading.Thread(target=_heartbeat_loop, daemon=True).start()
    log.info("icorsi-auth started (handoff dir %s)", AUTH_DIR)
    while True:
        try:
            req = _read_json(REQUEST_FILE)
            rid = req.get("request_id") if isinstance(req, dict) else None
            if rid and isinstance(rid, str) and rid not in answered and rid != _result_id():
                answered.add(rid)
                if len(answered) > 100:
                    answered.clear()
                _handle(rid, req, creds, problem)
        except Exception as e:  # never die: a crash loop must not hammer anything
            log.error("loop error: %s", type(e).__name__)
        time.sleep(POLL_SECONDS)


def _handle(rid, req, creds, problem):
    now = time.time()
    log.info("login request %s... received (reason=%s)", rid[:8], str(req.get("reason", ""))[:80])
    if not creds:
        return _answer(rid, ok=False, error=f"icorsi-auth is not configured: {problem}", retry_after=0)
    try:
        if now - float(req.get("requested_at", now)) > STALE_REQUEST:
            return _answer(rid, ok=False, error="stale request ignored", retry_after=0)
    except (TypeError, ValueError):
        pass
    with _login_lock() as got:
        if not got:
            return _answer(rid, ok=False, error="another login is in progress in icorsi-auth", retry_after=60)
        state = _load_state()
        _lift_stale_halt(state, creds)
        if state["halted"]:
            return _answer(rid, ok=False, error=f"halted after {state['halted']}: {_advice(state['halted'])}"[:300],
                           retry_after=0)
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
            r = do_login(creds)
        except LoginFailure as e:
            _record(state, now, e.code, e.posted)
            log.error("login failed: %s (stopped at %s)", e.code, e.where or "?")
            halt = _apply_failure(state, creds, e.code, e.posted)
            if halt:
                log.error("halting: %s", halt)
                msg = f"halted after {halt}: {_advice(halt)}"
            else:
                msg = f"login failed: {e.code}" + (f" at {e.where}" if e.where else "")
            return _answer(rid, ok=False, error=msg[:300],
                           retry_after=max(0, int(state["next_allowed_at"] - time.time())))
        except Exception as e:
            _record(state, now, "exception", True)
            log.error("login failed: %s", type(e).__name__)
            halt = _apply_failure(state, creds, "exception", True)
            msg = "internal error: " + type(e).__name__ + (f" - halted after {halt}" if halt else "")
            return _answer(rid, ok=False, error=msg, retry_after=PRE_POST_RETRY)
        _record(state, now, "ok", True)
    log.info("login ok (parts=%d, privatetoken=%s, session_cookie=%s, wstoken_len=%d, relaunched_launch_php=%s)",
             r["parts"], bool(r["privatetoken"]), bool(r["session_cookie"]), len(r["wstoken"]),
             r["fallback_launch"])
    out = dict(ok=True, wstoken=r["wstoken"], privatetoken=r["privatetoken"], parts=r["parts"],
               session_cookie=r["session_cookie"])
    if r["parts"] == 2:
        out["warning"] = "justloggedin not set - no privatetoken"
    _answer(rid, **out)


def _advice(code):
    base = code.split(":", 1)[0]
    if base == "repeated_failures":
        return ("two consecutive logins failed after the credentials were sent (" + code.split(":", 1)[-1] +
                ") - check `docker logs icorsi-auth` and sign in once in a browser, then run --clear-halt (or change the credential)")
    if base == "interstitial":
        return ("Microsoft showed an unexpected page (" + code + ") - sign in once in a browser to clear it "
                "(MFA registration, password change, consent...), then run --clear-halt (or change the credential)")
    if base == "blocked_required_host":
        return "the network allowlist blocked a host the login needs (" + code + ") - the sidecar needs an update"
    return _ADVICE.get(code, "see `docker logs icorsi-auth`, then run --clear-halt (or change the credential)")


# ---------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------
def cmd_probe():
    """Reach the Microsoft e-mail page through the real allowlist; types nothing, needs no credentials."""
    try:
        r = do_login(None, probe=True)
    except LoginFailure as e:
        print(f"FAIL: {e.code} (stopped at {e.where or '?'})")
        return 1
    aborted = ", ".join(f"{h} x{n}" for h, n in sorted(r["aborted_hosts"].items())) or "none"
    print("OK: launch.php -> login page -> /auth/oidc/ -> Microsoft e-mail field reached; nothing typed")
    print("allowlist aborted hosts: " + aborted)
    return 0


def cmd_once(creds, problem, force):
    if not creds:
        print("FAIL:", problem)
        return 1
    with _login_lock() as got:
        if not got:
            print("REFUSED: login in progress")
            return 2
        state = _load_state()
        _lift_stale_halt(state, creds)
        if state["halted"]:
            print(f"REFUSED: halted after {state['halted']} (fix the cause, then run --clear-halt)")
            return 2
        now = time.time()
        gate = _gate(state, now, force)
        if gate:
            print(f"REFUSED: {gate[0]} (retry in {gate[1]}s; --force skips the spacing, not the daily cap)")
            return 2
        try:
            r = do_login(creds)
        except LoginFailure as e:
            _record(state, now, e.code, e.posted)
            halt = _apply_failure(state, creds, e.code, e.posted)
            print(f"FAIL: {e.code} (stopped at {e.where or '?'})"
                  + (f" - daemon halted ({halt}) until credentials change or --clear-halt" if halt else ""))
            return 1
        except Exception as e:
            _record(state, now, "exception", True)
            _apply_failure(state, creds, "exception", True)
            print("FAIL:", type(e).__name__)
            return 1
        _record(state, now, "ok", True)
    print(f"OK: parts={r['parts']} wstoken_len={len(r['wstoken'])} privatetoken={bool(r['privatetoken'])} "
          f"session_cookie={r['session_cookie']['name'] if r['session_cookie'] else None} "
          f"relaunched_launch_php={r['fallback_launch']}")
    return 0


def cmd_clear_halt():
    with _login_lock() as got:
        if not got:
            print("REFUSED: login in progress")
            return 2
        state = _load_state()
        was = state["halted"]
        state["halted"], state["halt_fp"], state["fails"], state["next_allowed_at"] = "", "", 0, 0.0
        _save_state(state)
    print(f"OK: cleared halt ({was})" if was else "OK: was not halted")
    return 0


def _harden():
    """PR_SET_DUMPABLE=0: /proc/<pid>/environ and /mem become root-owned, so the same-uid Chromium
    processes cannot read the secrets that execve left in this process's environment block."""
    try:
        ctypes.CDLL(None).prctl(4, 0, 0, 0, 0)
    except (OSError, AttributeError):
        log.warning("could not make the process non-dumpable")


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
    _harden()


def _load_creds():
    """Read and REMOVE the secrets from the environment so no child process inherits them."""
    username = os.environ.pop("ICORSI_MS_USERNAME", "").strip()
    password = os.environ.pop("ICORSI_MS_PASSWORD", "")
    secret = os.environ.pop("ICORSI_MS_TOTP_SECRET", "")
    if not (username and password and secret.strip()):
        return None, "ICORSI_MS_USERNAME / ICORSI_MS_PASSWORD / ICORSI_MS_TOTP_SECRET not all set"
    for v in (username, password):
        if v.lower().startswith("your-") and "-here" in v.lower():
            return None, "ICORSI_MS_* still holds the .env.example placeholder"
    try:
        key = decode_totp_secret(secret)
    except (binascii.Error, ValueError):
        return None, "ICORSI_MS_TOTP_SECRET is not valid base32"
    fp = hashlib.sha256(b"\0".join(x.encode() for x in (username, password, secret))).hexdigest()[:4]
    return types.SimpleNamespace(username=username, password=password, totp_key=key, fp=fp), ""


def main():
    if "--selftest" in sys.argv:
        sys.exit(cmd_selftest())
    _harden()
    if "--once" in sys.argv or "--probe" in sys.argv or "--clear-halt" in sys.argv:
        _drop_root()
    creds, problem = _load_creds()
    if "--clear-halt" in sys.argv:
        sys.exit(cmd_clear_halt())
    if "--probe" in sys.argv:
        sys.exit(cmd_probe())
    if "--once" in sys.argv:
        sys.exit(cmd_once(creds, problem, "--force" in sys.argv))
    run_daemon(creds, problem)


if __name__ == "__main__":
    main()

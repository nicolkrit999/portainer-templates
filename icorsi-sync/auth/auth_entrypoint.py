#!/usr/bin/env python3
"""Drop-privileges entrypoint for icorsi-auth (stdlib only).

Starts as root only long enough to make the bind-mounted /auth handoff dir and the sidecar-only /state dir owned by PUID/PGID
(mode 0700), then permanently drops to that user and execs icorsi_auth.py. Only /auth and /state are touched.
"""

import os
import sys


def _int_env(name, default):
    val = (os.environ.get(name) or "").strip()
    try:
        return int(val)
    except ValueError:
        return default


PUID = _int_env("PUID", 1000)
PGID = _int_env("PGID", 1000)
AUTH = os.environ.get("AUTH_HANDOFF_DIR", "/auth")
STATE = os.environ.get("AUTH_STATE_DIR", "/state")


def _chown_tree(path):
    try:
        os.chown(path, PUID, PGID)
        for root, dirs, files in os.walk(path):
            for name in dirs + files:
                try:
                    os.chown(os.path.join(root, name), PUID, PGID)
                except OSError:
                    pass
    except OSError:
        pass


def main():
    if os.geteuid() == 0:
        for d in (AUTH, STATE):
            if os.path.isdir(d):
                _chown_tree(d)
                try:
                    os.chmod(d, 0o700)
                except OSError:
                    pass
        try:
            os.setgroups([PGID])
        except OSError:
            pass
        os.setgid(PGID)
        os.setuid(PUID)
    os.environ["HOME"] = "/tmp"
    os.execvp(sys.executable, [sys.executable, "/app/icorsi_auth.py"])


if __name__ == "__main__":
    main()

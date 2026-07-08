#!/usr/bin/env python3
"""Drop-privileges entrypoint (stdlib only).

The container starts as root only long enough to make the bind-mounted /data
writable by the unprivileged runtime user, then permanently drops to PUID/PGID
and execs the sync process. This keeps the app off root while still working with
a host directory owned by whatever uid the deployer uses.
"""

import os
import sys
import shutil

def _int_env(name, default):
    # Treat unset AND present-but-empty (e.g. compose passing an undefined "${PUID}") as default.
    val = (os.environ.get(name) or "").strip()
    try:
        return int(val)
    except ValueError:
        return default


PUID = _int_env("PUID", 1000)
PGID = _int_env("PGID", 1000)
DATA = os.environ.get("STATE_DIR", "/data")
TMPDIR = os.environ.get("TMPDIR", os.path.join(DATA, "tmp"))


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
    os.makedirs(DATA, exist_ok=True)
    # Purge TMPDIR on every start so download temps left by a SIGKILL/OOM/crash (not just a
    # clean exit) never accumulate, then recreate it fresh.
    shutil.rmtree(TMPDIR, ignore_errors=True)
    os.makedirs(TMPDIR, exist_ok=True)
    if os.geteuid() == 0:
        _chown_tree(DATA)
        # Drop root's supplementary groups BEFORE setgid/setuid, while still privileged -
        # otherwise the process would keep root's group memberships after dropping.
        try:
            os.setgroups([PGID])
        except OSError:
            pass
        os.setgid(PGID)
        os.setuid(PUID)
    os.environ.setdefault("HOME", DATA)
    os.execvp(sys.executable, [sys.executable, "/app/sync.py"])


if __name__ == "__main__":
    main()

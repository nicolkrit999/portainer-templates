#!/bin/bash
set -e

# ── 1. ownCloud trusted-domain fix ──────────────────────────────────────────
# ownCloud rejects requests whose Host header is not a configured trusted domain.
# When hitting the container directly (http://owncloud:8080), the Host header
# would be "owncloud:8080" which is not trusted. We fix this by:
#   a) resolving the internal hostname to an IP via DNS
#   b) adding the trusted domain → same IP in /etc/hosts
#   c) watch.py rewrites the WebDAV URL to use the trusted domain as host
# Result: TCP connects to the real container, but Host header = trusted domain.
if [ -n "$OWNCLOUD_HOST_HEADER" ] && [ -n "$OWNCLOUD_WEBDAV_URL" ]; then
    OC_HOSTNAME=$(python3 -c "from urllib.parse import urlparse; print(urlparse('$OWNCLOUD_WEBDAV_URL').hostname)")
    OC_IP=$(getent hosts "$OC_HOSTNAME" 2>/dev/null | awk '{print $1; exit}')
    if [ -n "$OC_IP" ]; then
        echo "# icorsi-notes trusted-domain mapping" >> /etc/hosts
        echo "$OC_IP  $OWNCLOUD_HOST_HEADER" >> /etc/hosts
        echo "[entrypoint] /etc/hosts: $OWNCLOUD_HOST_HEADER -> $OC_IP (via $OC_HOSTNAME)"
    else
        echo "[entrypoint] WARNING: could not resolve '$OC_HOSTNAME'; Host header may cause 400s" >&2
    fi
fi

# ── 2. Merge baked agents/skills into the mounted ~/.claude volume ───────────
# The volume persists the OAuth subscription token across restarts.
# We copy our baked config (agents, skills, CLAUDE.md, MCP) into it without
# overwriting anything already there (credentials, user edits).
if [ -d /opt/claude-home ]; then
    cp -rn /opt/claude-home/. /root/.claude/
    echo "[entrypoint] Merged /opt/claude-home -> /root/.claude (no-overwrite)"
fi

exec python3 /app/watch.py

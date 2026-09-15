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

# ── 3. Self-heal the Claude Code main state file ────────────────────────────
# CLAUDE_CONFIG_DIR (set in the Dockerfile) keeps .claude.json inside the volume.
# If it is missing anyway - first boot on the new image after the file used to
# live at the ephemeral /root/.claude.json, or a volume that only has the CLI's
# own backups/ - restore it, otherwise `claude -p` exits 1 on every course with
# "Claude configuration file not found ... A backup file exists".
# Preference: legacy /root/.claude.json (freshest state) > newest parseable backup.
CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-/root/.claude}"
export CLAUDE_CONFIG_DIR
CLAUDE_STATE="$CLAUDE_CONFIG_DIR/.claude.json"
if [ ! -s "$CLAUDE_STATE" ]; then
    if [ -s /root/.claude.json ] && [ "$CLAUDE_STATE" != /root/.claude.json ]; then
        mv /root/.claude.json "$CLAUDE_STATE"
        echo "[entrypoint] Moved legacy /root/.claude.json -> $CLAUDE_STATE"
    else
        restored=""
        for b in $(ls -t "$CLAUDE_CONFIG_DIR"/backups/.claude.json.backup.* 2>/dev/null); do
            if python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$b" 2>/dev/null; then
                cp "$b" "$CLAUDE_STATE"
                restored="$b"
                break
            fi
        done
        if [ -n "$restored" ]; then
            echo "[entrypoint] Restored $CLAUDE_STATE from backup $restored"
        else
            echo "[entrypoint] WARNING: $CLAUDE_STATE missing and no usable backup found." >&2
            echo "[entrypoint]          Run: docker exec -it icorsi-notes claude   (and log in once)" >&2
        fi
    fi
fi

exec python3 /app/watch.py

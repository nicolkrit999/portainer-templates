FROM node:22-slim

# System packages:
#   fuse3      - FUSE kernel interface required by rclone mount
#   python3    - the watch.py daemon
#   curl       - rclone installer
#   ca-certificates - TLS roots (WebDAV + npm)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    fuse3 \
    python3 \
    && curl -sSL https://rclone.org/install.sh | bash \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI (npm package; Node 22 already in base image)
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /app

# Baked-in ~/.claude content: agents, skills, global CLAUDE.md, MCP config.
# entrypoint.sh merges this into the mounted ~/.claude volume (no-overwrite),
# so OAuth credentials written by `claude login` survive image rebuilds.
COPY claude-home/ /opt/claude-home/

# Application
COPY entrypoint.sh /entrypoint.sh
COPY watch.py prompt.md courses.example.json /app/

RUN chmod +x /entrypoint.sh

# FUSE requires /dev/fuse + cap_add: SYS_ADMIN (set in compose, not here)
# Uncomment user_allow_other in fuse config so rclone mount works as root:
RUN sed -i 's/#user_allow_other/user_allow_other/' /etc/fuse.conf || true

CMD ["/entrypoint.sh"]

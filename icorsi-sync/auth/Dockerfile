# python:3.12-slim (3.12.13-slim-trixie, Debian 13) - pinned by digest (same digest as ../Dockerfile)
FROM python@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    XDG_CONFIG_HOME=/tmp/.config \
    PUID=1000 \
    PGID=1000 \
    AUTH_HANDOFF_DIR=/auth

# Playwright 1.63.0 pins the browser revision (Chrome 153); bump only this version to upgrade.
# Headless shell only (no full Chrome / firefox / webkit): --with-deps installs the Debian 13
# libraries + fonts it needs. ffmpeg is only used for video recording, which is never enabled.
RUN pip install playwright==1.63.0 \
 && playwright install --with-deps --only-shell chromium \
 && rm -rf /ms-playwright/ffmpeg-* /var/lib/apt/lists/* /root/.cache \
 && chmod -R a+rX /ms-playwright

WORKDIR /app
# Only the sidecar code: sync.py and the course map are deliberately NOT in this image.
COPY icorsi_auth.py auth_entrypoint.py ./
# Runs as an unprivileged PUID/PGID chosen at runtime -> baked-in code must be world-readable.
RUN chmod -R a+rX /app

# Playwright is the only third-party dependency; the Chromium sandbox is off (see README).
CMD ["python", "/app/auth_entrypoint.py"]

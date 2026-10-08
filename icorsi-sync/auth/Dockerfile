# python:3.12-slim - pinned by digest for reproducible builds (same digest as ../Dockerfile)
FROM python@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PUID=1000 \
    PGID=1000 \
    AUTH_HANDOFF_DIR=/auth

WORKDIR /app
# Only the sidecar code: sync.py and the course map are deliberately NOT in this image.
COPY icorsi_auth.py auth_entrypoint.py ./
# Runs as an unprivileged PUID/PGID chosen at runtime -> baked-in code must be world-readable.
RUN chmod -R a+rX /app

# stdlib only - no pip deps
CMD ["python", "/app/auth_entrypoint.py"]

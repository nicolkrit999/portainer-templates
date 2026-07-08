# python:3.12-slim - pinned by digest for reproducible builds
FROM python@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf

ENV PYTHONUNBUFFERED=1 \
    TZ=Europe/Zurich \
    PUID=1000 \
    PGID=1000 \
    STATE_DIR=/data \
    TMPDIR=/data/tmp

WORKDIR /app
# Only code + template are baked in. The REAL course map is provided at runtime
# via the private volume at /data/courses.json.
COPY sync.py entrypoint.py courses.example.json ./
# The app runs as an unprivileged PUID/PGID chosen at runtime, so the baked-in code must be
# world-readable + the dir traversable (can't chown to an unknown-at-build uid). a+rX = read
# for files, execute/traverse for dirs.
RUN chmod -R a+rX /app

# Large downloads stream through TMPDIR (=/data/tmp), off the container writable layer.
# The entrypoint starts as root, chowns the bind-mounted /data to PUID/PGID, then
# drops privileges and execs sync.py - so the app never runs as root.
# stdlib only - no pip deps
CMD ["python", "/app/entrypoint.py"]

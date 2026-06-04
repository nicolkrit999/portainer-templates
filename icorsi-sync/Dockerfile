FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    TZ=Europe/Zurich

WORKDIR /app
# Only code + template are baked in. The REAL course map is provided at runtime
# via the private volume at /data/courses.json.
COPY sync.py courses.example.json ./

# stdlib only — no pip deps
CMD ["python", "sync.py"]

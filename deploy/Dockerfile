# Scratch vertical slice: minimal production-style image for the sensor demo.
# Two layers: (1) application code, (2) runtime environment + entrypoint.
FROM python:3.12-slim

# Layer 1 — application code only (no tests, no caches).
COPY backend/__init__.py /app/backend/__init__.py
COPY backend/engine.py /app/backend/engine.py

# Layer 2 — runtime configuration and demo entrypoint (readings on stdout).
WORKDIR /app
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "backend.engine"]

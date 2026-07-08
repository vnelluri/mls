# ============================================================================
# CI/deploy image only -- local dev NEVER needs Docker (use scripts/dev.py).
# Multi-stage: base -> dev (adds moto for integration tests) -> prod (default).
# ============================================================================

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8
WORKDIR /srv/app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

# ---- dev: CI integration tests (moto emulator available) --------------------
FROM base AS dev
COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY scripts ./scripts
USER nobody
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---- prod: minimal, non-root, healthchecked (moto NEVER installed here) -----
FROM base AS prod
RUN addgroup --system mlserv && adduser --system --ingroup mlserv mlserv
USER mlserv
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=15s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)" || exit 1
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim AS builder

# The venv is copied whole into the runtime stage, so uv itself never ships
ENV PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /usr/local/bin/uv

# --locked fails the build if uv.lock and pyproject.toml disagree, so the image
# never resolves a dependency the test run did not see.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project && rm -rf /root/.cache

# Copy full source and install (hatchling needs source for metadata)
COPY . .
# CI resolves the version and passes it as VERSION (.git is excluded from the build context)
ARG VERSION=0.0.0
# The pretend-version is set here, not on the dependency layer, so it cannot leak
# into a dependency that builds from an sdist with setuptools-scm.
RUN SETUPTOOLS_SCM_PRETEND_VERSION="${VERSION#v}" uv sync --locked --no-dev && \
    rm -rf /root/.cache

# The project is an editable install, which UV_COMPILE_BYTECODE skips
RUN python -m compileall -q /app

FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app

# The editable install points at /app, so both trees keep their builder paths
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app

# uid 200 cannot write __pycache__ into these root-owned trees, so the build fails
# here unless the builder baked it. pip is only an installer, so it is removed.
RUN python -c "import importlib.util, os, sys, httpx; missing = [p for p in map(importlib.util.cache_from_source, (httpx.__file__, '/app/server.py')) if not os.path.exists(p)]; sys.exit(f'bytecode missing: {missing}' if missing else 0)" && \
    /usr/local/bin/python -m pip uninstall -y -q pip

# Default token path is /home/alpacon/.alpacon-mcp/token.json, not under /root
RUN addgroup --system --gid 200 alpacon && \
    adduser --system --uid 200 --gid 200 --home /home/alpacon --shell /usr/sbin/nologin alpacon && \
    mkdir -p /app/logs /app/config && \
    chown -R alpacon:alpacon /app/logs /app/config /home/alpacon

USER alpacon

# Default port (MCAR - MCP Alpacon Remote)
EXPOSE 8237

# Health check using the built-in /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; r = httpx.get('http://localhost:8237/health'); r.raise_for_status()" || exit 1

# HTTP streamable transport with JWT auth (sets host=0.0.0.0 internally)
CMD ["python", "main_http.py"]

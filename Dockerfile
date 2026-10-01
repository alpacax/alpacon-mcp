FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    UV_COMPILE_BYTECODE=1

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

# uid 200 cannot write __pycache__ into this root-owned tree, so bytecode is baked
# here. The project is an editable install, which UV_COMPILE_BYTECODE skips.
RUN python -m compileall -q /app && \
    python -c "import importlib.util, os, sys, httpx; missing = [p for p in map(importlib.util.cache_from_source, (httpx.__file__, '/app/server.py')) if not os.path.exists(p)]; sys.exit(f'bytecode missing: {missing}' if missing else 0)"

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

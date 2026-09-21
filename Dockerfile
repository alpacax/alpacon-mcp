FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/usr/local

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /usr/local/bin/uv

# Copy full source and install (hatchling needs source for metadata)
COPY . .
# CI resolves the version and passes it as VERSION (.git is excluded from the build context)
ARG VERSION=0.0.0
# --locked fails the build if uv.lock and pyproject.toml disagree, so the image
# never resolves a dependency the test run did not see.
RUN SETUPTOOLS_SCM_PRETEND_VERSION="${VERSION#v}" uv sync --locked --no-dev && \
    rm -rf /root/.cache

# The image must carry the SDK the test run validated, not a later 2.x release.
RUN python -c "\
import importlib.metadata as m, sys, tomllib; \
locked = next(p['version'] for p in tomllib.load(open('uv.lock','rb'))['package'] if p['name'] == 'mcp'); \
installed = m.version('mcp'); \
sys.exit(0) if installed == locked else sys.exit(f'mcp {installed} installed, {locked} locked')"

# Default port (MCAR - MCP Alpacon Remote)
EXPOSE 8237

# Health check using the built-in /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; r = httpx.get('http://localhost:8237/health'); r.raise_for_status()" || exit 1

# HTTP streamable transport with JWT auth (sets host=0.0.0.0 internally)
CMD ["python", "main_http.py"]

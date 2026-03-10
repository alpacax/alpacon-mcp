FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy full source and install (hatchling needs source for metadata)
COPY . .
RUN pip install --no-cache-dir . && \
    rm -rf /root/.cache

# Default port (MCAR - MCP Alpacon Remote)
EXPOSE 8237

# Health check using the built-in /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; r = httpx.get('http://localhost:8237/health'); r.raise_for_status()" || exit 1

# HTTP streamable transport with JWT auth (sets host=0.0.0.0 internally)
CMD ["python", "main_http.py"]

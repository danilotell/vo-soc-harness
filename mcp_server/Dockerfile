# Custom Vision One MCP server.
# Builds a runtime image that serves over the HTTP transport by default.
FROM python:3.11-slim

# uv for fast, reproducible dependency installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install runtime deps first (better layer caching), pinned to the lockfile so
# the image installs exactly what was tested. No dev group in the image.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Application source.
COPY src ./src

# Drop root: run as an unprivileged user that owns the app (incl. .venv).
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

# Serve over HTTP, reachable from outside the container.
# Set MCP_AUTH_TOKEN at runtime to require a bearer token (see .env.example).
ENV MCP_TRANSPORT=http \
    MCP_HTTP_HOST=0.0.0.0 \
    MCP_HTTP_PORT=8000
EXPOSE 8000

# Credentials are provided at runtime, e.g.:
#   docker run -p 8000:8000 -e VO_REGION=... -e VO_API_KEY=... \
#     -e MCP_AUTH_TOKEN=... custom-vo-mcp
# Run the venv interpreter directly (no uv needed at runtime).
CMD [".venv/bin/python", "src/custom_vo_mcp.py"]

# Prepare this image with network access, then run it with --network none.
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential patchelf ccache libmagic1 ca-certificates git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY InstallRelease ./InstallRelease
COPY cli ./cli
RUN uv sync --locked --dev
COPY build.sh install.sh ./
COPY scripts ./scripts
COPY test ./test
COPY .github/scripts ./.github/scripts
ENV UV_OFFLINE=true
CMD ["/app/.venv/bin/python", "-m", "pytest", "-q", "test"]

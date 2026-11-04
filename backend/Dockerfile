FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app

# Dependencies first, so code changes don't reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY debatedojo ./debatedojo
COPY formats ./formats
COPY personas.yaml ./
COPY evals ./evals
RUN uv sync --frozen --no-dev

RUN useradd --create-home app && mkdir -p /app/data && chown -R app /app
USER app
VOLUME /app/data
EXPOSE 8060
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8060/api/health')"
CMD ["uv", "run", "--no-sync", "debatedojo", "serve", "--host", "0.0.0.0", "--port", "8060"]

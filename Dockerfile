FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml .
RUN uv venv /app/.venv && uv pip install --python /app/.venv/bin/python .

COPY src/ src/
RUN uv pip install --python /app/.venv/bin/python --no-deps .

FROM python:3.12-slim

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "linguee_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Two stages: build the React bundle with Node, then run FastAPI with the
# bundle baked in. One image, one process, one URL -- which is what makes the
# free Hugging Face Space deployment work without CORS or a second service.

FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=7860 \
    UV_SYSTEM_PYTHON=1

# uv resolves and installs far faster than pip, which matters on a free build.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first so edits to source do not invalidate the layer.
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project -o requirements.txt \
    && uv pip install --system -r requirements.txt

COPY dayzero/ ./dayzero/
COPY scripts/ ./scripts/
# The pre-warmed cache ships with the image: the demo runs even if Overpass
# rate-limits or the venue network dies mid-judging.
COPY cache/ ./cache/
COPY --from=frontend /build/dist ./frontend/dist

# Hugging Face Spaces runs containers as a non-root user, and the SQLite cache
# needs to be writable for any location the visitor looks up.
RUN useradd -m -u 1000 app && chown -R app:app /app
USER app

EXPOSE 7860
CMD ["sh", "-c", "uvicorn dayzero.api:app --host 0.0.0.0 --port ${PORT:-7860}"]

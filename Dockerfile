FROM node:24-bookworm-slim AS frontend
WORKDIR /build/web
RUN npm install --global pnpm@11.25.0
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm run build

FROM python:3.14-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=10000 \
    DATABASE_URL=sqlite:////app/data/prototype.db
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 app \
    && mkdir /app/data && chown app:app /app/data
COPY api/ api/
COPY adapters/ adapters/
COPY domain/ domain/
COPY config/ config/
COPY scripts/start_server.py scripts/start_server.py
COPY --from=frontend /build/web/dist/ web/dist/
USER app
EXPOSE 10000
CMD ["python", "scripts/start_server.py"]

# Render worker (plan.md section 8). Follows https://www.remotion.dev/docs/docker
# Build context: renderer/   e.g. docker build -t reel-renderer renderer
FROM node:22-bookworm-slim

# Chrome Headless Shell shared libraries + DejaVu Sans (theme font; no network fonts at render time).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libdbus-1-3 libatk1.0-0 libgbm-dev libasound2 libxrandr2 libxkbcommon-dev \
    libxfixes3 libxcomposite1 libxdamage1 libatk-bridge2.0-0 libpango-1.0-0 libcairo2 libcups2 \
    fonts-dejavu-core ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# Unprivileged user owns the app (Remotion's webpack cache writes under node_modules/.cache).
RUN useradd --create-home --uid 10001 renderer && mkdir -p /app/.jobs /workspace/output && chown -R renderer /app /workspace/output
USER renderer
WORKDIR /app
COPY --chown=renderer package.json package-lock.json tsconfig.json ./
RUN npm ci && npx remotion browser ensure \
  && mkdir -p node_modules/.cache && chmod 1777 /app/.jobs node_modules/.cache
COPY --chown=renderer src ./src

# The image must also run under an arbitrary uid (compose `user:` matching the api service), because
# api and renderer write into the same shared output volume. Hence world-writable sticky job/cache
# dirs above, HOME=/tmp (an arbitrary uid has no home), and tsx started directly (no npx/npm cache).
ENV HOME=/tmp \
    RENDER_WORKER_PORT=8001 \
    ARTIFACT_ROOT=/workspace/output \
    RENDER_WORK_DIR=/app/.jobs \
    RENDER_CONCURRENCY=1
EXPOSE 8001
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s CMD node -e "fetch('http://127.0.0.1:8001/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node_modules/.bin/tsx", "src/worker.ts"]

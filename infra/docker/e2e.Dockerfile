FROM node:22-bookworm-slim AS packages
WORKDIR /tests
COPY frontend/tests/e2e/package*.json ./
RUN npm ci --omit=dev --no-audit --no-fund && npm cache clean --force

FROM node:22-bookworm-slim
WORKDIR /tests
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/chromium
COPY --from=packages /tests /tests
RUN ./node_modules/.bin/playwright-core install --with-deps --only-shell chromium && rm -rf /var/lib/apt/lists/*
COPY frontend/tests/e2e/*.mjs ./
CMD ["node","gate6.mjs"]

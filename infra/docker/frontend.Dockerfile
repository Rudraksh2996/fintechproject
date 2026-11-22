FROM node:22-alpine AS build
WORKDIR /app
COPY frontend ./
RUN npm ci --no-audit --no-fund && npm run build && rm -rf node_modules && npm cache clean --force
FROM nginx:1.28-alpine
COPY infra/nginx/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

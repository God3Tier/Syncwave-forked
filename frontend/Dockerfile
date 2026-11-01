# syntax=docker/dockerfile:1
#
# The SyncWave web UI: a static React build served by nginx on port 8080.
# The gateway routes / here and /api/<service>/ to the services, so the
# browser only ever talks to one origin.

FROM node:24-alpine AS build
WORKDIR /app
# Dependencies first: this layer is reused until the lockfile changes.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.30-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
  CMD ["wget", "-qO-", "http://127.0.0.1:8080/health"]

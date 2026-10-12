ARG NODE_IMAGE=node:22.23-alpine3.24
ARG CADDY_IMAGE=caddy:2.11.7-alpine
FROM ${NODE_IMAGE} AS build

WORKDIR /app
RUN npm install --global pnpm@11.25.0
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN pnpm build

FROM ${CADDY_IMAGE}
COPY frontend/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
EXPOSE 80 443 443/udp

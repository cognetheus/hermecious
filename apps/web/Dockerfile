# syntax=docker/dockerfile:1

FROM node:22.23.4-bookworm-slim AS build
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /srv/web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM node:22.23.4-bookworm-slim
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
WORKDIR /srv/web
# Root-owned and read-only for the unprivileged `node` user that runs the server.
COPY --from=build /srv/web/.next/standalone ./
COPY --from=build /srv/web/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]

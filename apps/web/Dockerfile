# GTMOS web: Next.js standalone build.
FROM node:24-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:24-alpine AS build
WORKDIR /app
# Rewrites (browser → /api/v1 → FastAPI) are resolved at build time, so the API host is a build arg.
ARG API_INTERNAL_URL=http://api:8000
ENV API_INTERNAL_URL=$API_INTERNAL_URL NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:24-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -S gtmos && adduser -S gtmos -G gtmos
COPY --from=build /app/public ./public
COPY --from=build --chown=gtmos:gtmos /app/.next/standalone ./
COPY --from=build --chown=gtmos:gtmos /app/.next/static ./.next/static
USER gtmos
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=10 \
  CMD wget -qO- http://127.0.0.1:3000/ >/dev/null || exit 1
CMD ["node", "server.js"]

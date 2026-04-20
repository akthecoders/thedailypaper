# Dokploy build for the Astro static site.
# The Python agent does NOT run in this container — it runs on GitHub Actions.
# This image only builds site/ and serves the static output with nginx.
#
# Build context must be the repo root (so we can COPY site/ and the generated
# site/src/content/papers/ that the agent commits).

FROM node:20-alpine AS builder

WORKDIR /app

# Leverage Docker layer cache: deps first, source second.
COPY site/package.json site/package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY site/ ./

# SITE_URL is a build-time variable for Astro (canonical URL, RSS, OG tags).
ARG SITE_URL
ENV SITE_URL=${SITE_URL}

# PUBLIC_SUBSCRIBE_WORKER_URL is baked into the subscribe form + subscriber
# count hydration at build time. Must be passed as a Docker build arg
# (Dokploy: Build → Build Args) — runtime env vars don't reach the Astro build.
ARG PUBLIC_SUBSCRIBE_WORKER_URL
ENV PUBLIC_SUBSCRIBE_WORKER_URL=${PUBLIC_SUBSCRIBE_WORKER_URL}

RUN npm run build


FROM nginx:alpine AS runtime

# Tight nginx config with correct MIME types and SPA-friendly 404 fallback.
RUN rm /etc/nginx/conf.d/default.conf
COPY <<'EOF' /etc/nginx/conf.d/default.conf
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    # Astro generates directory-style URLs (/papers/slug/index.html)
    location / {
        try_files $uri $uri/ $uri.html /404.html;
    }

    # Long cache for immutable assets
    location /_astro/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    error_page 404 /404.html;
}
EOF

COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

# No in-container HEALTHCHECK — Dokploy/Traefik does its own HTTP health checks
# externally, and busybox wget under Alpine's default hardening was triggering
# spurious "unhealthy" states that caused restart loops.

CMD ["nginx", "-g", "daemon off;"]

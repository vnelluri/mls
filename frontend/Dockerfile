# CI/deploy-only image. Local development does NOT use Docker — see
# scripts/dev.mjs and README.md for the local workflow.
#
# Vite bakes VITE_* values into the JS bundle at BUILD time, so each
# environment (dev/stage/prod) gets its own image, built with its own args:
#
#   docker build \
#     --build-arg VITE_API_BASE_URL=https://api.mlserv.example.com \
#     --build-arg VITE_ENTRA_TENANT_ID=<tenant-guid> \
#     --build-arg VITE_ENTRA_CLIENT_ID=<spa-client-id> \
#     --build-arg VITE_ENTRA_API_SCOPE=api://<api-client-id>/.default \
#     -t mlserv-frontend:<tag> .
#
# Setting env vars on the ECS task definition has NO effect on the bundle.

# ---- build stage ----
FROM node:20-alpine AS build
WORKDIR /app

# Installed before the VITE_* ARGs are declared so this layer's cache key
# depends only on package.json/package-lock.json, not on per-environment
# build-arg values — dev/stage/prod builds of the same commit reuse it.
COPY package.json package-lock.json ./
RUN npm ci

ARG VITE_API_BASE_URL
# Demo mode must never ship by accident: opt in explicitly for demo builds.
ARG VITE_DEMO_MODE=false
ARG VITE_ENTRA_TENANT_ID
ARG VITE_ENTRA_CLIENT_ID
ARG VITE_ENTRA_API_SCOPE
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_DEMO_MODE=$VITE_DEMO_MODE \
    VITE_ENTRA_TENANT_ID=$VITE_ENTRA_TENANT_ID \
    VITE_ENTRA_CLIENT_ID=$VITE_ENTRA_CLIENT_ID \
    VITE_ENTRA_API_SCOPE=$VITE_ENTRA_API_SCOPE

# Explicit allowlist (not `COPY . .`) so host-only files (.env, iac/, .claude/)
# can never ride into the image regardless of .dockerignore upkeep.
COPY index.html vite.config.ts tsconfig.json tsconfig.node.json tailwind.config.ts postcss.config.js ./
COPY scripts ./scripts
COPY src ./src
RUN npm run build

# ---- runtime stage ----
FROM nginx:alpine AS runtime
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]

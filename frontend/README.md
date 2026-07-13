# Truist Model Serving (TMS) — Frontend

React + TypeScript + Vite frontend for the batch ML-serving and monitoring platform. Independent
companion to the ML *training* platform — its own tenants, its own auth state, no shared data.

## Quickstart (no Docker)

Local development never uses Docker — the `scripts/dev.mjs` bootstrapper checks the backend is up,
then runs Vite directly.

```bash
npm install
npm run dev
```

`npm run dev` does the following, in order:

1. Copies `.env.example` to `.env` if `.env` doesn't exist yet.
2. Reads `VITE_API_BASE_URL` from `.env` and polls `${VITE_API_BASE_URL}/health` for up to ~10s.
3. If the backend isn't reachable, it prints a clear error and exits — it will **not** start Vite
   against a backend that isn't there:

   ```
   Can't reach the backend at http://localhost:8001/health — start the backend first:
   cd ../backend && python scripts/dev.py — then re-run this script.
   ```

4. Once the backend responds, it starts Vite (`npx vite`) and forwards its exit code.

If you want to skip the backend health check entirely (e.g. developing UI against mocked data), use:

```bash
npm run dev:vite-only
```

## Tests

```bash
npm test          # vitest run (jsdom, no backend needed)
npm run test:watch
```

Vitest + Testing Library, colocated as `src/**/*.test.ts(x)`. The suite pins
`VITE_DEMO_MODE=false` in `vitest.config.ts` so results don't depend on your
local `.env`; the demo-mode behavior is tested explicitly via `vi.stubEnv`.
Coverage focuses on the logic the pages lean on: the `getJobActions` matrix
(staging vs production × role capabilities), the `useTenantContext`
capability flags per role, the status-badge enum→label/palette mapping,
`Pagination` ranges and boundaries, the axios auth interceptor (bearer vs
`X-Demo-Role`), and relative-time formatting.

## Environment variables

See `.env.example`:

| Variable | Purpose |
|---|---|
| `VITE_API_BASE_URL` | Backend base URL. Defaults to `http://localhost:8001`. |
| `VITE_DEMO_MODE` | `true` shows a cosmetic role selector on the login page instead of the Microsoft sign-in button. Local dev only. |
| `VITE_ENTRA_TENANT_ID` | Entra ID (Azure AD) tenant ID, used to build the MSAL authority URL. Production only. |
| `VITE_ENTRA_CLIENT_ID` | Entra ID app registration client ID. Production only. |
| `VITE_ENTRA_API_SCOPE` | Scope requested for backend API tokens (the token's `aud` must match the backend's `ENTRA_AUDIENCE`/`ENTRA_CLIENT_ID`). Defaults to `api://<VITE_ENTRA_CLIENT_ID>/.default`; set explicitly when the API is a separate app registration. Production only. |

**Important:** because this is a static Vite SPA, `VITE_*` values are baked into the JS bundle at
*build* time, not read at container runtime. Setting environment variables on the ECS task
definition has no effect on already-built assets — the CI pipeline must set them before running
`npm run build` for each environment (dev/stage/prod).

## Role gating — how it works

Every role/tenant decision in the UI flows through **`src/auth/useTenantContext.ts`** — the single
source of truth. It exposes `role`, `tenantId`, and boolean flags (`canCreatePipeline`,
`canSubmitJob`, `canApproveStep`, `canRegisterModel`, `canPromoteModel`, `canManageTenants`). No
page component re-derives role logic locally; they all read these flags.

Roles:

- **PlatformAdmin** — view-only across all tenants. `tenantId` is `null` by design (spans every
  tenant). Manages Tenants and Group Mappings.
- **LeadDataScientist** — the only role that can create/mutate anything, scoped to their own
  tenant: create pipelines, submit/stop/retry jobs, approve/reject steps, register/promote models.
- **DataScientist** — view-only within their own tenant.

### The bug this project deliberately avoids

A sibling project shipped a bug where a tenant-scoped action handler did roughly:

```ts
function submitJob() {
  if (!tenantId) return; // Platform Admin has tenantId === null — silently no-ops here
  ...
}
```

Clicking "Submit Job" as a Platform Admin did *nothing* — no error, no loading state — because
Platform Admin's `tenantId` is `null` by design. This frontend avoids that pattern everywhere:
every gated control is **hidden or disabled with an explanatory tooltip/banner** (e.g. "Platform
Admins have view-only access across tenants — sign in as a Lead Data Scientist to create a
pipeline"), and if a gated handler is ever reached anyway, it sets a visible error message instead
of silently returning.

## Demo-mode auth — how it works

`VITE_DEMO_MODE=true` shows a role selector on the login screen, but that selector is **purely
cosmetic** (styling only). The authoritative role for the whole session always comes from the
backend's `GET /auth/me` response — the backend's own `AUTH_MODE=dev` setting controls what role is
actually injected, independent of this frontend. Never trust a client-side-decoded token claim (or
this selector) for authorization decisions.

## Design tokens — Truist brand palette

`src/theme/tokens.ts` is the single source of truth for every brand color (hex values live there
exactly once):

- `tailwind.config.ts` imports `tokens.ts` directly — Tailwind 3.4+ loads TypeScript config files
  natively (via its bundled `jiti` loader), so no separate build step is needed to keep Tailwind's
  `theme.colors.truist.*` / `theme.colors.status.*` in sync with the source values.
- `src/theme/injectThemeVars.ts` calls `buildThemeCss()` (also from `tokens.ts`) and injects a
  `<style>` tag defining `--truist-*` / `--status-*` CSS custom properties on `:root`, once, at app
  startup (`main.tsx`, before render). This is what `PipelineCanvas`'s raw SVG `stroke`/`fill`
  attributes read, since Tailwind utility classes don't apply inside SVG attributes.

`src/theme/theme.css` holds ordinary global/base styles (Tailwind directives, scrollbar styling,
focus rings) and documents this at the top — it does not hand-duplicate the token hex values.

`src/components/StatusBadge.tsx` is the single place that maps `MonitoringStatus` / `JobStatus` /
`StepStatus` to a colored pill. Nothing else inlines its own status-color logic.

## Pipeline Canvas

`src/components/canvas/PipelineCanvas.tsx` renders a pipeline's steps as an SVG left-to-right chain
of connected node boxes (`StepNode.tsx`, via `foreignObject` so ordinary HTML/Tailwind can lay out
each node's text while the connectors and node borders use the raw CSS custom properties). Steps
carry a generic `dependsOn: string[]` even though v1 pipelines are always linear, so branching
layouts aren't a rewrite later — only the layout algorithm (currently: place nodes in array order)
would need to change.

Four step config panels open when a node is clicked **in the builder only** (`PipelineBuilderPage`,
gated on `canCreatePipeline`) — never in the read-only job-detail canvas:

- `DataPipelineStepPanel` — Snowflake source + destination S3 URI.
- `ExecuteModelStepPanel` — model (searchable against `GET /models`), EMR application ID, execution
  role ARN, entry point / input / output S3 URIs.
- `DataQualityStepPanel` — repeatable `{name, type, threshold}` checks.
- `ApprovalStepPanel` — optional approver note; the pipeline-level `requiresApproval` toggle lives
  in the builder header, not per-step.

## API contract notes / deviations

Everything is built against the documented contract in the task brief. Two small additions were
necessary and are called out in code comments where they occur, since the contract doesn't
explicitly enumerate them:

- `DELETE /group-mappings/{id}` — the contract only lists `GET/PUT /group-mappings`, but the Group
  Mappings screen requires delete-behind-confirm. Follows the same REST shape as everything else.
- `GET /models?monitoringStatus=` — needed so the Monitoring Dashboard's status tiles can drill into
  "the models in that state" (an explicit requirement). Follows the same filter convention as the
  documented `stage` filter.
- `GET /jobs?status=` — used by the Admin Dashboard to compute per-status job counts. Same
  reasoning: filtering by query param is the documented pattern for list endpoints generally.

**These three need to be verified against the live backend once both projects are running
together** — if the backend doesn't support one of them, the affected UI (delete mapping / status
drill-down / admin job counts) will need a small adjustment, but nothing else depends on them.

## Verification performed

- `npx tsc --noEmit` — clean, no type errors.
- `npm run build` — production build succeeds.
- `npm run dev` — confirmed Vite starts when a backend is reachable, and confirmed the *specific
  failure-path message* is correct when it isn't (backend not running yet in this environment,
  which is expected — see below).

## What still needs to happen once both projects are running together

The backend was being built in parallel and wasn't necessarily up while this frontend was built —
so beyond `tsc`/`build`/the dev-script error path, **no live integration testing has happened yet**.
Once both are up:

- Confirm `GET /auth/me` shape matches `CurrentUser` exactly and that role-switching (via the
  backend's `AUTH_MODE=dev`) is reflected correctly, including the three `can*`-flag deviations
  above.
- Submit a real job end-to-end: data pipeline step → execute model step → data quality check →
  (optional) approval, and confirm the `MonitoringSnapshot` + model `currentMonitoringStatus` update
  as expected, and that the Monitoring Dashboard / Model Detail trend table reflect it.
- Confirm pagination shape (`{items, total, page, pageSize}`) matches exactly on every list
  endpoint.
- Confirm the three endpoints called out above exist as expected, or adjust if the backend named
  them differently.

## Production checklist

- Set `VITE_DEMO_MODE=false`, `VITE_ENTRA_TENANT_ID`, `VITE_ENTRA_CLIENT_ID`,
  `VITE_ENTRA_API_SCOPE` (if the API is a separate app registration), and the real
  `VITE_API_BASE_URL` at **build** time in CI before `npm run build`.
- Token acquisition is fully wired: login uses `loginRedirect` (completed by
  `handleRedirectPromise` on return), and every API request acquires a token via
  `acquireTokenSilent` (`src/auth/acquireToken.ts`), falling back to a re-auth redirect when
  interaction is required. Expose the API scope on the backend app registration and grant the SPA
  registration access to it.
- On the Entra side, ensure the backend app registration emits the `groups` claim (the backend
  resolves roles from group membership) and the SPA registration lists the deployed origin as a
  SPA redirect URI.
- Point the ECS target group's health check at `/` (nginx serves `index.html` for any path via SPA
  fallback — see `nginx.conf`).

## Docker (CI/deploy only — not used locally)

```bash
docker build \
  --build-arg VITE_API_BASE_URL=https://api.mlserv.example.com \
  --build-arg VITE_ENTRA_TENANT_ID=<tenant-guid> \
  --build-arg VITE_ENTRA_CLIENT_ID=<spa-client-id> \
  --build-arg VITE_ENTRA_API_SCOPE=api://<api-client-id>/.default \
  -t ml-serving-monitoring-frontend .
docker run -p 8080:80 ml-serving-monitoring-frontend
```

The `--build-arg` values above are baked into the JS bundle at build time (see
"Environment variables" above) — omitting them ships an image whose API calls
fall back to `http://localhost:8001` and whose MSAL config has no client ID.

Multi-stage build: `node:20-alpine` builds the static bundle, `nginx:alpine` serves it on port 80
with SPA-fallback routing (`nginx.conf`). Port 80 was chosen (rather than 3000) to match a typical
production nginx setup fronted by an ALB — see the `iac/` Terraform module.

## ECS deploy (outline)

Provisioning is Terraform: **`iac/`** is a complete module (log group, task
definition with the port-80 health check, Fargate service with optional ALB
attachment) — see `iac/README.md` for usage.

1. Build and push the image to ECR, passing the target environment's `VITE_*` config as
   `--build-arg` flags (baked into the bundle at build time — see "Docker" above for the full
   flag list):
   ```bash
   docker build \
     --build-arg VITE_API_BASE_URL=https://api.mlserv.example.com \
     --build-arg VITE_ENTRA_TENANT_ID=<tenant-guid> \
     --build-arg VITE_ENTRA_CLIENT_ID=<spa-client-id> \
     --build-arg VITE_ENTRA_API_SCOPE=api://<api-client-id>/.default \
     -t <ecr-repo>:<tag> .
   docker push <ecr-repo>:<tag>
   ```
2. `terraform apply` the `iac/` module with your image, subnets, security groups,
   and target group (reuse the backend's ECS cluster via its `cluster_arn` output).
3. Point an ALB target group at container port 80; health check path `/`.

## Repository layout

```
src/
  main.tsx, App.tsx, routes.tsx        Role-gated routing (/admin/* is Platform-Admin-only)
  auth/                                 AuthContext, useTenantContext (role-gating source of truth), msalConfig
  api/                                  Thin per-resource API modules + shared client
  types/platform.ts                     All data model types (matches backend field names exactly)
  theme/                                tokens.ts (source of truth), theme.css, injectThemeVars.ts
  components/
    layout/                             Layout, Sidebar, Topbar
    shared/                             StatusBadge, Pagination, ConfirmDialog, DataTable, LoadingSpinner, EmptyState, ui primitives
    canvas/                             PipelineCanvas, StepNode, panels/*
  pages/                                admin/, pipelines/, jobs/, models/, monitoring/, audit/, auth/
scripts/dev.mjs                         No-Docker local dev bootstrapper
iac/                                    Terraform module: ECS Fargate service
Dockerfile                              CI/deploy-only, multi-stage, nginx:alpine
```

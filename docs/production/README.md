# Vesper production verification — 2026-10-20

## Verdict: FAIL

The Vercel-to-Render routing defect is fixed and deployed. The public frontend now reaches the
Render API through a same-origin rewrite and completes read-only investigations against the
backend's explicitly labelled demo fixture. Production acceptance is still blocked because the
configured FalkorDB endpoint does not offer a certificate-verified TLS connection and the Cognito
app client does not yet allow the Vercel callback URL.

## Verified public endpoints

- Frontend: <https://vesper-frontend-delta.vercel.app/>
- Backend: <https://vesper-73uk.onrender.com/>
- Health: <https://vesper-frontend-delta.vercel.app/api/health>
- API documentation: <https://vesper-73uk.onrender.com/docs>
- Deployed routing commit: `528e67626109d096be4628dbefda0f0cfae39a92`

The health response on 2026-10-20 reported `mode=demo`, `database_connected=false`, graph
`demo_sample_graph`, eight sample transactions, and seven sample edges. Those counts are not the
production FalkorDB graph and are not presented as production evidence.

## Architecture

```text
Browser
  -> Vercel static frontend
  -> Vercel /api/* same-origin rewrite
  -> Render FastAPI service
  -> Cognito access-token validation
  -> FalkorDB bitcoin_investigator graph
```

The first three hops are verified. Cognito and FalkorDB remain blocked in the live environment.

## Implemented changes

- Added Vercel rewrites for `/api/:path*` at both supported project roots.
- Added explicit `Authorization` CORS support and no-store API responses.
- Added `/api/live` and database-backed `/api/ready` endpoints.
- Added certificate and hostname verification for FalkorDB TLS.
- Added production configuration validation that rejects demo mode, plaintext FalkorDB,
  incomplete Cognito settings, insecure callbacks, wildcard/non-HTTPS CORS, and the wrong graph.
- Added deterministic database connection cleanup during shutdown and after failed connects.
- Added streaming heartbeats, disconnect handling, and correct investigation-slot lifetime.
- Preserved caller control of memory-enabled versus memory-disabled previews.
- Made production quick-start seeds come from the live search API instead of fixed fixture IDs.
- Fixed a reduced-motion resize frame that could briefly clear the office canvas on mobile.
- Added a reproducible Playwright viewport check and GitHub Actions test workflow.

## Required Render variables

`PRODUCTION=true`, `APP_MODE=cloud`, `APP_HOST=0.0.0.0`, `AUTH_MODE=cognito`,
`CORS_ORIGINS=https://vesper-frontend-delta.vercel.app`, `FALKORDB_URL` using a verified
`rediss://` endpoint (or the separate host/port/password fields with `FALKORDB_SSL=true`),
`FALKORDB_GRAPH_NAME=bitcoin_investigator`, all `COGNITO_*` fields, `MODEL_PROVIDER=cloud`, and
the model-provider API key. Secrets must stay in Render, never source control.

## Executed verification

- Backend: 104 passed, 0 failed; one Starlette/httpx deprecation warning.
- Frontend unit/contract tests: 40 passed, 0 failed.
- Playwright local demo: 390x844, 768x1024, 1280x720, 1440x900, and 1920x1080; no horizontal
  overflow, no uncaught page errors, investigation completed, Skeptic result rendered.
- Public routing: `/api/health`, `/api/auth/config`, `/api/stats`, transaction search, case list,
  and investigation streaming reached Render after commit `528e676`.
- Controlled in-memory memory A/B test: prior-case recall was revalidated and changed the selected
  graph action; this is fixture evidence, not cloud persistence evidence.
- TLS probe: public FalkorDB TCP accepted a connection, but a certificate-verified TLS handshake
  timed out; no credentials or writes were sent.
- Cognito authorize probe: the production Vercel callback returned `redirect_mismatch`.

Evidence files in this directory include the backend and frontend test logs, browser JSON,
baseline HTTP responses, TLS probe, controlled memory comparison, and responsive screenshots.

## Security and remaining blockers

1. **FAIL — FalkorDB TLS:** obtain the TLS-enabled FalkorDB Cloud endpoint. Do not deploy the
   plaintext endpoint or disable certificate verification.
2. **FAIL — Cognito callback:** add the exact Vercel callback and logout URLs with a full
   read-modify-write update of the Cognito app client.
3. **FAIL — live graph evidence:** current node/edge counts, transaction retrieval, graph-driven
   investigations, and Skeptic checks cannot be verified until TLS succeeds.
4. **FAIL — live persistence:** saving, owner isolation, restart survival, and cloud memory A/B
   remain unverified. No production database writes were attempted.
5. **PASS WITH WARNINGS — frontend:** routing, rendering, responsive layouts, read-only streaming,
   and the original office identity are verified against demo evidence. Authentication and cloud
   data remain unavailable.
6. **PASS WITH WARNINGS — dependency audit:** runtime dependencies are pinned for deployment, but
   a dedicated vulnerability scanner was not available in this run.

Production must remain `FAIL` until the two external configuration blockers are repaired and the
complete live regression suite is repeated successfully.

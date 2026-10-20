from __future__ import annotations

import logging
import asyncio
import json
import queue
import re
import threading
import time
from datetime import datetime, timezone
from functools import lru_cache
from uuid import uuid4
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import jwt

from backend.app.agents.orchestrator import InvestigationOrchestrator
from backend.app.config import Settings, get_settings, validate_track2_isolated_demo, validate_production
from backend.app.models import HealthResponse, InvestigationRequest, InvestigationResponse, TransactionSearchResponse
from backend.app.services.graph_store import GraphStore
from backend.app.services.track2_demo_store import Track2DemoGraphStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)

JWKS_CACHE_TTL_SECONDS = 3600
JWKS_STALE_GRACE_SECONDS = 6 * 3600
JWKS_REQUEST_TIMEOUT_SECONDS = 5
MAX_CONCURRENT_INVESTIGATIONS = 4
investigation_slots = threading.BoundedSemaphore(MAX_CONCURRENT_INVESTIGATIONS)


class ResilientCognitoJwksClient(jwt.PyJWKClient):
    """Cache Cognito keys across requests and allow bounded stale use on outages."""

    def __init__(self, uri: str):
        super().__init__(uri, cache_jwk_set=True, lifespan=JWKS_CACHE_TTL_SECONDS,
                         timeout=JWKS_REQUEST_TIMEOUT_SECONDS)
        self._last_good_jwks: dict[str, Any] | None = None
        self._last_good_at: float | None = None

    def fetch_data(self) -> Any:
        data = super().fetch_data()
        self._last_good_jwks = data
        self._last_good_at = time.monotonic()
        return data

    def get_jwk_set(self, refresh: bool = False):
        try:
            return super().get_jwk_set(refresh=refresh)
        except jwt.PyJWKClientConnectionError:
            # Never use stale keys for an unknown kid/rotation refresh. For an
            # ordinary cache-expiry outage, allow a short bounded grace period.
            stale_age = (time.monotonic() - self._last_good_at) if self._last_good_at is not None else float("inf")
            if refresh or self._last_good_jwks is None or stale_age > JWKS_STALE_GRACE_SECONDS:
                raise
            logger.warning("Cognito JWKS endpoint unavailable; using cached keys (age_seconds=%d)", int(stale_age))
            return jwt.PyJWKSet.from_dict(self._last_good_jwks)


@lru_cache(maxsize=4)
def cognito_jwks_client(issuer: str) -> ResilientCognitoJwksClient:
    """One client per configured issuer, preserving its JWKS cache across requests."""
    return ResilientCognitoJwksClient(f"{issuer}/.well-known/jwks.json")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = PROJECT_ROOT / "frontend"

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    validate_track2_isolated_demo(settings)
    validate_production(settings)
    if settings.auth_required and (settings.auth_mode != "cognito" or not settings.cognito_configured):
        raise RuntimeError("Non-local deployment requires complete Amazon Cognito configuration (AUTH_MODE=cognito and all COGNITO_* settings).")
    app.state.settings = settings
    app.state.store = Track2DemoGraphStore(settings) if settings.track2_isolated_demo else GraphStore(settings)
    app.state.orchestrator = InvestigationOrchestrator(app.state.store, settings)
    app.state.process_instance_id = f"proc_{uuid4().hex[:12]}"
    app.state.process_started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        yield
    finally:
        app.state.store.close()


app = FastAPI(
    title="Bitcoin Investigator",
    description="Evidence-first Bitcoin transaction investigations backed by FalkorDB graph context and persistent case memory.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def cache_versioned_frontend_assets(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    if request.url.path == "/":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    elif request.url.path.startswith("/assets/"):
        filename = Path(request.url.path).name
        immutable = bool(re.search(r"\.[0-9a-f]{12,}\.", filename))
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable" if immutable else "no-cache, must-revalidate"
    return response


def require_auth(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str | None:
    settings: Settings = request.app.state.settings
    if settings.track2_isolated_demo:
        client_host = request.client.host if request.client else ""
        if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
            raise HTTPException(status_code=403, detail="The isolated demonstration is available on loopback only.")
        return settings.isolated_demo_identity
    if not settings.auth_required:
        return
    if settings.auth_mode != "cognito" or not settings.cognito_configured:
        raise HTTPException(status_code=503, detail="Authentication is required but Amazon Cognito is not configured.")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="A valid Cognito access token is required.", headers={"WWW-Authenticate": "Bearer"})
    try:
        issuer = f"https://cognito-idp.{settings.cognito_region}.amazonaws.com/{settings.cognito_user_pool_id}"
        jwks = cognito_jwks_client(issuer)
        key = jwks.get_signing_key_from_jwt(credentials.credentials).key
        claims = jwt.decode(credentials.credentials, key, algorithms=["RS256"], issuer=issuer,
                            options={"verify_aud": False, "require": ["exp", "iss", "token_use", "client_id"]})
        if claims.get("token_use") != "access" or claims.get("client_id") != settings.cognito_app_client_id:
            raise ValueError("Wrong Cognito token type or app client")
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise ValueError("Cognito access token has no subject")
        return subject
    except jwt.PyJWKClientConnectionError as exc:
        logger.warning("Cognito JWKS unavailable (%s)", type(getattr(exc, "__cause__", None)).__name__)
        raise HTTPException(status_code=503, detail="Cognito token verification is temporarily unavailable. Retry shortly.") from exc
    except Exception as exc:
        logger.info("Rejected Cognito token (%s)", type(exc).__name__)
        raise HTTPException(status_code=401, detail="Invalid or expired Cognito access token.", headers={"WWW-Authenticate": "Bearer"}) from exc


def require_demo_write_target(request: Request) -> None:
    settings: Settings = request.app.state.settings
    if not settings.track2_isolated_demo:
        return
    try:
        validate_track2_isolated_demo(settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Isolated demo write target is unavailable.") from exc
    if request.app.state.store.graph_name != settings.isolated_demo_graph_name:
        raise HTTPException(status_code=503, detail="Isolated demo write target is unavailable.")


def require_investigation_capacity():
    """Bound expensive investigation work per application process."""
    if not investigation_slots.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Investigation capacity is busy. Retry shortly.",
                            headers={"Retry-After": "3"})
    try:
        yield
    finally:
        investigation_slots.release()
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

if (FRONTEND_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")


@app.get("/api/health", response_model=HealthResponse, tags=["system"])
def health(request: Request) -> dict[str, Any]:
    result = request.app.state.store.health()
    settings: Settings = request.app.state.settings
    return {**result,
            "environment": "isolated_demo" if settings.track2_isolated_demo else result["mode"],
            "demo_identity": settings.isolated_demo_identity if settings.track2_isolated_demo else None,
            "process_instance_id": request.app.state.process_instance_id}


@app.get("/api/live", tags=["system"])
def liveness(request: Request):
    return {"ok": True, "revision": request.app.state.settings.render_git_commit or None}


@app.get("/api/ready", tags=["system"])
def readiness(request: Request):
    result = request.app.state.store.health()
    ready = result["mode"] == "cloud" and result["database_connected"]
    return JSONResponse({**result, "ok": ready,
                         "revision": request.app.state.settings.render_git_commit or None},
                        status_code=200 if ready else 503)


@app.get("/api/demo/track2/status", tags=["system"])
def track2_demo_status(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    if not settings.track2_isolated_demo:
        return {"enabled": False, "data_source": "CLOUD" if settings.app_mode == "cloud" else "DEMO"}
    result = request.app.state.store.health()
    return {"enabled": True, "data_source": "ISOLATED DEMO",
            "demo_identity": settings.isolated_demo_identity,
            "graph_name": settings.falkordb_graph_name,
            "database_connected": result["database_connected"],
            "process_instance_id": request.app.state.process_instance_id,
            "process_started_at": request.app.state.process_started_at}


@app.get("/api/auth/config", tags=["system"])
def auth_config(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    return {"required": settings.auth_required, "provider": "cognito" if settings.auth_required else None,
            "region": settings.cognito_region if settings.cognito_configured else None,
            "client_id": settings.cognito_app_client_id if settings.cognito_configured else None,
            "domain": settings.cognito_domain if settings.cognito_configured else None,
            "callback_url": settings.cognito_callback_url if settings.cognito_configured else None,
            "scopes": settings.cognito_scope_list if settings.cognito_configured else []}


@app.get("/api/stats", tags=["graph"])
def stats(request: Request, _: None = Depends(require_auth)) -> dict[str, Any]:
    try:
        return request.app.state.store.get_stats()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to read graph stats")
        raise HTTPException(status_code=502, detail="Could not read stats from FalkorDB. Check the server logs and connection configuration.") from exc


@app.get("/api/transactions/search", response_model=TransactionSearchResponse, tags=["graph"])
def search_transactions(
    request: Request,
    query: str = Query(default="", max_length=50),
    label: str = Query(default="", pattern="^(|illicit|licit|unknown)$"),
    limit: int = Query(default=20, ge=1, le=100),
    _: None = Depends(require_auth),
) -> dict[str, Any]:
    store = request.app.state.store
    try:
        items = store.search_transactions(query=query, label=label, limit=limit)
        return {"items": items, "count": len(items), "mode": store.mode}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Transaction search failed")
        raise HTTPException(status_code=502, detail="Transaction search failed. Check the server logs and graph schema.") from exc


@app.get("/api/transactions/{tx_id}", tags=["graph"])
def get_transaction(tx_id: str, request: Request, _: None = Depends(require_auth)) -> dict[str, Any]:
    if not tx_id.isdigit() or len(tx_id) > 50:
        raise HTTPException(status_code=422, detail="Transaction ID must contain digits only and be at most 50 characters.")
    store = request.app.state.store
    try:
        transaction = store.get_transaction(tx_id)
        if transaction is None:
            raise HTTPException(status_code=404, detail="Transaction not found in the selected graph.")
        neighbors = store.get_neighbors(tx_id)
        return {"transaction": transaction, "neighbors": neighbors, "mode": store.mode}
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Transaction lookup failed")
        raise HTTPException(status_code=502, detail="Transaction lookup failed. Check the server logs and graph schema.") from exc


@app.post("/api/investigations", response_model=InvestigationResponse, tags=["investigations"])
def create_investigation(body: InvestigationRequest, request: Request, owner_id: str | None = Depends(require_auth), _capacity: None = Depends(require_investigation_capacity), _write_target: None = Depends(require_demo_write_target)) -> dict[str, Any]:
    orchestrator = request.app.state.orchestrator
    try:
        result = orchestrator.investigate(body.seed_tx_id, body.max_hops, owner_id=owner_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Seed transaction was not found in the selected graph.")
        return result
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Investigation failed")
        raise HTTPException(status_code=502, detail="Investigation failed. Check the server logs for details.") from exc


@app.post("/api/investigations/preview", tags=["investigations"])
def preview_investigation(body: InvestigationRequest, request: Request, owner_id: str | None = Depends(require_auth), _capacity: None = Depends(require_investigation_capacity)) -> dict[str, Any]:
    """Run evidence gathering and agent analysis without writing a case or memory."""
    orchestrator = request.app.state.orchestrator
    try:
        settings: Settings = request.app.state.settings
        store = request.app.state.store
        if settings.track2_isolated_demo:
            store.reset_query_accounting()
        result = orchestrator.preview(body.seed_tx_id, body.max_hops, owner_id=owner_id,
                                      use_local_model=not settings.track2_isolated_demo,
                                      memory_enabled=body.memory_enabled,
                                      include_policy_explanation=settings.track2_isolated_demo)
        if result is None:
            raise HTTPException(status_code=404, detail="Seed transaction was not found in the selected graph.")
        if settings.track2_isolated_demo:
            result["demo_query_accounting"] = store.query_accounting()
        return result
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Read-only investigation preview failed")
        raise HTTPException(status_code=502, detail="Investigation preview failed. Check the server logs for details.") from exc


@app.post("/api/investigations/preview/stream", tags=["investigations"])
def stream_preview_investigation(body: InvestigationRequest, request: Request, owner_id: str | None = Depends(require_auth)):
    """Stream safe workflow milestones, followed by the complete read-only result."""
    if not investigation_slots.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Investigation capacity is busy. Retry shortly.", headers={"Retry-After": "3"})
    orchestrator = request.app.state.orchestrator
    investigation_id = f"inv_{uuid4().hex[:12]}"
    events: queue.Queue[dict[str, Any] | None] = queue.Queue()

    def publish_progress(event: dict[str, Any]) -> None:
        logger.info("investigation id=%s stage=%s agent=%s status=%s elapsed_ms=%s",
                    investigation_id, event.get("stage"), event.get("agent"),
                    event.get("status"), event.get("elapsed_ms"))
        events.put({**event, "investigation_id": investigation_id})

    def run_preview() -> None:
        try:
            settings: Settings = request.app.state.settings
            store = request.app.state.store
            if settings.track2_isolated_demo:
                store.reset_query_accounting()
            result = orchestrator.preview(body.seed_tx_id, body.max_hops,
                                          use_local_model=not settings.track2_isolated_demo,
                                          progress_callback=publish_progress,
                                          investigation_id=investigation_id, owner_id=owner_id,
                                          memory_enabled=body.memory_enabled,
                                          include_policy_explanation=settings.track2_isolated_demo)
            if result is None:
                events.put({"type": "error", "status": 404,
                            "detail": "Seed transaction was not found in the selected graph."})
            else:
                result["investigation_id"] = investigation_id
                if settings.track2_isolated_demo:
                    result["demo_query_accounting"] = store.query_accounting()
                events.put({"type": "result", "result": result})
        except RuntimeError as exc:
            logger.warning("Investigation %s unavailable (%s)", investigation_id, type(exc).__name__)
            events.put({"type": "error", "status": 503, "detail": str(exc)})
        except Exception as exc:
            logger.exception("Investigation %s failed", investigation_id)
            events.put({"type": "error", "status": 502,
                        "detail": "Investigation failed. Check the server logs, then retry."})
        finally:
            events.put(None)
            investigation_slots.release()

    async def event_stream():
        worker = threading.Thread(target=run_preview, name=f"bureau-{investigation_id}", daemon=True)
        try:
            worker.start()
        except Exception:
            investigation_slots.release()
            raise
        last_heartbeat = time.monotonic()
        yield f"event: started\ndata: {json.dumps({'investigation_id': investigation_id})}\n\n"
        while True:
            if await request.is_disconnected():
                break
            try:
                item = events.get_nowait()
            except queue.Empty:
                if time.monotonic() - last_heartbeat >= 10:
                    yield ": heartbeat\n\n"
                    last_heartbeat = time.monotonic()
                await asyncio.sleep(0.1)
                continue
            if item is None:
                break
            event_type = item.pop("type", "progress")
            yield f"event: {event_type}\ndata: {json.dumps(item, separators=(',', ':'))}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform",
                                      "X-Accel-Buffering": "no"})


@app.post("/api/investigations/save", tags=["investigations"])
def save_investigation(body: InvestigationRequest, request: Request, owner_id: str | None = Depends(require_auth), _capacity: None = Depends(require_investigation_capacity), _write_target: None = Depends(require_demo_write_target)) -> dict[str, Any]:
    """Explicitly rerun deterministic evidence reads and persist the resulting case."""
    orchestrator = request.app.state.orchestrator
    try:
        settings: Settings = request.app.state.settings
        store = request.app.state.store
        if settings.track2_isolated_demo:
            store.reset_query_accounting()
        preview = orchestrator.preview(body.seed_tx_id, body.max_hops, use_local_model=False, owner_id=owner_id,
                                       include_policy_explanation=settings.track2_isolated_demo)
        if preview is None:
            raise HTTPException(status_code=404, detail="Seed transaction was not found in the selected graph.")
        saved = orchestrator.save_preview(preview, owner_id=owner_id)
        if settings.track2_isolated_demo:
            confirmation = store.confirm_case_memory_provenance(
                saved["case_id"], saved["memory_id"], settings.isolated_demo_identity)
            if not confirmation["confirmed"]:
                raise HTTPException(status_code=503, detail="The write was not confirmed by database read-back; inspect the isolated case list before retrying.")
            saved["persistence_confirmation"] = confirmation
            saved["demo_query_accounting"] = store.query_accounting()
        return saved
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Case save failed")
        raise HTTPException(status_code=502, detail="Case could not be saved. Check the server logs for details.") from exc


@app.get("/api/cases", tags=["memory"])
def list_cases(request: Request, limit: int = Query(default=20, ge=1, le=50), owner_id: str | None = Depends(require_auth)) -> dict[str, Any]:
    store = request.app.state.store
    try:
        items = store.list_cases(limit=limit, owner_id=owner_id)
        return {"items": items, "count": len(items), "mode": store.mode}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Case listing failed")
        raise HTTPException(status_code=502, detail="Could not load cases from the selected graph.") from exc


@app.get("/api/cases/{case_id}", tags=["memory"])
def get_case(case_id: str, request: Request, owner_id: str | None = Depends(require_auth)) -> dict[str, Any]:
    store = request.app.state.store
    try:
        case = store.get_case(case_id, owner_id=owner_id)
        if case is None:
            raise HTTPException(status_code=404, detail="Case not found.")
        return case
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Case lookup failed")
        raise HTTPException(status_code=502, detail="Could not load this case from the selected graph.") from exc


@app.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    index_file = FRONTEND_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Frontend files are missing from this project checkout.")
    return FileResponse(index_file)

"""Run explicitly with backend.track1.app:create_app --factory."""
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, StrictInt

from .config import Target
from .investigator import Track1Investigator, unavailable
from .store import EvidenceUnavailable, IsolationError, SyntheticStore


class SyntheticRequest(BaseModel):
    start_txid: str = Field(pattern=r"^SYN-[0-9]{6}$")
    max_hops: StrictInt = Field(default=3, ge=1, le=6)


def create_app():
    target = Target.from_environment()
    app = FastAPI(title="Vesper — synthetic Track 1", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def loopback_only(request: Request, call_next):
        if not request.client or request.client.host not in {"127.0.0.1", "::1", "testclient"}:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Loopback access only"}, status_code=403)
        return await call_next(request)

    @app.get("/api/health")
    def health():
        store = SyntheticStore(target)
        try:
            return store.health()
        except EvidenceUnavailable:
            return unavailable()
        except IsolationError:
            raise HTTPException(503, "Graph isolation check failed") from None
        finally:
            store.close()

    @app.post("/api/investigate")
    def investigate(body: SyntheticRequest):
        store = SyntheticStore(target)
        try:
            return Track1Investigator(store).investigate(body.start_txid, body.max_hops)
        except IsolationError:
            raise HTTPException(503, "Graph isolation check failed") from None
        finally:
            store.close()

    @app.get("/", response_class=HTMLResponse)
    def home():
        return '''<!doctype html><html lang="en"><meta charset="utf-8"><title>Vesper · Track 1</title>
<style>body{max-width:900px;margin:60px auto;font:17px system-ui;color:#173238;background:#f5f4ee}input,button{font:inherit;padding:12px}pre{white-space:pre-wrap;background:white;padding:24px;border:1px solid #b5c7c4}</style>
<h1>Vesper · Connected evidence</h1><p>Team-authored synthetic scenarios. No real Bitcoin records or personal data.</p>
<p>Enter a start ID from the generated scenario manifest. This interface reads only the disposable graph.</p>
<form><input aria-label="Synthetic transaction ID" placeholder="SYN-000001" pattern="SYN-[0-9]{6}" required><button>Investigate</button></form>
<pre id="result">Ready. Findings are investigative leads, not legal conclusions about any person.</pre>
<script>document.querySelector('form').onsubmit=async e=>{e.preventDefault();const out=document.querySelector('#result');out.textContent='Reading graph…';try{const r=await fetch('/api/investigate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({start_txid:document.querySelector('input').value,max_hops:3})});out.textContent=JSON.stringify(await r.json(),null,2)}catch{out.textContent='Evidence unavailable.'}};</script></html>'''

    return app

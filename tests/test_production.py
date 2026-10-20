import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from backend.app import main
from backend.app.config import Settings, validate_production
from backend.app.services.graph_store import GraphStore


def test_render_marker_requires_auth_even_with_default_loopback():
    assert Settings(_env_file=None, render=True).auth_required


@pytest.mark.parametrize('overrides', [dict(app_mode='demo'), dict(falkordb_url='redis://host:6379'), dict(falkordb_url='rediss://host:6379?ssl_cert_reqs=none'), dict(cognito_callback_url='http://example.com'), dict(cors_origins='*')])
def test_production_rejects_insecure_configuration(overrides):
    config=dict(production=True, app_mode='cloud', falkordb_url='rediss://host:6379', auth_mode='cognito', cognito_region='region', cognito_user_pool_id='pool', cognito_app_client_id='client', cognito_domain='example.com', cognito_callback_url='https://example.com/', cors_origins='https://example.com')
    config.update(overrides)
    with pytest.raises(RuntimeError): validate_production(Settings(_env_file=None, **config))


def test_readiness_does_not_mistake_demo_for_database(install_demo_api):
    settings=Settings(_env_file=None)
    install_demo_api(settings, GraphStore(settings))
    with TestClient(main.app) as client:
        assert client.get('/api/live').status_code == 200
        result=client.get('/api/ready')
        assert result.status_code == 503
        assert result.json()['ok'] is False
        assert result.headers['cache-control'] == 'no-store'


def test_readiness_reprobes_cached_connection():
    store=GraphStore(Settings(_env_file=None, app_mode='cloud'))
    def offline(*args, **kwargs): raise ConnectionError('private endpoint')
    store._graph=SimpleNamespace(ro_query=offline)
    result=store.health()
    assert not result['database_connected']
    assert 'private endpoint' not in result['message']


def test_shutdown_closes_database_client():
    closed=[]
    store=GraphStore(Settings(_env_file=None))
    store._client=SimpleNamespace(close=lambda:closed.append(True))
    store.close();store.close()
    assert closed == [True]
    assert store._client is None


def test_cors_accepts_bearer_header_for_configured_origin(install_demo_api):
    settings=Settings(_env_file=None)
    install_demo_api(settings, GraphStore(settings))
    with TestClient(main.app) as client:
        result=client.options('/api/stats', headers={'Origin':'http://localhost:8000', 'Access-Control-Request-Method':'GET', 'Access-Control-Request-Headers':'authorization'})
        assert result.status_code == 200
        rejected=client.options('/api/stats', headers={'Origin':'https://untrusted.example', 'Access-Control-Request-Method':'GET'})
        assert rejected.status_code == 400


def test_vercel_supports_both_project_roots():
    root=Path(__file__).resolve().parents[1]
    for path in ('vercel.json', 'frontend/vercel.json'):
        config=json.loads((root/path).read_text())
        assert config['rewrites']==[{'source':'/api/:path*','destination':'https://vesper-73uk.onrender.com/api/:path*'}]


def test_stream_disconnect_keeps_capacity_until_worker_finishes(monkeypatch):
    import asyncio
    import threading
    from backend.app.models import InvestigationRequest
    started=threading.Event(); finish=threading.Event()
    def preview(*args, **kwargs):
        started.set(); finish.wait(timeout=3)
        return {'persisted':False}
    slots=threading.BoundedSemaphore(1)
    monkeypatch.setattr(main,'investigation_slots',slots)
    async def disconnected(): return True
    request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        orchestrator=SimpleNamespace(preview=preview),
        settings=Settings(_env_file=None), store=GraphStore(Settings(_env_file=None)))),
        is_disconnected=disconnected)
    async def consume():
        response=main.stream_preview_investigation(InvestigationRequest(seed_tx_id='730000004'),request,owner_id=None)
        async for _ in response.body_iterator: pass
    try:
        asyncio.run(consume())
        assert started.wait(timeout=1)
        assert not slots.acquire(blocking=False)
    finally:
        finish.set()
    assert slots.acquire(timeout=2)
    slots.release()


def test_production_accepts_secure_configuration():
    validate_production(Settings(_env_file=None, production=True, app_mode='cloud',
        falkordb_url='rediss://db.example:6379', auth_mode='cognito',
        cognito_region='region', cognito_user_pool_id='pool', cognito_app_client_id='client',
        cognito_domain='example.com', cognito_callback_url='https://example.com/',
        cors_origins='https://example.com'))

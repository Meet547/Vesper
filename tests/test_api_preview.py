from fastapi.testclient import TestClient

from backend.app import main
from backend.app.agents.orchestrator import InvestigationOrchestrator
from backend.app.config import Settings
from backend.app.services.graph_store import GraphStore


def test_served_frontend_is_never_reused_from_browser_cache(install_demo_api):
    demo_settings = Settings(_env_file=None, app_mode="demo", model_provider="local")
    demo_store = GraphStore(demo_settings)
    install_demo_api(demo_settings, demo_store)
    with TestClient(main.app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "<h1>Vesper</h1>" in response.text
        assert "no-store" in response.headers["cache-control"]
        assert response.headers["pragma"] == "no-cache"


def test_preview_api_is_read_only_and_reports_real_backend_events(monkeypatch, install_demo_api):
    demo_settings = Settings(_env_file=None, app_mode="demo", model_provider="local",
                             ollama_base_url="http://127.0.0.1:9")
    demo_store = GraphStore(demo_settings)
    install_demo_api(demo_settings, demo_store)
    with TestClient(main.app) as client:
        response = client.post("/api/investigations/preview", json={"seed_tx_id": "730000004", "max_hops": 2})
        assert response.status_code == 200
        payload = response.json()
        assert payload["persisted"] is False
        assert "case_id" not in payload
        assert {event["agent"] for event in payload["agent_events"]} >= {"Scout", "Tracer", "Historian", "Skeptic", "Reporter"}
        assert demo_store.list_cases(10) == []


def test_streaming_preview_emits_safe_stage_events_and_final_report(monkeypatch, install_demo_api):
    demo_settings = Settings(_env_file=None, app_mode="demo", model_provider="cloud",
                             ollama_api_key="", ollama_cloud_model="gpt-oss:20b")
    demo_store = GraphStore(demo_settings)
    install_demo_api(demo_settings, demo_store)
    with TestClient(main.app) as client:
        response = client.post("/api/investigations/preview/stream",
                               json={"seed_tx_id": "730000004", "max_hops": 2})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = response.text
        assert "event: started" in body
        assert '"agent":"Scout"' in body
        assert '"agent":"Tracer"' in body
        assert '"agent":"Analyst"' in body
        assert '"agent":"Reporter"' in body
        assert "event: result" in body
        assert '"investigation_id":"inv_' in body
        assert '"persisted":false' in body
        assert "hidden reasoning" not in body.lower()
        assert demo_store.list_cases(10) == []


def test_streaming_preview_reports_missing_seed_without_fake_result(monkeypatch, install_demo_api):
    demo_settings = Settings(_env_file=None, app_mode="demo", model_provider="cloud")
    demo_store = GraphStore(demo_settings)
    install_demo_api(demo_settings, demo_store)
    with TestClient(main.app) as client:
        response = client.post("/api/investigations/preview/stream",
                               json={"seed_tx_id": "999999999", "max_hops": 2})
        assert response.status_code == 200
        assert "event: error" in response.text
        assert "Seed transaction was not found" in response.text
        assert "event: result" not in response.text


def test_streaming_preview_exposes_memory_search_and_validation_and_api_result(monkeypatch, install_demo_api):
    demo_settings = Settings(_env_file=None, app_mode="demo", model_provider="local",
                             ollama_base_url="http://127.0.0.1:9")
    demo_store = GraphStore(demo_settings)
    demo_orchestrator = InvestigationOrchestrator(demo_store, demo_settings)
    saved = demo_orchestrator.investigate("730000004", 3)
    assert saved is not None
    install_demo_api(demo_settings, demo_store, demo_orchestrator)

    with TestClient(main.app) as client:
        response = client.post("/api/investigations/preview/stream",
                               json={"seed_tx_id": "730000002", "max_hops": 3})
        assert response.status_code == 200
        assert "event: progress" in response.text
        assert '"event_name":"memory_candidate_found"' in response.text
        assert '"event_name":"memory_verified"' in response.text
        assert "event: memory_candidate_found" not in response.text
        assert '"validationStatus":"VERIFIED_RELEVANT"' in response.text
        assert f'"caseId":"{saved["case_id"]}"' in response.text
        assert '"current_facts_unchanged":true' in response.text


def test_saved_case_api_returns_related_memories_and_structured_memory_status(monkeypatch, install_demo_api):
    demo_settings = Settings(_env_file=None, app_mode="demo", model_provider="local",
                             ollama_base_url="http://127.0.0.1:9")
    demo_store = GraphStore(demo_settings)
    demo_orchestrator = InvestigationOrchestrator(demo_store, demo_settings)
    first = demo_orchestrator.investigate("730000004", 3)
    second = demo_orchestrator.preview("730000002", 3, use_local_model=False)
    assert first and second
    saved_second = demo_orchestrator.save_preview(second)
    install_demo_api(demo_settings, demo_store, demo_orchestrator)

    with TestClient(main.app) as client:
        response = client.get(f"/api/cases/{saved_second['case_id']}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["memorySchemaVersion"] == "1.0"
        assert payload["relatedMemories"][0]["caseId"] == first["case_id"]
        assert payload["relatedMemories"][0]["validationStatus"] == "VERIFIED_RELEVANT"
        assert payload["structuredReport"]["memory_review"]["current_facts_unchanged"] is True


def test_non_local_startup_fails_closed_without_cognito(monkeypatch, install_demo_api):
    import asyncio
    import pytest
    from backend.app import main

    settings = Settings(_env_file=None)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(settings, "app_host", "0.0.0.0")
    monkeypatch.setattr(settings, "auth_mode", "none")
    for name in (
        "cognito_region", "cognito_user_pool_id", "cognito_app_client_id",
        "cognito_domain", "cognito_callback_url",
    ):
        monkeypatch.setattr(settings, name, "")
    with pytest.raises(RuntimeError, match="requires complete Amazon Cognito"):
        asyncio.run(main.lifespan(main.app).__aenter__())


def test_stream_handoffs_use_real_context_and_terminal_snapshot_is_idle(install_demo_api):
    import json

    settings = Settings(_env_file=None, app_mode="demo", model_provider="cloud", ollama_api_key="")
    store = GraphStore(settings)
    install_demo_api(settings, store)
    with TestClient(main.app) as client:
        response = client.post("/api/investigations/preview/stream",
                               json={"seed_tx_id": "730000004", "max_hops": 2})
        assert response.status_code == 200
        frames = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        progress = [frame for frame in frames if "agent" in frame]
        handoffs = [frame["handoff"] for frame in progress if frame.get("event_name") == "agent_handoff"]
        assert [(item["from"], item["to"]) for item in handoffs] == [
            ("Scout", "Tracer"), ("Tracer", "Skeptic"), ("Historian", "Skeptic"), ("Skeptic", "Reporter")]
        assert handoffs[0]["evidence_ids"] == ["tx:730000004"]
        final = progress[-1]
        assert final["agent"] == "Reporter"
        assert final["shared_context"]["report_status"] == "ready"
        assert final["shared_context"]["active_agents"] == []
        assert final["shared_context"]["skeptic_conclusions"]["invalid_paths"] == 0
        assert all(frame["shared_context"]["investigation_id"] == final["investigation_id"]
                   for frame in progress if frame.get("shared_context"))
        assert store.list_cases(50) == []


def test_investigation_capacity_fails_fast_with_retry_after(monkeypatch, install_demo_api):
    import threading

    settings = Settings(_env_file=None, app_mode="demo", model_provider="local",
                        ollama_base_url="http://127.0.0.1:9")
    store = GraphStore(settings)
    install_demo_api(settings, store)
    monkeypatch.setattr(main, "investigation_slots", threading.BoundedSemaphore(0))
    with TestClient(main.app) as client:
        response = client.post("/api/investigations/preview/stream",
                               json={"seed_tx_id": "730000004", "max_hops": 2})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "3"
    assert response.json()["detail"] == "Investigation capacity is busy. Retry shortly."

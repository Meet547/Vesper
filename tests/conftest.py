"""API tests use isolated application-lifespan state, never local .env settings."""
import pytest

from backend.app import main
from backend.app.agents.orchestrator import InvestigationOrchestrator


@pytest.fixture
def install_demo_api(monkeypatch):
    def install(settings, store, orchestrator=None):
        monkeypatch.setattr(main, "get_settings", lambda: settings)
        monkeypatch.setattr(main, "GraphStore", lambda _settings: store)
        coordinator = orchestrator or InvestigationOrchestrator(store, settings)
        monkeypatch.setattr(main, "InvestigationOrchestrator", lambda *_args: coordinator)
    return install

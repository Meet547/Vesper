import httpx
import pytest
from types import SimpleNamespace

from backend.app.agents.local_model import LocalModelAgent
from backend.app.agents.orchestrator import InvestigationOrchestrator
from backend.app.config import Settings
from backend.app.services.graph_store import GraphStore
from backend.app.tools.investigation_tools import InvestigationTools


def test_local_model_tool_allowlist_is_read_only_and_bounded():
    agent = LocalModelAgent(InvestigationTools(GraphStore(Settings(app_mode="demo"))), "http://localhost:11434", "test")
    assert agent._invoke("get_transaction", {"tx_id": "730000004"})["txId"] == "730000004"
    assert len(agent._invoke("trace_paths", {"tx_id": "730000004", "max_hops": 99})) <= 20
    with pytest.raises(ValueError, match="allowlist"):
        agent._invoke("save_case", {})
    with pytest.raises(ValueError, match="digits only"):
        agent._invoke("get_transaction", {"tx_id": "1 MATCH (n)"})


def test_model_json_tool_intent_is_invoked_via_allowlist_and_not_reported_as_prose():
    class FakeClient:
        def __init__(self):
            self.messages = [
                {"message": {"content": '{"name":"get_transaction","arguments":{"tx_id":"730000004"}}'}},
                {"message": {"content": "The seed label is illicit in this demo fixture."}},
            ]

        def post(self, *_args, **_kwargs):
            value = self.messages.pop(0)
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: value)

    store = GraphStore(Settings(app_mode="demo"))
    agent = LocalModelAgent(InvestigationTools(store), "http://localhost:11434", "test", client=FakeClient())
    result = agent.analyze("730000004", 2, {"seed": {"txId": "730000004"}})
    assert result["status"] == "complete"
    assert "name" not in result["observations"]
    assert result["events"] == [{"agent": "Analyst", "type": "tool_call", "tool": "get_transaction", "status": "completed", "read_only": True}]


def _demo_tools():
    return InvestigationTools(GraphStore(Settings(app_mode="demo")))


def test_model_connection_resolution_keeps_provider_configurable():
    assert Settings(_env_file=None, app_mode="demo").model_connection["provider"] == "local"
    cloud = Settings(_env_file=None, app_mode="demo", model_provider="cloud", ollama_api_key="KEY")
    assert cloud.model_connection == {"provider": "cloud", "base_url": "https://ollama.com",
                                      "model": "gpt-oss:20b", "api_key": "KEY"}
    assert cloud.model_configured is True
    assert Settings(_env_file=None, app_mode="demo", model_provider="cloud").model_configured is False


def test_cloud_provider_sends_bearer_and_strips_thinking_metadata():
    captured = {}

    class CloudClient:
        def post(self, url, json=None, headers=None):
            captured["url"], captured["headers"] = url, headers or {}
            return SimpleNamespace(raise_for_status=lambda: None,
                                   json=lambda: {"message": {"content": "Concise finding.",
                                                             "thinking": "SECRET_INTERNAL_REASONING"}})

    agent = LocalModelAgent(_demo_tools(), "https://ollama.com", "gpt-oss:20b",
                            client=CloudClient(), api_key="SECRET_KEY")
    result = agent.analyze("730000004", 2, {"seed": {"txId": "730000004"}})
    assert result["status"] == "complete"
    assert result["observations"] == "Concise finding."
    assert "SECRET_INTERNAL_REASONING" not in result["observations"]
    assert captured["url"] == "https://ollama.com/api/chat"
    assert captured["headers"].get("Authorization") == "Bearer SECRET_KEY"
    assert "SECRET_KEY" not in result["observations"]


def test_cloud_http_401_is_unavailable_and_does_not_leak_secret():
    def raise_401():
        raise httpx.HTTPStatusError("401", request=httpx.Request("POST", "https://ollama.com/api/chat"),
                                    response=httpx.Response(401))

    class UnauthClient:
        def post(self, *_a, **_k):
            return SimpleNamespace(raise_for_status=raise_401)

    agent = LocalModelAgent(_demo_tools(), "https://ollama.com", "gpt-oss:20b",
                            client=UnauthClient(), api_key="SECRET_KEY")
    result = agent.analyze("730000004", 2, {"seed": {"txId": "730000004"}})
    assert result["status"] == "unavailable"
    assert result["observations"] == ""
    assert all("SECRET_KEY" not in w for w in result["warnings"])


def test_cloud_retries_once_on_429(monkeypatch):
    monkeypatch.setattr("backend.app.agents.local_model.time.sleep", lambda *_a, **_k: None)

    class FlakyClient:
        def __init__(self):
            self.calls = 0

        def post(self, *_a, **_k):
            self.calls += 1
            code = 429 if self.calls == 1 else 200
            return SimpleNamespace(status_code=code, raise_for_status=lambda: None,
                                   json=lambda: {"message": {"content": "ok after retry"}})

    client = FlakyClient()
    agent = LocalModelAgent(_demo_tools(), "https://ollama.com", "gpt-oss:20b",
                            client=client, api_key="KEY")
    result = agent.analyze("730000004", 2, {"seed": {"txId": "730000004"}})
    assert client.calls == 2
    assert result["status"] == "complete"
    assert result["observations"] == "ok after retry"


def test_orchestrator_cloud_without_key_is_unavailable_without_calling_model():
    settings = Settings(_env_file=None, app_mode="demo", model_provider="cloud")
    preview = InvestigationOrchestrator(GraphStore(settings), settings).preview("730000004", 2, use_local_model=True)
    assert preview["local_model"]["status"] == "unavailable"
    assert "not configured" in preview["local_model"]["message"]
    assert preview["persisted"] is False

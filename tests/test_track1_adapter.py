"""Track 1-only checks; legacy validators and Track 2 tests stay unchanged."""
import json

import pytest
from pydantic import ValidationError

from backend.app.models import InvestigationRequest
from backend.track1.app import SyntheticRequest
from backend.track1.config import Target
from backend.track1.investigator import Track1Investigator
from backend.track1.store import EvidenceUnavailable, IsolationError, SyntheticStore, check_hops


def test_synthetic_contract_does_not_weaken_legacy_request():
    with pytest.raises(ValidationError):
        InvestigationRequest(seed_tx_id="SYN-000001")
    assert InvestigationRequest(seed_tx_id="730000004").seed_tx_id == "730000004"
    assert SyntheticRequest(start_txid="SYN-000001").start_txid == "SYN-000001"
    for value in ("730000004", "SYN-1", "SYN-000001 OR true", "SYN-000001\n"):
        with pytest.raises(ValidationError):
            SyntheticRequest(start_txid=value)


def test_hop_bound_is_strict():
    for value in (0, 7, True, "3", 3.0):
        with pytest.raises(ValueError):
            check_hops(value)
    assert check_hops(6) == 6


def test_configuration_requires_opt_in_and_named_graph(monkeypatch, tmp_path):
    monkeypatch.delenv("VESPER_TRACK", raising=False)
    with pytest.raises(ValueError):
        Target.from_environment()
    monkeypatch.setenv("VESPER_TRACK", "track1_synthetic")
    monkeypatch.setenv("VESPER_TRACK1_GRAPH", "production")
    with pytest.raises(ValueError):
        Target.from_environment()
    monkeypatch.setenv("VESPER_TRACK1_GRAPH", "vesper_synthetic_verify")
    path = tmp_path / "target.json"
    monkeypatch.setenv("VESPER_TRACK1_TARGET_FILE", str(path))
    path.write_text(json.dumps({"container_name": "another-container", "host": "127.0.0.1"}))
    with pytest.raises(ValueError):
        Target.from_environment()


def test_database_identity_mismatch_prevents_query():
    target = Target(16479, "expected-run", "owned-container", "vesper_synthetic_verify")
    store = SyntheticStore(target)
    class WrongServer:
        def info(self, section):
            return {"run_id": "another-server"}
        def close(self):
            pass
    store.redis = WrongServer()
    with pytest.raises(IsolationError):
        store.read("RETURN 1")
    store.close()


@pytest.mark.parametrize("fail_stage", ["health", "get_transaction", "expand_outgoing", "edge"])
def test_outage_discards_all_partial_evidence(fail_stage):
    class InterruptedStore:
        def health(self):
            if fail_stage == "health":
                raise EvidenceUnavailable()
            return {"database_connected": True}
        def get_transaction(self, txid):
            if fail_stage == "get_transaction":
                raise EvidenceUnavailable()
            return {"txId": txid, "label": "hub"}
        def expand_outgoing(self, start, hops):
            if fail_stage == "expand_outgoing":
                raise EvidenceUnavailable()
            return {"paths": [{"txids": [start, "SYN-000002"], "relationship_ids": [1], "hops": 1}], "truncated": False}
        def edge(self, a, b):
            raise EvidenceUnavailable()
    result = Track1Investigator(InterruptedStore()).investigate("SYN-000001")
    assert result["status"] == "evidence_unavailable"
    assert result["paths"] == [] and result["action"] is None and result["conclusion"] is None
    assert "SYN-" not in json.dumps(result)

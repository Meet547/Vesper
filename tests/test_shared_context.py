from copy import deepcopy

from backend.app.agents.orchestrator import InvestigationOrchestrator
from backend.app.agents.shared_context import SharedInvestigationContext
from backend.app.config import Settings
from backend.app.services.graph_store import GraphStore


def test_model_decisions_cannot_replace_deterministic_graph_facts():
    context = SharedInvestigationContext("case_demo", "11", 2, "inv_demo")
    ledger = {
        "source_graph": "fixture",
        "transactions": {"11": {"label": "licit"}},
        "edges": [{"edge_id": "11->22", "source": "11", "target": "22", "evidence_paths": [0]}],
        "paths": [{"path_index": 0, "node_ids": ["11", "22"], "valid": True}],
    }
    context.set_graph_evidence(ledger, [])
    graph_facts = deepcopy(context.final_context()["verified_facts"])
    context.classify_claims([
        {"claim_id": "m1", "claim_text": "reported 7 paths", "verification_status": "rejected",
         "expected_value": 1, "evidence_ids": ["evidence_ledger"]},
        {"claim_id": "m2", "claim_text": "possible link", "verification_status": "unverified"},
    ])
    result = context.final_context()
    assert result["verified_facts"] == graph_facts
    assert result["evidence_ledger"]["ref"] == "preview.evidence_ledger"
    assert result["rejected_claims"][0]["claim_id"] == "m1"
    assert result["unverified_claims"][0]["claim_id"] == "m2"
    assert result["authority"]["graph"] == "DETERMINISTIC_GRAPH_EVIDENCE"


def test_shared_context_is_read_by_role_agents_streams_real_handoffs_and_persists(monkeypatch):
    captured_payload = {}

    class AnalystStub:
        def __init__(self, *_args, **_kwargs):
            pass

        def analyze(self, _seed, _hops, evidence):
            captured_payload.update(evidence)
            return {"status": "complete", "observations": "A pattern may be relevant; verify with graph evidence.",
                    "events": [], "model": "test-stub", "warnings": []}

    monkeypatch.setattr("backend.app.agents.orchestrator.LocalModelAgent", AnalystStub)
    store = GraphStore(Settings(_env_file=None, app_mode="demo"))
    settings = Settings(_env_file=None, app_mode="demo", model_provider="local")
    orchestrator = InvestigationOrchestrator(store, settings)
    streamed = []
    preview = orchestrator.preview("730000004", 2, use_local_model=True, progress_callback=streamed.append,
                                   investigation_id="inv_context_test")

    assert preview is not None and preview["persisted"] is False
    context = preview["shared_context"]
    assert set(context["shared_readers"]) == {"Scout", "Tracer", "Historian", "Analyst", "Skeptic", "Reporter"}
    assert context["investigation_id"] == "inv_context_test"
    assert context["graph_scope"]["hop_depth"] == 2
    assert context["graph_scope"]["current_nodes"]
    assert captured_payload["shared_investigation_context"]["seed_transaction"] == "730000004"
    assert any(h["from"] == "Scout" and h["to"] == "Tracer" and h["type"] == "seed_context" for h in context["handoffs"])
    assert any(h["from"] == "Tracer" and h["to"] == "Skeptic" and h["type"] == "evidence_handoff" for h in context["handoffs"])
    assert any(h["from"] == "Skeptic" and h["to"] == "Reporter" and h["type"] == "verification_handoff" for h in context["handoffs"])
    event_names = {event.get("event_name") for event in streamed}
    assert {"agent_handoff", "context_sync_started", "context_sync_completed", "meeting_started",
            "meeting_completed", "cross_verification_started", "cross_verification_completed"} <= event_names
    assert all("shared_context" in event for event in streamed if event.get("event_name"))
    assert preview["local_model"]["observations"] not in str(context)
    assert context["status"] == "complete"
    assert context["active_agents"] == []
    assert context["report_status"] == "ready"
    assert context["memory_lookup_status"] == "complete"
    terminal = streamed[-1]
    assert terminal["agent"] == "Reporter" and terminal["stage"] == "completed"
    assert terminal["shared_context"]["report_status"] == "ready"
    assert terminal["shared_context"]["active_agents"] == []

    saved = orchestrator.save_preview(preview)
    record = store.get_case(saved["case_id"])
    assert saved["persisted"] is True
    assert record["sharedContext"]["case_id"] == saved["case_id"]
    assert record["sharedContext"]["handoffs"]
    assert record["sharedContext"]["verified_facts"]
    # Save is explicit; the preview itself did not persist anything.
    assert len(store.list_cases(10)) == 1


def test_failed_directed_path_never_becomes_verified_shared_evidence():
    context = SharedInvestigationContext("case_fixture", "11", 2)
    ledger = {"transactions": {"11": {"label": "licit"}, "99": {"label": "illicit"}},
              "edges": [{"edge_id": "11->99", "source": "11", "target": "99", "evidence_paths": [0]}],
              "paths": [{"path_index": 0, "valid": False, "node_ids": ["11", "99"],
                         "validation_reason": "Directed edge is missing"}]}
    context.set_graph_evidence(ledger, [])
    snapshot = context.public_snapshot()
    assert [fact["fact_id"] for fact in snapshot["verified_facts"]] == ["tx:11"]
    assert snapshot["unverified_claims"][0]["claim_id"] == "path:0"
    # Snapshots and the caller's ledger cannot mutate the authoritative context.
    snapshot["verified_facts"].clear()
    ledger["transactions"].clear()
    assert len(context.public_snapshot()["verified_facts"]) == 1


def test_candidate_memory_and_unresolved_claims_keep_their_verification_status():
    context = SharedInvestigationContext("case_fixture", "11", 2)
    context.add_memory_candidate({"caseId": "prior_case", "sharedTransactions": ["11"]})
    context.add_hypothesis("claim_1", "A count to check")
    context.classify_claims([{"claim_id": "claim_1", "verification_status": "rejected", "reason": "Count mismatch"}])
    context.finish()
    snapshot = context.public_snapshot()
    assert snapshot["memory_candidates"][0]["authority"] == "UNVERIFIED_MEMORY"
    assert snapshot["hypotheses"][0]["verification"] == "rejected"
    assert snapshot["skeptic_conclusions"]["claim_counts"]["rejected"] == 1
    assert "saved cases" not in str(snapshot["open_questions"])

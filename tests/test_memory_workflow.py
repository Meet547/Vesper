"""Persistent-memory contract and Skeptic revalidation regressions.

Behavioral cases use the explicitly labelled demo graph as a unit-test fixture.
Durability in production is verified separately through the authenticated Cloud UI.
"""
import json
from types import SimpleNamespace
from pathlib import Path
import pytest

from backend.app.agents.orchestrator import InvestigationOrchestrator
from backend.app.agents.reporter import ReporterAgent
from backend.app.agents.skeptic import SkepticAgent
from backend.app.config import Settings
from backend.app.services.graph_store import GraphStore


def test_saved_demo_case_has_auditable_versioned_evidence_and_reloads():
    store = GraphStore(Settings(app_mode="demo"))
    orchestrator = InvestigationOrchestrator(store)
    saved = orchestrator.investigate("730000004", 3)

    assert saved and saved["persisted"] is True
    case = store.get_case(saved["case_id"])
    assert case["memorySchemaVersion"] == "1.0"
    assert case["evidenceLedger"]["transactions"]
    assert case["evidenceRefs"]["transaction_ids"]
    assert case["verifiedClaims"]
    assert case["traces"]


def test_demo_memory_save_is_idempotent_for_stable_case_and_memory_ids():
    store = GraphStore(Settings(_env_file=None, app_mode="demo"))
    case = {"case_id": "case-stable", "memory_id": "memory-stable",
            "seed": {"txId": "730000004", "label": "illicit"}, "traces": [],
            "skeptic": {}, "related_memories": [], "summary": "fixture", "status": "needs_human_review",
            "created_at": "2026-10-17T00:00:00+00:00", "evidence_tx_ids": ["730000004"]}
    store.save_case(case)
    store.save_case(case)
    assert len(store._demo_cases) == 1
    assert len(store._demo_memories) == 1


def test_concurrent_preview_sessions_keep_seed_evidence_separate():
    from concurrent.futures import ThreadPoolExecutor

    store = GraphStore(Settings(_env_file=None, app_mode="demo"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(InvestigationOrchestrator(store).preview, "730000004", 2, False)
        second_future = pool.submit(InvestigationOrchestrator(store).preview, "730000002", 2, False)
        first, second = first_future.result(), second_future.result()
    assert first["seed"]["txId"] == "730000004"
    assert second["seed"]["txId"] == "730000002"
    first_seeds = [item["tx_id"] for item in first["evidence_ledger"]["transactions"].values()
                   if item.get("is_seed")]
    second_seeds = [item["tx_id"] for item in second["evidence_ledger"]["transactions"].values()
                    if item.get("is_seed")]
    assert first_seeds == ["730000004"]
    assert second_seeds == ["730000002"]


def test_historian_retrieves_only_transaction_overlap_with_explanation():
    store = GraphStore(Settings(app_mode="demo"))
    orchestrator = InvestigationOrchestrator(store)
    first = orchestrator.investigate("730000004", 3)
    second = orchestrator.preview("730000002", 3, use_local_model=False)

    assert first and second
    case_memory = next(memory for memory in second["related_memories"] if memory["caseId"] == first["case_id"])
    assert {"730000002", "730000004"}.issubset(set(case_memory["sharedTransactions"]))
    assert "shares transaction IDs" in case_memory["relevanceReason"]
    assert case_memory["validationStatus"] == "VERIFIED_RELEVANT"
    assert "730000002->730000004" in case_memory["currentSupportingEdges"]


def test_no_overlap_returns_no_memory_and_report_does_not_invent_a_link(monkeypatch):
    import backend.app.services.graph_store as graph_store_module

    # Add one disconnected transaction only inside this isolated demo fixture.
    # The production graph and evaluation corpus are not changed.
    monkeypatch.setattr(graph_store_module, "_DEMO_TRANSACTIONS", {
        **graph_store_module._DEMO_TRANSACTIONS,
        "999888": {"txId": "999888", "label": "unknown", "timeStep": 1, "sourceDataset": "fixture"},
    })
    store = GraphStore(Settings(app_mode="demo"))
    orchestrator = InvestigationOrchestrator(store)
    orchestrator.investigate("730000004", 3)
    unrelated = orchestrator.preview("999888", 3, use_local_model=False)

    assert unrelated
    assert unrelated["related_memories"] == []
    assert unrelated["structured_report"]["memory_review"]["validated_count"] == 0
    assert "no saved case sharing transaction IDs" in unrelated["summary"]


def test_skeptic_rejects_a_memory_whose_shared_label_conflicts_with_current_graph():
    store = GraphStore(Settings(app_mode="demo"))
    orchestrator = InvestigationOrchestrator(store)
    first = orchestrator.investigate("730000004", 3)
    current = orchestrator.preview("730000002", 3, use_local_model=False)
    candidate = next(memory for memory in current["related_memories"] if memory["caseId"] == first["case_id"])
    remembered_label_claim = next(claim for claim in candidate["verifiedClaims"]
                                  if claim.get("claim_type") == "transaction_label" and claim.get("tx_id") == "730000002")
    remembered_label_claim["label"] = "licit"

    checked = SkepticAgent().validate_memories([candidate], current["evidence_ledger"], store)[0]
    assert checked["validationStatus"] == "CONTRADICTED"
    assert checked["labelConflicts"] == [{
        "tx_id": "730000002", "remembered_label": "licit", "current_label": "unknown",
        "evidence_id": "tx:730000002",
    }]


def test_skeptic_excludes_stale_memory_paths_when_current_edge_disappears(monkeypatch):
    import backend.app.services.graph_store as graph_store_module

    store = GraphStore(Settings(_env_file=None, app_mode="demo"))
    first = InvestigationOrchestrator(store).investigate("730000004", 2)
    current = InvestigationOrchestrator(store).preview("730000002", 2, use_local_model=False)
    candidate = next(memory for memory in current["related_memories"] if memory["caseId"] == first["case_id"])
    removed = set(candidate["evidence"][0]["edge_ids"])
    monkeypatch.setattr(graph_store_module, "_DEMO_EDGES",
                        [edge for edge in graph_store_module._DEMO_EDGES if f"{edge[0]}->{edge[1]}" not in removed])
    checked = SkepticAgent().validate_memories([candidate], current["evidence_ledger"], store)[0]
    assert checked["validationStatus"] == "STALE"


def test_controlled_memory_ab_changes_frontier_after_skeptic_revalidation():
    from scripts.demo_milestone_8_4_memory_ab import run_demo

    result = run_demo()
    assert result["production_graph_touched"] is False
    assert result["same_graph_policy_budget_and_seed"] is True
    assert result["causal_trace"]["historian_recall"] is True
    assert result["causal_trace"]["skeptic_validated_memory"] is True
    assert result["causal_trace"]["changed_action"] is True
    assert result["causal_trace"]["route_independently_verified"] is True
    assert result["causal_trace"]["shared_current_graph_edge"] == "731000001->731000002"
    assert result["interpretation"]["verified_path_count_delta"] == 1
    assert result["interpretation"]["total_source_read_delta"] > 0


def test_reporter_excludes_contradicted_memory_from_report_facts():
    store = GraphStore(Settings(app_mode="demo"))
    orchestrator = InvestigationOrchestrator(store)
    first = orchestrator.investigate("730000004", 3)
    current = orchestrator.preview("730000002", 3, use_local_model=False)
    candidate = next(memory for memory in current["related_memories"] if memory["caseId"] == first["case_id"])
    candidate["evidenceLedger"]["transactions"]["730000002"]["label"] = "licit"
    candidate = SkepticAgent().validate_memories([candidate], current["evidence_ledger"], store)

    report = ReporterAgent().create_report(current["seed"], current["evidence_ledger"],
        current["skeptic"], candidate, model_observations="",
        evaluated_claims=current["claim_validation"]["validated_claims"])
    review = report["structured_report"]["memory_review"]
    assert review["validated_count"] == 0
    assert review["excluded_count"] == 1
    assert review["current_facts_unchanged"] is True
    assert "CONTRADICTED" in report["summary"]
    assert "Validated memory from case" not in report["summary"]


def test_reporter_explains_only_a_skeptic_verified_memory_policy_route():
    memory = {"caseId": "case_a", "memoryId": "memory_a",
              "validationStatus": "VERIFIED_RELEVANT", "currentSupportingEdges": ["731000001->731000002"]}
    decision = {"selected_action": "follow_verified_memory_route", "action_outcome": {
        "memory_route_verified": True, "selected_frontier_tx_id": "731000002",
        "route_evidence_id": "path:downstream:731000001>731000002>731000003>731000004",
        "memory_provenance": {"case_id": "case_a", "memory_id": "memory_a",
                              "source_path_id": "path:downstream:731000002>731000003>731000004"},
    }}

    explanation = ReporterAgent._memory_policy_explanation([memory], [decision])

    assert explanation["status"] == "verified"
    assert explanation["frontier_tx_id"] == "731000002"
    assert explanation["current_supporting_edges"] == ["731000001->731000002"]
    assert "independently verified the joined current route" in explanation["explanation"]
    assert ReporterAgent._memory_policy_explanation(
        [{**memory, "validationStatus": "PARTIALLY_RELEVANT"}], [decision]) is None
    assert ReporterAgent._memory_policy_explanation(
        [memory], [{**decision, "action_outcome": {**decision["action_outcome"],
                  "memory_route_verified": False}}]) is None


def test_cloud_save_writes_linked_versioned_memory_without_model_reasoning():
    class WriteGraph:
        def __init__(self):
            self.calls = []

        def query(self, query, params, timeout):
            self.calls.append((query, params, timeout))
            return SimpleNamespace(result_set=[[params["case_id"], params["memory_id"], len(params["evidence_tx_ids"])]] )

        def ro_query(self, *_args, **_kwargs):
            raise AssertionError("save_case should use the explicit graph write path")

    store = GraphStore(Settings(_env_file=None, app_mode="cloud", falkordb_host="example", falkordb_password="fixture"))
    graph = WriteGraph()
    store._graph = graph
    case = {
        "case_id": "case_fixture", "memory_id": "memory_fixture", "seed": {"txId": "900", "label": "unknown"},
        "traces": [{"direction": "downstream", "hops": 1, "nodes": [{"txId": "900"}, {"txId": "901"}]}],
        "skeptic": {"findings": []}, "related_memories": [], "summary": "fixture summary",
        "status": "needs_human_review", "created_at": "2026-10-16T00:00:00+00:00",
        "evidence_tx_ids": ["900", "901"], "evidence_ledger": {"transactions": {"900": {"label": "unknown"}}, "edges": [], "paths": []},
        "verified_claims": [{"claim_type": "seed_existence", "evidence_ids": ["900"]}],
        "rejected_claims": [], "memory_schema_version": "1.0", "model_metadata": {"analysis_status": "not_run"},
    }

    stored = store.save_case(case)
    retry_stored = store.save_case(case)
    query, params, _ = graph.calls[0]
    assert stored["linkedEvidence"] == 2
    assert retry_stored["caseId"] == stored["caseId"]
    assert len(graph.calls) == 2  # stable MERGE keys make retries idempotent
    assert "MERGE (c:InvestigationCase" in query and "MERGE (m:InvestigationMemory" in query
    assert "GENERATED_MEMORY" in query and "REFERENCES" in query
    assert params["schema_version"] == "1.0"
    assert json.loads(params["evidence_refs_json"])["transaction_ids"] == ["900", "901"]
    assert json.loads(params["verified_claims_json"])[0]["claim_type"] == "seed_existence"
    assert "chain_of_thought" not in params["findings_json"].lower()


def test_cloud_recall_query_joins_case_and_memory_and_uses_graph_overlap():
    class ReadGraph:
        def __init__(self):
            self.call = None

        def ro_query(self, query, params, timeout):
            self.call = (query, params, timeout)
            row = ["case_1", "memory_1", "900", "prior", "[]", "{}", "{}", "[]", "[]", "{}", "1.0", "2026-10-16", ["901"]]
            return SimpleNamespace(result_set=[row])

        def query(self, *_args, **_kwargs):
            raise AssertionError("memory recall must remain read-only")

    store = GraphStore(Settings(_env_file=None, app_mode="cloud", falkordb_host="example", falkordb_password="fixture"))
    graph = ReadGraph()
    store._graph = graph
    memories = store.find_related_memories(["901"], limit=5, owner_id="cognito-user-a")

    query, params, _ = graph.call
    assert "(c:InvestigationCase)-[:GENERATED_MEMORY]->(m:InvestigationMemory)" in query
    assert "m:InvestigationMemory)-[:REFERENCES]->(t:Transaction)" in query
    assert params["context_tx_ids"] == ["901"]
    assert params["owner_id"] == "cognito-user-a"
    assert "c.ownerId = $owner_id" in query and "m.ownerId = $owner_id" in query
    assert memories[0]["caseId"] == "case_1"
    assert memories[0]["sharedTransactions"] == ["901"]
    assert "901" in memories[0]["relevanceReason"]


def test_cloud_case_reload_returns_related_memories_and_saved_evidence_fields():
    class ReadGraph:
        def ro_query(self, query, params, timeout):
            assert params == {"case_id": "case_1", "owner_id": "cognito-user-a"}
            assert "c.ownerId = $owner_id" in query
            assert "OPTIONAL MATCH (c)-[:GENERATED_MEMORY]->(m:InvestigationMemory) WHERE m.ownerId = $owner_id" in query
            values = ["case_1", "900", "needs_human_review", "summary", "2026-10-16", json.dumps({
                "skeptic": {"reviewStatus": "needs_human_review"}, "relatedMemories": [{"caseId": "case_0"}],
                "evidenceLedger": {"transactions": {"900": {"label": "unknown"}}},
                "structuredReport": {"memory_review": {"validated_count": 1}},
                "claimValidation": {"claims_verified": 1}, "modelMetadata": {"analysis_status": "not_run"},
            }), "memory_1", "[]", json.dumps({"transactions": {"900": {"label": "unknown"}}}),
                "{}", "[]", "[]", "1.0", "{}"]
            return SimpleNamespace(result_set=[values])

    store = GraphStore(Settings(_env_file=None, app_mode="cloud", falkordb_host="example", falkordb_password="fixture"))
    store._graph = ReadGraph()
    saved = store.get_case("case_1", owner_id="cognito-user-a")
    assert saved["relatedMemories"] == [{"caseId": "case_0"}]
    assert saved["evidenceLedger"]["transactions"]["900"]["label"] == "unknown"
    assert saved["structuredReport"]["memory_review"]["validated_count"] == 1
    assert saved["claimValidation"]["claims_verified"] == 1
    assert saved["memorySchemaVersion"] == "1.0"
    assert saved["sharedContext"] == {}  # legacy findingsJson omitted sharedContext


def test_authenticated_cloud_memory_reads_and_saves_fail_closed_without_owner():
    settings = Settings(_env_file=None, app_mode="cloud", auth_mode="cognito",
                        falkordb_host="example", falkordb_password="fixture")
    store = GraphStore(settings)
    with pytest.raises(RuntimeError, match="verified owner"):
        store.find_related_memories(["900"])
    with pytest.raises(RuntimeError, match="verified owner"):
        store.list_cases()
    with pytest.raises(RuntimeError, match="verified owner"):
        store.get_case("case_1")
    with pytest.raises(RuntimeError, match="verified owner"):
        store.save_case({"seed": {"txId": "900"}})


def test_authenticated_save_assigns_owner_to_case_and_memory_nodes():
    class WriteGraph:
        def __init__(self): self.call = None
        def query(self, query, params, timeout):
            self.call = (query, params)
            return SimpleNamespace(result_set=[["case_owner", "memory_owner", 2]])

    settings = Settings(_env_file=None, app_mode="cloud", auth_mode="cognito",
                        falkordb_host="example", falkordb_password="fixture")
    store = GraphStore(settings)
    graph = WriteGraph()
    store._graph = graph
    case = {
        "case_id": "case_owner", "memory_id": "memory_owner", "seed": {"txId": "900", "label": "unknown"},
        "traces": [], "skeptic": {"findings": []}, "related_memories": [], "summary": "fixture",
        "status": "needs_human_review", "created_at": "2026-10-16T00:00:00+00:00",
        "evidence_tx_ids": ["900"], "evidence_ledger": {},
    }
    store.save_case(case, owner_id="cognito-user-a")
    query, params = graph.call
    assert "MERGE (c:InvestigationCase {caseId: $case_id, ownerId: $owner_id})" in query
    assert "MERGE (m:InvestigationMemory {memoryId: $memory_id, ownerId: $owner_id})" in query
    assert params["owner_id"] == "cognito-user-a"


def test_bureau_report_renders_historian_reason_and_skeptic_memory_status():
    frontend = Path(__file__).resolve().parents[1] / "frontend" / "index.html"
    source = frontend.read_text()
    assert "Related case memory · ${fmtNumber(memories.length)} candidate" in source
    assert "Why recalled:" in source
    assert "Skeptic:" in source
    assert "Current confirmation:" in source
    assert "Candidate excluded from Reporter findings." in source

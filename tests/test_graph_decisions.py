from copy import deepcopy

import pytest

import backend.app.services.graph_store as graph_data
from backend.app.agents.graph_decisions import action_state, choose_next_action, rank_verified_frontiers, validate_action_call
from backend.app.agents.orchestrator import InvestigationOrchestrator
from backend.app.agents.skeptic import SkepticAgent
from backend.app.config import Settings
from backend.app.services.graph_store import GraphStore


def test_new_verified_relationship_changes_selected_graph_action():
    seed = {"txId": "100", "label": "unknown", "timeStep": 8, "sourceDataset": "fixture"}
    middle = {"txId": "200", "label": "unknown", "timeStep": 8, "sourceDataset": "fixture"}
    endpoint = {"txId": "300", "label": "licit", "timeStep": 8, "sourceDataset": "fixture"}
    one_hop = {"direction": "downstream", "hops": 1, "nodes": [seed, middle],
               "edge_ids": ["100->200"]}

    one_hop_only = action_state(seed_checked=True, seed_exists=True,
                                neighbors={"downstream": 1}, traced_directions=["downstream", "upstream"],
                                paths=[one_hop], frontier_verified=True, max_hops=2, memory_enabled=False)
    before = choose_next_action(one_hop_only)
    assert before["selected_action"] == "expand_verified_frontier"

    discovered_path = {"direction": "downstream", "hops": 2,
                       "nodes": [seed, middle, endpoint],
                       "edge_ids": ["100->200", "200->300"]}
    after_new_relationship = deepcopy(one_hop_only)
    after_new_relationship["paths"].append(discovered_path)
    after_new_relationship["frontier_expanded"] = True
    after = choose_next_action(after_new_relationship)

    assert after["selected_action"] == "cross_check_path"
    assert after["eligible_actions"] != before["eligible_actions"]
    assert discovered_path["edge_ids"] == ["100->200", "200->300"]
    assert [node["txId"] for node in discovered_path["nodes"]] == ["100", "200", "300"]


def test_removing_critical_directed_edge_changes_same_policy_frontier():
    original_edges = graph_data._DEMO_EDGES
    critical_edge = ("730000002", "730000004")
    try:
        baseline = InvestigationOrchestrator(
            GraphStore(Settings(app_mode="demo"))
        ).preview("730000002", 3, use_local_model=False, memory_enabled=False)
        baseline_frontier = next(
            decision["action_outcome"]["selected_frontier_tx_id"]
            for decision in baseline["graph_decisions"]
            if decision["selected_action"] == "expand_verified_frontier"
        )

        graph_data._DEMO_EDGES = [
            edge for edge in original_edges if tuple(edge) != critical_edge
        ]
        ablated = InvestigationOrchestrator(
            GraphStore(Settings(app_mode="demo"))
        ).preview("730000002", 3, use_local_model=False, memory_enabled=False)
        ablated_expansions = [decision for decision in ablated["graph_decisions"]
                              if decision["selected_action"] == "expand_verified_frontier"]

        assert baseline_frontier == "730000004"
        assert ablated_expansions == []
    finally:
        graph_data._DEMO_EDGES = original_edges


def test_skeptic_verified_memory_changes_policy_to_follow_bounded_route():
    state = action_state(seed_checked=True, seed_exists=True,
                         neighbors={"downstream": 1}, traced_directions=["downstream", "upstream"],
                         paths=[{"direction": "downstream", "hops": 1,
                                 "nodes": [{"txId": "100"}, {"txId": "200"}]}],
                         frontier_verified=True, max_hops=3, memory_checked=True)
    state["memory_frontier_suggestions"] = [{
        "frontier_tx_id": "200", "case_id": "case-a", "memory_id": "memory-a",
        "memory_path_id": "path:downstream:200>201>202",
        "route": {"evidence_id": "path:downstream:100>200>201>202"},
    }]
    choice = choose_next_action(state)
    assert choice["selected_action"] == "follow_verified_memory_route"
    assert choice["memory_suggestion"]["frontier_tx_id"] == "200"
    state["memory_route_processed"] = True  # fresh route check rejected a changed source edge
    resumed = choose_next_action(state)
    assert resumed["selected_action"] == "expand_verified_frontier"


def test_observed_frontier_topology_changes_selected_transaction():
    seed = {"txId": "100"}
    left = {"txId": "200"}
    right = {"txId": "300"}
    candidates = [
        {"direction": "downstream", "nodes": [seed, left]},
        {"direction": "downstream", "nodes": [seed, right]},
    ]
    baseline = rank_verified_frontiers(candidates, {"200": 1, "300": 0})
    alternative = rank_verified_frontiers(candidates, {"200": 0, "300": 2})
    assert baseline[0]["endpoint"] == "200"
    assert alternative[0]["endpoint"] == "300"


@pytest.mark.parametrize("action,arguments", [
    ("trace_downstream", {"tx_id": "1; MATCH (n)", "max_hops": 2}),
    ("trace_upstream", {"tx_id": "100", "max_hops": 5}),
    ("finalize_report", {"cypher": "MATCH (n) RETURN n"}),
])
def test_graph_action_argument_schema_rejects_invalid_calls(action, arguments):
    with pytest.raises(ValueError):
        validate_action_call(action, arguments)


def test_demo_decision_log_cites_verified_path_and_action_outcomes():
    store = GraphStore(Settings(app_mode="demo"))
    result = InvestigationOrchestrator(store).preview("730000002", 3, use_local_model=False)
    decisions = result["graph_decisions"]

    expanded = next(item for item in decisions if item["selected_action"] == "expand_verified_frontier")
    cross_check = next(item for item in decisions if item["selected_action"] == "cross_check_path")
    assert expanded["action_outcome"]["expanded_paths"] >= 1
    assert expanded["next_step_after_outcome"] == "cross_check_path"
    assert expanded["outcome_changed_next_step"] is True
    assert expanded["action_outcome"]["selected_frontier_tx_id"] == "730000004"
    assert expanded["graph_evidence_ids"] == expanded["evidence_available_before"]["evidence_ids"]
    assert expanded["action_result_evidence_ids"]
    assert expanded["graph_action_budget"]["used"] <= expanded["graph_action_budget"]["limit"]
    assert any("path:downstream:730000002>730000004>730000003" == evidence_id
               for evidence_id in cross_check["graph_evidence_ids"])
    assert result["shared_context"]["current_graph_decision"]["selected_action"] == "finalize_report"
    assert result["persisted"] is False


def test_graph_unavailable_raises_instead_of_returning_an_illustrative_report():
    class UnavailableGraphStore(GraphStore):
        def __init__(self):
            super().__init__(Settings(app_mode="cloud"))

        def get_transaction(self, _tx_id):
            raise RuntimeError("FalkorDB read unavailable")

    with pytest.raises(RuntimeError, match="FalkorDB read unavailable"):
        InvestigationOrchestrator(UnavailableGraphStore()).preview("100", 2, use_local_model=False)


def test_skeptic_rejects_changed_classification_in_returned_path():
    store = GraphStore(Settings(app_mode="demo"))
    path = store.trace_paths("730000002", 1, direction="downstream")[0]
    path["nodes"][1]["label"] = "illicit" if path["nodes"][1]["label"] != "illicit" else "licit"
    validation = store.validate_paths([path], 1, "730000002")
    assert validation["validPathCount"] == 0
    assert validation["paths"][0]["reason"] == "transaction_properties_mismatch"


def _two_hop_fixture_path(store):
    path = next(path for path in store.trace_paths("730000002", 2, direction="downstream")
                if path["hops"] == 2)
    ids = [node["txId"] for node in path["nodes"]]
    path["evidence_id"] = "path:downstream:" + ">".join(ids)
    return path


def test_skeptic_uses_fresh_node_and_directed_edge_lookups_not_tracer_validator():
    class SpyStore(GraphStore):
        def __init__(self):
            super().__init__(Settings(app_mode="demo"))
            self.node_reads = 0
            self.edge_reads = 0
            self.validation_calls = 0

        def validate_paths(self, paths, max_hops, seed_tx_id=None):
            self.validation_calls += 1
            return super().validate_paths(paths, max_hops, seed_tx_id)

        def get_transaction(self, tx_id):
            self.node_reads += 1
            return super().get_transaction(tx_id)

        def has_flow_edge(self, source_tx_id, target_tx_id):
            self.edge_reads += 1
            return super().has_flow_edge(source_tx_id, target_tx_id)

    store = SpyStore()
    path = _two_hop_fixture_path(store)
    validations_before = store.validation_calls
    direct = SkepticAgent().independently_verify_paths([path], store, "730000002", 2)
    assert direct["allPathsValid"] is True
    assert store.validation_calls == validations_before
    assert store.node_reads == 3 and store.edge_reads == 2

    result = InvestigationOrchestrator(store).preview("730000002", 2, use_local_model=False)
    assert result["skeptic"]["checks"]["pathValidation"]["independentSource"] == "SkepticAgent.independently_verify_paths"
    assert store.node_reads >= 3
    assert store.edge_reads >= 2


@pytest.mark.parametrize("corruption", [
    "reversed_edge", "missing_intermediate", "absent_intermediate_node", "altered_property", "wrong_endpoint",
    "invalid_hop_count", "fabricated_evidence_reference",
])
def test_skeptic_rejects_corrupted_graph_paths_and_provenance(corruption):
    store = GraphStore(Settings(app_mode="demo"))
    path = _two_hop_fixture_path(store)
    ids = [node["txId"] for node in path["nodes"]]
    if corruption == "reversed_edge":
        path["edge_ids"][0] = f"{ids[1]}->{ids[0]}"
    elif corruption == "missing_intermediate":
        path["nodes"].pop(1)
        path["hops"] = 1
        new_ids = [node["txId"] for node in path["nodes"]]
        path["edge_ids"] = [f"{source}->{target}" for source, target in zip(new_ids, new_ids[1:])]
        path["evidence_id"] = "path:downstream:" + ">".join(new_ids)
    elif corruption == "altered_property":
        path["nodes"][1]["label"] = "illicit"
    elif corruption == "wrong_endpoint":
        path["nodes"][0]["txId"] = "730000001"
        new_ids = [node["txId"] for node in path["nodes"]]
        path["edge_ids"] = [f"{source}->{target}" for source, target in zip(new_ids, new_ids[1:])]
        path["evidence_id"] = "path:downstream:" + ">".join(new_ids)
    elif corruption == "invalid_hop_count":
        path["hops"] = 4
    else:
        path["evidence_id"] = "path:downstream:made-up-evidence"

    skeptic_store = store
    if corruption == "absent_intermediate_node":
        hidden_id = ids[1]
        class HiddenNodeStore:
            settings = store.settings
            get_transaction = lambda self, tx_id: None if tx_id == hidden_id else store.get_transaction(tx_id)
            has_flow_edge = lambda self, source, target: store.has_flow_edge(source, target)
        skeptic_store = HiddenNodeStore()
    check = SkepticAgent().independently_verify_paths([path], skeptic_store, "730000002", 3)["paths"][0]
    assert check["valid"] is False

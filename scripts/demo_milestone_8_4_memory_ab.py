"""Reproduce a controlled memory-disabled/enabled decision comparison.

This script is hard-pinned to the isolated in-process demo fixture. It never
connects to FalkorDB and never writes production graph data.
"""
from __future__ import annotations

import json
from time import perf_counter
from typing import Any

import backend.app.services.graph_store as graph_data
from backend.app.agents.orchestrator import InvestigationOrchestrator
from backend.app.config import Settings
from backend.app.services.graph_store import GraphStore


TRANSACTIONS = {
    tx_id: {"txId": tx_id, "label": "unknown", "timeStep": 8, "sourceDataset": "bureau_synthetic_v1"}
    for tx_id in ("731000001", "731000002", "731000003", "731000004", "731000005", "731000006", "731000007", "731000008")
}
EDGES = [("731000001", "731000002"), ("731000001", "731000005"), ("731000002", "731000003"), ("731000003", "731000004"),
         ("731000005", "731000006"), ("731000005", "731000007"), ("731000005", "731000008")]


class CountingDemoStore(GraphStore):
    def __init__(self):
        super().__init__(Settings(_env_file=None, app_mode="demo", max_trace_paths=20))
        self.reads: dict[str, int] = {}

    def _count(self, operation: str) -> None:
        self.reads[operation] = self.reads.get(operation, 0) + 1

    def get_transaction(self, tx_id):
        self._count("transaction_reads")
        return super().get_transaction(tx_id)

    def has_flow_edge(self, source_tx_id, target_tx_id):
        self._count("edge_reads")
        return super().has_flow_edge(source_tx_id, target_tx_id)

    def get_neighbors(self, tx_id):
        self._count("neighbor_reads")
        return super().get_neighbors(tx_id)

    def trace_paths(self, tx_id, max_hops, direction=None):
        self._count("path_reads")
        return super().trace_paths(tx_id, max_hops, direction)

    def find_related_memories(self, context_tx_ids, limit=5, owner_id=None):
        self._count("memory_lookup_reads")
        return super().find_related_memories(context_tx_ids, limit, owner_id)

    def reset_counts(self):
        self.reads = {}


def summarize_run(result: dict[str, Any], reads: dict[str, int], elapsed_ms: float) -> dict[str, Any]:
    valid_paths = [path for path, check in zip(result["traces"], result["skeptic"]["checks"]["pathValidation"]["paths"])
                   if check.get("valid")]
    decisions = result["graph_decisions"]
    memory_decisions = [item for item in decisions if item["selected_action"] == "follow_verified_memory_route"]
    return {
        "selected_actions": [item["selected_action"] for item in decisions],
        "selected_frontiers": [item.get("action_outcome", {}).get("selected_frontier_tx_id") for item in decisions
                                if item.get("action_outcome", {}).get("selected_frontier_tx_id")],
        "verified_paths": [{"evidence_id": path["evidence_id"], "transaction_ids": [node["txId"] for node in path["nodes"]],
                            "edge_ids": path["edge_ids"]} for path in valid_paths],
        "memory_route_decisions": [item["action_outcome"] for item in memory_decisions],
        "memory_linked_case_ids": [item["caseId"] for item in result["related_memories"]
                                    if item.get("validationStatus") == "VERIFIED_RELEVANT"],
        "graph_action_budget": result["graph_action_budget"],
        "source_read_counts": dict(reads),
        "elapsed_ms": round(elapsed_ms, 3),
    }


def run_demo() -> dict[str, Any]:
    old_transactions, old_edges = graph_data._DEMO_TRANSACTIONS, graph_data._DEMO_EDGES
    graph_data._DEMO_TRANSACTIONS, graph_data._DEMO_EDGES = TRANSACTIONS, EDGES
    try:
        store = CountingDemoStore()
        case_a = InvestigationOrchestrator(store).investigate("731000002", 2)
        if not case_a or not case_a.get("persisted"):
            raise RuntimeError("Fixture Case A failed to save its verified memory")

        store.reset_counts()
        started = perf_counter()
        baseline = InvestigationOrchestrator(store).preview("731000001", 3, use_local_model=False, memory_enabled=False)
        baseline_ms = (perf_counter() - started) * 1000
        baseline_run = summarize_run(baseline, dict(store.reads), baseline_ms)

        store.reset_counts()
        started = perf_counter()
        memory_enabled = InvestigationOrchestrator(store).preview("731000001", 3, use_local_model=False, memory_enabled=True)
        memory_ms = (perf_counter() - started) * 1000
        memory_run = summarize_run(memory_enabled, dict(store.reads), memory_ms)

        chosen_route = next((item for item in memory_run["memory_route_decisions"]
                             if item.get("memory_route_verified")), None)
        selected_case = (chosen_route or {}).get("memory_provenance", {}).get("case_id")
        trace = {
            "source": "isolated_in_process_fixture",
            "production_graph_touched": False,
            "case_a": {"case_id": case_a["case_id"], "memory_id": case_a["memory_id"],
                       "verified_edge_ids": [edge["edge_id"] for edge in case_a["evidence_ledger"]["edges"]]},
            "case_b_seed": "731000001",
            "same_graph_policy_budget_and_seed": True,
            "policy_budget_limit": baseline_run["graph_action_budget"]["limit"],
            "memory_disabled": baseline_run,
            "memory_enabled": memory_run,
            "causal_trace": {
                "prior_case_id": case_a["case_id"],
                "stored_memory_id": case_a["memory_id"],
                "shared_current_graph_edge": "731000001->731000002",
                "historian_recall": case_a["case_id"] in memory_run["memory_linked_case_ids"],
                "skeptic_validated_memory": case_a["case_id"] in memory_run["memory_linked_case_ids"],
                "changed_action": "follow_verified_memory_route" in memory_run["selected_actions"],
                "changed_frontier": "731000002" in memory_run["selected_frontiers"],
                "route_independently_verified": bool(chosen_route),
                "reporter_path_evidence_id": (chosen_route or {}).get("route_evidence_id"),
                "memory_case_provenance": selected_case,
            },
            "interpretation": {
                "verified_path_count_delta": len(memory_run["verified_paths"]) - len(baseline_run["verified_paths"]),
                "total_source_read_delta": sum(memory_run["source_read_counts"].values()) - sum(baseline_run["source_read_counts"].values()),
                "neighbor_read_delta": memory_run["source_read_counts"].get("neighbor_reads", 0) - baseline_run["source_read_counts"].get("neighbor_reads", 0),
                "note": "Read counts are method-level source reads in this deterministic fixture; timings are local wall-clock measurements, not a production latency claim.",
            },
        }
        if not all(trace["causal_trace"][key] for key in (
            "historian_recall", "skeptic_validated_memory", "changed_action", "changed_frontier", "route_independently_verified")):
            raise RuntimeError("Controlled memory A/B did not demonstrate the required causal path")
        return trace
    finally:
        graph_data._DEMO_TRANSACTIONS, graph_data._DEMO_EDGES = old_transactions, old_edges


if __name__ == "__main__":
    print(json.dumps(run_demo(), indent=2, sort_keys=True))

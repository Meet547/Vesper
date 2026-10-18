"""Reproduce Milestone 8.3 decisions and Skeptic negative controls offline."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from backend.app.agents.graph_decisions import rank_verified_frontiers
from backend.app.agents.orchestrator import InvestigationOrchestrator
from backend.app.agents.skeptic import SkepticAgent
from backend.app.config import Settings
from backend.app.services.graph_store import GraphStore


def main() -> dict:
    store = GraphStore(Settings(app_mode="demo", _env_file=None))
    result = InvestigationOrchestrator(store).preview("730000002", 3, use_local_model=False)
    paths = store.trace_paths("730000002", 1, direction="downstream")
    candidates = [path for path in paths if path["hops"] == 1]
    baseline_counts = {}
    for path in candidates:
        endpoint = path["nodes"][-1]["txId"]
        baseline_counts[endpoint] = len([node for node in store.get_neighbors(endpoint)["outgoing"]
                                         if node["txId"] not in {item["txId"] for item in path["nodes"]}])
    baseline_rank = rank_verified_frontiers(candidates, baseline_counts)
    selected = next((item for item in baseline_rank if item["observed_next_edge_count"] > 0), None)
    # Isolated counterfactual counts exercise the same ranking rules and seed;
    # they do not mutate either the fixture graph or production data.
    counterfactual_counts = dict(baseline_counts)
    if selected:
        counterfactual_counts[selected["endpoint"]] = 0
    counterfactual_rank = rank_verified_frontiers(candidates, counterfactual_counts)
    counterfactual_selected = next((item for item in counterfactual_rank
                                    if item["observed_next_edge_count"] > 0), None)

    two_hop = next(path for path in store.trace_paths("730000002", 2, direction="downstream")
                   if path["hops"] == 2)
    two_hop["evidence_id"] = "path:downstream:" + ">".join(node["txId"] for node in two_hop["nodes"])
    skeptic = SkepticAgent()
    negative = {}
    mutations = {
        "reversed_edge": lambda item: item["edge_ids"].__setitem__(0, "730000004->730000002"),
        "missing_intermediate": lambda item: (item["nodes"].pop(1), item.__setitem__("hops", 1),
                                                item.__setitem__("edge_ids", ["730000002->" + item["nodes"][1]["txId"]]),
                                                item.__setitem__("evidence_id", "path:downstream:" + ">".join(n["txId"] for n in item["nodes"]))),
        "absent_intermediate_node": lambda item: None,
        "altered_property": lambda item: item["nodes"][1].__setitem__("label", "illicit"),
        "incorrect_endpoint": lambda item: item["nodes"][0].__setitem__("txId", "730000001"),
        "invalid_hop_count": lambda item: item.__setitem__("hops", 4),
        "fabricated_evidence_reference": lambda item: item.__setitem__("evidence_id", "path:downstream:invented"),
    }
    for name, mutate in mutations.items():
        corrupted = deepcopy(two_hop)
        mutate(corrupted)
        skeptic_store = store
        if name == "absent_intermediate_node":
            hidden_id = two_hop["nodes"][1]["txId"]
            class HiddenNodeStore:
                settings = store.settings
                get_transaction = lambda self, tx_id: None if tx_id == hidden_id else store.get_transaction(tx_id)
                has_flow_edge = lambda self, source, target: store.has_flow_edge(source, target)
            skeptic_store = HiddenNodeStore()
        check = skeptic.independently_verify_paths([corrupted], skeptic_store, "730000002", 3)["paths"][0]
        negative[name] = {"rejected": not check["valid"], "reason": check["reason"]}

    trace = {
        "source": "isolated_demo_fixture",
        "mode": result["mode"],
        "persisted": result["persisted"],
        "policy": "deterministic allowlisted action policy; optional Analyst model disabled",
        "action_budget": result["graph_action_budget"],
        "decisions": result["graph_decisions"],
        "verified_paths": [
            {"evidence_id": item["evidence_id"], "direction": item["direction"],
             "hops": item["hops"], "transaction_ids": [n["txId"] for n in item["nodes"]],
             "edge_ids": item["edge_ids"]}
            for item, check in zip(result["traces"], result["skeptic"]["checks"]["pathValidation"]["paths"])
            if check["valid"]
        ],
        "frontier_comparison": {
            "same_seed_and_rules": True,
            "baseline_observed_next_edge_counts": baseline_counts,
            "baseline_selected": selected["endpoint"] if selected else None,
            "counterfactual_observed_next_edge_counts": counterfactual_counts,
            "counterfactual_selected": counterfactual_selected["endpoint"] if counterfactual_selected else None,
            "note": "Counterfactual is isolated rank-input evidence; graph fixture and production data were not mutated.",
        },
        "skeptic_negative_controls": negative,
    }
    return trace


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, sort_keys=True))

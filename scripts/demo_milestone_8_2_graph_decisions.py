"""Reproduce graph-dependent next-action selection with an isolated fixture."""
import json

import backend.app.services.graph_store as graph_data
from backend.app.agents.graph_decisions import action_state, choose_next_action
from backend.app.agents.orchestrator import InvestigationOrchestrator
from backend.app.config import Settings
from backend.app.services.graph_store import GraphStore


def main() -> None:
    store = GraphStore(Settings(app_mode="demo"))
    seed_id = "730000002"
    one_hop = store.trace_paths(seed_id, 1, direction="downstream")
    one_hop_state = action_state(
        seed_checked=True, seed_exists=True, neighbors={"downstream": 1},
        traced_directions=["downstream", "upstream"], paths=one_hop,
        frontier_verified=bool(store.validate_paths(one_hop, 1, seed_id)["validPathCount"]),
        max_hops=2,
    )
    before = choose_next_action(one_hop_state)

    base = next((path for path in one_hop if path["nodes"][-1]["txId"] == "730000004"), None)
    if base is None:
        raise RuntimeError("The isolated fixture lost the first controlled edge.")
    extended = store.trace_paths("730000004", 1, direction="downstream")
    candidate = next((path for path in extended if path["nodes"][0]["txId"] == "730000004"), None)
    if candidate is None:
        raise RuntimeError("The isolated fixture no longer contains the controlled second edge.")
    multi_hop = {"direction": "downstream", "hops": 2,
                 "nodes": base["nodes"] + candidate["nodes"][1:]}
    after_state = dict(one_hop_state)
    after_state["paths"] = [*one_hop, multi_hop]
    after_state["frontier_expanded"] = True
    after = choose_next_action(after_state)

    preview = InvestigationOrchestrator(store).preview(seed_id, 2, use_local_model=False)
    verified_paths = [path for path in preview["evidence_ledger"]["paths"]
                      if path.get("valid") is True and path.get("hop_count", 0) >= 2]
    if not verified_paths:
        raise RuntimeError("No verified multi-hop path was returned by the isolated fixture preview.")

    original_edges = graph_data._DEMO_EDGES
    critical_edge = ("730000002", "730000004")
    baseline_frontier = next(
        item["action_outcome"]["selected_frontier_tx_id"]
        for item in preview["graph_decisions"]
        if item["selected_action"] == "expand_verified_frontier"
    )
    try:
        graph_data._DEMO_EDGES = [edge for edge in original_edges if tuple(edge) != critical_edge]
        ablated = InvestigationOrchestrator(store).preview(
            seed_id, 3, use_local_model=False, memory_enabled=False
        )
        ablated_expansions = [item for item in ablated["graph_decisions"]
                              if item["selected_action"] == "expand_verified_frontier"]
    finally:
        graph_data._DEMO_EDGES = original_edges
    ablated_frontier = (ablated_expansions[0]["action_outcome"]["selected_frontier_tx_id"]
                        if ablated_expansions else None)
    if baseline_frontier != "730000004" or ablated_frontier is not None:
        raise RuntimeError("Critical-edge ablation did not change the selected frontier as expected.")

    print(json.dumps({
        "source": "isolated_demo_fixture",
        "graph_indispensability": {
            "same_seed_and_policy": True,
            "removed_directed_edge": "730000002->730000004",
            "frontier_with_edge": baseline_frontier,
            "frontier_after_edge_removal": ablated_frontier,
            "selected_frontier_changed": baseline_frontier != ablated_frontier,
            "source": "in_memory_demo_fixture; not a live FalkorDB run",
        },
        "one_hop_information": {"selected_action": before["selected_action"],
                                 "eligible_actions": before["eligible_actions"]},
        "after_second_relationship": {"selected_action": after["selected_action"],
                                      "eligible_actions": after["eligible_actions"]},
        "verified_paths": [{"evidence_id": path["evidence_id"], "direction": path["direction"],
                            "hops": path["hop_count"], "transaction_ids": path["node_ids"],
                            "edge_ids": path["edge_ids"]}
                           for path in verified_paths],
        "graph_decisions": [{"selected_action": item["selected_action"],
                             "reason": item["selection_reason"],
                             "graph_evidence_ids": item["graph_evidence_ids"],
                             "outcome_changed_next_step": item["outcome_changed_next_step"]}
                            for item in preview["graph_decisions"]],
        "persisted": preview["persisted"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

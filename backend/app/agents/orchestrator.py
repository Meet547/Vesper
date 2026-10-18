from __future__ import annotations

from datetime import datetime, timezone
from copy import deepcopy
from time import perf_counter
from typing import Any
from uuid import uuid4

from backend.app.agents.evidence_ledger import build_evidence_ledger, compact_ledger_for_model
from backend.app.agents.graph_decisions import (ACTION_CATALOG, action_state, choose_next_action,
    memory_frontier_suggestions, rank_verified_frontiers, validate_action_call)
from backend.app.agents.historian import HistorianAgent
from backend.app.agents.local_model import LocalModelAgent
from backend.app.agents.reporter import ReporterAgent
from backend.app.agents.shared_context import SharedInvestigationContext
from backend.app.agents.scout import ScoutAgent
from backend.app.agents.skeptic import SkepticAgent
from backend.app.agents.tracer import TracerAgent
from backend.app.config import Settings
from backend.app.tools.investigation_tools import InvestigationTools
from backend.app.services.graph_store import GraphStore

GRAPH_ACTION_BUDGET = 16
ACTION_OWNERS = {
    "inspect_seed": "Scout", "trace_downstream": "Tracer", "trace_upstream": "Tracer",
    "expand_verified_frontier": "Tracer", "cross_check_path": "Skeptic",
    "follow_verified_memory_route": "Tracer",
    "recall_related_case": "Historian", "request_additional_evidence": "Vesper",
    "finalize_report": "Reporter",
}


class InvestigationOrchestrator:
    """Evidence-first agent workflow with a read-only preview and explicit persistence."""

    def __init__(self, store: GraphStore, settings: Settings | None = None):
        tools = InvestigationTools(store)
        self.store = store
        self.settings = settings
        self.tools = tools
        self.scout = ScoutAgent(tools)
        self.tracer = TracerAgent(tools)
        self.skeptic = SkepticAgent()
        self.historian = HistorianAgent(store)
        self.reporter = ReporterAgent()

    def preview(self, seed_tx_id: str, max_hops: int, use_local_model: bool = True,
                progress_callback=None, investigation_id: str | None = None,
                owner_id: str | None = None, memory_enabled: bool = True,
                include_policy_explanation: bool = False) -> dict[str, Any] | None:
        """Run a read-only investigation and optionally publish safe lifecycle events.

        Progress events describe completed workflow stages only; they never include
        model prompts, hidden reasoning, credentials, or unvalidated claims.
        """
        started = perf_counter()
        investigation_id = investigation_id or f"inv_{uuid4().hex[:12]}"
        shared = SharedInvestigationContext(f"case_{uuid4().hex[:12]}", seed_tx_id, max_hops, investigation_id)

        def emit(agent: str, stage: str, status: str, message: str, **extra: Any) -> None:
            shared.set_activity(agent, stage, status)
            if progress_callback:
                progress_callback({"agent": agent, "stage": stage, "status": status,
                                   "message": message, "investigation_id": investigation_id,
                                   "elapsed_ms": round((perf_counter() - started) * 1000),
                                   "shared_context": shared.public_snapshot(), **extra})

        def publish_context(event_name: str, agent: str, stage: str, message: str,
                            **extra: Any) -> None:
            if progress_callback:
                progress_callback({"agent": agent, "event_name": event_name, "stage": stage,
                                   "status": "completed", "message": message,
                                   "investigation_id": investigation_id,
                                   "shared_context": shared.public_snapshot(), **extra})

        def handoff(source: str, target: str, kind: str, summary: str,
                    evidence_ids: list[str] | None = None, **details: Any) -> None:
            item = shared.add_handoff(source, target, kind, summary, evidence_ids, **details)
            publish_context("agent_handoff", source, "context_handoff", summary, handoff=item)

        graph_started = perf_counter()
        events: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        action_budget = {"limit": GRAPH_ACTION_BUDGET, "used": 0,
                         "remaining": GRAPH_ACTION_BUDGET, "exhausted": False,
                         "scope": "selected allowlisted graph workflow actions; low-level read queries are separately bounded by GraphStore"}
        state = action_state(max_hops=max(1, min(int(max_hops), 4)), memory_enabled=memory_enabled)

        def evidence_ids(paths: list[dict[str, Any]]) -> list[str]:
            ids: set[str] = set()
            for path in paths:
                nodes = path.get("nodes") if isinstance(path, dict) else []
                ids.update(f"tx:{node.get('txId')}" for node in nodes if isinstance(node, dict) and node.get("txId"))
                ids.update(f"edge:{edge_id}" for edge_id in path.get("edge_ids", []))
                tx_ids = [str(node.get("txId")) for node in nodes if isinstance(node, dict)]
                if len(tx_ids) > 1:
                    ids.add("path:" + str(path.get("direction")) + ":" + ">".join(tx_ids))
            return sorted(ids)

        def record_decision(choice: dict[str, Any], before: dict[str, Any], outcome: dict[str, Any],
                            graph_ids: list[str], no_outcome_next: str) -> None:
            if choice["selected_action"] not in ACTION_CATALOG or not set(choice["eligible_actions"]).issubset(ACTION_CATALOG):
                raise ValueError("graph policy selected an action outside the constrained catalog")
            if action_budget["remaining"] <= 0:
                action_budget["exhausted"] = True
                outcome = {**outcome, "budget_exhausted": True}
                raise RuntimeError("The bounded graph action budget was exhausted before report completion")
            action_budget["used"] += 1
            action_budget["remaining"] = action_budget["limit"] - action_budget["used"]
            action = choice["selected_action"]
            no_outcome_state = deepcopy(before.get("_policy_state") or state)
            if action.startswith("trace_"):
                direction = action.removeprefix("trace_")
                no_outcome_state["traced_directions"] = list(no_outcome_state.get("traced_directions", [])) + [direction]
            elif action == "expand_verified_frontier":
                no_outcome_state["frontier_expanded"] = True
            elif action == "follow_verified_memory_route":
                no_outcome_state["memory_route_processed"] = True
            elif action == "cross_check_path":
                no_outcome_state["path_checked"] = True
                no_outcome_state["all_paths_valid"] = False
            elif action == "recall_related_case":
                no_outcome_state["memory_checked"] = True
            elif action == "request_additional_evidence":
                no_outcome_state["additional_evidence_requested"] = True
            elif action == "inspect_seed":
                no_outcome_state["seed_checked"] = True
                no_outcome_state["seed_exists"] = False
            computed_no_outcome_next = choose_next_action(no_outcome_state)["selected_action"]
            next_choice = choose_next_action(state)["selected_action"]
            before_public = {key: value for key, value in before.items() if not key.startswith("_")}
            max_hops_bound = int(state["max_hops"])
            action_arguments = {
                "inspect_seed": {"tx_id": str(seed_tx_id)},
                "trace_downstream": {"tx_id": str(seed_tx_id), "max_hops": 1},
                "trace_upstream": {"tx_id": str(seed_tx_id), "max_hops": 1},
                "expand_verified_frontier": {"seed_tx_id": str(seed_tx_id), "max_hops": max_hops_bound, "frontier_limit": 20},
                "follow_verified_memory_route": {
                    "seed_tx_id": str(seed_tx_id),
                    "frontier_tx_id": str((choice.get("memory_suggestion") or {}).get("frontier_tx_id", "0")),
                    "memory_id": str((choice.get("memory_suggestion") or {}).get("memory_id", "missing")),
                    "memory_path_id": str((choice.get("memory_suggestion") or {}).get("memory_path_id", "missing")),
                },
                "cross_check_path": {"seed_tx_id": str(seed_tx_id), "max_hops": max_hops_bound, "path_limit": 20},
                "recall_related_case": {"context_tx_ids": list(state.get("memory_context_tx_ids") or [str(seed_tx_id)])[:100], "limit": 5},
                "request_additional_evidence": {"reason": choice["selection_reason"][:240]},
                "finalize_report": {},
            }[action]
            action_call = validate_action_call(action, action_arguments)
            record = {
                "evidence_available_before": deepcopy(before_public),
                "eligible_actions": list(choice["eligible_actions"]),
                "selected_action": choice["selected_action"],
                "agent_responsible": ACTION_OWNERS[choice["selected_action"]],
                "action_call": action_call,
                "selection_reason": choice["selection_reason"],
                # Decision evidence is frozen from the pre-action snapshot. Results
                # become eligible only for subsequent decisions.
                "graph_evidence_ids": sorted(set(before.get("evidence_ids", []))),
                "memory_evidence_ids_before": sorted(set((before.get("_policy_state") or {}).get("memory_evidence_ids", []))),
                "action_result_evidence_ids": sorted(set(graph_ids)),
                "action_outcome": deepcopy(outcome),
                "next_step_without_outcome": computed_no_outcome_next,
                "next_step_after_outcome": next_choice,
                "outcome_changed_next_step": next_choice != no_outcome_next,
                "graph_action_budget": deepcopy(action_budget),
            }
            decisions.append(record)
            shared.record_graph_decision(record)
            if progress_callback:
                publish_context("graph_decision", "Vesper", "graph_decision",
                                f"Selected {choice['selected_action']}: {choice['selection_reason']}",
                                graph_decision=record)

        def state_before() -> dict[str, Any]:
            ids = set()
            if state.get("seed_checked") and state.get("seed_exists"):
                ids.add(f"tx:{seed_tx_id}")
            for group in (state.get("neighbor_evidence_ids") or {}).values():
                ids.update(group)
            ids.update(evidence_ids(state.get("paths", [])))
            return {"evidence_ids": sorted(ids), "_policy_state": deepcopy(state),
                    "seed_checked": state["seed_checked"], "seed_exists": state["seed_exists"],
                    "seed_properties": deepcopy(state.get("seed_properties")),
                    "available_neighbors": deepcopy(state["neighbors"]),
                    "neighbor_evidence_ids": deepcopy(state.get("neighbor_evidence_ids", {})),
                    "traced_directions": list(state["traced_directions"]),
                    "returned_paths": [{"direction": path.get("direction"), "hops": path.get("hops"),
                                        "transaction_ids": [node.get("txId") for node in path.get("nodes", [])],
                                        "transaction_properties": deepcopy(path.get("nodes", [])),
                                        "edge_ids": list(path.get("edge_ids", []))}
                                       for path in state["paths"]],
                    "frontier_expanded": state["frontier_expanded"],
                    "path_checked": state["path_checked"], "memory_checked": state["memory_checked"],
                    "memory_context_tx_ids": list(state.get("memory_context_tx_ids", []))}

        def merge_paths(current: list[dict[str, Any]], additions: list[dict[str, Any]]) -> list[dict[str, Any]]:
            unique = {}
            for path in current + additions:
                nodes = path.get("nodes") or []
                ids = tuple(str(node.get("txId", "")) for node in nodes if isinstance(node, dict))
                if len(ids) < 2:
                    continue
                direction = path.get("direction")
                path["hops"] = len(ids) - 1
                path["edge_ids"] = [f"{source}->{target}" for source, target in zip(ids, ids[1:])]
                path["evidence_id"] = "path:" + str(direction) + ":" + ">".join(ids)
                unique[(direction, ids)] = path
            return sorted(unique.values(), key=lambda item: (item["hops"], item["direction"],
                                                               tuple(node["txId"] for node in item["nodes"])))[:self.settings.max_trace_paths if self.settings else 20]

        # 1. Seed inspection and bounded first-hop neighbor sampling.
        choice = choose_next_action(state)
        before = state_before()
        emit("Scout", "validating", "started", "Checking the seed transaction in the selected graph.")
        seed = self.scout.find_seed(seed_tx_id, shared_context=shared)
        neighbor_records = self.tools.get_neighbors(seed_tx_id) if seed else {"incoming": [], "outgoing": []}
        state.update({"seed_checked": True, "seed_exists": seed is not None,
                      "neighbors": {"downstream": len(neighbor_records.get("outgoing", [])),
                                    "upstream": len(neighbor_records.get("incoming", []))},
                      "seed_properties": deepcopy(seed),
                      "neighbor_evidence_ids": {
                          "downstream": [f"tx:{item.get('txId')}" for item in neighbor_records.get("outgoing", []) if item.get("txId")],
                          "upstream": [f"tx:{item.get('txId')}" for item in neighbor_records.get("incoming", []) if item.get("txId")],
                      }})
        neighbor_ids = [f"tx:{item.get('txId')}" for values in neighbor_records.values() for item in values if item.get("txId")]
        record_decision(choice, before, {"seed_found": seed is not None,
                                         "available_downstream_neighbors": state["neighbors"]["downstream"],
                                         "available_upstream_neighbors": state["neighbors"]["upstream"]},
                        ([f"tx:{seed_tx_id}"] if seed else []) + neighbor_ids,
                        "request_additional_evidence")
        events.append({"agent": "Scout", "type": "graph_read", "tool": "get_transaction",
                       "status": "completed" if seed else "not_found", "read_only": True})
        if seed is None:
            choice = choose_next_action(state)
            before = state_before()
            state["additional_evidence_requested"] = True
            record_decision(choice, before, {"status": "inconclusive", "reason": "seed_not_found",
                                             "requested": "Confirm the transaction ID or choose a seed present in the selected graph."},
                            [], "finalize_report")
            shared.set_focus("Confirm the transaction ID or choose another graph seed.",
                             "seed transaction not found; no graph claims were produced", None)
            shared.finish("not_found")
            emit("Scout", "failed", "failed", "The transaction was not found in the selected graph.")
            return None
        emit("Scout", "graph_search", "completed", "Seed transaction found; graph properties recorded.")
        seed_evidence_id = f"tx:{seed_tx_id}"
        shared.add_update("Scout", "seed_validated", "Seed transaction exists in the selected graph; dataset properties recorded.", [seed_evidence_id])
        handoff("Scout", "Tracer", "seed_context", "Seed validated; select a directed neighbor frontier from observed graph connections.",
                [seed_evidence_id], seed_transaction=seed_tx_id, hop_depth=max_hops)

        # 2. Select each available direction from sampled seed connections, then
        # expand only frontiers whose one-hop path has independently verified.
        traces: list[dict[str, Any]] = []
        while choose_next_action(state)["selected_action"] in {"trace_downstream", "trace_upstream"}:
            choice = choose_next_action(state)
            before = state_before()
            direction = choice["selected_action"].removeprefix("trace_")
            emit("Tracer", "graph_search", "started", f"Inspecting the observed {direction} FLOWS_TO frontier.")
            one_hop = self.tracer.trace(seed_tx_id, 1, shared_context=shared, direction=direction)
            one_hop = [path for path in one_hop if int(path.get("hops", 0)) == 1]
            traces = merge_paths(traces, one_hop)
            state["traced_directions"].append(direction)
            first_checks = self.store.validate_paths(one_hop, 1, seed_tx_id) if one_hop else {"paths": []}
            valid_frontiers = [path for path, check in zip(one_hop, first_checks.get("paths", [])) if check.get("valid")]
            state["frontier_verified"] = state["frontier_verified"] or bool(valid_frontiers)
            state["paths"] = traces
            record_decision(choice, before, {"direction": direction, "returned_paths": len(one_hop),
                                             "verified_frontier_paths": len(valid_frontiers)},
                            evidence_ids(one_hop), "recall_related_case")
            events.append({"agent": "Tracer", "type": "graph_read", "tool": f"trace_{direction}",
                           "status": "completed" if one_hop else "empty", "path_count": len(one_hop), "read_only": True})
            emit("Tracer", "graph_search", "completed", f"Read {len(one_hop)} one-hop {direction} path(s).", path_count=len(one_hop))

        memory_candidates: list[dict[str, Any]] = []
        related_memories: list[dict[str, Any]] = []
        # Give graph-linked memory one bounded decision point before topology
        # ranking. Its evidence is checked against the pre-memory ledger to avoid
        # circularly validating a remembered route with itself.
        if choose_next_action(state)["selected_action"] == "recall_related_case":
            choice = choose_next_action(state)
            before = state_before()
            context_ids = [seed_tx_id]
            for trace in traces:
                context_ids.extend(str(node["txId"]) for node in trace.get("nodes", [])
                                   if isinstance(node, dict) and str(node.get("txId", "")).isdigit())
            context_ids = list(dict.fromkeys(context_ids))[:100]
            state["memory_context_tx_ids"] = list(context_ids)
            emit("Historian", "memory_lookup", "started", "Checking prior saved cases linked to the verified one-hop scope.")
            memory_candidates = self.historian.recall(context_ids, shared_context=shared, owner_id=owner_id)
            state["memory_checked"] = True
            current_scope = self.skeptic.independently_verify_paths(traces, self.store, seed_tx_id, 1)
            current_ledger = build_evidence_ledger(seed, traces, current_scope, 1, self.store.graph_name)
            related_memories = self.skeptic.validate_memories(memory_candidates, current_ledger, self.store,
                                                               shared_context=shared)
            verified_frontiers = [path for path, check in zip(traces, current_scope.get("paths", []))
                                  if check.get("valid") and path.get("hops") == 1]
            suggestions = memory_frontier_suggestions(related_memories, verified_frontiers, state["max_hops"])
            state["memory_frontier_suggestions"] = suggestions
            state["memory_evidence_ids"] = sorted({
                f"case:{item['case_id']}" for item in suggestions if item.get("case_id")
            } | {
                f"memory:{item['memory_id']}" for item in suggestions if item.get("memory_id")
            } | {
                str(evidence_id) for item in suggestions for evidence_id in item.get("supporting_evidence_ids", [])
            })
            fallback = "follow_verified_memory_route" if suggestions else "expand_verified_frontier"
            record_decision(choice, before,
                            {"candidate_count": len(memory_candidates),
                             "candidate_case_ids": [str(item.get("caseId")) for item in memory_candidates],
                             "validated_memory_count": sum(item.get("validationStatus") == "VERIFIED_RELEVANT" for item in related_memories),
                             "suggested_frontier_tx_id": suggestions[0]["frontier_tx_id"] if suggestions else None,
                             "suggested_case_id": suggestions[0]["case_id"] if suggestions else None},
                            [f"case:{item.get('caseId')}" for item in memory_candidates] +
                            [f"tx:{tx_id}" for tx_id in context_ids], fallback)
            events.append({"agent": "Historian", "type": "memory_search_completed",
                           "tool": "find_related_memories", "status": "completed",
                           "memory_count": len(memory_candidates), "read_only": True})
            emit("Historian", "memory_lookup", "completed",
                 f"Found {len(memory_candidates)} candidate(s); Skeptic validated {sum(item.get('validationStatus') == 'VERIFIED_RELEVANT' for item in related_memories)} against current graph evidence.",
                 memory_count=len(memory_candidates))

        if choose_next_action(state)["selected_action"] == "follow_verified_memory_route":
            choice = choose_next_action(state)
            before = state_before()
            suggestion = choice["memory_suggestion"]
            proposed = deepcopy(suggestion["route"])
            checked_route = self.skeptic.independently_verify_paths([proposed], self.store, seed_tx_id,
                                                                    state["max_hops"])
            valid = bool(checked_route.get("allPathsValid"))
            if valid:
                traces = merge_paths(traces, [proposed])
            state["paths"] = traces
            state["memory_route_processed"] = True
            state["frontier_expanded"] = False
            record_decision(choice, before,
                            {"memory_route_verified": valid,
                             "selected_frontier_tx_id": suggestion["frontier_tx_id"],
                             "route_evidence_id": proposed.get("evidence_id") if valid else None,
                             "memory_provenance": proposed.get("memory_provenance"),
                             "verified_path_count": checked_route.get("validPathCount", 0),
                             "rejected_path_count": checked_route.get("invalidPathCount", 0)},
                            evidence_ids([proposed]) if valid else [],
                            "cross_check_path" if valid else "expand_verified_frontier")
            events.append({"agent": "Skeptic", "type": "memory_route_revalidation",
                           "tool": "independently_verify_paths", "status": "verified" if valid else "rejected",
                           "case_id": suggestion.get("case_id"), "memory_id": suggestion.get("memory_id"),
                           "read_only": True})

        if choose_next_action(state)["selected_action"] == "expand_verified_frontier":
            choice = choose_next_action(state)
            before = state_before()
            one_hop_validation = self.store.validate_paths(traces, 1, seed_tx_id)
            valid_indices = {index for index, check in enumerate(one_hop_validation.get("paths", [])) if check.get("valid")}
            verified_frontiers = [path for index, path in enumerate(traces) if index in valid_indices and path.get("hops") == 1]
            additions: list[dict[str, Any]] = []
            observed_counts: dict[str, int] = {}
            for frontier in verified_frontiers[:20]:
                nodes = frontier.get("nodes") or []
                endpoint = str(nodes[-1].get("txId")) if frontier.get("direction") == "downstream" else str(nodes[0].get("txId"))
                neighbors = self.tools.get_neighbors(endpoint)
                relevant = neighbors.get("outgoing" if frontier.get("direction") == "downstream" else "incoming", [])
                observed_counts[endpoint] = len({str(item.get("txId")) for item in relevant
                                                 if str(item.get("txId", "")) not in {str(node.get("txId")) for node in nodes}})
            ranked_frontiers = rank_verified_frontiers(verified_frontiers, observed_counts)
            selected_frontier = next((item for item in ranked_frontiers
                                      if item["observed_next_edge_count"] > 0), None)
            if selected_frontier:
                frontier = selected_frontier["path"]
                nodes = frontier.get("nodes") or []
                endpoint = selected_frontier["endpoint"]
                extensions = self.tracer.trace(endpoint, max(1, state["max_hops"] - 1),
                                               shared_context=shared, direction=frontier["direction"])
                for extension in extensions:
                    extension_nodes = extension.get("nodes") or []
                    if not extension_nodes:
                        continue
                    combined = (nodes + extension_nodes[1:]) if frontier["direction"] == "downstream" else (extension_nodes[:-1] + nodes)
                    ids = [str(node.get("txId", "")) for node in combined]
                    if len(ids) < 3 or len(ids) - 1 > state["max_hops"] or len(set(ids)) != len(ids):
                        continue
                    additions.append({"direction": frontier["direction"], "hops": len(ids) - 1,
                                      "nodes": combined, "edge_ids": [f"{source}->{target}" for source, target in zip(ids, ids[1:])]})
                    if len(additions) >= 20:
                        break
            traces = merge_paths(traces, additions)
            state["paths"] = traces
            state["frontier_expanded"] = True
            record_decision(choice, before, {"verified_frontiers": len(verified_frontiers),
                                             "frontier_ranking": [{"endpoint": item["endpoint"],
                                                                   "observed_next_edge_count": item["observed_next_edge_count"]}
                                                                  for item in ranked_frontiers],
                                             "selected_frontier_tx_id": selected_frontier["endpoint"] if selected_frontier else None,
                                             "selection_criteria": "highest observed unexamined directed-neighbor count; deterministic tie by direction then path IDs",
                                             "expanded_paths": len(additions),
                                             "maximum_path_depth": max((path["hops"] for path in traces), default=0)},
                            sorted(set(evidence_ids(additions) + [f"tx:{item['endpoint']}" for item in ranked_frontiers])), "recall_related_case")
            events.append({"agent": "Tracer", "type": "graph_read", "tool": "expand_verified_frontier",
                           "status": "completed" if additions else "empty", "path_count": len(additions), "read_only": True})

        # 3. Continue with the action selected by current graph evidence. A shallow
        # frontier checks case overlap before path review; a newly found multi-hop
        # path goes straight to independent verification.
        context_ids = [seed_tx_id]
        for trace in traces:
            context_ids.extend(str(node["txId"]) for node in trace.get("nodes", [])
                               if isinstance(node, dict) and str(node.get("txId", "")).isdigit())
        context_ids = list(dict.fromkeys(context_ids))[:100]
        state["memory_context_tx_ids"] = list(context_ids)
        memory_started = perf_counter()
        path_validation = self.store.validate_paths([], state["max_hops"], seed_tx_id)
        while True:
            choice = choose_next_action(state)
            action = choice["selected_action"]
            if action == "cross_check_path":
                before = state_before()
                emit("Skeptic", "path_validation", "started", "Independently verifying each transaction, property, ordered edge, endpoint, and hop count.")
                path_validation = self.store.validate_paths(traces, state["max_hops"], seed_tx_id)
                state["path_checked"] = True
                state["all_paths_valid"] = bool(path_validation.get("allPathsValid"))
                record_decision(choice, before, {"checked_paths": path_validation["checkedPathCount"],
                                                 "valid_paths": path_validation["validPathCount"],
                                                 "invalid_paths": path_validation["invalidPathCount"]},
                                evidence_ids(traces), "recall_related_case")
                events.append({"agent": "PathValidation", "type": "independent_validation", "tool": "validate_paths",
                               "status": "completed", "valid_path_count": path_validation["validPathCount"],
                               "invalid_path_count": path_validation["invalidPathCount"], "read_only": True})
                emit("Skeptic", "path_validation", "completed", "Independent directed-path review completed.",
                     valid_path_count=path_validation["validPathCount"], invalid_path_count=path_validation["invalidPathCount"])
                continue
            if action == "recall_related_case" and not state["memory_checked"]:
                before = state_before()
                emit("Historian", "memory_lookup", "started", "Checking prior saved cases for shared transaction context.")
                memory_candidates = self.historian.recall(context_ids, shared_context=shared, owner_id=owner_id)
                state["memory_checked"] = True
                fallback = "cross_check_path" if traces else "request_additional_evidence"
                record_decision(choice, before,
                                {"candidate_count": len(memory_candidates),
                                 "candidate_case_ids": [str(item.get("caseId")) for item in memory_candidates]},
                                [f"case:{item.get('caseId')}" for item in memory_candidates] +
                                [f"tx:{tx_id}" for tx_id in context_ids], fallback)
                events.append({"agent": "Historian", "type": "memory_search_completed",
                               "tool": "find_related_memories", "status": "completed",
                               "memory_count": len(memory_candidates), "read_only": True})
                emit("Historian", "memory_lookup", "completed",
                     f"Found {len(memory_candidates)} saved-case candidate(s) by graph transaction overlap.",
                     memory_count=len(memory_candidates))
                continue
            if action == "request_additional_evidence" and not state["additional_evidence_requested"]:
                before = state_before()
                state["additional_evidence_requested"] = True
                record_decision(choice, before,
                                {"status": "inconclusive", "reason": choice["selection_reason"],
                                 "request": "Confirm another seed, source, or evidence scope; no unsupported graph claim was promoted."},
                                evidence_ids(traces), "finalize_report")
                continue
            if action == "finalize_report":
                break
            raise RuntimeError(f"Graph decision policy stalled on unsupported action: {action}")

        graph_duration_ms = round((perf_counter() - graph_started) * 1000)
        for index, path in enumerate(traces):
            path["evidence_id"] = path.get("evidence_id") or ("path:" + str(path.get("direction")) + ":" + ">".join(
                str(node.get("txId")) for node in path.get("nodes", [])))
        # Skeptic performs a separate graph reread with its own verifier; the
        # Tracer/query validator above is never the Reporter authority by itself.
        path_validation = self.skeptic.independently_verify_paths(
            traces, self.store, seed_tx_id, state["max_hops"]
        )
        ledger = build_evidence_ledger(seed, traces, path_validation, state["max_hops"], self.store.graph_name)
        shared.set_graph_evidence(ledger, traces)
        shared.add_update("Tracer", "graph_evidence_ready",
                          f"{path_validation.get('validPathCount', 0)} independently verified path(s), {len(ledger.get('transactions', {}))} unique transaction(s), and {len(ledger.get('edges', []))} distinct edge(s) are in scope.",
                          [path.get("evidence_id") for path in traces] +
                          [edge.get("edge_id") for edge in ledger.get("edges", []) if edge.get("edge_id")])
        handoff("Tracer", "Skeptic", "evidence_handoff",
                f"{len(traces)} directed path(s) are ready for independent validation.",
                [path.get("evidence_id") for path in traces], path_count=len(traces),
                unique_transaction_count=len(ledger.get("transactions", {})))
        shared.set_focus("Independently verify graph evidence and compare any saved-case candidates.",
                         "validating paths and deterministic counts", "Skeptic")

        skeptic_report = self.skeptic.review(seed, traces, path_validation, seed_exists=True,
                                             ledger=ledger, shared_context=shared)
        shared.set_skeptic_review(skeptic_report)
        events.append({"agent": "Skeptic", "type": "evidence_validation", "tool": "validate_paths",
                       "status": "completed", "valid_path_count": path_validation["validPathCount"],
                       "invalid_path_count": path_validation["invalidPathCount"], "read_only": True})

        for candidate in memory_candidates:
            shared.add_memory_candidate(candidate)
        shared.add_update("Historian", "memory_lookup_completed",
                          f"Found {len(memory_candidates)} saved-case candidate(s) by transaction overlap; all candidates await current-graph validation.",
                          [f"case:{candidate.get('caseId')}" for candidate in memory_candidates],
                          source_type="memory", verification="unverified")
        handoff("Historian", "Skeptic", "memory_handoff",
                f"Review {len(memory_candidates)} saved-case candidate(s) against current graph evidence.",
                [f"case:{candidate.get('caseId')}" for candidate in memory_candidates],
                cases=[{"case_id": candidate.get("caseId"), "shared_transactions": candidate.get("sharedTransactions", [])}
                       for candidate in memory_candidates])
        shared.set_focus("Cross-check graph paths, prior case candidates, and any model claims.",
                         "synchronizing graph evidence and case memory", "Skeptic")
        meeting_participants = ["Tracer", "Historian", "Skeptic"] + (["Analyst"] if use_local_model and self.settings else [])
        publish_context("context_sync_started", "Vesper", "context_sync",
                        "Synchronizing graph evidence and memory candidates.",
                        status="started",
                        meeting_participants=meeting_participants)
        publish_context("meeting_started", "Vesper", "meeting",
                        "Tracer and Historian are syncing their contributions for Skeptic review.",
                        status="started",
                        meeting_id=f"meeting_{investigation_id}", meeting_participants=meeting_participants,
                        meeting_focus="Compare deterministic graph paths with saved-case candidates.")
        for candidate in memory_candidates:
            candidate_event = {"agent": "Historian", "type": "memory_candidate_found", "status": "candidate",
                               "case_id": candidate.get("caseId"),
                               "shared_transactions": candidate.get("sharedTransactions", []), "read_only": True}
            events.append(candidate_event)
            if progress_callback:
                progress_callback({"agent": "Historian", "event_name": "memory_candidate_found",
                                   "stage": "memory_lookup", "status": "completed",
                                   "message": "Historian found a prior case with shared graph transactions.",
                                   "elapsed_ms": round((perf_counter() - started) * 1000),
                                   "investigation_id": investigation_id,
                                   "shared_context": shared.public_snapshot(),
                                   "case_id": candidate.get("caseId"),
                                   "shared_transactions": candidate.get("sharedTransactions", [])})

        memory_validation_started = perf_counter()
        if memory_candidates:
            emit("Skeptic", "memory_validation", "started", "Independently checking recalled paths and shared facts against the current graph.",
                 memory_count=len(memory_candidates))
        if not related_memories and memory_candidates:
            related_memories = self.skeptic.validate_memories(memory_candidates, ledger, self.store,
                                                              shared_context=shared)
        for memory in related_memories:
            shared.add_validated_memory(memory)
            status = memory.get("validationStatus", "UNVERIFIED")
            event_type = "memory_verified" if status in {"VERIFIED_RELEVANT", "PARTIALLY_RELEVANT"} else "memory_rejected"
            memory_event = {"agent": "Skeptic", "type": event_type, "stage": "memory_validation",
                            "status": status, "case_id": memory.get("caseId"),
                            "shared_transactions": memory.get("sharedTransactions", []),
                            "supporting_evidence_ids": memory.get("supportingEvidenceIds", []),
                            "message": memory.get("validationReason", "Memory validation completed."),
                            "read_only": True}
            events.append(memory_event)
            if progress_callback:
                progress_callback({"agent": "Skeptic", "event_name": event_type,
                                   "stage": "memory_validation",
                                   "status": "completed" if event_type == "memory_verified" else "warning",
                                   "memory_status": status,
                                   "case_id": memory.get("caseId"),
                                   "shared_transactions": memory.get("sharedTransactions", []),
                                   "supporting_evidence_ids": memory.get("supportingEvidenceIds", []),
                                   "message": memory.get("validationReason", "Memory validation completed."),
                                   "elapsed_ms": round((perf_counter() - started) * 1000)})
        memory_validation_duration_ms = round((perf_counter() - memory_validation_started) * 1000)
        if memory_candidates:
            verified_memory_count = sum(memory.get("validationStatus") in {"VERIFIED_RELEVANT", "PARTIALLY_RELEVANT"}
                                        for memory in related_memories)
            events.append({"agent": "Skeptic", "type": "memory_validation_completed", "status": "completed",
                           "verified_memory_count": verified_memory_count,
                           "rejected_memory_count": len(related_memories) - verified_memory_count, "read_only": True})
            emit("Skeptic", "memory_validation", "completed",
                 f"Validated {verified_memory_count} of {len(related_memories)} recalled memory candidate(s).",
                 verified_memory_count=verified_memory_count,
                 rejected_memory_count=len(related_memories) - verified_memory_count)
        memory_verified_count = sum(item.get("verification") == "verified"
                                    for item in shared.final_context()["validated_memories"])
        shared.add_update("Skeptic", "memory_cross_verification",
                          f"Validated {memory_verified_count} saved-case candidate(s); unsupported remembered context is excluded.",
                          [evidence_id for memory in related_memories
                           for evidence_id in memory.get("supportingEvidenceIds", [])],
                          source_type="memory", verification="verified")

        if choose_next_action(state)["selected_action"] == "request_additional_evidence":
            request_choice = choose_next_action(state)
            request_before = state_before()
            state["additional_evidence_requested"] = True
            request_reason = request_choice["selection_reason"]
            record_decision(request_choice, request_before,
                            {"status": "inconclusive", "reason": request_reason,
                             "request": "Confirm another seed, source, or evidence scope; no unsupported graph claim was promoted."},
                            evidence_ids(traces), "finalize_report")

        model_result: dict[str, Any] = {"status": "disabled", "observations": "", "events": [], "model": None, "warnings": []}
        model_duration_ms = 0
        if use_local_model and self.settings:
            model_started = perf_counter()
            emit("Analyst", "agent_reasoning", "started", "Reviewing validated graph evidence; deterministic facts remain authoritative.")
            connection = self.settings.model_connection
            compact = compact_ledger_for_model(ledger)
            evidence_payload = {
                "seed_tx_id": seed_tx_id,
                "max_hops": max_hops,
                "seed": seed,
                "compact_ledger": compact,
                "skeptic": {
                    "reviewStatus": skeptic_report["reviewStatus"],
                    "uniqueTransactionsReviewed": skeptic_report["uniqueTransactionsReviewed"],
                    "pathsIndependentlyValidated": skeptic_report["checks"]["pathsIndependentlyValidated"],
                    "flags": skeptic_report["flags"],
                },
                "shared_investigation_context": shared.public_snapshot(),
            }
            if connection["provider"] == "cloud" and not connection["api_key"]:
                model_result = {"status": "unavailable", "observations": "", "events": [], "model": connection["model"],
                                "message": "Ollama Cloud analysis is unavailable: OLLAMA_API_KEY is not configured; deterministic graph checks remain authoritative.",
                                "warnings": ["Ollama Cloud API key is not configured; the report contains only deterministic evidence."]}
            else:
                analyst = LocalModelAgent(self.tools, connection["base_url"], connection["model"],
                                          self.settings.ollama_timeout_seconds, api_key=connection["api_key"] or None)
                shared.record_read("Analyst")
                model_result = analyst.analyze(seed_tx_id, max_hops, evidence_payload)
            model_duration_ms = round((perf_counter() - model_started) * 1000)
            if model_result.get("status") == "complete" and model_result.get("observations"):
                # Store only extracted, short candidate claims. Raw private reasoning is never retained.
                analyst_candidates = self.reporter.extract_claims(model_result["observations"], ledger)[:8]
                for candidate in analyst_candidates:
                    shared.add_hypothesis(candidate.get("claim_id"), candidate.get("claim_text") or "")
                shared.add_update("Analyst", "interpretation_candidates",
                                  "Analyst contributed bounded claim candidates for Skeptic verification.",
                                  [str(candidate.get("claim_id")) for candidate in analyst_candidates],
                                  source_type="hypothesis", verification="unverified")
                handoff("Analyst", "Skeptic", "interpretation_handoff",
                        "Review extracted interpretation claims against the deterministic evidence ledger.",
                        [str(candidate.get("claim_id")) for candidate in analyst_candidates])
            events.extend(model_result.get("events", []))
            events.append({"agent": "Analyst", "type": "local_model", "tool": "ollama_chat", "status": model_result["status"], "read_only": True})
            emit("Analyst", "agent_reasoning", "completed" if model_result["status"] == "complete" else "warning",
                 "Model interpretation is ready." if model_result["status"] == "complete" else "Model interpretation unavailable; deterministic evidence is preserved.",
                 model_status=model_result["status"])
            for warning in model_result.get("warnings") or []:
                events.append({"agent": "Analyst", "type": "warning", "tool": "ollama_chat", "status": "warning", "message": warning, "read_only": True})

        # Claim pipeline: extract candidates from model prose, then the Skeptic
        # independently validates every claim with deterministic validators.
        model_observations = model_result.get("observations") or ""
        candidate_claims = self.reporter.extract_claims(model_observations, ledger)
        validation_started = perf_counter()
        shared.set_activity("Skeptic", "claim_validation", "started")
        publish_context("cross_verification_started", "Skeptic", "cross_verification",
                        f"Checking {len(candidate_claims)} extracted claim candidate(s) against deterministic graph facts.",
                        status="started",
                        candidate_count=len(candidate_claims))
        claim_evaluation = self.skeptic.evaluate_claims(candidate_claims, ledger, model_observations,
                                                         shared_context=shared)
        shared.classify_claims(claim_evaluation["validated_claims"])
        validation_duration_ms = round((perf_counter() - validation_started) * 1000)
        events.append({"agent": "Skeptic", "type": "claim_validation", "tool": "evaluate_claims",
                       "status": "completed",
                       "verified": claim_evaluation["claims_verified"],
                       "rejected": claim_evaluation["claims_rejected"],
                       "unverified": claim_evaluation["claims_unverified"], "read_only": True})
        emit("Skeptic", "claim_validation", "completed", "Claim checks completed against the deterministic evidence ledger.",
             verified=claim_evaluation["claims_verified"], rejected=claim_evaluation["claims_rejected"],
             unverified=claim_evaluation["claims_unverified"])

        publish_context("cross_verification_completed", "Skeptic", "cross_verification",
                        "Claim decisions are recorded; deterministic graph evidence remains authoritative.",
                        verified=claim_evaluation["claims_verified"], rejected=claim_evaluation["claims_rejected"],
                        unverified=claim_evaluation["claims_unverified"])
        publish_context("meeting_completed", "Vesper", "meeting",
                        "Shared evidence review is complete; Reporter can assemble the case summary.",
                        status="completed",
                        meeting_id=f"meeting_{investigation_id}", meeting_participants=meeting_participants,
                        meeting_focus="Reporter receives verified facts and qualified claim decisions.")
        publish_context("context_sync_completed", "Vesper", "context_sync",
                        "Shared investigation context synchronized.", status="completed")
        shared.set_focus("Prepare the evidence-first report from verified facts and labeled caveats.",
                         "assembling the final case summary", "Reporter")
        handoff("Skeptic", "Reporter", "verification_handoff",
                "Reporter receives deterministic facts and explicitly qualified claim decisions.",
                [str(claim.get("claim_id")) for claim in claim_evaluation["validated_claims"]
                 if claim.get("verification_status") == "verified"],
                rejected_claim_ids=[str(claim.get("claim_id")) for claim in claim_evaluation["validated_claims"]
                                    if claim.get("verification_status") == "rejected"],
                unverified_claim_ids=[str(claim.get("claim_id")) for claim in claim_evaluation["validated_claims"]
                                      if claim.get("verification_status") == "unverified"])

        emit("Reporter", "reporting", "started", "Preparing the evidence-first report and caveats.")
        report = self.reporter.create_report(seed, ledger, skeptic_report, related_memories,
                                             model_observations=model_observations,
                                             evaluated_claims=claim_evaluation["validated_claims"],
                                             shared_context=shared,
                                             graph_decisions=decisions if include_policy_explanation else None)
        summary = report["summary"]
        events.append({"agent": "Reporter", "type": "report", "tool": "create_evidence_summary", "status": "completed", "read_only": True})
        reporter_memory_explanation = (report["structured_report"].get("memory_policy_explanation") or {}).get("explanation")
        reporter_completion = reporter_memory_explanation or "Evidence-first report is ready."
        shared.add_update("Reporter", "report_ready",
                          reporter_completion,
                          ["evidence_ledger"])
        shared.set_focus("Investigation report is ready for human review.", "reviewing evidence and limitations", None)
        finalize_choice = choose_next_action(state)
        finalize_before = state_before()
        record_decision(finalize_choice, finalize_before,
                        {"report_status": "ready", "verified_path_count": path_validation.get("validPathCount", 0),
                         "unverified_path_count": path_validation.get("invalidPathCount", 0)},
                        evidence_ids([path for path, check in zip(traces, path_validation.get("paths", [])) if check.get("valid")]),
                        "finalize_report")
        shared.finish("complete")
        emit("Reporter", "completed", "completed", reporter_completion)

        return {
            "seed": seed, "traces": traces, "skeptic": skeptic_report,
            "related_memories": related_memories, "summary": summary,
            "evidence_ledger": ledger,
            "graph_decisions": decisions,
            "compact_model_payload": evidence_payload if use_local_model and self.settings else None,
            "structured_report": report["structured_report"],
            "claim_validation": claim_evaluation,
            "shared_context": shared.final_context(),
            "graph_action_budget": deepcopy(action_budget),
            "local_model": model_result,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "mode": self.store.mode, "agent_events": events,
            "timings": {"graph_ms": graph_duration_ms, "model_ms": model_duration_ms,
                        "memory_validation_ms": memory_validation_duration_ms,
                        "claim_validation_ms": validation_duration_ms,
                        "total_ms": round((perf_counter() - started) * 1000)},
            "persisted": False,
        }

    def save_preview(self, preview: dict[str, Any], owner_id: str | None = None) -> dict[str, Any]:
        """Persist an already-reviewed preview only when explicitly requested."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        ledger = preview.get("evidence_ledger") or {}
        evidence_tx_ids = list((ledger.get("transactions") or {}).keys())
        if not evidence_tx_ids:
            evidence_tx_ids = [preview["seed"]["txId"]] + [str(node["txId"]) for trace in preview["traces"] for node in trace.get("nodes", []) if isinstance(node, dict) and str(node.get("txId", "")).isdigit()]
        claim_validation = preview.get("claim_validation") or {}
        validated_claims = claim_validation.get("validated_claims") or []
        verified_claims = [claim for claim in validated_claims if claim.get("verification_status") == "verified"]
        rejected_claims = [claim for claim in validated_claims if claim.get("verification_status") in {"rejected", "unverified"}]
        verified_claims.extend(finding for finding in (preview.get("skeptic", {}).get("findings") or [])
                               if finding.get("status") == "verified")
        verified_claims.extend({"claim_type": "transaction_label", "tx_id": tx_id,
                               "label": transaction.get("label", "unknown"),
                               "verification_status": "verified", "evidence_ids": [f"tx:{tx_id}"],
                               "source": "deterministic_evidence_ledger"}
                              for tx_id, transaction in (ledger.get("transactions") or {}).items())
        verified_claims.extend({"claim_type": "directed_edge", "edge_id": edge.get("edge_id"),
                               "source": edge.get("source"), "target": edge.get("target"),
                               "verification_status": "verified", "evidence_ids": [f"edge:{edge.get('edge_id')}"],
                               "claim_source": "deterministic_evidence_ledger"}
                              for edge in ledger.get("edges", []) if edge.get("edge_id"))
        model_result = preview.get("local_model") or {}
        model_connection = self.settings.model_connection if self.settings else {}
        model_metadata = {
            "provider": (self.settings.model_provider if self.settings else None),
            "model": model_result.get("model") or model_connection.get("model"),
            "analysis_status": model_result.get("status", "not_run"),
        }
        case_payload = {
            "case_id": f"case_{uuid4().hex[:12]}", "memory_id": f"memory_{uuid4().hex[:12]}",
            "seed": preview["seed"], "traces": preview["traces"], "skeptic": preview["skeptic"],
            "related_memories": preview["related_memories"], "summary": preview["summary"],
            "evidence_ledger": ledger,
            "shared_context": preview.get("shared_context", {}),
            "structured_report": preview.get("structured_report", {}),
            "evidence_refs": {
                "transaction_ids": evidence_tx_ids,
                "edge_ids": [edge.get("edge_id") for edge in ledger.get("edges", []) if edge.get("edge_id")],
                "path_ids": [f"path:{path.get('path_index')}" for path in ledger.get("paths", [])],
            },
            "verified_claims": verified_claims, "rejected_claims": rejected_claims,
            "claim_validation": claim_validation, "model_metadata": model_metadata,
            "memory_schema_version": "1.0",
            "status": preview["skeptic"]["reviewStatus"], "created_at": now,
            "evidence_tx_ids": evidence_tx_ids,
        }
        if isinstance(case_payload.get("shared_context"), dict):
            case_payload["shared_context"]["case_id"] = case_payload["case_id"]
        persisted = self.historian.remember(case_payload, owner_id=owner_id)
        return {**preview, "case_id": persisted["caseId"], "memory_id": persisted["memoryId"],
                "created_at": now, "persisted": True}

    def investigate(self, seed_tx_id: str, max_hops: int, owner_id: str | None = None) -> dict[str, Any] | None:
        """Backward-compatible explicit save operation; previews never call this."""
        preview = self.preview(seed_tx_id, max_hops, use_local_model=False, owner_id=owner_id)
        return self.save_preview(preview, owner_id=owner_id) if preview is not None else None

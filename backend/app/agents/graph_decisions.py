"""Deterministic, graph-evidence-driven action selection for one investigation."""
from __future__ import annotations

from copy import deepcopy
from typing import Any
import re


ACTION_CATALOG = (
    "inspect_seed",
    "trace_downstream",
    "trace_upstream",
    "expand_verified_frontier",
    "follow_verified_memory_route",
    "cross_check_path",
    "recall_related_case",
    "request_additional_evidence",
    "finalize_report",
)
ACTION_ARGUMENT_KEYS = {
    "inspect_seed": {"tx_id"},
    "trace_downstream": {"tx_id", "max_hops"},
    "trace_upstream": {"tx_id", "max_hops"},
    "expand_verified_frontier": {"seed_tx_id", "max_hops", "frontier_limit"},
    "follow_verified_memory_route": {"seed_tx_id", "frontier_tx_id", "memory_id", "memory_path_id"},
    "cross_check_path": {"seed_tx_id", "max_hops", "path_limit"},
    "recall_related_case": {"context_tx_ids", "limit"},
    "request_additional_evidence": {"reason"},
    "finalize_report": set(),
}


def validate_action_call(action: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Validate the internal allowlisted action call shape and hard bounds."""
    if action not in ACTION_ARGUMENT_KEYS or not isinstance(arguments, dict):
        raise ValueError("unsupported graph action call")
    if set(arguments) != ACTION_ARGUMENT_KEYS[action]:
        raise ValueError("graph action arguments do not match the strict schema")
    for key in ("tx_id", "seed_tx_id"):
            if key in arguments and (not isinstance(arguments[key], str) or not re.fullmatch(r"\d{1,50}", arguments[key])):
                raise ValueError("transaction IDs must contain 1 to 50 digits")
    if "max_hops" in arguments and (type(arguments["max_hops"]) is not int or not 1 <= arguments["max_hops"] <= 4):
        raise ValueError("max_hops must be an integer from 1 through 4")
    for key in ("frontier_limit", "path_limit"):
        if key in arguments and (type(arguments[key]) is not int or not 1 <= arguments[key] <= 20):
            raise ValueError(f"{key} must be an integer from 1 through 20")
    if "limit" in arguments and (type(arguments["limit"]) is not int or not 1 <= arguments["limit"] <= 10):
        raise ValueError("memory limit must be an integer from 1 through 10")
    if "context_tx_ids" in arguments:
        values = arguments["context_tx_ids"]
        if not isinstance(values, list) or len(values) > 100 or any(
                not isinstance(value, str) or not re.fullmatch(r"\d{1,50}", value) for value in values
        ):
            raise ValueError("context_tx_ids must contain at most 100 digit-only transaction IDs")
    for key in ("memory_id", "memory_path_id"):
        if key in arguments and (not isinstance(arguments[key], str) or not re.fullmatch(r"[A-Za-z0-9:_>.-]{1,200}", arguments[key])):
            raise ValueError(f"{key} must be a bounded memory evidence identifier")
    if "frontier_tx_id" in arguments and (not isinstance(arguments["frontier_tx_id"], str)
                                           or not re.fullmatch(r"\d{1,50}", arguments["frontier_tx_id"])):
        raise ValueError("frontier_tx_id must contain 1 to 50 digits")
    if "reason" in arguments and (not isinstance(arguments["reason"], str) or len(arguments["reason"]) > 240):
        raise ValueError("reason must be a string of at most 240 characters")
    return {"name": action, "arguments": deepcopy(arguments)}


def rank_verified_frontiers(frontiers: list[dict[str, Any]], observed_counts: dict[str, int]) -> list[dict[str, Any]]:
    """Rank verified one-hop paths by observed next-edge availability.

    Counts are local, bounded neighbor reads. Ties are deterministic and never
    use dataset labels as a risk score.
    """
    ranked = []
    for path in frontiers:
        nodes = path.get("nodes") or []
        if not nodes:
            continue
        direction = path.get("direction")
        endpoint = str(nodes[-1 if direction == "downstream" else 0].get("txId", ""))
        count = max(0, int(observed_counts.get(endpoint, 0)))
        ids = tuple(str(node.get("txId", "")) for node in nodes)
        ranked.append({"path": path, "endpoint": endpoint, "observed_next_edge_count": count,
                       "rank_key": (-count, direction or "", ids)})
    return sorted(ranked, key=lambda item: item["rank_key"])


def memory_frontier_suggestions(memories: list[dict[str, Any]], frontiers: list[dict[str, Any]],
                                max_hops: int) -> list[dict[str, Any]]:
    """Join Skeptic-verified memory segments at an already verified frontier.

    Memory may propose a route for a fresh graph check; it never makes the
    joined path a current fact. Only same-case, live-validated segments qualify.
    """
    suggestions = []
    for memory in memories or []:
        if memory.get("validationStatus") != "VERIFIED_RELEVANT":
            continue
        validation = memory.get("pathValidation") or {}
        checks = validation.get("paths") or []
        if not validation.get("allPathsValid"):
            continue
        remembered_paths = memory.get("evidence") or []
        for frontier in frontiers:
            nodes = frontier.get("nodes") or []
            direction = frontier.get("direction")
            if len(nodes) != 2 or direction not in {"upstream", "downstream"}:
                continue
            ids = [str(node.get("txId", "")) for node in nodes]
            endpoint = ids[-1] if direction == "downstream" else ids[0]
            for index, path in enumerate(remembered_paths):
                if index >= len(checks) or checks[index].get("valid") is not True:
                    continue
                if path.get("direction") != direction:
                    continue
                old_nodes = path.get("nodes") or []
                old_ids = [str(node.get("txId", "")) for node in old_nodes if isinstance(node, dict)]
                if direction == "downstream" and old_ids and old_ids[0] == endpoint:
                    combined_ids = ids + old_ids[1:]
                elif direction == "upstream" and old_ids and old_ids[-1] == endpoint:
                    combined_ids = old_ids[:-1] + ids
                else:
                    continue
                if len(combined_ids) - 1 < 2 or len(combined_ids) - 1 > max_hops or len(set(combined_ids)) != len(combined_ids):
                    continue
                combined_nodes = (nodes + old_nodes[1:]) if direction == "downstream" else (old_nodes[:-1] + nodes)
                edges = [f"{source}->{target}" for source, target in zip(combined_ids, combined_ids[1:])]
                suggestions.append({
                    "frontier_tx_id": endpoint,
                    "case_id": memory.get("caseId"),
                    "memory_id": memory.get("memoryId"),
                    "memory_path_id": path.get("evidence_id"),
                    "supporting_evidence_ids": list(memory.get("supportingEvidenceIds") or []),
                    "route": {"direction": direction, "hops": len(combined_ids) - 1,
                              "nodes": deepcopy(combined_nodes), "edge_ids": edges,
                              "evidence_id": "path:" + direction + ":" + ">".join(combined_ids),
                              "memory_provenance": {"case_id": memory.get("caseId"),
                                                    "memory_id": memory.get("memoryId"),
                                                    "source_path_id": path.get("evidence_id")}},
                })
    return sorted(suggestions, key=lambda item: (item["frontier_tx_id"],
                                                 -int(item["route"].get("hops", 0)),
                                                 item["case_id"] or "", item["memory_path_id"] or ""))


def choose_next_action(state: dict[str, Any]) -> dict[str, Any]:
    """Select one safe action using only the bounded graph state supplied.

    No labels are interpreted as real-world risk. Counts are observed, bounded
    results, not graph-wide degree or reachability claims.
    """
    if not state.get("seed_checked"):
        return _choice("inspect_seed", ["inspect_seed"], "The seed has not yet been confirmed in the selected graph.")
    if not state.get("seed_exists"):
        if state.get("additional_evidence_requested"):
            return _choice("finalize_report", ["finalize_report"],
                           "The missing seed was surfaced as an explicit evidence gap; finish without graph claims.")
        return _choice("request_additional_evidence", ["request_additional_evidence", "finalize_report"],
                       "The seed was not found, so graph traversal cannot start.")

    neighbors = state.get("neighbors") or {}
    remaining = [direction for direction in ("downstream", "upstream")
                 if int(neighbors.get(direction, 0) or 0) > 0
                 and direction not in set(state.get("traced_directions") or [])]
    if remaining:
        # Counts are capped returned neighbors. They only prioritize which observed
        # direction is inspected first; they are not treated as complete degrees.
        direction = sorted(remaining, key=lambda item: (-int(neighbors.get(item, 0) or 0), item))[0]
        return _choice(f"trace_{direction}", [f"trace_{item}" for item in remaining],
                       f"The seed lookup returned {int(neighbors.get(direction, 0) or 0)} {direction} neighbor(s); inspect this available direction first.")

    paths = state.get("paths") or []
    max_depth = max((int(path.get("hops", 0) or 0) for path in paths), default=0)
    if max_depth == 1 and state.get("frontier_verified") and int(state.get("max_hops", 1)) > 1 and not state.get("memory_checked") and state.get("memory_enabled", True):
        return _choice("recall_related_case", ["recall_related_case", "expand_verified_frontier", "finalize_report"],
                       "A live-verified one-hop frontier exists; check graph-linked memory for a bounded route before choosing which frontier to expand.")
    suggestions = state.get("memory_frontier_suggestions") or []
    if state.get("memory_route_processed") and not state.get("frontier_expanded"):
        return _choice("expand_verified_frontier", ["expand_verified_frontier", "cross_check_path", "finalize_report"],
                       "The memory route was checked; continue with bounded live frontier expansion.")
    if suggestions and not state.get("memory_route_processed") and not state.get("frontier_expanded"):
        suggestion = suggestions[0]
        return {**_choice("follow_verified_memory_route", ["follow_verified_memory_route", "expand_verified_frontier", "finalize_report"],
                           "A prior case has a live-verified path segment joined to this current frontier; independently recheck the proposed route before using it."),
                "memory_suggestion": deepcopy(suggestion)}
    if max_depth == 1 and state.get("frontier_verified") and int(state.get("max_hops", 1)) > 1 and not state.get("frontier_expanded"):
        return _choice("expand_verified_frontier", ["expand_verified_frontier", "recall_related_case", "finalize_report"],
                       "A one-hop frontier is available within the requested bound; inspect its next directed edge before reporting.")
    if state.get("frontier_expanded") and not state.get("path_checked"):
        if max_depth >= 2:
            return _choice("cross_check_path", ["cross_check_path", "recall_related_case", "request_additional_evidence"],
                           f"Expansion exposed a {max_depth}-hop ordered path; independently verify every node and directed edge.")
        if not state.get("memory_checked"):
            return _choice("recall_related_case", ["recall_related_case", "cross_check_path", "request_additional_evidence"],
                           "The bounded frontier returned no longer path; check current case overlap before reviewing the shorter paths.")
    if paths and not state.get("path_checked"):
        return _choice("cross_check_path", ["cross_check_path", "recall_related_case", "request_additional_evidence"],
                       "Returned paths require independent node, property, direction, endpoint, and hop verification.")
    if not state.get("memory_checked"):
        return _choice("recall_related_case", ["recall_related_case", "request_additional_evidence", "finalize_report"],
                       "Current graph evidence is collected; check for overlapping saved cases and revalidate any candidate.")
    if not paths or not state.get("all_paths_valid"):
        if state.get("additional_evidence_requested"):
            return _choice("finalize_report", ["finalize_report"],
                           "The evidence gap is recorded; finish with an inconclusive, bounded result.")
        return _choice("request_additional_evidence", ["request_additional_evidence", "finalize_report"],
                       "No independently verified path is available; report an explicit evidence gap and request a valid seed or source.")
    return _choice("finalize_report", ["finalize_report"], "All reported paths passed the independent graph checks.")


def _choice(action: str, eligible: list[str], reason: str) -> dict[str, Any]:
    return {"selected_action": action, "eligible_actions": eligible, "selection_reason": reason}


def action_state(*, seed_checked: bool = False, seed_exists: bool = False,
                 neighbors: dict[str, int] | None = None, traced_directions: list[str] | None = None,
                 paths: list[dict[str, Any]] | None = None, max_hops: int = 3,
                 frontier_verified: bool = False, frontier_expanded: bool = False, path_checked: bool = False,
                 all_paths_valid: bool = False, memory_checked: bool = False,
                 additional_evidence_requested: bool = False, memory_enabled: bool = True) -> dict[str, Any]:
    return {"seed_checked": seed_checked, "seed_exists": seed_exists,
            "neighbors": dict(neighbors or {}), "traced_directions": list(traced_directions or []),
            "paths": list(paths or []), "max_hops": max_hops,
            "frontier_verified": frontier_verified, "frontier_expanded": frontier_expanded, "path_checked": path_checked,
            "all_paths_valid": all_paths_valid, "memory_checked": memory_checked or not memory_enabled,
            "memory_enabled": memory_enabled, "memory_evidence_ids": [], "memory_frontier_suggestions": [],
            "additional_evidence_requested": additional_evidence_requested}
